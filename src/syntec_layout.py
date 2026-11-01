"""SYNTEC .lad 并联分支布局引擎

格式依据 (反编译 MLCEdit.exe + cnc_1.lad/B_branch.lad 实测):
  每格 4 字节 = [conn, opcode, arg_lo, arg_hi]
  conn 的 4 个位描述该格前后两条"列边界"上的竖线:
    bit2 (0x04) = 左边界 上半段 (竖线从本行往上)
    bit3 (0x08) = 左边界 下半段 (竖线从本行往下)
    bit0 (0x01) = 右边界 上半段  (== 右邻格 bit2)
    bit1 (0x02) = 右边界 下半段  (== 右邻格 bit3)
  一条竖线在列边界 B 上跨 r0..r1 行:
    r0 行: 左侧格 |= 0x02, 右侧格 |= 0x08      (只有下半段)
    中间行: 左侧格 |= 0x03, 右侧格 |= 0x0c      (上下贯通)
    r1 行: 左侧格 |= 0x01, 右侧格 |= 0x04      (只有上半段)

布局规则:
  并联块占列区间 [A,B), 每个分支占一行, 分支元件从 A 左对齐, 短分支右侧留 EMPTY;
  竖线画在 A 和 B 两个列边界上, 覆盖该块的全部行;
  主行(row0)的空隙填 WIRE, 分支行填 EMPTY。
  依据: cnc_1.lad R25-R29 (5 分支, 元件@col0, 竖线@col1) 与 R31-R32 (输出并联, 竖线@col9)。
"""
import syntec_lad as L

COLS = L.COLS


# ==================== 网络树 ====================
# ('LEAF', el) / ('SERIES', [nodes]) / ('PARALLEL', [nodes]) / ('GAP', n)

def leaf(el):
    return ('LEAF', el)


def series(*nodes):
    flat = []
    for n in nodes:
        if n[0] == 'SERIES':
            flat.extend(n[1])
        else:
            flat.append(n)
    return ('SERIES', flat)


def parallel(*nodes):
    flat = []
    for n in nodes:
        if n[0] == 'PARALLEL':
            flat.extend(n[1])
        else:
            flat.append(n)
    return ('PARALLEL', flat)


def _w(node):
    if node[0] == 'LEAF':
        return L.span_of(node[1])
    if node[0] == 'GAP':
        return node[1]
    if node[0] == 'SERIES':
        return sum(_w(c) for c in node[1])
    if node[0] == 'PARALLEL':
        return max(_w(c) for c in node[1])
    raise ValueError(node[0])


# ==================== 布局 ====================
def layout(node):
    """返回 (rows, width, guides, pads)
    rows:   [ [(col_offset, element), ...], ... ]  每个元素相对本节点起点
    width:  本节点占的列数
    guides: [(boundary_col, r_start, r_end)]  需要画竖线的列边界
    pads:   [(col_lo, col_hi, r_start, r_end)]  并联体内需要用横线补满的矩形
            (真实程序里短分支是"左对齐 + 横线补到汇合点", 不是右对齐留空)
    """
    t = node[0]

    if t == 'GAP':
        return [[(0, ('GAP', node[1]))]], node[1], [], []

    if t == 'LEAF':
        return [[(0, node[1])]], L.span_of(node[1]), [], []

    if t == 'SERIES':
        parts = [layout(c) for c in node[1]]
        # 串联里各部件行数可以不同 (例如 (A|B) 2 行 then (C|D|E) 3 行):
        # 一律靠上对齐, 行数少的部件占据前几行, 下面的行留给行数多的部件。
        # 两个并联块的竖线在同一列边界上会拼成一条连续的线, 接线仍然是通的。
        nrow = max(len(p[0]) for p in parts)
        rows = [[] for _ in range(nrow)]
        guides, pads = [], []
        off = 0
        for crows, cw, cg, cp in parts:
            for j, r in enumerate(crows):
                for (o, el) in r:
                    rows[j].append((o + off, el))
            for (B, r0, r1) in cg:
                guides.append((B + off, r0, r1))
            for (a, b, r0, r1) in cp:
                pads.append((a + off, b + off, r0, r1))
            off += cw
        return rows, off, guides, pads

    if t == 'PARALLEL':
        parts = [layout(c) for c in node[1]]
        W = max(p[1] for p in parts)
        rows, guides, pads = [], [], []
        starts = []
        for crows, cw, cg, cp in parts:
            base = len(rows)
            starts.append(base)
            for r in crows:                 # 各分支都从块的左边界起排 (左对齐)
                rows.append([(o, el) for (o, el) in r])
            for (B, r0, r1) in cg:
                guides.append((B, base + r0, base + r1))
            for (a, b, r0, r1) in cp:
                pads.append((a, b, base + r0, base + r1))
        # 分支是"靠上对齐"的: 每个分支的输入/输出都在它的首行。
        # 因此分叉/汇合竖线只跨 0..live, 而不是整个块高 ——
        # 块底下那些行是长分支的"余量"(死端), 竖线不能延伸过去, 否则会把
        # 余量上的横线短接到汇合点。依据 cnc_1.lad R15-R19:
        #   分支2 = (I2359|I2360) 占 2 行, 后面的 I2140 靠上放在第 3 行,
        #   第 4 行只有接线位; 汇合竖线(col5)只到第 3 行, 不进第 4 行。
        live = max(starts) if starts else 0
        guides.append((0, 0, live))         # 左边界 (分叉)
        guides.append((W, 0, live))         # 右边界 (汇合)
        # 只有"分支输出行"才补横线; 分支内部的死端行不能补, 否则会短接。
        # 依据 cnc_1.lad R118-R121: 分支 (I86|I100) -> I2049 的第 2 行是死端,
        # 后面必须全 0x00; 补成 0x0d 就把 I100 直接接到了汇合点。
        for s in starts:
            pads.append((0, W, s, s))
        return rows, W, guides, pads

    raise ValueError(t)


# ==================== 转 10 列网格 ====================
def to_grid(node, total=COLS, left_anchor=False):
    """把网络树排成 10 列网格。
    返回 list[list[(conn, element)]] ; conn 已按竖线规则填好。
    left_anchor=True 时整体靠左 (END/LAB 等单元素行), 否则末元素右对齐到最右列。
    """
    rows, W, guides, pads = layout(node)

    if W > total:
        raise ValueError(
            f"本行需要 {W} 列, 超出梯形图 {total} 列上限; 请拆成多条 rung 或减少串联元件")

    # 末元素右对齐: 把"最后一个 leaf"固定到最右列, 中间留空隙
    # 实现方式: 在 root.series 的最后一个 child 前插入 GAP
    gap = total - W
    if gap > 0 and not left_anchor:
        if node[0] == 'SERIES' and len(node[1]) >= 2:
            kids = list(node[1])
            kids = kids[:-1] + [('GAP', gap)] + kids[-1:]
            rows, W, guides, pads = layout(('SERIES', kids))
        else:
            # 只有一个元件 (或根本身是并联): 整体右移
            rows = [[(o + gap, el) for (o, el) in r] for r in rows]
            guides = [(B + gap, r0, r1) for (B, r0, r1) in guides]
            pads = [(a + gap, b + gap, r0, r1) for (a, b, r0, r1) in pads]

    n = len(rows)
    if n > 64:
        # 实测最大: cnc_1.lad R941-R999 一条 59 行 / 52 分支的大并联。
        raise ValueError(f"本行需要 {n} 行, 超过 64 行上限")

    # 建网格
    grid = [[(0, ('EMPTY',)) for _ in range(total)] for _ in range(n)]

    for j, r in enumerate(rows):
        for (o, el) in r:
            if el[0] == 'GAP':
                continue
            w = L.span_of(el)
            if o + w > total:
                raise ValueError(f"元素 {el} 在列 {o} 放不下 (宽 {w}, 共 {total} 列)")
            grid[j][o] = (0, el)
            for k in range(1, w):
                grid[j][o + k] = None          # 8 字节块的后半列

    # 主行空隙填 WIRE (元素之间 + GAP 处); None 是 8 字节块的后半列, 必须保留
    for j in range(n):
        if j == 0:
            # 主行整行补导线 (含行尾): 全量实测"主行补满整行"比"补到末元件为止"
            # 多命中 10 条 rung 的字节; 行尾保持 00 的情况集中在分支行(下面 else)。
            for c in range(0, total):
                if grid[j][c] is not None and grid[j][c][1][0] == 'EMPTY':
                    grid[j][c] = (0, ('WIRE',))
        else:
            # 分支行: 空隙保持 EMPTY 不填连接线
            # 依据 B_branch.lad R2: I101@col0 之后 col1..9 全 00(EMPTY), 而非 0d(WIRE)
            pass

    # 并联体内部空白补横线: 短分支从"最后一个元件的右边缘"补到汇合点。
    # 依据 cnc.lad R10/R11: 分支短的一行在元件后面用 0x0d 补到竖线位置;
    # 元件前面的空白保持 0x00(不导通), 不能补。
    for (a, b, r0, r1) in pads:
        for r in range(max(0, r0), min(n, r1 + 1)):
            last = None
            for c in range(max(0, a), min(total, b)):
                cell = grid[r][c]
                if cell is not None and cell[1][0] not in ('EMPTY', 'WIRE'):
                    last = c + L.span_of(cell[1])
            if last is None:
                continue
            for c in range(last, min(total, b)):
                cell = grid[r][c]
                if cell is not None and cell[1][0] == 'EMPTY':
                    grid[r][c] = (0, ('WIRE',))

    # 画竖线
    def _left_cell(g, i):
        """列边界左侧的那一格: 从 i 向左找, 跳过 8 字节块的后半列(None)。
           块右边缘的接线位记在块的起始格上(conn 字节在起始列的 b0)。"""
        while i >= 0:
            if g[i] is not None:
                return i
            i -= 1
        return -1

    def _right_cell(g, i):
        """列边界右侧的那一格: 从 i 向右找, 跳过 8 字节块的后半列"""
        while i < len(g):
            if g[i] is not None:
                return i
            i += 1
        return -1

    for (B, r0, r1) in guides:
        if r0 > r1:
            r0, r1 = r1, r0
        if B <= 0 or B >= total:
            continue                     # 母线端不画
        for r in range(r0, r1 + 1):
            g = grid[r]
            li = _left_cell(g, B - 1)
            ri = _right_cell(g, B)
            if li < 0 or ri < 0 or li == ri:
                continue
            lo_bit = 0
            ri_bit = 0
            if r == r0:
                lo_bit, ri_bit = 0x02, 0x08
            if r == r1:
                lo_bit |= 0x01
                ri_bit |= 0x04
            if r0 < r < r1:
                lo_bit |= 0x03
                ri_bit |= 0x0C
            g[li] = (g[li][0] | lo_bit, g[li][1])
            g[ri] = (g[ri][0] | ri_bit, g[ri][1])

    return grid


# ==================== 序列化 ====================
def emit_grid(grid):
    """把 (conn, element) 网格写成 40 字节"""
    out = bytearray()
    for cell in grid:
        if cell is None:
            continue
        conn, el = cell
        body = L.enc_el(el)
        out += bytes([conn]) + body[1:]
    if len(out) != 40:
        raise ValueError(f"行长度 {len(out)} != 40: {[c[1][0] if c else None for c in grid]}")
    return bytes(out)


def check_grid(grid):
    """按 MLCEdit 的 AutoFix 规则自检, 返回问题列表(空表示编辑器不会改写)"""
    problems = []
    n = len(grid)

    # 单行内水平一致性 (AutoFixOneLine): 左格右边缘位必须等于右格左边缘位
    for j, g in enumerate(grid):
        for c in range(COLS - 1):
            a, b = g[c], g[c + 1]
            if a is None or b is None:
                continue
            ca, cb = a[0], b[0]
            if bool(ca & 0x01) != bool(cb & 0x04):
                problems.append(f"行{j+1} 列{c}|{c+1} 右上半段不一致 ({ca:02x} vs {cb:02x})")
            if bool(ca & 0x02) != bool(cb & 0x08):
                problems.append(f"行{j+1} 列{c}|{c+1} 右下半段不一致 ({ca:02x} vs {cb:02x})")

    # 第一格不允许左边缘竖线
    for j, g in enumerate(grid):
        if g[0] is not None and (g[0][0] & 0x0C):
            problems.append(f"行{j+1} 第1格有左边缘竖线 conn={g[0][0]:02x} (编辑器会清除)")

    # 行间竖线配对 (AutoFixTwoLine)
    #   上行的下半段只在"下行有对应上半段"时才保留 —— 左边缘 bit3<->bit2, 右边缘 bit1<->bit0
    for j in range(n - 1):
        g1, g2 = grid[j], grid[j + 1]
        for c in range(COLS):
            if g1[c] is None or g2[c] is None:
                continue
            c1, c2 = g1[c][0], g2[c][0]
            if bool(c1 & 0x08) != bool(c2 & 0x04):
                problems.append(f"行{j+1}/{j+2} 列{c} 左边缘竖线不配对 ({c1:02x} vs {c2:02x})")
            # AutoFixTwoLine 只在两格都不是 8 字节块时检查右边缘
            bi1 = L.span_of(g1[c][1]) == 2
            bi2 = L.span_of(g2[c][1]) == 2
            if not bi1 and not bi2 and bool(c1 & 0x02) != bool(c2 & 0x01):
                problems.append(f"行{j+1}/{j+2} 列{c} 右边缘竖线不配对 ({c1:02x} vs {c2:02x})")
    return problems


def build_lad(rungs, tail=b'\x00\xfe'):
    """rungs: list of (node, left_anchor) 或 node; 返回完整文件字节"""
    out = bytearray()
    for item in rungs:
        if isinstance(item, tuple) and len(item) == 2 and isinstance(item[1], bool):
            node, la = item
        else:
            node, la = item, False
        out += emit_grid(to_grid(node, left_anchor=la))
    out += tail
    return bytes(out)


# ==================== 渲染 (给人看) ====================
COIL_SYM_SHORT = {'NO': '=', 'NC': '/', 'RP': '^', 'FP': 'v',
                  'LATCH': 'S', 'UNLATCH': 'R'}

FB_OP_SYM = {'ADD': '+', 'SUB': '-', 'MUL': '*', 'DIV': '/',
             'ADD_IMM': '+', 'SUB_IMM': '-', 'MUL_IMM': '*', 'DIV_IMM': '/',
             'AND': '&', 'OR': '|', 'XOR': '^',
             'AND_IMM': '&', 'OR_IMM': '|', 'XOR_IMM': '^',
             'GT': '>', 'LT': '<', 'EQ': '==', 'GTK': '>', 'LTK': '<', 'EQK': '=='}


def _opnd(v, imm):
    """功能块操作数: 寄存器 R300 / 立即数 K5 (SYNTEC 习惯用 K 表示常数)"""
    return f"K{v}" if imm else f"R{v}"


def el_label(el):
    """元件 -> 显示文本 (尽量在 7 个字符内说清是什么)"""
    k = el[0]
    if k == 'WIRE':
        return '─' * 7          # 真实导线(0x0d), 铺满整格才看得出是一条连续的线
    if k == 'EMPTY':
        return ''               # 空白格(0x00): 物理上同样导通, 但编辑器不画线, 保持留白
    if k == 'END':
        return 'END'
    if k == 'CONTACT':
        return dev_name(el[2]) if el[1] == 'NO' else '/' + dev_name(el[2])
    if k == 'COIL':
        return COIL_SYM_SHORT.get(el[1], '=') + dev_name(el[2])
    if k == 'CONTACT_T':
        return f"TM{el[2]}" if el[1] == 'NO' else f"/TM{el[2]}"
    if k == 'CONTACT_C':
        return f"CT{el[2]}" if el[1] == 'NO' else f"/CT{el[2]}"
    if k == 'FB':
        cat = el[1]
        if cat == 'FLOW':
            name = el[2] if len(el) > 2 else 'FLOW'
            lb = el[3] if len(el) > 3 else ''
            return f"{name} {lb}".strip()
        if cat == 'TIMER':
            return f"TM{el[3]} K{(el[5][0] | el[5][1] << 8) if len(el) > 5 else 0}"
        if cat == 'CNTR':
            return f"CT{el[3]}"
        op = REV_NAME.get(el[2], str(el[2]))
        sym = FB_OP_SYM.get(op, op)
        imm = op.endswith('_IMM')
        if cat == 'CMP':
            return f"{_opnd(el[3], False)}{sym}{_opnd(el[4], False)}"
        if cat == 'MOVE':
            return f"R{el[4]}={_opnd(el[3], imm)}"
        return f"{_opnd(el[4], False)}{sym}{_opnd(el[3], imm)}"
    if k == 'RAW':
        return '?'
    return str(k)


REV_NAME = {}
for _t in ('MATH_TYPE', 'MOVE_TYPE', 'LOGIC_TYPE', 'CMP_TYPE', 'TOOL_TYPE'):
    for _n, _c in getattr(L, _t, {}).items():
        REV_NAME.setdefault(_c, _n)


DEV_LETTER = "IOCSA"


def dev_name(n):
    """16 位 PLCBits -> 设备名 (I0/O1/C2/S3/A4 或 Rx.y)"""
    n3 = n & 0xFFF
    n4 = (n >> 12) & 0xF
    if n4 == 0:
        t = n3 >> 9
        if t < 5:
            return f"{DEV_LETTER[t]}{n3 & 0x1FF}"
        return f"?{t}:{n3 & 0x1FF}"
    if 1 <= n4 <= 5:
        return f"R{(n3 >> 5) + (n4 - 1) * 128}.{n3 & 0x1F}"
    return f"?BIT{n:04X}"


VERT_UP, VERT_DN = 0x01, 0x02      # 右边界: 上半段 / 下半段


def render_line(grid):
    """把一个网格行渲染成【一行】文本。

    老版 render_grid 输出 上/中/下 三行, 竖线被拆到元件行上下两侧, 读起来是断的。
    这里改用连接位直接给竖线分级:
        上半段+下半段 -> │  (贯穿)
        只有上半段   -> ╵  (线从上方下来, 到本行为止 = 汇合点)
        只有下半段   -> ╷  (线从本行向下延伸 = 分叉点)
    一行 rung 行 = 一行文本, 分支层次一眼能看出。
    """
    W = 8
    buf = [' '] * (COLS * W + 2)
    for c in range(COLS):
        cell = grid[c]
        if cell is None:
            continue
        _conn, el = cell
        txt = str(el_label(el))
        st = c * W
        room = W * L.span_of(el) - 1             # 最后一格留给竖线
        for i, ch in enumerate(txt[:room]):
            buf[st + i] = ch
    for c in range(COLS):
        cell = grid[c]
        if cell is None:
            continue
        conn, el = cell
        e = c + L.span_of(el)
        if e >= COLS:                            # 右母线不画竖线
            continue
        up, dn = bool(conn & VERT_UP), bool(conn & VERT_DN)
        if up and dn:
            buf[e * W - 1] = '│'
        elif up:
            buf[e * W - 1] = '╵'
        elif dn:
            buf[e * W - 1] = '╷'
    return ''.join(buf).rstrip()


def render_grid(grid, rownum=''):
    W = 8
    top = [' '] * (COLS * W + 2)
    bot = [' '] * (COLS * W + 2)
    mid = [' '] * (COLS * W + 2)
    for c in range(COLS):
        cell = grid[c]
        if cell is None:
            continue
        conn, el = cell
        if c > 0:
            p = c * W - 1
            if conn & 0x04:
                top[p] = '│'
            if conn & 0x08:
                bot[p] = '│'
        if c + L.span_of(el) < COLS:
            p = (c + L.span_of(el)) * W - 1
            if conn & 0x01:
                top[p] = '│'
            if conn & 0x02:
                bot[p] = '│'
        txt = el_label(el)
        st = c * W
        for i, ch in enumerate(str(txt)[:W - 1]):
            mid[st + i] = ch
    return ''.join(top).rstrip(), ''.join(mid).rstrip(), ''.join(bot).rstrip()
