#!/usr/bin/env python3
"""Syntec cnc.lad 解码/编码 (逆向 v3, 列对齐)。

单元基础: 4 字节 [b0, type, b2, b3]; b0=垂直分支标志位(位0↑ 位1↓ 位2 位3)
  触点/线圈: b2=地址号, b3=族(触点=0, 线圈=2)
功能块: 8 字节 [cell][param4], param=[B,0,0,0x80]; 计算 B = B OP A

已知 4 字节类型:
  0x00 空  0x0d 横线  0xcf END
  0x01 常开接点  0x03 常闭接点
  0x0e 常开线圈 0x10 常闭线圈 0x05 正缘脉冲 0x07 负缘脉冲 0x12 Latch 0x14 Unlatch
已知 8 字节(功能块)类型:
  math:  0x21 ADD  0x27 ADD_IMM  0x33 SUB  0x45 MUL  0x57 DIV  (假设)
  move:  0x72 MOV(reg)  0x70 MOV_IMM  (假设)
  logic: 0x81 AND  0x93 OR  0xa5 XOR  (假设)
  cmp :  0x5e 大于(>) 0x62 小于(<) 0x66 等于(=)   [寄存器 vs 寄存器]
         0x6a 大于(>数值型) 0x6e 等于(=数值型)     [寄存器 vs 常数]   (均由编辑器实测确认)
  timer: 8 种变体(精度×源), 见 TIMER_TYPE; 参数块=[值低,值高,值低,0x80] 16位小端
文件尾: [00 fe]; 无批注时网格后直接 00 fe。
"""
import sys

TYPE4 = {
    0x00: 'EMPTY', 0x0d: 'WIRE', 0xcf: 'END',
    0xd0: 'RTS', 0xfd: 'FEND',
    0x01: ('CONTACT','NO'), 0x03: ('CONTACT','NC'),
    0x0e: ('COIL','NO'), 0x10: ('COIL','NC'),
    0x05: ('COIL','RP'), 0x07: ('COIL','FP'),
    0x12: ('COIL','LATCH'), 0x14: ('COIL','UNLATCH'),
}
TYPE8 = {
    # 数学块: 8位操作数模式(小地址) 0x21/0x27/0x45/0x57 ; 16位操作数模式(大地址, cnc.lad真机) 0x33/0x4b/0x5d
    0x21:'MATH',0x27:'MATH',0x33:'MATH',0x45:'MATH',0x4b:'MATH',0x57:'MATH',0x5d:'MATH',
    0x5e:'CMP',0x62:'CMP',0x66:'CMP',0x6a:'CMP',0x6e:'CMP',
    0x70:'MOVE',0x72:'MOVE',
    0x81:'LOGIC',0x93:'LOGIC',0xa5:'LOGIC',
    # 定时器变体 (精度×源, 全部由 B_timer.lad + 编辑器实测确认, 2026-10-31)
    0xc5:'TIMER',0xe4:'TIMER',0xe3:'TIMER',0xe2:'TIMER',
    0xe7:'TIMER',0xc4:'TIMER',0xc3:'TIMER',0xc2:'TIMER',
    # 计数器变体 (方向×源, 由 B_counter.lad 反推)
    0xc6:'CNTR',0xc7:'CNTR',0xc9:'CNTR',0xe0:'CNTR',0xe1:'CNTR',
    # 流程块 (8 字节, 带 6 字节 ASCII 标签)
    0xcb:'FLOW',0xd5:'FLOW',
    0xe5:'CNTR',0xe6:'CNTR',0xe9:'CNTR',0xea:'CNTR',
}

# ---- 定时器类型映射 (精度, 源) 源: 'K'=常数  'R'=寄存器 ----
# 全部 8 组合均由 B_timer.lad + 编辑器实测核对确认 (2026-10-31):
#   | 精度  | 常数(K) | 寄存器(R) |
#   | 1s    | c5      | e4        |
#   | 0.1s  | c4      | e3        |
#   | 0.01s | c3      | e2        |
#   |0.001s | c2      | e7        |
# 参数块: [值低字节, 值高字节, 值低字节, 0x80]; 值为 16 位小端整数
#   (常数=预设值; 寄存器=寄存器号, 如 R300 -> 0x012c).
TIMER_TYPE = {
    ('1s','K'):0xc5, ('1s','R'):0xe4,
    ('0.1s','K'):0xc4, ('0.1s','R'):0xe3,
    ('0.01s','K'):0xc3, ('0.01s','R'):0xe2,
    ('0.001s','K'):0xc2, ('0.001s','R'):0xe7,
}

# ---- 计数器类型映射 (方向, 源) 源: 'K'=预设值#N  'R'=寄存器R ----
CNTR_TYPE = {
    ('UP','K'):0xc6, ('UP','R'):0xe5,
    ('DOWN','K'):0xc7, ('DOWN','R'):0xe6,
    ('RESET','K'):0xc9,
    ('RING_UP','K'):0xe0, ('RING_UP','R'):0xe9,
    ('RING_DOWN','K'):0xe1, ('RING_DOWN','R'):0xea,
}
# 供预览显示用: opcode -> 可读标签 (与 TIMER_TYPE/CNTR_TYPE 互逆)
TIMER_LABEL = {v: f'TIM {pr} {sr}' for (pr, sr), v in TIMER_TYPE.items()}
CNTR_LABEL  = {v: f'CT {d} {sr}'  for (d, sr), v in CNTR_TYPE.items()}

COLS = 10

CMP_SYMBOL = {0x5e:'>',0x62:'<',0x66:'=',0x6a:'>K',0x6e:'=K'}
# 数学 opcode 对照 (2026-10-31 cnc.lad 真机实测修订):
#   加: 0x21(8位) / 0x33(16位) ; 加立即数: 0x27
#   乘: 0x45(8位) / 0x4b(16位) ; 除: 0x57(8位) / 0x5d(16位)
MATH_SYMBOL = {0x21:'+',0x27:'+K',0x33:'+',0x45:'×',0x4b:'×',0x57:'÷',0x5d:'÷'}
MOVE_SYMBOL = {0x72:'→',0x70:'←K'}
LOGIC_SYMBOL = {0x81:'AND',0x93:'OR',0xa5:'XOR'}

# ---- 类型映射 (2026-11-01 用 cnc.lad/cnc_1.lad 全量实测补齐 R/R 与 立即数 两类变体) ----
CONTACT_TYPE = {'NO':0x01,'NC':0x03}
COIL_TYPE    = {'NO':0x0e,'NC':0x10,'RP':0x05,'FP':0x07,'LATCH':0x12,'UNLATCH':0x14}
# 运算块: 不带 _IMM 的是 寄存器 vs 寄存器; 带 _IMM 的是 常数 vs 寄存器 (A=#常数, B=目标寄存器)
#   语义均为 B = B op A
MATH_TYPE    = {'ADD':0x21,'ADD_IMM':0x27,
                'SUB':0x33,'SUB_IMM':0x39,
                'MUL':0x45,'MUL_IMM':0x4b,
                'DIV':0x57,'DIV_IMM':0x5d}
MOVE_TYPE    = {'MOV':0x72,'MOV_IMM':0x70}
LOGIC_TYPE   = {'AND':0x81,'AND_IMM':0x87,'OR':0x93,'OR_IMM':0x99,
                'XOR':0xa5,'XOR_IMM':0xab}
# 比较: 不带 K 的是 R vs R; 带 K 的是 #常数 vs R (A=#常数, B=寄存器), 语义 A op B
CMP_TYPE     = {'GT':0x5e,'LT':0x62,'EQ':0x66,'GTK':0x6a,'LTK':0x6c,'EQK':0x6e}
TOOL_TYPE    = {'ROT':0xb0}

# ================= 解码 =================
def decode(data: bytes):
    rows = []
    cur = []
    col = 0
    pos = 0
    n = len(data)
    while pos + 4 <= n:
        b0,b1,b2,b3 = data[pos:pos+4]
        if b1 == 0x00 and (b2 != 0 or b3 != 0):
            break  # 进入网格后段(00 fe 或 批注)
        if b1 in TYPE8:
            if pos + 8 > n:
                break
            param = data[pos+4:pos+8]
            cur.append(('FB', b1, b2, b3, param, pos))
            pos += 8; col += 2
        else:
            t = TYPE4.get(b1)
            if t is None:
                break
            cur.append((t, b0, b2, b3, pos))
            pos += 4; col += 1
        if col >= COLS:
            rows.append(cur); cur = []; col = 0
    if cur:
        rows.append(cur)
    terminator = data[-2:] if len(data) - pos >= 2 else b''
    meta = data[pos:len(data)-2] if terminator else data[pos:]
    return rows, meta, terminator

def vflag(b0):
    if not b0: return ''
    s=''
    if b0&1: s+='↑'
    if b0&2: s+='↓'
    if b0&4: s+='r'
    if b0&8: s+='R'
    return s

def cell_label(c):
    if c[0]=='FB':
        _,typ,b2,b3,param,_=c
        cat=TYPE8[typ]
        if cat=='FLOW':
            lb=(bytes([b2,b3])+bytes(param))[:6].split(b'\x00')[0]
            return f'[{FLOW_NAME.get(typ,"FLOW")} "{lb.decode("ascii","replace")}"]'
        A=(b3<<8)|b2            # 第8格: 操作数1 = 16位小端(b2低,b3高)
        B=(param[1]<<8)|param[0] # 第9格: 操作数2/目的 = 16位小端(param[0]低,param[1]高)
        if typ in TIMER_LABEL:
            return f"[{TIMER_LABEL[typ]} A=TM{A} B={B}]"
        if typ in CNTR_LABEL:
            return f"[{CNTR_LABEL[typ]} A=CT{A} B={B}]"
        sym=''
        if typ in CMP_SYMBOL: sym=CMP_SYMBOL[typ]
        elif typ in MATH_SYMBOL: sym=MATH_SYMBOL[typ]
        elif typ in MOVE_SYMBOL: sym=MOVE_SYMBOL[typ]
        elif typ in LOGIC_SYMBOL: sym=LOGIC_SYMBOL[typ]
        return f"[{cat}{sym} A={A} B={B}]"
    t=c[0]; b0,b2,b3,_=c[1],c[2],c[3],c[4]
    vf=vflag(b0)
    if t=='EMPTY': return '·'+vf
    if t=='WIRE':  return '─'+vf
    if t=='END':   return 'END'
    if t=='RTS':   return 'RTS'
    if t=='FEND':  return 'FEND'
    kind,sub=t
    if kind=='CONTACT': return f"[I{b2} {sub}]{vf}"
    if kind=='COIL':    return f"[O{b2} {sub}]{vf}"
    return str(t)

def show(data, name=''):
    rows,meta,term=decode(data)
    print(f"\n===== {name} ===== size={len(data)} rows={len(rows)} term={term.hex()} meta={len(meta)}B")
    for ri,row in enumerate(rows):
        print(f"  R{ri+1:2d}: "+" ".join(f"{cell_label(c):<20}" for c in row))
    if meta:
        print(f"  [meta]: {meta[:80].hex()}")

# ================= 编码 (无批注: 网格 + 00 fe) =================
def enc_4(el):
    k=el[0]
    if k=='WIRE':   return bytes([0,0x0d,0,0])
    if k=='EMPTY':  return bytes([0,0,0,0])
    if k=='END':    return bytes([0,0xcf,0,0])
    # 16 位地址: n = (设备索引<<9) | 编号, 设备索引 I=0 O=1 C=2 S=3 A=4
    #   实测 B_branch.lad R1 col9 [O200] = 00 0e c8 02 -> n=0x02c8=712 = (1<<9)|200
    #   cnc_1.lad R25 col9 [C1]        = 00 0e 01 04 -> n=0x0401=1025 = (2<<9)|1
    if k=='CONTACT':return bytes([0,CONTACT_TYPE[el[1]],el[2]&0xff,(el[2]>>8)&0xff])
    if k=='COIL':   return bytes([0,COIL_TYPE[el[1]],el[2]&0xff,(el[2]>>8)&0xff])
    raise ValueError(k)

def _code(tab, op):
    """op 可以是助记符, 也可以是原始 opcode 字节(反序列化时用)"""
    return op if isinstance(op, int) else tab[op]

def enc_fb(cat, op, A, B, timer_param=b''):
    if cat in ('TIMER','CNTR'):
        return bytes([0,_code(TIMER_TYPE if cat=='TIMER' else CNTR_TYPE, op),
                      A & 0xff, (A>>8)&0xff]) + (timer_param or b'\x00\x00\x00\x80')
    ttab={'MATH':MATH_TYPE,'MOVE':MOVE_TYPE,'LOGIC':LOGIC_TYPE,
          'CMP':CMP_TYPE,'ROT':TOOL_TYPE}[cat]
    return bytes([0,_code(ttab,op),A&0xff,(A>>8)&0xff])+bytes([B&0xff,(B>>8)&0xff,0,0x80])

def enc_timer(precision, source, A, value):
    """定时器 8 字节单元. precision: '1s'/'0.1s'/'0.01s'/'0.001s'; source: 'K'/'R'.
    value: 预设值(常数) 或 寄存器号(R, 显示值即寄存器号).
    参数块=[值低字节, 值高字节, 值低字节, 0x80]; 值为 16 位小端整数 (源 B_timer.lad 实测)."""
    typ = TIMER_TYPE[(precision, source)]
    v = value & 0xffff
    param = bytes([v & 0xff, (v >> 8) & 0xff, v & 0xff, 0x80])
    return bytes([0, typ, A & 0xff, (A >> 8) & 0xff]) + param

def enc_counter(direction, source, A, X):
    """计数器 8 字节单元. direction: 'UP'/'DOWN'/'RESET'/'RING_UP'/'RING_DOWN'; source:'K'/'R'.
    X: 预设值(#N) 或 寄存器号(R). 参数块=[X, 0, 0, 0x80]."""
    typ = CNTR_TYPE[(direction, source)]
    param = bytes([X & 0xff, 0, 0, 0x80])
    return bytes([0, typ, A & 0xff, (A >> 8) & 0xff]) + param

# ---- 流程控制 (8 字节; 标签为 6 字节 ASCII, 不足补 0) ----
# 实证: B_flow.lad R1 [JSR "HI"] = 00 cb 48 49 00 00 00 00 (编辑器生成)
#       cnc_1.lad R1334 [JSR "001"] = 00 cb 30 30 31 00 00 00 (col8)
#       cnc_1.lad R1339 [LAB "001"] = 00 d5 30 30 31 00 00 00 (col0)
#       cnc_1.lad R1352 [RTS]       = 00 d0 00 00 00 00 00 00 (col0)
#       cnc.lad  R1120 [END]        = 00 cf 00 00 00 00 00 80 (col0)
FLOW_TYPE = {'JMP':0xca, 'JSR':0xcb, 'MSG':0xd4, 'LAB':0xd5,
             'RTS':0xd0, 'END':0xcf, 'FEND':0xfd}
FLOW_NAME = {v: k for k, v in FLOW_TYPE.items()}
# 宽度: JSR/LAB 带 6 字节标签 => 8 字节(2 列); RTS/FEND 无标签 => 4 字节(1 列)
#   cnc_1.lad 实测: LAB "001"=[00 d5 30 30 31 00 00 00] (8B)
#                   RTS       =[00 d0 00 00] (4B, 后接普通连接线)
FLOW_WIDE = {'JMP':1, 'JSR':1, 'MSG':1, 'LAB':1, 'RTS':0, 'FEND':0, 'END':0}

def enc_flow(op, label=''):
    """op: 'JSR'/'LAB'/'RTS'/'FEND'/'END'/'JMP'/'MSG'; label: 标签(≤6 字节 ASCII)"""
    lb = str(label).encode('ascii', 'ignore')[:6]
    body = bytes([0, FLOW_TYPE[op]])
    if not FLOW_WIDE[op]:
        return body + b'\x00\x00'
    return body + lb.ljust(6, b'\x00')


def enc_el(el):
    """任意元件 -> 原始字节 (长度决定它占几列: 4 字节=1 列, 8 字节=2 列)。

    这是唯一的编码入口; span_of 直接由它推出来, 所以"占几列"永远与"写几个字节"一致,
    不会出现 8 字节块被算成 1 列这种错位。

    el 形态:
      ('EMPTY',) ('WIRE',) ('END',)                     4 字节
      ('CONTACT','NO'|'NC', n)  ('COIL', 符号, n)         4 字节
      ('CONTACT_T','NO'|'NC', tm号)  定时器触点 0x09/0x0a  4 字节
      ('CONTACT_C','NO'|'NC', ct号)  计数器触点 0x0b/0x0c  4 字节
      ('FB', cat, op, A, B[, param])                     8 字节 (cat=MATH/MOVE/LOGIC/CMP/ROT/TIMER/CNTR)
      ('FB','FLOW', 助记符, 标签)                          JSR/LAB 8 字节, RTS/FEND 4 字节
      ('FLOW4', opcode) / ('FLOW8', opcode, 6字节原样)     反序列化用, 字节原样保留
      ('RAW', 原始字节)                                   反序列化用, 完全原样
    """
    k = el[0]
    if k == 'RAW':
        return bytes(el[1])
    if k == 'FLOW8':
        return bytes([0, el[1]]) + bytes(el[2]).ljust(6, b'\x00')
    if k == 'FLOW4':
        return bytes([0, el[1], 0, 0])
    if k in ('EMPTY', 'WIRE', 'END', 'CONTACT', 'COIL'):
        return enc_4(el)
    if k == 'CONTACT_T':
        return bytes([0, 0x09 if el[1] == 'NO' else 0x0a, el[2] & 0xff, 0])
    if k == 'CONTACT_C':
        return bytes([0, 0x0b if el[1] == 'NO' else 0x0c, el[2] & 0xff, 0])
    if k == 'FB':
        cat = el[1]
        if cat == 'FLOW':
            return enc_flow(el[2], el[3] if len(el) > 3 else '')
        return enc_fb(cat, el[2], el[3], el[4],
                      el[5] if len(el) > 5 else b'')
    raise ValueError(f"无法编码的元件: {el!r}")


def span_of(el):
    """该元件占几列: 由编码后的字节数决定 (4 字节=1 列, 8 字节=2 列)"""
    return len(enc_el(el)) // 4


def is_left_anchored(el):
    """该元件单独成行时是否固定在 col0 (END / LAB / RTS / FEND)。"""
    if el[0]=='END':
        return True
    return el[0]=='FB' and el[1]=='FLOW' and el[2] in ('LAB','RTS','FEND')


def place_rung(els):
    """els: 有序元件列表。返回 10 列网格(功能块第2列用 None 占位)。
    规则: 单元件靠右(col9 或 FB@8); 多元件首@0 末靠右; FB 占 2 列。"""
    spans=[span_of(e) for e in els]
    n=len(els)
    if n==0:
        return [('WIRE',)]*COLS
    if n==1:
        # 单 END 元素、以及 LAB/RTS/FEND 这类"行首标记"放 col0(与编辑器一致); 其余靠右
        if is_left_anchored(els[0]):
            cols=[0]
        else:
            cols=[COLS-spans[0]]
    else:
        cols=[0]
        mc=1
        for i in range(1,n-1):
            cols.append(mc); mc+=spans[i]
        cols.append(COLS-spans[-1])
    grid=[('WIRE',)]*COLS
    for e,c in zip(els,cols):
        grid[c]=e
        if span_of(e)==2:          # 只有 8 字节块才吃掉右边一格(RTS/FEND 是 4 字节, 不吃)
            grid[c+1]=None
    # 校验总列数=10
    total=0
    for cell in grid:
        if cell is None: continue
        total += span_of(cell)
    if total!=COLS:
        raise ValueError(f"rung spans {total} cols, expected {COLS}")
    return grid

def emit_row(grid):
    out=bytearray()
    for cell in grid:
        if cell is None: continue
        if cell[0]=='FB':
            if cell[1]=='FLOW':
                out+=enc_flow(cell[2], cell[3] if len(cell)>3 else '')
            else:
                out+=enc_fb(cell[1],cell[2],cell[3],cell[4],cell[5] if len(cell)>5 else b'')
        else:
            out+=enc_4(cell)
    return bytes(out)

def build_grid(rungs):
    out=bytearray()
    for els in rungs:
        out+=emit_row(place_rung(els))
    out+=b'\x00\xfe'
    return bytes(out)

# ---- 直接按解码后的列位序列化(用于回环测试, 保留分支标志 b0) ----
def enc_decoded_cell(c):
    if c[0]=='FB':
        _,typ,b2,b3,param,_=c
        return bytes([0,typ,b2,b3])+param
    t,b0,b2,b3,pos=c
    if t=='EMPTY': return bytes([b0,0,0,0])
    if t=='WIRE':  return bytes([b0,0x0d,0,0])
    if t=='END':   return bytes([0,0xcf,0,0])
    kind,sub=t
    if kind=='CONTACT': return bytes([b0,CONTACT_TYPE[sub],b2,0])
    if kind=='COIL':    return bytes([b0,COIL_TYPE[sub],b2,2])
    raise ValueError(t)

def encode_rows(rows):
    out=bytearray()
    for row in rows:
        for c in row:
            out+=enc_decoded_cell(c)
    out+=b'\x00\xfe'
    return bytes(out)

def roundtrip(path):
    d=open(path,'rb').read()
    rows,meta,term=decode(d)
    enc=encode_rows(rows)
    # 比较网格部分(忽略 meta, 样本无批注)
    ok = d[:-2]==enc[:-2] if not meta else (d==enc)
    return ok, len(d), len(enc)

if __name__=='__main__':
    files=['B_coils','B_compare','B_contacts','B_logic','B_math','B_move']
    base=r'C:\Users\panming\Desktop'
    if len(sys.argv)>1:
        files=sys.argv[1:]; base=''
    for f in files:
        p=f if f.endswith('.lad') else f"{base}\\{f}.lad"
        try: show(open(p,'rb').read(), f)
        except FileNotFoundError: print(f"\n===== {f} ===== NOT FOUND")
