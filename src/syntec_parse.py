# -*- coding: utf-8 -*-
"""SYNTEC .lad 反序列化 —— 把已有文件还原成「网络树」, 供往返验证与 MCP 读取。

与 syntec_layout.py 互为逆过程:
    .lad (40 字节/行)  --decode-->  网格(conn + 元件)  --重建-->  网络树
    网络树  --syntec_layout.to_grid/emit_grid-->  网格  --emit-->  .lad

重建用的是"端子图 + 串并联约简", 不依赖原文件的列位:
  * 每个格子的左端子/右端子是图结点;
  * 竖线(conn)与横线(0x0d)是零阻边, 把端子并起来;
  * 每个元件是一条边;
  * 反复做并联约简(同一对端子的两条边)与串联约简(入度=出度=1 的端子),
    直到源端到汇端只剩一条边 —— 这棵边树就是 rung 的逻辑结构。

接线位判定 (与 syntec_layout 的写规则互逆):
    列边界 B 上, 第 r 行到第 r+1 行之间有竖线
      <=> 右边缘在 B 的格子(跨 B 的那个元件) conn bit1 (0x02) 置位
      <=> 左边缘在 B 的格子(从 B 开始的元件) conn bit2 (0x04) 置位

rung 划分: 竖线把若干行绑在一起, 因此"同一 rung" = 被竖线连通的连续行。
"""
import syntec_re as R

COLS = 10


# ==================== 单元解码 ====================
def decode_cell(op, raw):
    """4 字节单元 -> 语义元组 (与 syntec_lad.enc_el 的输入格式一致)"""
    if op == 0x00:
        return ('EMPTY',)
    if op == 0x0d:
        return ('WIRE',)
    if op == 0xcf:
        return ('END',)
    if op == 0xd0:
        return ('FLOW4', 0xd0)
    if op == 0xfd:
        return ('FLOW4', 0xfd)
    if op in (0x01, 0x03):
        return ('CONTACT', 'NO' if op == 0x01 else 'NC', raw[2] | (raw[3] << 8))
    if op in (0x09, 0x0a):                     # 定时器触点: 编号只占 1 字节
        return ('CONTACT_T', 'NO' if op == 0x09 else 'NC', raw[2])
    if op in (0x0b, 0x0c):                     # 计数器触点
        return ('CONTACT_C', 'NO' if op == 0x0b else 'NC', raw[2])
    for name, code in (('NO', 0x0e), ('NC', 0x10), ('RP', 0x05),
                       ('FP', 0x07), ('LATCH', 0x12), ('UNLATCH', 0x14)):
        if op == code:
            return ('COIL', name, raw[2] | (raw[3] << 8))
    return ('RAW', bytes(raw))


def decode_block(op, buf):
    """8 字节单元 -> 语义元组"""
    info = R.op_info(op)
    if not info:
        return ('RAW', bytes(buf))
    g, f = info['group'], info['func']
    A = buf[2] | (buf[3] << 8)
    B = buf[4] | (buf[5] << 8)

    if g == 'Function':
        cat = {0: 'MATH', 1: 'MATH', 2: 'MATH', 3: 'MATH',
               4: 'CMP', 5: 'CMP', 6: 'CMP',
               7: 'MOVE', 8: 'LOGIC', 9: 'LOGIC', 10: 'LOGIC'}[f]
        return ('FB', cat, op, A, B, bytes(buf[4:8]))
    if g == 'Timer':
        return ('FB', 'TIMER', op, A, 0, bytes(buf[4:8]))
    if g == 'Counter':
        return ('FB', 'CNTR', op, A, 0, bytes(buf[4:8]))
    if g == 'Flow':
        return ('FLOW8', op, bytes(buf[2:8]))     # 标签字节原样保留
    if g == 'Tool' and f == 0:
        return ('FB', 'ROT', op, A, B, bytes(buf[4:8]))
    return ('RAW', bytes(buf))


def decode_row(rec):
    """40 字节 -> 10 槽; 8 字节单元的第 2 列记 None
       每槽 = (conn, 语义元组, 原始字节) 或 None"""
    slots, i = [], 0
    while i < COLS:
        c0 = i * 4
        op = rec[c0 + 1]
        if R.is_bi(op) and i < COLS - 1:
            raw = bytes(rec[c0:c0 + 8])
            slots.append((rec[c0], decode_block(op, raw), raw))
            slots.append(None)
            i += 2
        else:
            raw = bytes(rec[c0:c0 + 4])
            slots.append((rec[c0], decode_cell(op, raw), raw))
            i += 1
    return slots


def span_of_slot(cell):
    return 1 if cell is None else len(cell[2]) // 4


NON_ELEMENT = ('EMPTY', 'WIRE')


def is_content(cell):
    return cell is not None and cell[1][0] not in NON_ELEMENT


# ==================== 竖线 / rung ====================
def guides(rows):
    """返回 [(B, r0, r1)]: 列边界 B 上从 r0 到 r1 行的竖线"""
    out = []
    n = len(rows)
    for B in range(1, COLS):
        left_at = {}                       # row -> 右边缘在 B 的那个格子的 conn
        for r, slots in enumerate(rows):
            for i, cell in enumerate(slots):
                if cell is None:
                    continue
                if i + span_of_slot(cell) == B:
                    left_at[r] = cell[0]
        r = 0
        while r < n - 1:
            if not (left_at.get(r, 0) & 0x02):
                r += 1
                continue
            r0 = r
            while r < n - 1 and (left_at.get(r, 0) & 0x02):
                r += 1
            out.append((B, r0, r))
    return out


def conn_conflicts(rows):
    """AutoFixOneLine 检查: 左格 bit1/bit0 必须与右格 bit2/bit3 一致"""
    bad = []
    for r, slots in enumerate(rows):
        for c in range(COLS - 1):
            a, b = slots[c], slots[c + 1]
            if a is None or b is None:
                continue
            if bool(a[0] & 0x01) != bool(b[0] & 0x04):
                bad.append((r, c, 'upper', a[0], b[0]))
            if bool(a[0] & 0x02) != bool(b[0] & 0x08):
                bad.append((r, c, 'lower', a[0], b[0]))
    return bad


def rung_groups(rows):
    """按竖线连通性把行切成若干 rung, 返回 [(r0, r1)]"""
    n = len(rows)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for _B, a, b in guides(rows):
        for r in range(a, b):
            union(r, r + 1)

    groups, start = [], 0
    for r in range(1, n + 1):
        if r == n or find(r) != find(start):
            groups.append((start, r - 1))
            start = r
    return groups


# ==================== 网络树重建 (端子图 + 串并联约简) ====================
class _DSU:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[ra] = rb


def leaf(el):
    return ('LEAF', el)


def series(nodes):
    """串联节点; 同类型嵌套就地摊平 (串联的串联 = 串联)"""
    flat = []
    for n in nodes:
        if n[0] == 'SERIES':
            flat.extend(n[1])
        else:
            flat.append(n)
    return ('SERIES', flat)


def parallel(nodes):
    """并联节点; 同类型嵌套就地摊平"""
    flat = []
    for n in nodes:
        if n[0] == 'PARALLEL':
            flat.extend(n[1])
        else:
            flat.append(n)
    return ('PARALLEL', flat)


def _flow_only(rows, r0, r1):
    """整条 rung 只有流程块(END/LAB/RTS/JSR) => 不参与串并联"""
    kinds = set()
    for r in range(r0, r1 + 1):
        for cell in rows[r]:
            if is_content(cell):
                kinds.add(cell[1][0])
    return bool(kinds) and kinds <= {'FLOW8', 'FLOW4', 'END'}


def _row_leaves(rows, r, lo, hi, keep_raw=False):
    out, i = [], lo
    while i < hi:
        cell = rows[r][i]
        if is_content(cell):
            out.append(leaf(('RAW', cell[2]) if keep_raw else cell[1]))
        i += max(1, span_of_slot(cell))
    return out


def _comp(rows, gd, r0, r1):
    """端子并查集: 竖线 + 横线(0x0d) 把端子连起来"""
    dsu = _DSU()
    for r in range(r0, r1 + 1):
        for B in range(COLS + 1):
            dsu.find((r, B))
    for B, a, b in gd:
        for r in range(a, b):
            dsu.union((r, B), (r + 1, B))
    for r in range(r0, r1 + 1):
        i = 0
        while i < COLS:
            cell = rows[r][i]
            sp = span_of_slot(cell)
            if cell is not None and cell[1][0] == 'WIRE':
                for k in range(i, i + sp):
                    dsu.union((r, k), (r, k + 1))
            i += sp
    return dsu


def _mk_edge(u, v, kind, row, col, payload=None, kids=None):
    return {'u': u, 'v': v, 'kind': kind, 'row': row, 'col': col,
            'payload': payload, 'kids': kids or []}


def _sub(e):
    """把一条边包成"子边描述"(统一形状, 不含 u/v)。
    注意: 必须原样保留这条边的层级 —— 并联边如果被摊开,
    串接时就会把两个分支变成串联, 结构就错了。"""
    return [{'kind': e['kind'], 'row': e['row'], 'col': e['col'],
             'payload': e['payload'], 'kids': list(e['kids'])}]


def _flat(e, kind):
    """把同类型的嵌套边摊平, 返回 [(排位键, 子树)] —— 尚未排序。
    排位键: 并联用最靠上的行号, 串联用最靠左的列号。"""
    if e['kind'] == 'leaf' or (e['kind'] == 'par') != (kind == 'PARALLEL'):
        return [(e['col'] if kind == 'SERIES' else e['row'], _edge_tree(e))]
    out = []
    for k in e['kids']:
        out.extend(_flat(k, kind))
    return out


def _edge_tree(e):
    """边 -> 网络树。
    注意: 同类型嵌套必须在"摊平"时按位置重新排序 —— 归并顺序(先合并哪两条)
    与视觉顺序无关; 若先摊平再排序, 整棵子树会带着它的最小行号一起挤到前面,
    分支上下顺序就乱了 (cnc_1.lad R15-R19 的 3 分支曾排成 0,2,1)。"""
    if e['kind'] == 'leaf':
        return leaf(e['payload'])
    kind = 'PARALLEL' if e['kind'] == 'par' else 'SERIES'
    items = _flat(e, kind)
    items.sort(key=lambda x: x[0])
    return (kind, [t for _k, t in items])


def _strip_dummy(node):
    """去掉源/汇两条哑边 (payload = WIRE)"""
    if node[0] == 'LEAF':
        return None if node[1] == ('WIRE',) else node
    kids = [k for k in (_strip_dummy(c) for c in node[1]) if k is not None]
    if not kids:
        return None
    if len(kids) == 1:
        return kids[0]
    return (node[0], kids)


def build_tree(rows, gd, r0, r1, keep_raw=False):
    """返回 (node, 问题说明) —— node 为 None 表示该 rung 无法重建"""
    content = [(r, i, c) for r in range(r0, r1 + 1)
               for i, c in enumerate(rows[r]) if is_content(c)]
    if not content:
        return None, 'blank'

    if _flow_only(rows, r0, r1):
        if r1 != r0:
            return None, '流程块跨多行'
        return series(_row_leaves(rows, r0, 0, COLS, keep_raw)), None

    bmax = max(i + span_of_slot(c) for _r, i, c in content)
    if bmax > COLS:
        return None, f'内容超出 {COLS} 列'
    dsu = _comp(rows, gd, r0, r1)
    SRC, SNK = ('SRC',), ('SNK',)
    edges = []
    for r, i, c in content:
        payload = ('RAW', c[2]) if keep_raw else c[1]
        edges.append(_mk_edge(dsu.find((r, i)),
                              dsu.find((r, i + span_of_slot(c))),
                              'leaf', r, i, payload))
    # 母线哑边: 只有确实接在左/右母线端点上的行才连。
    # 分支行在并联块的竖线处合流, 它接不到最右列, 不能硬连到汇点。
    touched = set()
    for e in edges:
        touched.add(e['u'])
        touched.add(e['v'])
    for r in range(r0, r1 + 1):
        if dsu.find((r, 0)) in touched:
            edges.append(_mk_edge(SRC, dsu.find((r, 0)), 'leaf', r, -1, ('WIRE',)))
        if dsu.find((r, bmax)) in touched:
            edges.append(_mk_edge(dsu.find((r, bmax)), SNK, 'leaf', r, bmax, ('WIRE',)))

    # ---- 约简 ----
    while True:
        # 1) 并联: 同一对端子之间的两条边
        by_pair, hit = {}, None
        for k, e in enumerate(edges):
            key = (e['u'], e['v'])
            if key in by_pair:
                a = edges[by_pair[key]]
                kids = _sub(a) + _sub(e)
                a['kind'] = 'par'
                a['kids'] = kids
                a['payload'] = None
                a['row'] = min(a['row'], e['row'])
                a['col'] = min(a['col'], e['col'])
                hit = k
                break
            by_pair[key] = k
        if hit is not None:
            edges.pop(hit)
            continue

        # 2) 串联: 入度=出度=1 的端子
        indeg, outdeg, ein, eout = {}, {}, {}, {}
        for e in edges:
            outdeg[e['u']] = outdeg.get(e['u'], 0) + 1
            indeg[e['v']] = indeg.get(e['v'], 0) + 1
            ein.setdefault(e['v'], []).append(e)
            eout.setdefault(e['u'], []).append(e)
        done = False
        for nd in list(indeg) + list(outdeg):
            if nd in (SRC, SNK):
                continue
            if indeg.get(nd, 0) == 1 and outdeg.get(nd, 0) == 1:
                e1, e2 = ein[nd][0], eout[nd][0]
                kids = _sub(e1) + _sub(e2)
                edges.remove(e1)
                edges.remove(e2)
                edges.append(_mk_edge(e1['u'], e2['v'], 'ser',
                                      min(e1['row'], e2['row']),
                                      min(e1['col'], e2['col']),
                                      None, kids))
                done = True
                break
        if done:
            continue
        break

    if len(edges) != 1:
        # 约简不下去 = 桥式(非串并联)电路: 两个元件共用输入但输出分叉, 或
        # 交叉跨接。物理上是合法的梯形图, 但无法写成 SERIES/PARALLEL 树。
        # cnc.lad R324-R326 就是这种 (I109 并联但输出分别去 MOVE 与后续串联)。
        return None, f'非串并联(桥式) (剩余 {len(edges)} 条边)'
    tree = _strip_dummy(_edge_tree(edges[0]))
    if tree is None:
        return None, 'blank'
    return tree, None


def reconstruct(rows, keep_raw=False):
    """全部逻辑行 -> [(node, left_anchor, r0, r1, why)]"""
    gd = guides(rows)
    out = []
    for a, b in rung_groups(rows):
        node, why = build_tree(rows, gd, a, b, keep_raw)
        content = [(r, i, c) for r in range(a, b + 1)
                   for i, c in enumerate(rows[r]) if is_content(c)]
        left_anchor = bool(content) and len(content) == 1 and content[0][1] == 0
        out.append((node, left_anchor, a, b, why))
    return out


# ==================== 统计 ====================
def count_parallel(node, acc):
    t = node[0]
    if t == 'LEAF':
        return
    if t == 'PARALLEL':
        acc['par'] += 1
        acc['branches'] += len(node[1])
        acc['max_branch'] = max(acc['max_branch'], len(node[1]))
    for c in node[1]:
        count_parallel(c, acc)
