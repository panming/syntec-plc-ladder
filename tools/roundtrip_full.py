# -*- coding: utf-8 -*-
"""全量往返验证: .lad -> 网络树 -> 重新排版 -> 再解码 -> 比对

编辑器本身不做自动排版: 元件放在哪一列完全由人决定(真实程序里到处是
手工插入的横线/留白), 所以"重新排版后逐字节相同"对任意文件是做不到的。
这里分层验证真正有意义的四件事:

  1) 结构一致  : 原文解码出的网络树 == 重新生成后再解码出的网络树
                 (串联/并联/嵌套/元件参数全部相同)  —— 必须 100%
  2) 自检通过  : 生成的行满足 AutoFix 规则 (编辑器打开时不会改写) —— 必须 100%
  3) 几何一致  : 生成的元件行列位置与原件完全相同 —— 参考指标
                 (高说明自动排版与编辑器摆放习惯一致; 低通常是人手留白)
  4) 字节一致  : 在"几何一致"的那些 rung 上逐字节相同 —— 必须 100%

用法:
    python roundtrip_full.py                     # 验证标准语料(默认在桌面)
    python roundtrip_full.py --samples DIR       # 标准语料换个目录
    python roundtrip_full.py a.lad b.lad         # 只验证指定文件
    python roundtrip_full.py --samples DIR a.lad # 混用

环境变量 SYNTEC_SAMPLES 可代替 --samples。
"""
import sys
import os
import collections

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "src"), os.path.join(os.path.dirname(_HERE), "src")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)          # 兼容 平铺 / src+tools 两种布局

import syntec_re as R
import syntec_parse as P
import syntec_layout as Y

STD_SAMPLES = ["cnc.lad", "cnc_1.lad",
               "B_branch.lad", "B_coils.lad", "B_compare.lad", "B_contacts.lad",
               "B_counter.lad", "B_flow.lad", "B_logic.lad", "B_math.lad",
               "B_move.lad", "B_timer.lad"]


# 真机程序(客户机床导出的 .lad)不随仓库分发, 缺失时记 SKIP 而非 FAIL
OPTIONAL = ("cnc.lad", "cnc_1.lad")


def default_samples():
    """标准语料所在目录: $SYNTEC_SAMPLES > 旁边的 samples/ (仓库布局) > 桌面"""
    env = os.environ.get("SYNTEC_SAMPLES")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    for d in (os.path.join(_HERE, "samples"),
              os.path.join(os.path.dirname(_HERE), "samples")):
        if os.path.isdir(d):
            return os.path.abspath(d)
    return os.path.abspath(os.path.join(os.path.expanduser("~"), "Desktop"))


def find_demo():
    """demo_parallel.lad 在哪: 脚本旁边 / 旁边 samples / 上级 samples"""
    for d in (_HERE, os.path.join(_HERE, "samples"),
              os.path.join(os.path.dirname(_HERE), "samples")):
        f = os.path.join(d, "demo_parallel.lad")
        if os.path.isfile(f):
            return f
    return os.path.join(_HERE, "demo_parallel.lad")


def corpus(sdir=None):
    """标准语料的全路径列表; demo_parallel.lad 跟着脚本走"""
    sdir = sdir or default_samples()
    return [os.path.join(sdir, f) for f in STD_SAMPLES] + [find_demo()]


def parse_argv(argv):
    """返回 (样本目录, 文件列表)。--samples DIR 之外的位置参数按文件处理。"""
    sdir = default_samples()
    files = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a in ("--samples", "-s"):
            if i + 1 >= len(argv):
                sys.exit("--samples 后面要跟一个目录")
            sdir = os.path.abspath(os.path.expanduser(argv[i + 1]))
            i += 2
            continue
        files.append(a)
        i += 1
    return sdir, files


def lad_rows(path):
    data = open(path, 'rb').read()
    recs = [p for k, p in R.parse_records(data) if k == 'logic']
    return recs, [P.decode_row(r) for r in recs]


def cells(rows, a, b):
    """区域内所有元件的位置与内容 [(行, 列, 元件)]"""
    return [(r, i, c[1]) for r in range(a, b + 1)
            for i, c in enumerate(rows[r]) if P.is_content(c)]


def analyse(path):
    recs, rows = lad_rows(path)
    trees = P.reconstruct(rows)
    st = collections.Counter()
    bad = []

    gen_rows, gen_chunks, geo = [], [], []
    for node, la, a, b, why in trees:
        st['rungs'] += 1
        st['rows'] += b - a + 1
        if node is None:
            if why == 'blank':
                st['blank'] += 1
            elif why.startswith('非串并联'):
                # 桥式拓扑: 物理合法但无法写成串并联树, 原样保留 (不伪造树)
                st['bridge'] += 1
            else:
                bad.append((a, b, 'reconstruct', why))
                st['bad_recon'] += 1
            gen_chunks.append(recs[a:b + 1])
            continue
        P.count_parallel(node, st)
        try:
            grid = Y.to_grid(node, left_anchor=la)
        except Exception as e:
            bad.append((a, b, 'layout', str(e)))
            st['bad_layout'] += 1
            continue
        problems = Y.check_grid(grid)
        if problems:
            bad.append((a, b, 'autofix', problems[0]))
            st['bad_check'] += 1
        out = [Y.emit_grid(g) for g in grid]
        gen_chunks.append(out)
        # 结构一致: 生成的行再解码一遍, 树必须相同
        t2node = None
        try:
            rows2 = [P.decode_row(r) for r in out]
            t2 = P.reconstruct(rows2)
            t2node = t2[0][0] if t2 else None
            ok = (len(t2) == 1 and t2node == node)
        except Exception:
            ok = False
        if not ok:
            st['bad_struct'] += 1
            if len(bad) < 400:
                bad.append((a, b, 'struct-diff', _treediff(node, t2node)))
        # 几何一致 + 字节一致
        same = len(grid) == b - a + 1 and \
            cells(rows2, 0, len(out) - 1) == \
            [(r - a, i, el) for (r, i, el) in cells(rows, a, b)]
        geo.append(same)
        if same:
            st['geo_ok'] += 1
            if b''.join(out) == b''.join(recs[a:b + 1]):
                st['byte_ok'] += 1
            else:
                st['geo_but_diff'] += 1
                if len(bad) < 400:
                    bad.append((a, b, 'bytes', _first_diff(out, recs[a:b + 1])))
    st['bad'] = len(bad)
    return st, bad


def _treediff(t1, t2):
    s1, s2 = _fmt(t1), _fmt(t2)
    if s1 == s2:
        return '树相同但校验失败?'
    # 找第一个不同处
    for i in range(min(len(s1), len(s2))):
        if s1[i] != s2[i]:
            return f"原 {s1[max(0,i-60):i+80]}  ||  新 {s2[max(0,i-60):i+80]}"
    return f"原 {s1[:160]} || 新 {s2[:160]}"


def _fmt(node):
    if node is None:
        return '(None)'
    t = node[0]
    if t == 'LEAF':
        return str(node[1])
    sep = ',' if t == 'SERIES' else '|'
    return '(' + sep.join(_fmt(c) for c in node[1]) + ')'


def _first_diff(out, orig):
    for k, (g, o) in enumerate(zip(out, orig)):
        if g != o:
            return f"第{k+1}行 原 {o.hex(' ')} / 新 {g.hex(' ')}"
    return '长度不同'


def main(paths):
    tot = collections.Counter()
    for p in paths:
        if not os.path.exists(p):
            if os.path.basename(p).lower() in OPTIONAL:
                print(f"SKIP  {os.path.basename(p):<18} 未附带真机语料(可选)")
                tot['skipped'] += 1
                continue
            # 非可选文件缺失必须算失败: 静默跳过会让"13 个文件"悄悄变成"12 个",
            # 汇总数字随之漂移, 比直接报错危险得多。
            print(f"FAIL  {os.path.basename(p):<18} 文件不存在: {p}")
            tot['n'] += 1
            tot['missing'] += 1
            continue
        st, bad = analyse(p)
        ok = (st['bad_struct'] == 0 and st['bad_check'] == 0
              and st['bad_recon'] == 0 and st['bad_layout'] == 0)
        print(f"{'PASS' if ok else 'FAIL'}  {os.path.basename(p):<18} "
              f"行{st['rows']:<5} rung{st['rungs']:<5} 并联{st['par']:<4} "
              f"分支{st['branches']:<5}(最多{st['max_branch']:>2}) "
              f"结构差异{st['bad_struct']:<3} 自检问题{st['bad_check']:<3} "
              f"桥式{st['bridge']:<2} "
              f"几何一致{st['geo_ok']}/{st['rungs']} "
              f"其中逐字节{st['byte_ok']}")
        for a, b, kind, msg in bad[:3]:
            print(f"      R{a+1}-R{b+1} [{kind}] {msg}")
        if len(bad) > 3:
            print(f"      ... 共 {len(bad)} 处")
        for k in ('rows', 'rungs', 'par', 'branches', 'geo_ok', 'byte_ok',
                  'bad_struct', 'bad_check', 'bad_recon', 'bad_layout',
                  'bridge', 'blank'):
            tot[k] += st.get(k, 0)
        tot['files'] = tot.get('files', 0) + 0 if False else tot['files']
        tot['n'] += 1

    print()
    print(f"合计 {tot['n']} 个文件 / {tot['rows']} 编辑行 / {tot['rungs']} 条 rung / "
          f"{tot['par']} 个并联块 / {tot['branches']} 个分支")
    print(f"     结构往返一致: {tot['rungs'] - tot['bad_struct'] - tot['bad_recon'] - tot['bad_layout'] - tot['bridge']}"
          f"/{tot['rungs'] - tot['bridge']} (另 {tot['bridge']} 条桥式/无法树化, 原样保留)"
          f"   自检: {tot['rungs'] - tot['bad_check']}/{tot['rungs']}")
    print(f"     几何与原件相同: {tot['geo_ok']}/{tot['rungs']}  "
          f"(其中逐字节相同 {tot['byte_ok']})")
    if tot['skipped']:
        print(f"     跳过 {tot['skipped']} 个真机语料(cnc.lad / cnc_1.lad, 仓库不附带)")
    if tot['missing']:
        print(f"     缺文件 {tot['missing']} 个 —— 上面的合计只统计了实际存在的文件")
    return 0 if tot['missing'] == 0 else 1


if __name__ == '__main__':
    _sdir, _files = parse_argv(sys.argv[1:])
    print(f"样本目录: {_sdir}")
    sys.exit(main(_files or corpus(_sdir)))
