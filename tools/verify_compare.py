#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""比较块槽位回归。

编辑器里带 K 的比较块（GTK/LTK/EQK）两个槽位角色是**固定**的：
A 槽 = 常数，B 槽 = 寄存器，比较方向就是「左 op 右」。

这条是现场核对出来的：写 `EQK A=R83 B=#0`（想表达 R83 == 0），
编辑器把它显示成 `A=#83 B=R0` —— 常数 83 与寄存器 R0 比较，恒不成立。
程序能存、能打开、能通过校验，就是不生效。

本脚本盯四件事：
  1. cmp_reg_const 的语义映射（寄存器 op 常数 → 编辑器要的写法）
  2. 旧写法必须被拒绝，不能静默生成
  3. 往返后 A 侧仍带 # 前缀（类型不能丢）
  4. 渲染出来的文本和编辑器一致（K5 < R210，不是 R210 > K5）
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "src"))

import syntec_model as M       # noqa: E402
import syntec_read as R        # noqa: E402

OUT = os.path.join(os.environ.get("TEMP", "/tmp"), "syntec_cmp_check.lad")
FAIL, OK = "[FAIL]", "[OK  ]"
fails = 0


def check(cond, msg, extra=""):
    global fails
    print(("  %s %s" % (OK if cond else FAIL, msg)))
    if not cond:
        fails += 1
        if extra:
            print("        " + str(extra))


def main():
    print("1. cmp_reg_const 语义映射")
    cases = [
        # (寄存器, 运算, 常数, 期望 op, 期望 A, 期望 B, 说明)
        ("R210", ">", 5,   "LTK", "#5", "R210", "R210>5  ->  5<R210"),
        ("R210", "<", 5,   "GTK", "#5", "R210", "R210<5  ->  5>R210"),
        ("R210", "==", 5,  "EQK", "#5", "R210", "R210==5 ->  5==R210"),
        ("R83", ">", 0,    "LTK", "#0", "R83",  "R83>0   ->  0<R83"),
        ("R81", "<", 1,    "GTK", "#1", "R81",  "R81<1   ->  1>R81"),
    ]
    for reg, op, c, eop, ea, eb, note in cases:
        el = M.cmp_reg_const(reg, op, c)
        ok = el["op"] == eop and el["A"] == ea and el["B"] == eb
        check(ok, note, el)

    print("\n2. 写反的槽位必须被拒绝")
    bad = [
        ("EQK", "R83", "#0"),
        ("GTK", "R210", "#100"),
        ("LTK", "R210", "#100"),
    ]
    for op, a, b in bad:
        p = M.LadderProject()
        p.add_rung(elements=[{"kind": "compare", "op": op, "A": a, "B": b},
                             {"kind": "coil", "norm": "NO", "addr": "A1"}])
        p.add_rung(elements=[{"kind": "end"}])
        try:
            p.save(OUT)
            check(False, "%s A=%s B=%s 应该被拒绝，实际存下去了" % (op, a, b))
        except ValueError as e:
            check("A 槽必须是常数" in str(e), "%s A=%s B=%s 被拒绝" % (op, a, b), e)

    print("\n3. 往返后类型不丢")
    p = M.LadderProject()
    for i, (reg, op, c) in enumerate([("R210", ">", 5), ("R210", "<", 5),
                                      ("R210", "==", 5)], start=1):
        p.add_rung(elements=[M.cmp_reg_const(reg, op, c),
                             {"kind": "coil", "norm": "NO", "addr": "A%d" % i}])
    p.add_rung(elements=[{"kind": "end"}])
    path, _ = p.save(OUT)
    info = R.read_ladder(path)
    got = []
    for r in info["rungs"][:-1]:
        c = [e for e in r["elements"] if e.get("kind") == "compare"]
        if c:
            got.append(c[0])
    check(len(got) == 3, "读回 3 条比较块", len(got))
    for el in got:
        check(str(el["A"]).startswith("#"), "A 侧仍是常数 %r" % el["A"], el)
        check(not str(el["B"]).startswith("#"), "B 侧仍是寄存器 %r" % el["B"], el)

    print("\n4. 渲染与编辑器一致")
    txt = R.render_file(path)
    for want in ("K5<R210", "K5>R210", "K5==R210"):
        check(want in txt, "渲染出现 %s" % want, txt.strip().splitlines()[:6])
    check("R210>K5" not in txt, "不再出现反过来的 R210>K5")

    print("\n" + "=" * 70)
    if fails:
        print("%d 项失败   [FAIL]" % fails)
        return 1
    print("全部通过   [PASS]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
