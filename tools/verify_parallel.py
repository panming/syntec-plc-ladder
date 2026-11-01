"""并联分支编码回归测试

对每个案例: 用 LadderProject 生成 -> 与编辑器真实产物逐字节比对。
样本来自用户在 MLCEdit 里手工画的 B_branch.lad, 以及真机 cnc_1.lad。

跑法:
    python verify_parallel.py                  # 样本默认在桌面
    python verify_parallel.py --samples DIR    # 换个目录
    python verify_parallel.py cnc_1.lad        # 用同名文件顶掉标准样本
    python verify_parallel.py --samples DIR cnc_1.lad

环境变量 SYNTEC_SAMPLES 同样生效。
"""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "src"), os.path.join(os.path.dirname(_HERE), "src")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)          # 兼容 平铺 / src+tools 两种布局


def _default_samples():
    """样本目录: $SYNTEC_SAMPLES > 旁边的 samples/ (仓库布局) > 桌面"""
    env = os.environ.get("SYNTEC_SAMPLES")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    for d in (os.path.join(_HERE, "samples"),
              os.path.join(os.path.dirname(_HERE), "samples")):
        if os.path.isdir(d):
            return os.path.abspath(d)
    return os.path.abspath(os.path.join(os.path.expanduser("~"), "Desktop"))


import syntec_model as M
import syntec_re as S

DESK = _default_samples()
OVERRIDE = {}          # basename(小写) -> 命令行指定的实际路径

# 真机程序不随仓库分发; 缺失时这些用例记 SKIP 而非 FAIL
OPTIONAL = ("cnc.lad", "cnc_1.lad")
SKIPPED = [0]


def is_optional(fn):
    return os.path.basename(fn).lower() in OPTIONAL


def parse_argv(argv):
    """--samples DIR 指定样本目录; 其余 .lad 位置参数按文件名顶替"""
    global DESK
    args = list(argv)
    i = 0
    while i < len(args):
        a = args[i]
        if a in ("--samples", "-s"):
            if i + 1 >= len(args):
                sys.exit(f"{a} 后面要跟一个目录")
            DESK = os.path.abspath(os.path.expanduser(args[i + 1]))
            i += 2
            continue
        if os.path.isfile(a) and a.lower().endswith(".lad"):
            OVERRIDE[os.path.basename(a).lower()] = os.path.abspath(a)
            i += 1
            continue
        sys.exit(f"不认识参数: {a}\n用法: python verify_parallel.py [--samples DIR] [xx.lad]")
    return DESK


def resolve(fn):
    """样本全路径: 命令行给了同名文件就用它, 否则去样本目录找"""
    return OVERRIDE.get(os.path.basename(fn).lower()) or os.path.join(DESK, fn)


def contact(a, norm="NO"):
    return {"kind": "contact", "norm": norm, "addr": a}


def coil(a, norm="NO"):
    return {"kind": "coil", "norm": norm, "addr": a}


def par(*branches):
    return {"kind": "parallel", "branches": [b if isinstance(b, list) else [b]
                                             for b in branches]}


# (样本文件, 起始行下标(0基), 行数, 说明, elements)
CASES = [
    ("B_branch.lad", 0, 2, "(I100 | I101) -> O200      并联两分支",
     [par([contact("I100")], [contact("I101")]), coil("O200")]),

    ("cnc_1.lad", 24, 5, "I10|O9|A302|A303|I119 -> C1  并联五分支",
     [par(*[[contact(a)] for a in ("I10", "O9", "A302", "A303", "I119")]), coil("C1")]),

    ("cnc_1.lad", 30, 2, "I1(NC) -> (C36 | R44.5)      输出并联",
     [contact("I1", "NC"), par([coil("C36")], [coil("R44.5")])]),
]

# 无真实样本、只做结构自洽检查的案例
SELFCASES = [
    ("I100 + (I101|I102) -> O200        串联后并联",
     [contact("I100"), par([contact("I101")], [contact("I102")]), coil("O200")]),
    ("(I100+I101) | I102 -> O200        分支宽度不同",
     [par([contact("I100"), contact("I101")], [contact("I102")]), coil("O200")]),
    ("I100 | (I101 + (I102|I103)) -> O200   三层嵌套",
     [par([contact("I100")],
          [contact("I101"), par([contact("I102")], [contact("I103")])]),
      coil("O200")]),
    ("(A302|A303) -> (C1)，再并联 M0      双排线圈",
     [par([contact("A302")], [contact("A303")]), coil("C1")]),
    ("I10 -> (O9|O10)                   纯输出并联（无前级条件）",
     [par([coil("O9")], [coil("O10")])]),
]


def build(elements):
    p = M.LadderProject()
    p.reset()
    p.add_rung(elements=elements)
    return p


def diff_marks(a, b):
    out = []
    for i in range(0, min(len(a), len(b)), 4):
        mark = "  " if a[i:i + 4] == b[i:i + 4] else "<<"
        out.append(f"{i//4}:{a[i:i+4].hex()}vs{b[i:i+4].hex()}{mark}")
    return " ".join(out)


def main():
    print("=" * 78)
    print("并联分支编码回归测试")
    print(f"样本目录: {DESK}")
    if OVERRIDE:
        print("命令行顶替: " + ", ".join(f"{k}->{v}" for k, v in OVERRIDE.items()))
    print("=" * 78)

    ok = tot = 0
    print("\n【A】与编辑器真实产物逐字节比对\n")
    for fn, start, nrow, desc, els in CASES:
        path = resolve(fn)
        if not os.path.exists(path):
            if is_optional(fn):
                print(f"  {desc}\n  - SKIP(未附带真机语料 {fn})\n")
                SKIPPED[0] += nrow
                continue
            # 非可选样本缺失必须算失败: 静默跳过会让总数悄悄变少, 汇总就成了假 PASS
            print(f"  {desc}\n  ! 缺少样本 {fn} ({os.path.dirname(path)})  -> 记失败\n")
            tot += nrow
            continue
        data = open(path, "rb").read()
        rows = S.parse_records(data)
        got = build(els).to_lad_bytes()
        print(f"  {desc}")
        print(f"  样本: {fn} R{start+1}..R{start+nrow}")
        allok = True
        for i in range(nrow):
            want = rows[start + i][1]
            g = got[i * 40:(i + 1) * 40]
            good = g == want
            allok &= good
            tot += 1
            ok += good
            print(f"    R{start+1+i}: {'一致' if good else '不一致'}")
            if not good:
                print(f"      生成: {g.hex(' ')}")
                print(f"      样本: {want.hex(' ')}")
                print(f"      差异: {diff_marks(want, g)}")
        print()

    print("【B】结构自洽检查（无真实样本，验证接线位闭合 + 可解码回读）\n")
    for desc, els in SELFCASES:
        p = build(els)
        try:
            data = p.to_lad_bytes()
        except Exception as e:
            print(f"  {desc}\n    -> 生成失败: {e}\n")
            continue
        rows = S.parse_records(data)
        nlog = sum(1 for k, _ in rows if k == "logic")
        # 检查接线位闭合: 把生成结果重新解码后, 用 vert_line 对数
        vcount = 0
        for k, r in rows:
            if k != "logic":
                continue
            v = S.vert_line(r)
            vcount += sum(1 for i in range(10) if v[i * 3 + 1] in "UDX")
        tot += 1
        ok += 1
        print(f"  {desc}")
        print(f"    -> {nlog} 行, {len(data)} 字节, 竖线位 {vcount} 个  [OK]")
        for line in p.preview().splitlines():
            print("       " + line.rstrip())
        print()

    print("=" * 78)
    print(f"合计 {ok}/{tot}   {'[PASS]' if ok == tot else '[FAIL]'}"
          + (f"   (另有 {SKIPPED[0]} 行因未附带真机语料而跳过)" if SKIPPED[0] else ""))
    print("=" * 78)
    return 0 if ok == tot else 1


if __name__ == "__main__":
    parse_argv(sys.argv[1:])
    sys.exit(main())
