#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""注释记录(ct=1/2/3/4)的编码验证。

三件事:
  1. 自造样例: 编码 -> 用 syntec_re.parse_raw 读回 -> 文本必须一模一样
     (覆盖 1 条记录、跨多条记录、纯 ASCII、纯中文、混合)
  2. 真机语料: 把文件里每一条注释重新编码, 与原件逐字节比对
     (cnc.lad 有 657 条, 能过就说明槽位/续记录/字节数全部对得上)
  3. 端到端: 造一个带注释的工程存盘, 再用 read_ladder 读回来核对数量

用法:
    python tools/verify_comments.py
    python tools/verify_comments.py --samples D:/lad语料
    SYNTEC_SAMPLES=D:/lad语料 python tools/verify_comments.py
"""
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import syntec_lad as L          # noqa: E402
import syntec_model as M        # noqa: E402
import syntec_re as R           # noqa: E402
import syntec_read as RD        # noqa: E402


# ---- 真机语料定位: 显式参数 > 环境变量 > 常见位置, 找不到就跳过 ----
OPTIONAL = ("cnc.lad", "cnc_1.lad")


def find_samples(argv):
    cands = []
    for i, a in enumerate(argv):
        if a == "--samples" and i + 1 < len(argv):
            cands.append(argv[i + 1])
        elif a.startswith("--samples="):
            cands.append(a.split("=", 1)[1])
        elif not a.startswith("-"):
            cands.append(a)
    if os.environ.get("SYNTEC_SAMPLES"):
        cands.append(os.environ["SYNTEC_SAMPLES"])
    cands += [os.path.join(ROOT, "samples"),
              os.path.join(os.path.expanduser("~"), "Desktop")]
    for c in cands:
        if c and os.path.isdir(c):
            found = [os.path.join(c, f) for f in OPTIONAL
                     if os.path.isfile(os.path.join(c, f))]
            if found:
                return c, found
    return None, []


# ---- 1. 自造样例往返 ----
SELF_CASES = [
    ("短 ASCII", "SYNTEC", 1),
    ("短中文", "潤滑油泵", 1),
    ("整条记录边界(18 字节)", "123456789012345678", 1),
    ("刚过一条记录(19 字节)", "1234567890123456789", 1),
    ("跨三条记录", "潤滑油泵控制程序：自動週期打油，" * 3, 1),
    ("变量注释", None, 4),      # 用 enc_varcmt 生成
    ("版本记录", "2\tSYNTEC 10.1", 2),
]


def check_self_cases():
    print("=== 1. 自造样例: 编码 -> 解码 ===")
    ok = bad = 0
    for label, text, ct in SELF_CASES:
        if ct == 4:
            raw = L.enc_varcmt("O20", "泵", "打油時吸合")
            back = R.text_of(R.parse_raw(raw)[0][1])
            want = "O20 \t泵 \t打油時吸合"
        else:
            raw = L.enc_comment(text, ct)
            back = R.text_of(R.parse_raw(raw)[0][1])
            want = text
        good = (back == want)
        ok += good
        bad += (not good)
        print(f"  {'OK ' if good else 'FAIL'} {label:24s} {len(raw)//40} 条记录  "
              f"{'' if good else repr(back) + ' != ' + repr(want)}")
    print(f"  -> {ok}/{ok + bad} 往返一致\n")
    return bad == 0


# ---- 2. 真机语料逐字节 ----
def check_corpus(files):
    print("=== 2. 真机语料: 每条注释重新编码后逐字节比对 ===")
    if not files:
        print("  SKIP(未找到 cnc.lad / cnc_1.lad, 用 --samples 指定目录)\n")
        return True
    all_ok = True
    for f in files:
        data = open(f, "rb").read()
        pos = ok = bad = 0
        for kind, payload, _rec, ct in R.parse_raw(data):
            if kind == "logic":
                pos += 40
                continue
            enc = L.enc_comment(payload, ct)
            if enc != data[pos:pos + len(enc)]:
                bad += 1
                if bad == 1:
                    print(f"  ! {os.path.basename(f)} 首个不一致 ct={ct} "
                          f"文本={R.text_of(payload)[:20]!r}")
            else:
                ok += 1
            pos += len(enc)
        print(f"  {'OK ' if bad == 0 else 'FAIL'} {os.path.basename(f):14s} "
              f"注释 {ok} 条一致 / {bad} 条不一致")
        all_ok = all_ok and bad == 0
    print()
    return all_ok


# ---- 3. 端到端 ----
def check_end_to_end():
    print("=== 3. 端到端: 建工程 -> 加注释 -> 存盘 -> 读回 ===")
    out = os.path.join(tempfile.gettempdir(), "syntec_cmt_test.lad")
    p = M.LadderProject()
    p.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I2"},
                         {"kind": "coil", "norm": "NO", "addr": "O0"}])
    p.add_rung(elements=[{"kind": "end"}])
    p.add_header_comment("潤滑油泵控制程序 v1.0")
    p.add_header_comment("自動週期打油：間隔 30 分、打油 30 秒")
    p.add_varcmt("I2", "油位低", "ON=油位低 報警並禁止打油")
    p.add_varcmt("O0", "泵接觸器", "KM1 打油時吸合")
    p.save(out)

    info = RD.read_ladder(out)
    data = open(out, "rb").read()
    n_cmt = sum(1 for k, _p, _r, _c in R.parse_raw(data) if k == "comment")
    n_var = sum(1 for k, _p, _r, _c in R.parse_raw(data) if k == "varcmt")

    # 读入再存必须逐字节相同 (否则编辑器打开会看到被重排的注释)
    p2 = M.LadderProject()
    RD.load_into(p2, out)
    same = (p2.to_lad_bytes() == data)

    ok = (len(info["rungs"]) == 2 and n_cmt == 2 and n_var == 2 and same)
    print(f"  {'OK ' if ok else 'FAIL'} rung {len(info['rungs'])} 条 / "
          f"注释行 {n_cmt} 条 / 变量注释 {n_var} 条 / 往返一致 {same}")
    print(f"  产物: {out}\n")
    return ok


def main(argv):
    _d, files = find_samples(argv)
    results = [check_self_cases(), check_corpus(files), check_end_to_end()]
    print("=" * 62)
    print(("全部通过 [PASS]" if all(results) else "有失败 [FAIL]"))
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
