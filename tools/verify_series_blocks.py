#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""串联功能块是**条件**, 不是恒通 —— 锁住 2026-11-02 现场纠正的语义。

手册依据 (PLC Editor Manual-ZH-CN.chm):
  1-2.10 定时器: 输入保持 ON 才计时, 「当定时器到达设定时间时, 输出讯号为 ON」,
         输入 OFF 时「输出讯号为 OFF」。
  1-2.7  比较组件: 「当比较结果为成立(真)时, 输出讯号为 ON；不成立(假)时 OFF」。
现场结论: 只有定时器达到设定的时间、或运算返回值为真时, 才会导通后面的负载。

旧版把串联功能块当恒通 (「电流仍然流过去, 后面的输出每个扫描都执行」),
下游负载的布尔表达式会少一个 AND 项, 据此读程序会得出错误结论。
本脚本用真值表把这个语义钉死, 改动 syntec_paths.py 时必须跑。

用法: python tools/verify_series_blocks.py
"""
import itertools
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import syntec_model as M          # noqa: E402
import syntec_read as RD          # noqa: E402
import syntec_parse as P          # noqa: E402
import syntec_paths as PA         # noqa: E402

CASES = [
    # (名字, 元件列表, 下游线圈, 期望类别)
    #   'gate' = 功能块既是被驱动的负载, 又是下游条件 (定时器/算术/搬移)
    #   'cond' = 纯条件, 不是负载 (比较块)
    #   None   = 对照组, 没有串联功能块
    ("定时器", [{"kind": "contact", "norm": "NO", "addr": "I100"},
              {"kind": "timer", "name": "TM0", "precision": "1s",
               "source": "K", "preset": 10},
              {"kind": "coil", "norm": "NO", "addr": "O10"}], "=O10", "gate"),
    ("比较块", [{"kind": "contact", "norm": "NO", "addr": "I100"},
              {"kind": "compare", "op": "GT", "A": "#210", "B": "R211"},
              {"kind": "coil", "norm": "NO", "addr": "O12"}], "=O12", "cond"),
    ("算术运算", [{"kind": "contact", "norm": "NO", "addr": "I100"},
               {"kind": "math", "op": "ADD", "A": "R200", "B": "R201"},
               {"kind": "coil", "norm": "NO", "addr": "O13"}], "=O13", "gate"),
    ("资料搬移", [{"kind": "contact", "norm": "NO", "addr": "I100"},
               {"kind": "move", "op": "MOV", "A": "R220", "B": "R221"},
               {"kind": "coil", "norm": "NO", "addr": "O14"}], "=O14", "gate"),
    ("对照(无功能块)", [{"kind": "contact", "norm": "NO", "addr": "I100"},
                  {"kind": "coil", "norm": "NO", "addr": "O11"}], "=O11", None),
]


def build():
    p = M.LadderProject()
    for _name, els, _coil, _frag in CASES:
        p.add_rung(elements=els)
    p.add_rung(elements=[{"kind": "end"}])
    path = os.path.join(tempfile.gettempdir(), "syntec_series_blocks.lad")
    p.save(path)
    logic, _others, _tail = RD.split_records(open(path, "rb").read())
    rows = [P.decode_row(r) for r in logic]
    return rows, RD.read_ladder(path)


def rung_result(rows, info, idx):
    r = info["rungs"][idx]
    return PA.analyze(rows, r["row_start"] - 1, r["row_end"] - 1)


def main():
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    rows, info = build()

    # 0. 分类本身: 定时/运算是 gate, 比较是 cond, 线圈是 load, 流程块谁都不是
    timer_el = ("FB", "TIMER", 0, 0, 0, b"")
    cmp_el = ("FB", "CMP", "GT", 0, 0)
    flow_el = ("FB", "FLOW", "FEND", "")
    chk("定时器归 gate", PA.kind_of(timer_el) == "gate", PA.kind_of(timer_el))
    chk("比较块归 cond", PA.kind_of(cmp_el) == "cond", PA.kind_of(cmp_el))
    chk("线圈归 load", PA.kind_of(("COIL", "NO", 0)) == "load")
    chk("流程块不参与求值", PA.kind_of(flow_el) == "other", PA.kind_of(flow_el))

    # 1. 每条含串联功能块的 rung: gate 自己是被驱动的负载, 下游条件里必须带它
    for idx, (name, _els, coil_addr, expect) in enumerate(CASES):
        res = rung_result(rows, info, idx)
        loads = res["loads"]
        by_addr = {L["addr"]: L for L in loads}
        coil = by_addr.get(coil_addr)
        chk(f"{name}: 下游线圈存在", coil is not None,
            str([L["addr"] for L in loads]))
        if coil is None:
            continue
        text = coil["text"]
        if expect is None:
            chk("对照: 条件只有 I100", text == "I100", text)
            chk("对照: 不含任何 FB",
                all(e[0] != "FB" for t in coil["terms"] for e in t), text)
            chk("对照: 只有线圈一个负载", len(loads) == 1,
                str([L["addr"] for L in loads]))
            continue
        if expect == "cond":
            # 比较块是纯条件: 不驱动任何东西, 也不该被当成负载
            chk("比较块: 只有线圈一个负载", len(loads) == 1,
                str([L["addr"] for L in loads]))
            chk("比较块: 下游条件里确有 CMP 元件",
                any(e[0] == "FB" and e[1] == "CMP"
                    for t in coil["terms"] for e in t), text)
            continue
        # gate: 非线圈的那个负载就是串联功能块自己
        gates = [L for L in loads if not L["addr"].startswith("=")]
        chk(f"{name}: 恰有一个 gate 负载", len(gates) == 1,
            str([L["addr"] for L in loads]))
        if not gates:
            continue
        g = gates[0]
        chk(f"{name}: 下游条件带上了 {g['addr']}", g["addr"] in text, text)
        chk(f"{name}: through 列出该功能块",
            any(g["addr"] in x for x in coil["through"]),
            str(coil["through"]))
        # 防「退回恒通」的关键断言: 条件里至少有一个 FB 元件
        chk(f"{name}: 条件里确有 FB 元件",
            any(e[0] == "FB" for t in coil["terms"] for e in t), text)
        # 功能块自身的条件不含它自己, 也不含下游线圈
        chk(f"{name}: 自身条件只有 I100", g["text"] == "I100", g["text"])

    # 2. 真值表: =O10 必须等于 I100 AND (定时器已到时), 不是 I100 一个说了算
    res = rung_result(rows, info, 0)
    coil = next(L for L in res["loads"] if L["addr"] == "=O10")
    fb = next(e for t in coil["terms"] for e in t if e[0] == "FB")
    lit_i, lit_t = ("I100", False), PA.literal(fb)
    chk("功能块有稳定的真值键", lit_t is not None, str(lit_t))
    for i, t in itertools.product((False, True), repeat=2):
        vals = {lit_i: i, lit_t: t}
        got = PA.eval_terms(coil["terms"], vals)
        chk(f"真值 I100={int(i)} TM到时={int(t)} -> {int(i and t)}",
            got == (i and t), "got=%s text=%s" % (got, coil["text"]))
    # 定时器自身只看上游
    own = next(L for L in res["loads"] if L["addr"].startswith("TM"))
    for i, t in itertools.product((False, True), repeat=2):
        vals = {lit_i: i, lit_t: t}
        chk(f"定时器自身 I100={int(i)} -> {int(i)}",
            PA.eval_terms(own["terms"], vals) == i, own["text"])

    # 3. 旧措辞不能复活 (它会把人重新带回「恒通」的误解)
    for fn in ("tools/review_ladder.py", "src/mcp_server.py"):
        src = open(os.path.join(ROOT, fn), encoding="utf-8").read()
        chk(f"{fn} 不再宣称不阻断",
            "不会阻断" not in src and "不阻断电流" not in src
            and "每个扫描都执行" not in src)

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" +
              (f"  <- {detail}" if not ok else ""))
    print()
    if bad:
        print(f"[FAIL] {len(bad)}/{len(checks)} 项未通过")
        return 1
    print(f"[PASS] {len(checks)}/{len(checks)} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
