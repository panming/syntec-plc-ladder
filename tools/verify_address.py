#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地址权限回归：防止把 S 段当中间继电器这类错误再溜回来。

查四件事：
  1. R_ZONES 是否无缝覆盖 0~65535、有没有重叠
  2. check_write 的判定是否符合手册（写 S 拒绝、写只读 R 拒绝、无位存取区拒绝）
  3. validate 是否真的会拦下「写 S 段」的程序
  4. 真机语料里 S/I 段作为线圈出现了几次（应当为 0）

    python tools/verify_address.py [--samples DIR]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import syntec_address_db as ADB          # noqa: E402
import syntec_model as M                 # noqa: E402


def parse_argv(argv):
    d = os.path.join(ROOT, "samples")
    if "--samples" in argv:
        d = argv[argv.index("--samples") + 1]
    elif len(argv) > 1 and not argv[1].startswith("-"):
        d = argv[1]
    elif os.environ.get("SYNTEC_SAMPLES"):
        d = os.environ["SYNTEC_SAMPLES"]
    return d


def chk(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def main():
    ok_all = True
    print("=" * 66)
    print(" 1. R 区权限表完整性")
    print("-" * 66)
    zones = sorted(ADB.R_ZONES)
    ok_all &= chk("区段数 > 0", len(zones) > 0, f"{len(zones)} 段")
    ok_all &= chk("从 R0 开始", zones[0][0] == 0, f"首段 R{zones[0][0]}")
    gaps = []
    for a, b in zip(zones, zones[1:]):
        if b[0] != a[1] + 1:
            gaps.append((a[1], b[0]))
    ok_all &= chk("区段无空洞/无重叠", not gaps, str(gaps) if gaps else "连贯")

    print()
    print("=" * 66)
    print(" 2. check_write 判定")
    print("-" * 66)
    cases = [
        # (地址, 期望等级)
        ("S0", "error"),          # CNC->PLC 只读
        ("S32", "error"),
        ("I0", "warn"),           # 物理输入, 写无意义
        ("O0", None),
        ("C36", None),            # 已知系统命令, 允许写
        ("R50.0", None),          # 用户区 + 可位存取
        ("R210.1", None),         # 用户区(保持)
        ("R30", "error"),         # CNC 接口区只读
        ("R1200.0", "error"),     # 用户区但位存取=否
        ("R8000.0", "error"),     # CNC 接口区, 只读
        ("R44.5", None),          # PLC 警报讯息区, 可写
    ]
    for addr, want in cases:
        got, msg = ADB.check_write(addr)
        ok_all &= chk(f"{addr:9s} -> {str(got):5s}", got == want,
                      (msg or "")[:48])

    print()
    print("=" * 66)
    print(" 3. validate 是否拦下写 S 段")
    print("-" * 66)
    p = M.LadderProject()
    p.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I0"},
                         {"kind": "coil", "norm": "LATCH", "addr": "S0"}])
    p.add_rung(elements=[{"kind": "end"}])
    warns = [w for w in p.validate() if "S 段" in w]
    ok_all &= chk("写 S0 会被 validate 报出", bool(warns), warns[0][:56] if warns else "")

    p2 = M.LadderProject()
    p2.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I0"},
                          {"kind": "coil", "norm": "LATCH", "addr": "R50.0"}])
    p2.add_rung(elements=[{"kind": "end"}])
    clean = [w for w in p2.validate() if "R50" in w or "S 段" in w]
    ok_all &= chk("写 R50.0 不报警", not clean, str(clean) if clean else "")

    print()
    print("=" * 66)
    print(" 4. 真机语料：S / I 从不作线圈")
    print("-" * 66)
    samples = parse_argv(sys.argv)
    files = [os.path.join(samples, f) for f in sorted(os.listdir(samples))
             if f.endswith(".lad")] if os.path.isdir(samples) else []
    real = [p for p in (os.path.join(os.path.expanduser("~"), "Desktop", "cnc.lad"),
                        os.path.join(os.path.expanduser("~"), "Desktop", "cnc_1.lad"))
            if os.path.isfile(p)]
    files = real or files
    if not files:
        print("  [SKIP] 没有可用的 .lad 语料")
    import re
    for f in files:
        import syntec_read as R
        info = R.read_ladder(f)
        cnt = {}
        def walk(els):
            for e in (els or []):
                if e.get("kind") == "parallel":
                    for b in (e.get("branches") or []):
                        walk(b)
                a = e.get("addr")
                if e.get("kind") == "coil" and a:
                    k = re.match(r"[A-Z]+", str(a)).group()
                    cnt[k] = cnt.get(k, 0) + 1
        for r in info["rungs"]:
            walk(r["elements"])
        ok_all &= chk(os.path.basename(f), not cnt.get("S") and not cnt.get("I"),
                      "线圈分布 " + ", ".join(f"{k}:{v}" for k, v in sorted(cnt.items())))

    print()
    print("=" * 66)
    print(("全部通过 [PASS]" if ok_all else "有失败项 [FAIL]"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
