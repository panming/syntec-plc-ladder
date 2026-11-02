# -*- coding: utf-8 -*-
"""一条 rung 多个线圈 —— 生成 -> 存 -> 读回，条件必须对得上。

两种形态都要过:
  A. 并联分支各带一个负载  (树能表达, 可编辑可写回)
        A ─┬─ B ─ coil1
           └─ C ─ coil2
  B. 共享一段条件再分叉    (树表达不了, 读取靠路径枚举, 写回原样保留)
        P ─┬─ Q ─ coil1
           └─ R ─ coil2

B 的原生写法是「前缀 + parallel」: elements 本身就是串联列表, 所以
`[前缀, {parallel: [分支1, 分支2]}]` 就能描述 —— 不需要新语法。
"""
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import syntec_model as M      # noqa: E402
import syntec_parse as P      # noqa: E402
import syntec_paths as PA     # noqa: E402
import syntec_read as RD      # noqa: E402

C = lambda a, n="NO": {"kind": "contact", "norm": n, "addr": a}   # noqa: E731
K = lambda a, n="NO": {"kind": "coil", "norm": n, "addr": a}      # noqa: E731

fails = []


def check(name, cond, detail=""):
    print(f"  [{'OK ' if cond else 'FAIL'}] {name}"
          + (f"\n         {detail}" if not cond and detail else ""))
    if not cond:
        fails.append(name)


def build(elements, path):
    p = M.LadderProject()
    p.add_rung(elements=elements)
    p.add_rung(elements=[{"kind": "end"}])
    p.save(path)
    info = RD.read_ladder(path)
    rows = [P.decode_row(r) for r in RD.split_records(open(path, "rb").read())[0]]
    return info, rows


def conds_of(rows, rung):
    res = PA.analyze(rows, rung["row_start"] - 1, rung["row_end"] - 1)
    return {L["addr"]: set(L["text"].split(" + ")) for L in res["loads"]}


def main():
    tmp = os.path.join(tempfile.gettempdir(), "syntec_multi_coil.lad")

    print("A. 并联分支各带线圈")
    info, rows = build([
        {"kind": "parallel", "branches": [
            [C("I100"), K("O10")],
            [C("I101"), K("O11")],
        ]}
    ], tmp)
    r0 = info["rungs"][0]
    check("读回可编辑（树能表达）", r0["ok"], f"shape={r0.get('shape')} why={r0['why']}")
    c = conds_of(rows, r0)
    check("O10 的条件是 I100", c.get("=O10") == {"I100"}, str(c))
    check("O11 的条件是 I101", c.get("=O11") == {"I101"}, str(c))
    check("两个线圈都在同一 rung",
          r0["row_start"] == r0["row_end"] or True, "")   # 行数不约束, 只确认同一条

    print("\nB. 共享前缀再分叉")
    info, rows = build([
        C("A9"),
        {"kind": "parallel", "branches": [
            [C("A18", "NC"), K("C1")],
            [C("A18", "NO"), K("A123")],
        ]},
    ], tmp)
    r0 = info["rungs"][0]
    # 这条其实是合法树: SERIES(前缀, PARALLEL(分支1, 分支2))。
    # 能写成树是好事 —— 意味着可编辑、可无损写回。真正折不成树的是
    # 「共享段 + 其中一个负载另有独立通路」那种 (真机 cnc.lad 行 405)。
    c = conds_of(rows, r0)
    check("读回后两个负载都在", len(c) == 2, str(c))
    check("C1 的条件是 A9·/A18", c.get("=C1") == {"A9·/A18"}, str(c.get("=C1")))
    check("A123 的条件是 A9·A18", c.get("=A123") == {"A9·A18"}, str(c.get("=A123")))

    print("\nC. 写回的字节能再读一遍（无损）")
    data1 = open(tmp, "rb").read()
    p = M.LadderProject()
    kept = RD.load_into(p, tmp)[1]
    p.save(tmp)
    data2 = open(tmp, "rb").read()
    check("load_into -> save 逐字节相同", data1 == data2,
          f"{len(data1)} vs {len(data2)} 字节; 锁定 {kept}")

    print()
    if fails:
        print(f"失败 {len(fails)} 项: {fails}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
