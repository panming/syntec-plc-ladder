# -*- coding: utf-8 -*-
"""路径枚举 vs 串并联树 —— 两套独立算法对同一批 rung 求值, 结果必须一致。

为什么值得单独写一个测试: 路径枚举是用来**替代**树模型在桥式/多负载上的盲区的。
如果两套算法在树能表达的那 319 条上都对不上, 那它在另外 11 条上的结论也不能信。

对每条「只有一个负载 + 树可表达」的 rung:
  树   -> tree_terms() 得到 SOP (把负载叶子剔掉, 只留条件)
  枚举 -> analyze() 得到该负载的 SOP
随机取 N 组触点取值, 两边真值必须逐组相同。

用法: python tools/verify_paths.py [lad ...]
"""
import os
import random
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import syntec_parse as P      # noqa: E402
import syntec_paths as PA     # noqa: E402
import syntec_read as RD      # noqa: E402

SAMPLES = 200


def load_rows(path):
    logic, _others, _tail = RD.split_records(open(path, "rb").read())
    return [P.decode_row(r) for r in logic]


def cond_only(node):
    """把树里的负载/流程块剔掉, 只留条件元件的 SOP"""
    terms = PA.tree_terms(node)
    out = []
    for t in terms:
        keep = tuple(e for e in t if PA.kind_of(e) == "cond")
        out.append(keep)
    return PA.absorb(out)


def labels_of(terms):
    s = set()
    for t in terms:
        s.update(t)
    return s


def self_checks():
    """三条判定各造一个必中的例子 —— 检查项本身也要有测试,
    否则它可能悄悄退化成「永远不报」而没人发现。

      O10: I100 串过来        -> 有条件, 正常
      O11: 直接接母排          -> 空项, 恒真(无条件输出)
      O12: A1 与 /A1 串联      -> 恒假, 永远不会动作
    """
    import tempfile
    import syntec_model as M

    C = lambda a, n="NO": {"kind": "contact", "norm": n, "addr": a}   # noqa: E731
    K = lambda a: {"kind": "coil", "norm": "NO", "addr": a}          # noqa: E731

    p = M.LadderProject()
    p.add_rung(elements=[C("I100"), K("O10")])
    p.add_rung(elements=[K("O11")])
    p.add_rung(elements=[C("A1"), C("A1", "NC"), K("O12")])
    p.add_rung(elements=[{"kind": "end"}])
    path = os.path.join(tempfile.gettempdir(), "syntec_paths_selfcheck.lad")
    p.save(path)

    rows = load_rows(path)
    res = PA.analyze(rows, 0, 2)
    got = {L["addr"]: L for L in res["loads"]}

    cases = [
        ("有条件", lambda: got["=O10"]["terms"] == [("CONTACT", "NO", M.addr_bits("I100"))]
         or len(got["=O10"]["terms"]) == 1),
        ("无条件判恒真", lambda: any(not t for t in got["=O11"]["terms"])),
        ("A·/A 判恒假", lambda: not got["=O12"]["terms"] and bool(got["=O12"]["dead"])),
    ]
    bad = []
    for name, fn in cases:
        ok = bool(fn())
        print(f"  [{'OK ' if ok else 'FAIL'}] 自检: {name}")
        if not ok:
            bad.append(name)
    return bad


def check_file(path, samples=SAMPLES, rng=None):
    rng = rng or random.Random(20261102)
    rows = load_rows(path)
    info = RD.read_ladder(path)

    checked, skipped_multi, skipped_tree = 0, 0, 0
    fails = []
    for r in info["rungs"]:
        if r["elements"] is None:
            if r["why"] != "空白行":
                skipped_tree += 1
            continue
        a, b = r["row_start"] - 1, r["row_end"] - 1
        res = PA.analyze(rows, a, b)
        if len(res["loads"]) != 1:
            skipped_multi += 1
            continue
        if res["loads"][0]["unreachable"]:
            fails.append((r["index"], "枚举认为该负载不可达, 但树能表达"))
            continue

        node = P.build_tree(rows, P.guides(rows), a, b)[0]
        t_terms = cond_only(node)
        p_terms = res["loads"][0]["terms"]

        # 直接比集合: 吸收律是规范的, 等价的两组 SOP 化简后应完全相同
        if {frozenset(t) for t in t_terms} != {frozenset(t) for t in p_terms}:
            # 集合不同时再用真值表兜底 —— 吸收律未必唯一 (幂等/具体化差异)
            lits = labels_of(t_terms) | labels_of(p_terms)
            bad = None
            for _ in range(samples):
                vals = {lit: rng.random() < 0.5 for lit in lits}
                if PA.eval_terms(t_terms, vals) != PA.eval_terms(p_terms, vals):
                    bad = vals
                    break
            if bad is not None:
                fails.append((r["index"], "真值不一致\n"
                              f"      树  : {PA.sop_text(t_terms)}\n"
                              f"      枚举: {PA.sop_text(p_terms)}"))
                continue
        checked += 1

    return checked, skipped_tree, skipped_multi, fails


def main():
    print("判定自检（恒真 / 恒假 / 有条件）")
    base_fail = self_checks()
    print()

    files = sys.argv[1:]
    if not files:
        here = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
        files = [os.path.join(here, "samples", n)
                 for n in sorted(os.listdir(os.path.join(here, "samples")))
                 if n.endswith(".lad")]

    total_checked = total_fail = 0
    for f in files:
        checked, sk_tree, sk_multi, fails = check_file(f)
        total_checked += checked
        total_fail += len(fails)
        print(f"{os.path.basename(f):<28} 交叉验证 {checked:>4} 条"
              f"（跳过: 树不可表达 {sk_tree}, 多负载 {sk_multi}）"
              f"  失败 {len(fails)}")
        for idx, why in fails:
            print(f"    × R{idx}: {why}")

    print()
    if total_fail or base_fail:
        if base_fail:
            print(f"判定自检失败: {base_fail}")
        if total_fail:
            print(f"失败 {total_fail} / {total_checked} 条 —— 两套算法结果不一致，"
                  f"说明路径枚举有 bug，桥式/多负载上的结论不可信")
        return 1
    print(f"全部一致（{total_checked} 条）—— 路径枚举与树模型在可对照的部分等价")
    return 0


if __name__ == "__main__":
    sys.exit(main())
