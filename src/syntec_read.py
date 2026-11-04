# -*- coding: utf-8 -*-
"""SYNTEC .lad 读取 —— 把已有 PLC 程序还原成「梯形图语义」, 供 MCP / AI 使用。

这是 syntec_model(写) 的镜像:
    .lad  --read_ladder-->  rungs: [[元件 dict, ...], ...]  --add_rung/save-->  .lad

三层能力:
  1) el_to_dict     解码后的元件元组 -> 元件 dict (与 add_rung 的 elements 同格式)
  2) tree_to_elements  网络树 -> elements 列表 (串联摊平, 并联变 kind='parallel')
  3) read_ladder    整个文件 -> 每条 rung 的 elements + 保留记录 + 统计

重要设计: 模型表达不了的 rung (空白行 / 桥式拓扑) 不做有损转换, 而是原样
保留原始字节 (raw). 这样"读入 -> 只改其中一条 -> 存回"不会动到其它行。
"""
import os
import syntec_re as R
import syntec_lad as L
import syntec_parse as P
import syntec_layout as Y
import syntec_paths as PA

DEV = "IOCSA"

# opcode -> 助记符 (逆向表), 供读取时还原 op 名称
REV = {}
for _tab in ('MATH_TYPE', 'MOVE_TYPE', 'LOGIC_TYPE', 'CMP_TYPE', 'TOOL_TYPE',
             'FLOW_TYPE'):
    for _name, _code in getattr(L, _tab, {}).items():
        REV.setdefault(_code, _name)
REV_TIMER = {v: k for k, v in L.TIMER_TYPE.items()}      # opcode -> (精度, 源)
REV_CNTR = {v: k for k, v in L.CNTR_TYPE.items()}        # opcode -> (方向, 源)


# ==================== 地址 ====================
def bits_to_addr(n):
    """16 位 PLCBits -> 设备名 (addr_bits 的逆)"""
    n3, n4 = n & 0xFFF, (n >> 12) & 0xF
    if n4 == 0:
        t = n3 >> 9
        if t < 5:
            return f"{DEV[t]}{n3 & 0x1FF}"
        return f"#{n}"
    if 1 <= n4 <= 15:            # n4 是 4 位: 1..5 = R0~R639, 6..15 = R640~R2047
        base = (n3 >> 5) + (n4 - 1) * 128
        bit = n3 & 0x1F
        # 这一区永远是按位寻址的, bit=0 也照样显示 .0 —— 位设备里 "R50" 和
        # "R50.0" 编成同一个 16 位数, 少写一位会让人以为在读整个寄存器。
        return f"R{base}.{bit}"
    return f"#{n}"


def num_to_operand(v, imm=False):
    """功能块操作数: 寄存器号 -> 'R300', 立即数 -> '#5'"""
    return f"#{v}" if imm else f"R{v}"


# ==================== 元件元组 -> dict ====================
def el_to_dict(el):
    k = el[0]
    if k == 'CONTACT':
        return {'kind': 'contact', 'norm': el[1], 'addr': bits_to_addr(el[2])}
    if k == 'COIL':
        return {'kind': 'coil', 'norm': el[1], 'addr': bits_to_addr(el[2])}
    if k == 'CONTACT_T':
        return {'kind': 'contact_t', 'norm': el[1], 'index': el[2]}
    if k == 'CONTACT_C':
        return {'kind': 'contact_c', 'norm': el[1], 'index': el[2]}
    if k == 'END':
        return {'kind': 'end'}
    if k == 'FB':
        cat, op = el[1], el[2]
        if cat == 'TIMER':
            prec, src = REV_TIMER.get(op, ('1s', 'K'))
            src = '#' if src == 'K' else src          # 对外统一用 # 表示常数
            param = el[5]
            val = param[0] | (param[1] << 8)
            return {'kind': 'timer', 'name': f'TM{el[3]}', 'precision': prec,
                    'source': src, 'preset': val}
        if cat == 'CNTR':
            d, src = REV_CNTR.get(op, ('UP', 'K'))
            src = '#' if src == 'K' else src          # 对外统一用 # 表示常数
            param = el[5]
            val = param[0] | (param[1] << 8)
            return {'kind': 'counter', 'name': f'CT{el[3]}', 'direction': d,
                    'source': src, 'preset': val}
        if cat == 'FLOW':
            name = str(op).upper()
            if name in ('JSR', 'LAB'):
                return {'kind': name.lower(), 'label': str(el[3]) if len(el) > 3 else ''}
            return {'kind': name.lower()}
        mnem = REV.get(op, None)
        if cat == 'MATH':
            kind = 'math'
        elif cat == 'MOVE':
            kind = 'move'
        elif cat == 'LOGIC':
            kind = 'logic'
        elif cat == 'CMP':
            kind = 'compare'
        elif cat == 'ROT':
            return {'kind': 'raw', 'hex': L.enc_el(el).hex(' '), 'note': 'ROT 旋转块'}
        else:
            return {'kind': 'raw', 'hex': L.enc_el(el).hex(' '),
                    'note': f'未知功能块 {cat}/{op}'}
        if mnem is None:
            return {'kind': 'raw', 'hex': L.enc_el(el).hex(' '),
                    'note': f'{cat} opcode 0x{op:02x} 无对应助记符'}
        if cat == 'CMP':
            # op1 是常数还是寄存器由 opcode 决定 (官方 CMPx_ConstantToR vs CMPx_RtoR):
            #   0x6a / 0x6c / 0x6e 的 A 槽 = #常数
            #   0x5e / 0x62 / 0x66 的 A 槽 = 寄存器 (cnd_2 里 0x5e 的 A=961 就是 R961)
            # 早期一律当常数, 会把 R961>R2011 读成 #961>R2011。
            return {'kind': 'compare', 'op': mnem,
                    'A': num_to_operand(el[3], op in (0x6a, 0x6c, 0x6e)),
                    'B': num_to_operand(el[4])}
        imm = mnem.endswith('_IMM')
        return {'kind': kind, 'op': mnem,
                'A': num_to_operand(el[3], imm), 'B': num_to_operand(el[4])}
    # ('FLOW8', op, 6字节) / ('FLOW4', op) —— 流程块
    if k in ('FLOW8', 'FLOW4'):
        op = el[1]
        name = REV.get(op)
        if name in ('JSR', 'LAB', 'JMP', 'MSG'):
            raw = el[2] if k == 'FLOW8' else b''
            label = raw.split(b'\x00')[0].decode('ascii', 'replace')
            return {'kind': name.lower(), 'label': label}
        if name in ('RTS', 'FEND', 'END'):
            return {'kind': name.lower()}
        return {'kind': 'raw', 'hex': L.enc_el(el).hex(' '),
                'note': f'流程块 opcode 0x{op:02x}'}
    # ('RAW', bytes) —— 未知单元, 完全原样保留
    note = '未知单元' if k == 'RAW' else f'未识别单元 {k}'
    return {'kind': 'raw', 'hex': L.enc_el(el).hex(' '), 'note': note}


# ==================== 网络树 -> elements ====================
def tree_to_elements(node):
    """网络树 -> 元件 dict 列表 (串联摊平成列表, 并联收成一个 parallel 元素)"""
    t = node[0]
    if t == 'LEAF':
        return [el_to_dict(node[1])]
    if t == 'SERIES':
        out = []
        for c in node[1]:
            out.extend(tree_to_elements(c))
        return out
    if t == 'PARALLEL':
        return [{'kind': 'parallel',
                 'branches': [tree_to_elements(c) for c in node[1]]}]
    raise ValueError(t)


# ==================== 整文件读取 ====================
def split_records(data):
    """按 40 字节切成 记录; 返回 (logic_records, others, 文件尾剩余字节)

    others: [(该记录之前的逻辑行数, 原始字节)] —— 注释行/版本/变量注释。
    长注释会跨多条 40 字节记录, 这里按 syntec_re.parse_raw 的同一规则数出
    "消耗了几条", 把整段拼回去, 否则续行会被误当成逻辑行(行号整体错位)。
    """
    n = len(data) // 40
    body = data[:n * 40]
    logic, others = [], []
    idx = 0
    while idx < n:
        rec = body[idx * 40:(idx + 1) * 40]
        if rec[1] == 0 and rec[3] != 0:
            num2 = rec[2]
            consumed = 0
            if num2:
                num3, j = 6, 1
                while j <= num2:
                    num3 = num3 + 1 if (num3 % 4 != 3) else num3 + 3
                    if j < num2 and num3 == 42:
                        consumed += 1
                        num3 = 2
                    j += 1
            raw = b''.join(body[(idx + k) * 40:(idx + k + 1) * 40]
                           for k in range(consumed + 1))
            others.append((len(logic), raw))
            idx += 1 + consumed
        else:
            logic.append(rec)
            idx += 1
    return logic, others, len(data) - n * 40


def editor_rows(logic, others):
    """逻辑行索引 -> 它之前的注释行条数。

    ct=1/3 的注释**占编辑器的行**, 所以编辑器行号 = 逻辑行号 + 前面注释数 + 1。
    这里给每个逻辑行索引算出前缀和, 渲染时才能标对行号 (否则带注释的文件会差几行)。
    """
    before = [0] * (len(logic) + 1)
    for lr, _raw in others:
        before[min(lr, len(logic))] += 1
    cum, s = [], 0
    for i in range(len(logic) + 1):
        s += before[i]
        cum.append(s)
    return cum


def read_ladder(path):
    """读入一个 .lad, 返回结构化的梯形图信息 (不改动任何全局状态)

    返回 dict:
      path, size, version, logic_rows, rung_count
      rungs: [ {index, rows, elements, ok, why} ]
      kept : 无法用串并联模型表达的 rung (空白/桥式), elements 为 None
      comments: {名称: (短, 长)}
      stats: {parallel_blocks, branches, ...}
    """
    data = open(path, 'rb').read()
    logic, others, tail_len = split_records(data)
    rows = [P.decode_row(r) for r in logic]
    trees = P.reconstruct(rows)

    rungs = []
    erow = editor_rows(logic, others)
    for node, la, a, b, why in trees:
        rec = {'index': len(rungs) + 1, 'row_start': a + 1, 'row_end': b + 1,
               'rows': b - a + 1, 'left_anchor': la,
               'editor_row_start': a + 1 + erow[a],
               'editor_row_end': b + 1 + erow[b]}
        if node is None:
            if why == 'blank':
                rec.update(elements=None, ok=True, why='空白行', shape='blank',
                           note='空白行(无元件), 原样保留')
            else:
                # 折不成树的行照样能读: 用路径枚举把每个负载的使能条件算出来。
                # 这样"桥式/多负载"不再是审查盲区, 只是不能写回(布局还原不了)。
                res = PA.analyze(rows, a, b)
                loads = [{'addr': x['addr'], 'row': x['row'], 'col': x['col'],
                          'text': x['text'], 'n_paths': x['n_paths'],
                          'through': x['through'],
                          'unreachable': x['unreachable']}
                         for x in res['loads']]
                multi = len(loads) > 1
                rec.update(elements=None, ok=False, why=why,
                           shape='multi' if multi else 'bridge',
                           loads=loads,
                           note=('%d 个输出挤在一条 rung 上，使能条件互相交织 '
                                 '(不是同一段条件的并联分支) —— 可读取、可审查, '
                                 '保存时原样保留' % len(loads)) if multi else
                                f'{why} —— 可读取、可审查, 保存时原样保留')
        else:
            rec.update(elements=tree_to_elements(node), ok=True, why=None,
                       shape='tree', loads=None)
        rungs.append(rec)

    stats = {'par': 0, 'branches': 0, 'max_branch': 0}
    for node, _la, _a, _b, _why in trees:
        if node is not None:
            P.count_parallel(node, stats)

    return {
        'path': os.path.abspath(path),
        'size': len(data),
        'version': R.parse_version(data),
        'logic_rows': len(logic),
        'rung_count': len(rungs),
        'tail_bytes': tail_len,
        'rungs': rungs,
        'comments': R.load_comments(data),
        'stats': {'parallel_blocks': stats['par'],
                  'branches': stats['branches'],
                  'max_branch': stats['max_branch']},
        'has_extra_records': len(others) > 0,
        'extra_record_count': len(others),
    }


# ==================== 载入到工程(可读可写) ====================
def load_into(project, path, keep_geometry=True):
    """把 .lad 载入 LadderProject。

    keep_geometry=True (默认): 对每一条 rung 先试"用语义模型重新生成并比对字节",
    一致才转成可编辑的元件列表; 不一致(原件是人工摆放的布局)则锁定为原始字节。
    这样"读入 -> 原样保存"逐字节相同, AI 只改动它确实能完整表达的那些行。

    keep_geometry=False: 全部转成语义模型 (可全量编辑, 但保存后布局会被重排)。

    返回 (info, kept) ; kept: [(rung 序号, 原因)]
    """
    info = read_ladder(path)
    data = open(path, 'rb').read()
    logic, others, _tail = split_records(data)

    # 逻辑行 -> rung 序号
    rung_of_row = {}
    for k, r in enumerate(info['rungs']):
        for rr in range(r['row_start'] - 1, r['row_end']):
            rung_of_row[rr] = k

    project.reset(keep_path=False)
    project.set_path(path)
    project.rungs = [None] * len(info['rungs'])

    # 非逻辑记录(版本/注释行/变量注释) 一律按"它前面有几条逻辑行"定位。
    # 不能按类型拆到文件头/尾 —— cnc.lad 的第一条记录就是注释, 版本记录也在中间;
    # 拆开写会改变记录顺序, 逐字节就不同了。
    for row_idx, rec in others:
        k = rung_of_row.get(row_idx, len(info['rungs']))
        project.prefix[k] = project.prefix.get(k, b'') + rec

    kept = []
    for k, r in enumerate(info['rungs']):
        a, b = r['row_start'] - 1, r['row_end']
        orig = b''.join(logic[a:b])
        if r['elements'] is None:
            project.raw_rungs[k] = orig
            kept.append((k + 1, r['why']))
            continue
        if keep_geometry:
            la = r['left_anchor']
            try:
                regen = L_layout_rung(r['elements'], la)
            except Exception as e:
                regen = None
                r['why'] = f'无法重新排版: {e}'
            if regen == orig:
                project.rungs[k] = r['elements']
                project.left_anchor[k] = la
                continue
            project.raw_rungs[k] = orig
            kept.append((k + 1, r.get('why') or '布局与自动排版不同'))
            continue
        project.rungs[k] = r['elements']
        project.left_anchor[k] = r['left_anchor']
        for el in _walk_elements(r['elements']):
            if el.get('kind') == 'raw':
                kept.append((k + 1, el.get('note', 'raw')))
    project.comments = dict(info['comments'])
    return info, kept


def L_layout_rung(elements, la):
    """用语义模型重新生成一条 rung 的字节 (与 LadderProject.save 同一路径)"""
    import syntec_model as M
    return M.to_rung_bytes(elements, la)


def _walk_elements(els):
    for e in els:
        if e.get('kind') == 'parallel':
            for br in e.get('branches') or []:
                for x in _walk_elements(br):
                    yield x
        else:
            yield e


# ==================== 渲染 ====================
def render_file(path, start=1, end=None):
    """把指定范围的 rung 画成带竖线的梯形图文本 (start/end 是 rung 序号, 1 基)"""
    data = open(path, 'rb').read()
    logic, others, _t = split_records(data)
    rows = [P.decode_row(r) for r in logic]
    erow = editor_rows(logic, others)      # 注释行占编辑器行, 行号要算进去
    # 整份图统一列宽: 只要有一行出现 8 字符以上的标签(如 =R590.14),
    # 所有行都得跟着加宽, 否则那几行的竖线会和上下行错开。
    W = max((Y.needed_width([None if c is None else (c[0], c[1]) for c in row])
             for row in rows), default=8)
    out = []
    for k, (node, la, a, b, why) in enumerate(P.reconstruct(rows), 1):
        if k < start or (end and k > end):
            continue
        out.append(f'--- R{k} (编辑器行 {a + 1 + erow[a]}-{b + 1 + erow[b]}) ---')
        for r in range(a, b + 1):
            # decode_row 给的是 (conn, 语义, 原始字节); 渲染只要前两项
            grid = [None if c is None else (c[0], c[1]) for c in rows[r]]
            out.append(f'{r + 1 + erow[r]:>4}  {Y.render_line(grid, W=W)}')
    return '\n'.join(out)
