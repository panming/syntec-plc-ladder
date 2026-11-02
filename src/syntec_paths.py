# -*- coding: utf-8 -*-
"""梯形图路径枚举 —— 不求串并联约简, 直接枚举「母排 → 每个负载」的全部通路。

为什么需要 (有两类结构串并联树装不下):

  1) 桥式跨接: 两个元件共用输入, 输出又分叉, 折不成 (A+B)·C 这种括号式子。
     物理上完全合法, 编辑器照常编译, 但树模型只能拒绝还原。
  2) 一条 rung 多个负载: 条件共享同一段前缀, 每个负载各走各的通路。
     这不是「并联块」—— 并联块要求分支各自完整, 共享的那段只写一次就写不出来。

梯形图的物理语义本来就很简单: 左边火线, 右边负载, 任何一条连通的路径都让它得电。
所以逻辑值 = 所有通路的 OR-of-AND。串并联树只是这种「通路集合」的一种压缩写法
(`(A∥B)→C` 写成 `(A+B)·C`), 压不下去的时候, 回到通路列表就永远有答案。

求值模型的四条约定 (每一条都对应一类真实故障):
  * 元件边只能从**左端子流向右端子**。竖线/横线是等电位点, 由并查集合并。
    允许反向穿行会把 `/A18` 当成从右往左导通, 凭空多出通路。
  * 比较块(CMP)是**条件**, 不是负载 —— 结果为真才导通 (手册 1-2.7)。
  * 功能块(定时器/计数器/算术/搬移/逻辑运算)是 **gate**: 它自己是被驱动的负载,
    但对下游而言是**条件** —— 只有定时器到达设定时间 (手册 1-2.10「输出讯号为 ON」)
    或运算导通之后, 后面的负载才得电。旧版把串联功能块当恒通, 等于少算一个 AND 项。
  * 线圈是**负载**, 是通路终点, 不进入条件。把 `=C1` 算进 R590.17 的条件里,
    就成了「C1 亮着 R590.17 才亮」, 与真实逻辑完全无关。
    线圈串在中间的情形手册未明说, 暂按恒通, 不假装已经求证。
"""
import syntec_parse as P
import syntec_layout as Y

# 单条 rung 的路径数上限。11 条真机桥式 rung 实测最多 13 条, 这里留了三个数量级
# 的余量; 超过就标记 truncated, 宁可少算也不把机器拖死。
MAX_PATHS = 20000

_COND_TAGS = ('CONTACT', 'CONTACT_T', 'CONTACT_C', 'RAW')


def kind_of(el):
    """元件分类: 'cond' 条件 / 'gate' 串联功能块 / 'load' 负载 / 'other' 流程块。

    gate 是 2026-11-02 现场纠正后新增的类别: 定时器/运算块既是被驱动的负载,
    又对下游构成条件。手册 1-2.10「定时器到达设定时间时输出讯号为 ON」、
    1-2.7「比较结果为真时输出讯号为 ON」—— 都不是一条直通线。
    RAW 归条件 —— 读不懂的单元, 当作"可能导通也可能断开", 至少不会丢通路。
    """
    t = el[0]
    if t in _COND_TAGS:
        return 'cond'
    if t == 'COIL':
        return 'load'
    if t == 'FB':
        if el[1] == 'CMP':
            return 'cond'
        if el[1] == 'FLOW':
            return 'other'              # FEND / END / JSR / LAB / RTS, 不参与求值
        return 'gate'                   # TIMER / CNTR / MATH / MOVE / LOGIC
    return 'other'


def literal(el):
    """元件 -> (键, 是否取反)。用来查「同一项里 A 与 /A 同时出现」= 恒假,
    也用作真值表的变量键。功能块用 '@标签' 做键, 不与触点地址冲突。"""
    t = el[0]
    if t == 'CONTACT':
        return (Y.dev_name(el[2]), el[1] == 'NC')
    if t == 'CONTACT_T':
        return (f'TM{el[2]}', el[1] == 'NC')
    if t == 'CONTACT_C':
        return (f'CT{el[2]}', el[1] == 'NC')
    if t == 'FB':
        return ('@' + Y.el_label(el), False)
    return None


# ==================== 吸收律 ====================
def absorb(terms):
    """布尔吸收律 A + A·B = A: 若某一项的字母集合真包含另一项, 删掉长的。
    输入/输出都是 tuple(保序, 便于按物理顺序渲染), 比较时按 frozenset。"""
    uniq, seen = [], set()
    for t in terms:
        k = frozenset(t)
        if k in seen:
            continue
        seen.add(k)
        uniq.append(t)
    keys = [frozenset(t) for t in uniq]
    keep = []
    for i, t in enumerate(uniq):
        if any(j != i and keys[j] < keys[i] for j in range(len(uniq))):
            continue
        keep.append(t)
    return keep


def contradictory(term):
    """同一项里同一地址既有常开又有常闭 -> 该项永假。"""
    seen = {}
    for el in term:
        lit = literal(el)
        if lit is None:
            continue
        addr, neg = lit
        if addr in seen and seen[addr] != neg:
            return True
        seen[addr] = neg
    return False


def clean(terms):
    """去矛盾项 + 吸收。返回 (有效项, 被丢掉的矛盾项)。"""
    good, dead = [], []
    for t in terms:
        (dead if contradictory(t) else good).append(t)
    return absorb(good), absorb(dead)


# ==================== 图 ====================
def build(rows, r0, r1):
    """把 [r0, r1] 这几行建成一张有向图。

    返回 dict(edges, adj, starts) 或 None (无内容)。
      edges: [{'u','v','el','kind','row','col'}]  u/v 是并查集归一后的端子
      adj:   {节点: [出边下标]}      只含 u -> v 方向, 所以只能从左往右走
      starts: 接在左母排上的节点集合
    """
    gd = P.guides(rows)
    dsu = P._comp(rows, gd, r0, r1)
    content = [(r, i, c) for r in range(r0, r1 + 1)
               for i, c in enumerate(rows[r]) if P.is_content(c)]
    if not content:
        return None

    edges = []
    for r, i, c in content:
        el = c[1]
        edges.append({'u': dsu.find((r, i)),
                      'v': dsu.find((r, i + P.span_of_slot(c))),
                      'el': el, 'kind': kind_of(el), 'row': r, 'col': i})

    adj = {}
    for k, e in enumerate(edges):
        adj.setdefault(e['u'], []).append(k)

    # 左母排 = 那几行的列 0。竖线/横线已经把等电位点并过, 所以直接取 find((r,0))。
    # 分支行的列 0 若是 EMPTY, 它不会被并到任何元件的端子上, 自然不在 adj 里, 不会误当起点。
    starts = {dsu.find((r, 0)) for r in range(r0, r1 + 1)} & set(adj)
    return {'edges': edges, 'adj': adj, 'starts': starts}


def enumerate_paths(graph, target, max_paths=MAX_PATHS):
    """枚举 起点 → target 的所有简单通路 (节点不重复)。返回 ([tuple(边下标)], 是否截断)。

    剪枝用**节点**而不是边: 电流不会绕回已经过的等电位点。只按边去重的话,
    `A→B→C→B→D` 这种回流也会被当成一条通路, 算出来的项通常带 A·/A,
    只好靠矛盾检测事后剔除 —— 治标不治本。并联的两支仍能各走一次, 因为
    分叉点只在路径起点出现过。

    用显式栈而不是递归: 一条 rung 最多 256 行、上千条边, 递归会撞栈深限制。
    """
    edges, adj, starts = graph['edges'], graph['adj'], graph['starts']
    out = []
    for s in starts:
        if s == target:                 # 负载直接接母排: 空通路 = 恒真
            out.append(())
            continue
        visited = {s}
        path = []
        iters = [iter(adj.get(s, ()))]
        while iters:
            if len(out) >= max_paths:
                return out, True
            try:
                k = next(iters[-1])
            except StopIteration:
                iters.pop()
                if path:
                    visited.discard(edges[path.pop()]['v'])
                continue
            e = edges[k]
            if e['v'] == target:
                out.append(tuple(path + [k]))
                continue
            if e['v'] in visited:
                continue
            visited.add(e['v'])
            path.append(k)
            iters.append(iter(adj.get(e['v'], ())))
    return out, False


# ==================== 通路 -> 表达式 ====================
def term_of(path, edges):
    """一条通路 -> (条件元件 tuple, 途经的负载 tuple)

    条件按元件去重: 串联两个一模一样的触点等于一个 (A·A = A)。不去重的话
    渲染出来是 `A282·/A193·/A193·A190`, 而矛盾检测又按"同地址正负都出现"
    判恒假, 两个 /A193 会被误认成 /A193·A193 —— 白报一堆死项。

    串在前面的功能块 (gate) 要算进条件: 下游负载只有在它导通时才得电。
    旧版把它只记进 through (视为恒通), 求出来的表达式会少一个 AND 项。
    """
    conds, through, seen = [], [], set()
    for k in path:
        e = edges[k]
        if e['kind'] in ('cond', 'gate'):
            if e['el'] in seen:
                continue
            seen.add(e['el'])
            conds.append(e['el'])
        elif e['kind'] == 'load':
            through.append(e['el'])
        if e['kind'] == 'gate':
            through.append(e['el'])       # 仍列出「途经」, 供上层提示用
    return tuple(conds), tuple(through)


def term_text(term):
    return '·'.join(Y.el_label(e) for e in term)


def sop_text(terms, dead=()):
    """SOP -> 人读文本。空项 = 恒真(1), 无有效项 = 恒假(0)。"""
    if not terms:
        return '0' if dead else '1'
    parts = [term_text(t) or '1' for t in terms]
    return ' + '.join(parts)


# ==================== 主入口 ====================
def analyze(rows, r0, r1, max_paths=MAX_PATHS):
    """分析一条 rung 的全部负载及其使能条件。

    返回:
      n_edges / n_paths / truncated
      loads: [{'el','addr','row','col','terms','text','through','dead',
               'n_paths','unreachable'}]
        terms      保序 tuple 列表, 外层 OR 内层 AND
        through    通路上串着的其它功能块/负载 (gate 同时是下游负载的条件)
        dead       被判为恒假而丢掉的项 (通常是有 A 又有 /A)
        unreachable 一条通路都没有 -> 这个负载悬空
      notes: 结构层面值得提醒的话
    """
    out = {'loads': [], 'notes': [], 'truncated': False,
           'n_edges': 0, 'n_paths': 0}
    g = build(rows, r0, r1)
    if g is None:
        return out

    edges = g['edges']
    out['n_edges'] = len(edges)
    if not g['starts']:
        out['notes'].append('没有任何元件接在左母排上')
        return out

    for k, e in enumerate(edges):
        if e['kind'] not in ('load', 'gate'):
            continue
        paths, trunc = enumerate_paths(g, e['u'], max_paths)
        out['truncated'] = out['truncated'] or trunc
        out['n_paths'] += len(paths)

        raw, through, dead = [], set(), []
        for p in paths:
            conds, thr = term_of(p, edges)
            raw.append(conds)
            through.update(thr)
        terms, dead = clean(raw)

        rec = {'el': e['el'], 'addr': Y.el_label(e['el']),
               'row': e['row'] + 1, 'col': e['col'],
               'terms': terms, 'dead': dead,
               'through': [Y.el_label(x) for x in through],
               'n_paths': len(paths),
               'unreachable': not paths}
        rec['text'] = '—' if rec['unreachable'] else sop_text(terms, dead)
        out['loads'].append(rec)

    if out['truncated']:
        out['notes'].append(f'通路数超过 {max_paths} 条, 已截断 (结果不完整)')
    return out


# ==================== 与串并联树交叉验证 ====================
def tree_terms(node):
    """网络树 -> SOP (tuple 列表)。PARALLEL 是集合并, SERIES 是笛卡尔积。
    用来验证路径枚举的结果与既有的树模型一致 —— 两条独立路径算同一件事,
    对得上才说明枚举没走错。"""
    t = node[0]
    if t == 'LEAF':
        return [(node[1],)]
    if t == 'PARALLEL':
        acc = []
        for c in node[1]:
            acc.extend(tree_terms(c))
        return absorb(acc)
    if t == 'SERIES':
        acc = [()]
        for c in node[1]:
            sub = tree_terms(c)
            acc = [a + b for a in acc for b in sub]
        return absorb(acc)
    raise ValueError(t)


def eval_terms(terms, values):
    """给一组触点取值 {(地址, 取反): bool}, 算 SOP 的真值"""
    return any(all(values.get(literal(el), False) for el in t) for t in terms)


def tree_leaves(node, acc=None):
    """收集树里所有条件元件 (负载与流程块由调用方过滤)"""
    if acc is None:
        acc = []
    if node[0] == 'LEAF':
        acc.append(node[1])
    else:
        for c in node[1]:
            tree_leaves(c, acc)
    return acc
