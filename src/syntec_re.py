# -*- coding: utf-8 -*-
"""
SYNTEC .lad (新式梯形图文件) 解码器  v9
=========================================
全部规则来自反编译 MLCEdit.exe 的源码, 不是猜测:
  mainForm.Openfile()      -> 记录/行/注释 的解析
  PlcLineToCells.Convert() -> 每行 10 格, isBiCell 决定占 4 还是 8 字节
  plc.ConvertPlcOp()       -> plcop_map[opcode] 位段: group / func / isBiCell / op1mode / op2mode
  plc.GetOperand()         -> 操作数怎么从字节解成 I/O/C/S/A/R/TM/CT/#常量/字符串

文件结构
--------
  文件 = 若干条 40 字节记录 + 末尾 2 字节结束标记 00 FE (NOT_LINE_RU = 254)
  每条记录要么是"逻辑行"(40 字节 = 10 格), 要么是"注释行"
  注释行判定: byte[1]==0 且 byte[3]!=0
      byte[2]     = 注释字节数
      字符从 byte[6] 起, 每 4 字节格取 b2,b3 (跳过结构位), 每格 2 字符 / 每行 20 字符
      超长时跨到下一条 40 字节记录继续读
      byte[3]     = CommentType: 1/3=普通注释(占编辑器行), 2=版本(不占行), 4=设备变量注释(不占行)
  编辑器行号 = 只数"逻辑行 + ct∈{1,3} 的注释行", 从 R1 起
  注释文本编码 = Big5 (.NET 的 Encoding("Big5") 实为 cp950 扩展集)

单元 (每格 4 字节)
------------------
  byte0 = conn  接线字节, 竖线画在格左边缘:
            0x4 = 上半段(上一行->本行中线)   0x8 = 下半段(中线->下一行)
            0xC = 上下都接
            0x1/0x2 = 同一条竖线在右邻格视角的镜像, 渲染不读
  byte1 = opcode, 查 plcop_map
  byte2..3 = 操作数1 (16 位小端; Timer/Counter 模式只取 byte2)
  双格(8 字节)单元再追加:
  byte4..5 = 操作数2
  byte6    = 间接寻址位掩码: bit0=op2间接, bit1=op1间接 (Timer/RS232 组此字节另作他用)
  byte7    = 编辑器不读不写(SaveFile 整行 40 字节原样搬运), 常见 0x80 或 0x00

操作数编码 (plc.GetOperand)
---------------------------
  PLCBits      num=b2|b3<<8; n3=num&0xFFF; n4=num>>12
                 n4==0: 设备 = n3>>9 (0=I 1=O 2=C 3=S 4=A), 号 = n3&0x1FF
                 n4 1..5: R 号 = (n3>>5)+(n4-1)*128, 位 = n3&0x1F  ->  R1234.05
  Timer        TM + 有符号16位
  Counter      CT + 有符号16位
  Register     R + 无符号16位 (扁平, 非位编码; 如 R808 存 808)
  ConstValue   # + 有符号16位
  String       从该地址起 6 字节文本, 到 \\0 结束 (JMP/JSR/LAB/MSG 的标签)

用法
----
  python syntec_re.py <file> [起行] [止行]     按编辑器行号输出
  python syntec_re.py <file> --ascii 起 止      附加接线行
  python syntec_re.py <file> --dev             只列设备变量注释表
  python syntec_re.py <file> --struct          程序结构(主程序/子程序/JSR 指向)
  python syntec_re.py <file> --noannot         不显示寄存器中文注释
"""
import sys

# ==================== 权威 PLCOP 属性表 ====================
# plc.plcop_map[256] 原样搬运 (反编译自 tools/src/MLCEdit.Tools/plc.cs)
PLCOP_RAW = [
    0, 1, 0, 17, 0, 34, 0, 50, 0, 1057, 1073, 2113,
    2129, 7, 2, 0, 18, 0, 66, 0, 82, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 28163, 0, 0,
    0, 0, 0, 29187, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 28179, 0, 0, 0, 0, 0, 29203, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 28195, 0, 0,
    0, 0, 0, 29219, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 28211, 0, 0, 0, 0, 0, 29235, 28227, 0,
    0, 0, 28243, 0, 0, 0, 28259, 0, 0, 0, 29251, 0,
    29267, 0, 29283, 0, 29299, 0, 28275, 0, 0, 0, 0, 0,
    0, 0, 0, 0, 0, 0, 0, 0, 0, 28291, 0, 0,
    0, 0, 0, 29315, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 0, 0, 28307, 0, 0, 0, 0, 0, 29331, 0, 0,
    0, 0, 0, 0, 31411, 61171, 28371, 28387, 52931, 28323, 0, 0,
    0, 0, 0, 29347, 0, 0, 0, 0, 28170, 0, 0, 0,
    0, 0, 0, 0, 39432, 31240, 0, 39464, 31288, 31243, 31245, 31261,
    0, 0, 34356, 34308, 34324, 34340, 35333, 35349, 0, 35381, 5638, 5654,
    0, 0, 0, 5718, 5702, 0, 0, 0, 5670, 5686, 0, 31246,
    31244, 28188, 28204, 29244, 28236, 28252, 28268, 28284, 35397, 35413, 26116, 26132,
    26148, 27141, 27157, 26164, 0, 27205, 27221, 28300, 28316, 0, 0, 0,
    29214, 39470, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0,
    0, 5734, 0, 0,
]
assert len(PLCOP_RAW) == 256

GROUP = ['Null', 'Contact', 'Coil', 'Function', 'Timer', 'Counter',
         'Flow', 'HorizontalLink', 'Axis', 'Coord', 'Tool', 'Keyscan',
         'RS232', 'FileSys', 'External']
# OperandType: 0=PLCBits 1=Timer 2=Counter 3=Register 4=ConstValue 5=String 6=DeviceNameLead
OPER = ['PLCBits', 'Timer', 'Counter', 'Register', 'ConstValue', 'String',
        'DeviceNameLead', '?7']

# 各 group 的函数名 (plc.*_fun_title, 下标即 func)
FUN_TITLE = {
    'Function': ["ADD", "SUB", "MUL", "DIV", "CMP>", "CMP<", "CMP=", "MOV", "AND", "OR", "XOR"],
    'Timer':    ["TIM .01s", "TIM .1s", "TIM 1s", "TIM .001s"],
    'Counter':  ["CNT UP", "CNT DOWN", "-", "CNT RESET", "CNT RING UP", "CNT RING DOWN"],
    'Flow':     ["JMP", "JSR", "MSG", "LAB", "RTS", "END", "FEND"],
    'Axis':     ["AX RUN", "-", "AX STOP", "AX MOVE"],
    'Keyscan':  ["KEY SCAN"],
    'RS232':    ["RS232", "ASC>BIN", "BIN>ASC", "PUTCHAR", "GETCHAR", "HEX>DEC",
                 "MODR", "MODW", "MODRS", "SRI"],
    'FileSys':  ["TCH FILE", "-"],
    'Tool':     ["ROT"],
    'External': ["EXT FUNC", "BG RUN", "BG STOP"],
}

# EOpcode_V1 名称 (仅用于显示/交叉引用, 解码不依赖它)
EOF_NAME = {
    0x00: 'Empty', 0x01: 'NormalOpenContact', 0x03: 'NormalCloseContact',
    0x05: 'PosEdgeTriggerCoil', 0x07: 'NegEdgeTriggerCoil',
    0x09: 'NormalOpenContact_Timer', 0x0a: 'NormalCloseContact_Timer',
    0x0b: 'NormalOpenContact_Counter', 0x0c: 'NormalCloseContact_Counter',
    0x0d: 'Line', 0x0e: 'NormalOpenCoil', 0x10: 'NormalCloseCoil',
    0x12: 'LatchCoil', 0x14: 'UnLatchCoil',
    0x21: 'ADD_RtoR', 0x27: 'ADD_ConstantToR', 0x33: 'SUB_RtoR', 0x39: 'SUB_ConstantToR',
    0x45: 'MUL_RtoR', 0x4b: 'MUL_ConstantToR', 0x57: 'DIV_RtoR', 0x5d: 'DIV_ConstantToR',
    0x5e: 'CMPG_RtoR', 0x62: 'CMPL_RtoR', 0x66: 'CMPE_RtoR',
    0x6a: 'CMPG_ConstantToR', 0x6c: 'CMPL_ConstantToR', 0x6e: 'CMPE_ConstantToR',
    0x70: 'Move_ConstantToR', 0x72: 'Move_RtoR',
    0x81: 'AND_RtoR', 0x87: 'AND_ConstantToR', 0x93: 'OR_RtoR', 0x99: 'OR_ConstantToR',
    0xa5: 'XOR_RtoR', 0xab: 'XOR_ConstantToR', 0xb0: 'ROT',
    0xb8: 'AXRUN_Constant', 0xb9: 'AXRUN_R', 0xbb: 'AXSTOP', 0xbc: 'AXMOVE',
    0xbd: 'KEYSCAN', 0xbe: 'TchFile',
    0xc2: 'TIM_1ms_Constant', 0xc3: 'TIM_10ms_Constant', 0xc4: 'TIM_100ms_Constant',
    0xc5: 'TIM_1000ms_Constant', 0xc6: 'CNTUP_Constant', 0xc7: 'CNTDOWN_Constant',
    0xc9: 'CNTRESET', 0xca: 'JMP', 0xcb: 'JSR', 0xcf: 'END', 0xd0: 'RTS',
    0xd4: 'MSG', 0xd5: 'LAB', 0xd7: 'ExtFunc', 0xd8: 'RS232',
    0xd9: 'ASCToBIN', 0xda: 'BINToASC', 0xdb: 'PutChar', 0xdc: 'GetChar',
    0xdd: 'HexToDec', 0xde: 'MODR', 0xdf: 'MODW',
    0xe0: 'CNTRINGUP_Constant', 0xe1: 'CNTRINGDOWN_Constant',
    0xe2: 'TIM_10ms_R', 0xe3: 'TIM_100ms_R', 0xe4: 'TIM_1000ms_R', 0xe7: 'TIM_1ms_R',
    0xe5: 'CNTUP_R', 0xe6: 'CNTDOWN_R', 0xe9: 'CNTRINGUP_R', 0xea: 'CNTRINGDOWN_R',
    0xeb: 'MODRS', 0xec: 'SRI', 0xf0: 'BGNDRun', 0xf1: 'BGNDStop', 0xfd: 'FEND',
}


def op_info(op):
    """opcode -> {group, func, bi, op1mode, op2mode}; 未定义返回 None"""
    v = PLCOP_RAW[op]
    if v == 0:
        return None
    return {
        'group': GROUP[v & 0xF],
        'func': (v & 0x1F0) >> 4,
        'bi': bool(v & 0x200),
        'op1': OPER[(v & 0x1C00) >> 10],
        'op2': OPER[(v & 0xE000) >> 13],
    }


def is_bi(op):
    """该 opcode 是否占 8 字节(双格)"""
    return bool(PLCOP_RAW[op] & 0x200)


# 兼容旧接口: op -> (name, kind)   kind='fb' 表示双格
OP = {op: (EOF_NAME.get(op, f'Op{op:02x}'), 'fb' if is_bi(op) else 'c4')
      for op in range(256) if PLCOP_RAW[op]}


# ==================== 数值 ====================
def bytes_int(b1, b2):
    """plc.BytesInt: 有符号 16 位小端"""
    if b2 >> 7 == 0:
        return b2 * 256 + b1
    return -1 * ((b2 ^ 0xFF) * 256 + (b1 ^ 0xFF) + 1)


def bytes_uint(b1, b2):
    """plc.BytesUInt: 无符号 16 位小端"""
    return b2 * 256 + b1


# ==================== 操作数解码 (plc.GetOperand 移植) ====================
def get_operand(group, mode, addr, buf):
    """addr=2 取操作数1, addr=4 取操作数2; buf 为 4 或 8 字节单元缓冲"""
    n = len(buf)

    def at(i):
        return buf[i] if 0 <= i < n else 0

    if mode == 'PLCBits':
        num = at(addr) | (at(addr + 1) << 8)
        n3 = num & 0xFFF
        n4 = num >> 12
        if n4 == 0:
            dev = ("I", "O", "C", "S", "A")
            t = n3 >> 9
            if t < 5:
                return f"{dev[t]}{n3 & 0x1FF}"
            return f"?{t}:{n3 & 0x1FF}"
        if 1 <= n4 <= 5:
            return f"R{(n3 >> 5) + (n4 - 1) * 128}.{n3 & 0x1F}"
        return f"?BIT{num:04X}"

    if mode == 'Timer':
        return f"TM{bytes_int(at(addr), at(addr + 1))}"
    if mode == 'Counter':
        return f"CT{bytes_int(at(addr), at(addr + 1))}"
    if mode == 'Register':
        num = bytes_uint(at(addr), at(addr + 1))
        ind = False
        if group not in ('Timer', 'RS232'):
            if addr == 2 and at(6) in (2, 3):
                ind = True
            elif addr == 4 and at(6) in (1, 3):
                ind = True
        return ("@" if ind else "") + f"R{num}"
    if mode == 'ConstValue':
        return f"#{bytes_int(at(addr), at(addr + 1))}"
    if mode == 'String':
        raw = bytes(at(addr + i) for i in range(6)).split(b'\0')[0]
        return text_of(raw)
    if mode == 'DeviceNameLead':
        lead = {'Axis': 'AX', 'Coord': 'AG', 'Keyscan': 'KS', 'RS232': 'RS',
                'FileSys': 'FS', 'External': 'BG'}.get(group, '?')
        return f"{lead}{bytes_int(at(addr), at(addr + 1))}"
    return f"?{mode}"


# ==================== 记录解析 (mainForm.Openfile 的忠实移植) ====================
# 编辑器行只由两类记录产生: 逻辑记录 / 注释记录且 CommentType∈{1,3}
# CommentType=2(版本) 与 =4(设备变量注释) 不产生行
def parse_raw(data):
    """返回全部记录 [(kind, payload, raw_record, comment_type)]
       kind: 'logic' / 'comment' / 'version' / 'varcmt'"""
    n = len(data) // 40
    body = data[:n * 40]
    out = []
    idx = 0
    while idx < n:
        base = idx * 40
        rec = body[base:base + 40]
        if rec[1] == 0 and rec[3] != 0:
            num2 = rec[2]
            if num2 == 0:
                out.append(('comment', b'', rec, rec[3]))
                idx += 1
                continue
            chars = bytearray()
            num3 = 6
            cur = rec
            consumed = 0
            j = 1
            while j <= num2:
                chars.append(cur[num3])
                num3 = num3 + 1 if (num3 % 4 != 3) else num3 + 3
                if j < num2 and num3 == 42:
                    consumed += 1
                    cb = base + consumed * 40
                    cur = body[cb:cb + 40]
                    num3 = 2
                j += 1
            ct = rec[3]
            kind = 'comment' if ct in (1, 3) else ('version' if ct == 2 else 'varcmt')
            out.append((kind, bytes(chars), rec, ct))
            idx += 1 + consumed
        else:
            out.append(('logic', rec, rec, 0))
            idx += 1
    return out


def parse_records(data):
    """编辑器视角的行序列: 逻辑行 + ct∈{1,3} 注释行, 序号即编辑器行号 R1.."""
    return [(k, p) for k, p, _r, _c in parse_raw(data) if k in ('logic', 'comment')]


def parse_version(data):
    """CommentType=2 记录里的文件版本号"""
    for k, p, _r, _c in parse_raw(data):
        if k == 'version':
            try:
                return int(text_of(p).split('\t')[0])
            except Exception:
                return None
    return None


def text_of(payload):
    """Big5 解码。.NET 的 Encoding("Big5") 实为 cp950 扩展集,
       个别注释含扩展区字节(Python 的 big5 不支持), 回退 big5hkscs。"""
    try:
        return payload.decode('big5')
    except Exception:
        try:
            return payload.decode('big5hkscs', 'replace')
        except Exception:
            return payload.decode('big5', 'replace')


# ==================== 单元标签 ====================
COIL_SYM = {0: '=', 1: '/', 2: '^', 3: 'v', 4: 'S', 5: 'R'}


def _contact_label(info, buf):
    """触点: func 0/1=普通 NO/NC, 2/3=定时器, 4/5=计数器"""
    f = info['func']
    mode, suf = info['op1'], ('NO' if f % 2 == 0 else 'NC')
    if mode == 'PLCBits':
        return f"[{get_operand(info['group'], mode, 2, buf)} {suf}]"
    if mode == 'Timer':      # 定时器触点只用 1 字节编号 (ContactConverter 取 byteArg1[0])
        return f"[TM{buf[2]} {suf}]"
    if mode == 'Counter':
        return f"[CT{buf[2]} {suf}]"
    return f"[? {suf}]"


def _coil_label(info, buf):
    return f"[{get_operand(info['group'], info['op1'], 2, buf)} {COIL_SYM.get(info['func'], '?')}]"


def _block_label(op, info, buf):
    """双格功能块标签"""
    g, f = info['group'], info['func']
    title = FUN_TITLE.get(g, ['?'] * 16)
    name = title[f] if f < len(title) else f"f{f}"

    if g == 'Function':
        s1 = get_operand(g, info['op1'], 2, buf)
        s2 = get_operand(g, info['op2'], 4, buf)
        if f == 7:                                  # MOV: 源 -> 目标
            return f"[{name} {s1} -> {s2}]"
        # SUB/DIV 非交换, 必须写出结果式: arg2 是目标兼被操作数
        # 依据: mainForm 编辑提示 "SUB R** R**" (arg1=来源, arg2=目标);
        #       ROT 同模型 (arg1=来源 R50, arg2=目标 R86) 已由实机确认。
        #       cnc_1 R5 DIV #1000 R6030 亦证明 arg2 是目的: R6030=R6030/1000
        sym = {'SUB': '-', 'DIV': '/'}.get(name)
        if sym and s2:
            return f"[{name} {s1} {s2} ({s2}{sym}{s1})]"
        return f"[{name} {s1} {s2}]"

    if g == 'Timer':
        return f"[{name} {get_operand(g, info['op1'], 2, buf)} PV={get_operand(g, info['op2'], 4, buf)}]"

    if g == 'Counter':
        return f"[{name} {get_operand(g, info['op1'], 2, buf)} PV={get_operand(g, info['op2'], 4, buf)}]"

    if g == 'Tool':                                 # ROT: 源 -> 目标
        s1 = get_operand(g, info['op1'], 2, buf)
        s2 = get_operand(g, info['op2'], 4, buf)
        return f"[ROT {s1} -> {s2}]"

    if g == 'Flow':
        if f in (4, 5, 6):                          # RTS / END / FEND 无参数
            return f"[{name}]"
        lbl = get_operand(g, info['op1'], 2, buf)
        return f"[{name} {lbl}]" if lbl else f"[{name}]"

    # Axis / RS232 / FileSys / External / Keyscan
    s1 = get_operand(g, info['op1'], 2, buf)
    s2 = get_operand(g, info['op2'], 4, buf)
    parts = [p for p in (s1, s2) if p]
    return f"[{name} {' '.join(parts)}]" if parts else f"[{name}]"


def cell_labels(rec):
    """返回 [(label, is_second_half)] 共 10 项; 双格的第 2 格标 is_second_half=True"""
    out = []
    i = 0
    while i < 10:
        c0 = i * 4
        cell = rec[c0:c0 + 4]
        op = cell[1]
        info = op_info(op)
        if info and info['bi'] and i < 9:
            buf = rec[c0:c0 + 8]
            out.append((_block_label(op, info, buf), False))
            out.append(('', True))
            i += 2
            continue
        if op == 0x00:
            out.append(('·', False))            # Empty: 空白格, 不画横线
        elif op == 0x0d:
            out.append(('─', False))            # Line: 水平连线格
        elif info and info['group'] == 'Contact':
            out.append((_contact_label(info, cell), False))
        elif info and info['group'] == 'Coil':
            out.append((_coil_label(info, cell), False))
        elif info:
            out.append((f"[{EOF_NAME.get(op, f'Op{op:02x}')}]", False))
        else:
            out.append((f"?0x{op:02x}", False))
        i += 1
    return out


def decode_logic_row(rec):
    return [l for l, _ in cell_labels(rec)]


def dev_addr(num, bit_ok=True):
    """兼容旧接口: 把 16 位 PLCBits 原始值解成设备名 (I/O/C/S/A 或 Rxx.yy)"""
    return get_operand('Contact', 'PLCBits', 0,
                       bytes([num & 0xFF, (num >> 8) & 0xFF, 0, 0, 0, 0, 0, 0]))


# ==================== 接线 (conn byte0) ====================
def vert_line(rec):
    """固定 10 列, 每列 3 字符: ' . '无 / ' U '上半段 / ' D '下半段 / ' X '上下都有
       双格功能块的后半列没有独立 conn, 留空"""
    out = []
    i = 0
    while i < 10:
        c = rec[i * 4]
        up, dn = bool(c & 4), bool(c & 8)
        out.append(' X ' if up and dn else (' U ' if up else (' D ' if dn else ' . ')))
        if is_bi(rec[i * 4 + 1]) and i < 9:
            out.append(' . ')
            i += 2
        else:
            i += 1
    return ''.join(out)


# ==================== 程序结构 ====================
def find_blocks(rec):
    """遍历一行的单元: yield (列号, opcode, 该单元字节缓冲 4 或 8 字节)"""
    i = 0
    while i < 10:
        c0 = i * 4
        op = rec[c0 + 1]
        if is_bi(op) and i < 9:
            yield i, op, rec[c0:c0 + 8]
            i += 2
        else:
            yield i, op, rec[c0:c0 + 4]
            i += 1


def row_blocks(rec, ops):
    """取出本行中 opcode ∈ ops 的 (列号, 缓冲)"""
    return [(c, b) for c, op, b in find_blocks(rec) if op in ops]


def sections(data):
    """按 END / LAB / RTS 切出主程序与各子程序
       返回 [(kind, title, start_row, end_row)]"""
    rows = parse_records(data)
    out = []
    main_end = None
    for i, (k, p) in enumerate(rows):
        if k == 'logic' and p[1] == 0xcf:
            main_end = i
            break
    if main_end is None:
        return [('main', '主程序', 1, len(rows))]

    out.append(('main', '主程序', 1, main_end + 1))
    i = main_end + 1
    while i < len(rows):
        k, p = rows[i]
        if k == 'logic':
            labs = row_blocks(p, (0xd5,))
        else:
            labs = []
        if labs:
            start = i + 1
            title = get_operand('Flow', 'String', 2, labs[0][1])
            j = i
            end = len(rows)
            while j < len(rows):
                k2, p2 = rows[j]
                if k2 == 'logic' and row_blocks(p2, (0xd0,)):
                    end = j + 1
                    break
                j += 1
            out.append(('sub', f'子程序 {title}', start, end))
            i = end
        else:
            i += 1
    return out


def jsr_targets(data):
    """返回 ({标签: 定义行号}, [(调用行, 指令, 标签)])"""
    rows = parse_records(data)
    defs, calls = {}, []
    for i, (k, p) in enumerate(rows):
        if k != 'logic':
            continue
        for _c, buf in row_blocks(p, (0xd5,)):
            defs[get_operand('Flow', 'String', 2, buf)] = i + 1
        for _c, buf in row_blocks(p, (0xcb, 0xca)):
            op = buf[1]
            calls.append((i + 1, 'JSR' if op == 0xcb else 'JMP',
                          get_operand('Flow', 'String', 2, buf)))
    return defs, calls


# ==================== 设备注释表 ====================
def load_comments(data):
    """设备变量注释: {名称: (短注释, 长注释)}"""
    cm = {}
    for k, p, _r, _c in parse_raw(data):
        if k == 'varcmt':
            f = text_of(p).split('\t')
            if len(f) >= 3:
                cm[f[0].strip()] = (f[1].strip(), f[2].strip())
            elif len(f) >= 2:
                cm[f[0].strip()] = (f[1].strip(), '')
    return cm


def annotate(lab, cm):
    """给标签里的 Rxxxx 追加中文注释, 如 R808 -> R808(程式鎖)"""
    if not cm or 'R' not in lab:
        return lab
    out, i = [], 0
    while i < len(lab):
        if lab[i] == 'R' and (i == 0 or not lab[i - 1].isalnum()):
            j = i + 1
            while j < len(lab) and lab[j].isdigit():
                j += 1
            if j > i + 1:
                name = lab[i:j]
                note = cm.get(name, ('', ''))[0]
                if note:
                    out.append(f"{name}({note})")
                    i = j
                    continue
        out.append(lab[i])
        i += 1
    return ''.join(out)


# ==================== 报告 ====================
def _row_lines(rec, use_ascii, cm):
    labs = [annotate(l, cm) for l in decode_logic_row(rec) if l]
    lines = [' '.join(labs) if labs else '(空行)']
    if use_ascii:
        v = vert_line(rec)
        vv = ''.join(v[i * 3 + 1] for i in range(10))
        if vv.strip(' .'):
            lines.append('接线 ' + vv)
    return lines


def report(data, start=1, end=None, use_ascii=False, cm=None):
    rows = parse_records(data)
    total = len(rows)
    if end is None:
        end = total
    for idx in range(start - 1, min(end, total)):
        k, p = rows[idx]
        row = idx + 1
        if k == 'comment':
            print(f"R{row:<5d}| 注释 {text_of(p)}")
        else:
            lines = _row_lines(p, use_ascii, cm)
            print(f"R{row:<5d}| {lines[0]}")
            for extra in lines[1:]:
                print(f"{'':7s}| {extra}")
    return rows


def dump_devices(data):
    raw = parse_raw(data)
    n = sum(1 for k, _, _, _ in raw if k == 'varcmt')
    print(f"设备变量注释表: {n} 条")
    for k, p, _r, _c in raw:
        if k == 'varcmt':
            f = text_of(p).split('\t')
            if len(f) >= 3:
                print(f"  {f[0].strip():<8s} {f[1].strip():<28s} {f[2].strip()}")
            else:
                print('  ' + text_of(p))


def print_struct(data):
    rows = parse_records(data)
    print("=== 程序结构 ===")
    for kind, title, s, e in sections(data):
        print(f"  {title:<14s} R{s} .. R{e}   ({e - s + 1} 行)")
    defs, calls = jsr_targets(data)
    if calls:
        print("\n=== 调用与标签 ===")
        for r, kind, lbl in calls:
            tgt = defs.get(lbl)
            arrow = f"-> R{tgt}" if tgt else "(未定义!)"
            print(f"  R{r} {kind} {lbl}  {arrow}")
    if defs:
        print("\n=== 标签定义 ===")
        for lbl, r in sorted(defs.items(), key=lambda x: x[1]):
            who = [f"R{cr}" for cr, _k, l in calls if l == lbl]
            print(f"  {lbl} @ R{r}" + (f"   被 {', '.join(who)} 调用" if who else "   (无人调用)"))


# ==================== CLI ====================
if __name__ == '__main__':
    path = sys.argv[1] if len(sys.argv) > 1 else r"C:\Users\panming\Desktop\cnc.lad"
    data = open(path, 'rb').read()
    raw = parse_raw(data)
    rows = parse_records(data)
    nlog = sum(1 for k, _ in rows if k == 'logic')
    nvar = sum(1 for k, _, _, _ in raw if k == 'varcmt')

    print(f"文件: {path}  大小: {len(data)} 字节  ({len(data)//40} 条 40 字节记录 + "
          f"末尾 {data[-2:].hex(' ')} 结束标记)")
    print(f"编辑器行 {len(rows)} 行 = 逻辑 {nlog} + 注释 {len(rows)-nlog};  "
          f"文件版本 m_nLadVer={parse_version(data)}")
    print(f"另有设备变量注释 {nvar} 条 (CommentType=4, 不占编辑器行)")
    for i, (k, p) in enumerate(rows):
        if k == 'logic' and p[1] == 0xcf:
            print(f"END -> R{i+1}")

    args = sys.argv[2:]
    if args and args[0] == '--dev':
        print()
        dump_devices(data)
        sys.exit()
    if args and args[0] == '--struct':
        print()
        print_struct(data)
        sys.exit()

    ascii_mode = bool(args and args[0] == '--ascii')
    if ascii_mode:
        args = args[1:]
    use_annot = not (args and args[0] == '--noannot')
    if not use_annot:
        args = args[1:]
    cm = load_comments(data) if use_annot else None

    s = int(args[0]) if len(args) > 0 else 1
    e = int(args[1]) if len(args) > 1 else 30
    print(f"\n--- R{s}-R{e} ---")
    report(data, s, e, ascii_mode, cm)
