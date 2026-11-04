#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""离线生成模板 —— 不依赖 MCP，直接调 syntec-plc-ladder 仓库的源码。

什么时候用：
  1. MCP 工具没配好，但机器上有 syntec-plc-ladder 仓库；
  2. 想把生成过程固化成脚本（交付给用户，以后改参数重跑就行）；
  3. 需要批量生成多个机型变体。

用法：
    export SYNTEC_REPO=/path/to/syntec-plc-ladder    # 或者改下面的 SEARCH
    python build_program.py                 # 生成 + 校验 + 保存 + 回读比对
    python build_program.py --preview       # 另打印梯形图
    python build_program.py --sim           # 另跑时序仿真
    python build_program.py --out demo.lad

改这个文件时只需要动三处：
  ① IO 表        —— 地址和含义
  ② build()      —— 逻辑
  ③ 仿真场景     —— main() 里的 scenarios
"""
import argparse
import os
import sys

OUT_DEFAULT = "demo.lad"

# ---------------------------------------------------------------- 找仓库
# 顺序: 环境变量 -> 脚本所在位置往上找 -> 当前目录往上找。
# 这个文件按「仓库内的 skill/syntec-plc/assets/」摆放，所以往上三层就是仓库根。
_HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = [
    os.environ.get("SYNTEC_REPO"),
    os.path.join(_HERE, "..", ".."),
    os.path.join(_HERE, "..", "..", ".."),
    os.getcwd(),
    os.path.join(os.getcwd(), ".."),
]


def find_repo():
    for p in SEARCH:
        if not p:
            continue
        p = os.path.abspath(os.path.expanduser(p))
        if os.path.isfile(os.path.join(p, "src", "syntec_model.py")):
            return p
    sys.exit("找不到 syntec-plc-ladder 仓库。设环境变量 SYNTEC_REPO 指向它，"
             "或改本文件顶部的 SEARCH。")


REPO = find_repo()
sys.path.insert(0, os.path.join(REPO, "src"))
import syntec_model as M          # noqa: E402
import syntec_read as R           # noqa: E402
import syntec_re as RE            # noqa: E402  注释读取(验证用)


# ---------------------------------------------------------------- ① IO 表
# (地址, 短注释, 长注释)。注释必须繁体，否则 cp950 存不进去。
# 内部标志用 A 段虚拟辅助接点 (A0~A511); 要跨断电记住的数值用 R193~R255。
# 注意 S 段是核心->阶梯图的只读状态, C 段是给核心下的命令, 都不能当中间继电器。
IO = [
    ("I0", "啟動", "常開 按一下啟動"),
    ("I1", "停止", "常閉接法 ON=允許 按下=停"),
    ("I2", "故障", "常閉接法 ON=正常 斷開=故障"),
    ("O0", "泵", "打油時吸合"),
    ("O1", "運行指示", "泵運行時亮"),
    ("A0", "運行請求", "啟動置位 停止/故障復位"),
]

# 程序头注释（ct=1，占编辑器行号）
HEADER = [
    "示例程序 v1.0  —— 由 build_program.py 生成",
    "I0啟動 I1停止(常閉) I2故障(常閉)",
    "O0泵 O1運行指示",
    "故障鎖存後須排除故障再按 I1 復位",
]


def NO(a):
    return {"kind": "contact", "norm": "NO", "addr": a}


def NC(a):
    return {"kind": "contact", "norm": "NC", "addr": a}


def COIL(a, norm="NO"):
    return {"kind": "coil", "norm": norm, "addr": a}


def TMR(n, prec, preset):
    return {"kind": "timer", "name": f"TM{n}", "precision": prec,
            "source": "K", "preset": preset}


def TM_NO(n):
    return {"kind": "contact_t", "norm": "NO", "index": n}


# ---------------------------------------------------------------- ② 逻辑
def build():
    """返回 [(说明, elements), ...]。一段一件事。"""
    return [
        # 注意 I1/I2 是常闭接线: 正常时 ON(True), 按下/断开变 False。
        # 所以"允许运行"要用 NO 触点(为真才通), "触发停止"才用 NC 触点。
        ("启动/自保持 -> 请求位置位",
         [{"kind": "parallel", "branches": [[NO("I0")], [NO("A0")]]},
          NO("I1"), NO("I2"), COIL("A0", "LATCH")]),

        ("停止或故障 -> 请求位复位",
         [{"kind": "parallel", "branches": [[NC("I1")], [NC("I2")]]},
          COIL("A0", "UNLATCH")]),

        ("请求位驱动泵（唯一一处线圈）",
         [NO("A0"), COIL("O0")]),

        ("运行指示",
         [NO("O0"), COIL("O1")]),

        ("结束",
         [{"kind": "end"}]),
    ]


# ---------------------------------------------------------------- ③ 仿真
def simulate(prog, timeline, total, name):
    """扫描级仿真。timeline: [(秒, 函数)]，函数收到 state 后改输入。

    只覆盖常用元件（触点/线圈/定时器/并联）。够验证时序，不追求完整。
    精度固定按 10ms 一个扫描，够用。
    """
    tm = {}
    for els in prog.rungs:
        stack = [els]
        while stack:
            for e in stack.pop():
                if e["kind"] == "parallel":
                    stack.extend(e["branches"])
                elif e["kind"] == "timer":
                    idx = int("".join(c for c in e["name"] if c.isdigit()))
                    tm[idx] = e["preset"] * {"1s": 1, "0.1s": 0.1,
                                             "0.01s": 0.01, "0.001s": 0.001}[e["precision"]]
    bits = {"I0": False, "I1": True, "I2": True, "A0": False, "O0": False, "O1": False}
    elapsed = {k: 0.0 for k in tm}
    timeline = sorted(timeline)
    ti = 0
    last_print = None
    print(f"\n--- {name} ---")
    for step in range(int(total / 0.01) + 1):
        now = round(step * 0.01, 2)
        while ti < len(timeline) and abs(timeline[ti][0] - now) < 0.005:
            timeline[ti][1](bits)
            ti += 1

        def ev(els):
            """返回该组元件是否导通（串联）"""
            ok = True
            for e in els:
                k = e["kind"]
                if k == "contact":
                    v = bits.get(e["addr"], False)
                    ok &= (not v) if e["norm"] == "NC" else v
                elif k == "contact_t":
                    ok &= elapsed.get(e["index"], 0) >= tm.get(e["index"], 1e9)
                elif k == "parallel":
                    ok &= any(ev(br) for br in e["branches"])
                elif k in ("coil", "timer", "end"):
                    continue
                if not ok:
                    return False
            return ok

        for els in prog.rungs:
            for e in els:
                if e["kind"] != "coil":
                    continue
                on = ev(els)
                if e["norm"] == "LATCH":
                    if on:
                        bits[e["addr"]] = True
                elif e["norm"] == "UNLATCH":
                    if on:
                        bits[e["addr"]] = False
                else:
                    # 普通线圈必须两种状态都写, 否则断开后状态会一直停在 1
                    bits[e["addr"]] = on
            # 定时器: 条件成立才累计
            for i, e in enumerate(els):
                if e["kind"] == "timer":
                    idx = int("".join(c for c in e["name"] if c.isdigit()))
                    elapsed[idx] = elapsed[idx] + 0.01 if ev(els) else 0.0

        cur = (bits["O0"], bits["O1"])
        if cur != last_print and (cur[0] or cur[1] is not None):
            print(f"  {now:7.2f}s  O0={int(cur[0])} O1={int(cur[1])}")
            last_print = cur
    print(f"  结束: O0={int(bits['O0'])} O1={int(bits['O1'])}")
    return bits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--preview", action="store_true", help="打印梯形图")
    ap.add_argument("--sim", action="store_true", help="跑时序仿真")
    ap.add_argument("--repo", help="覆盖仓库路径")
    args = ap.parse_args()

    prog = M.LadderProject()

    # 程序头注释
    for line in HEADER:
        prog.add_header_comment(line)

    rungs = build()
    for _note, els in rungs:
        prog.add_rung(elements=els)

    # 设备变量注释
    for addr, short, long in IO:
        prog.set_comment(addr, short=short, long=long)

    # 校验。validate() 返回的是文字告警列表，按关键字区分要不要拦下保存。
    BLOCKING = ("双线圈", "重复元件", "既当输出线圈", "不是 END", "只有条件", "超出")
    issues = prog.validate()
    print(f"校验: {len(issues)} 条")
    for x in issues:
        print("  ", x)
    blocking = [x for x in issues if any(k in x for k in BLOCKING)]
    if blocking:
        # 注意: 这里是本脚本按关键字自己卡的 —— validate() 本身不阻断 save, 也不分级。
        sys.exit(f"有 {len(blocking)} 条必须先处理（脚本自己按关键字卡的，"
                 f"validate 本身不会阻止保存），改掉再存")

    path, nbytes = prog.save(args.out)        # save() 返回 (规范化路径, 字节数)
    print(f"已保存 {path}  ({nbytes} 字节)")

    # 回读比对：结构一致 + 逐字节
    orig = open(path, "rb").read()
    p2 = M.LadderProject()
    R.load_into(p2, path)
    same = p2.to_lad_bytes() == orig
    print(f"往返: {'逐字节相同' if same else '不同（结构可能仍一致，查 check_lad.py）'}")

    info = R.read_ladder(path)
    print(f"逻辑行 {info['logic_rows']}，注释 {len(info['comments'])} 条")

    # 行对照表：段序号 <-> 编辑器行号(注释行会占行号，两者不等)
    print("\n行对照:")
    for k, ((note, _els), rung) in enumerate(zip(rungs, info["rungs"]), 1):
        print(f"  第{k}段 编辑器行 {rung.get('editor_row_start', rung['row_start'])}"
              f"  {note}")

    if args.preview:
        print()
        print(R.render_file(path))

    if args.sim:
        simulate(prog, [(0.0, lambda b: b.update(I0=True)),
                        (0.5, lambda b: b.update(I0=False)),
                        (2.0, lambda b: b.update(I1=False)),
                        (2.5, lambda b: b.update(I1=True))],
                 3.0, "启动 -> 自保持 -> 停止")

    print("\n下一步: 用 check_lad.py 做字节体检，再用新代编辑器打开核对。")


if __name__ == "__main__":
    main()
