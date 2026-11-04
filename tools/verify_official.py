# -*- coding: utf-8 -*-
"""与官方编辑器的一致性回归 —— 基准来自反编译 MLCEdit.exe。

**这份脚本的期望值不是我们自己的假设，是官方程序集里的常量表。**
基准来源（2026-11-04 反编译，PLC Editor 安装目录 C:\\syntec\\LadEditor）：

  MLCEdit.exe  Tools/Converter/EOpcode_V1.cs   操作码 -> 元件类型
               （CellFactory.New 直接拿 v1CellBuf[1] 强转这个枚举）
  MLCEdit.exe  Tools/Converter/CellFactory.cs  每个操作码生成哪个 Cell
  MLCEdit.exe  Tools/plc.cs  plcop_map[256]    group / func / bi / op1 / op2 位段
  MLCEdit.exe  Tools/Converter/*Converter.cs   每个元件的字段布局
  MLCEdit.exe  ViewModule/LadderView.cs        元件怎么画（标题 / 操作数1 / 操作数2）

  LadDLL.dll 是原生 C++（文件读写），不在本脚本比对范围内。

检查项：
  1. 操作码快照：官方 80 个码的名称与数值，一个都不能错
  2. 覆盖：每个官方码都能解码，不抛异常（含官方标 "none" 的遗留码）
  3. 宽度：编码长度 = 官方 isBiCell（RTS 例外，见 FLOW_WIDE 的字节证据）
  4. 助记符：定时器/计数器/数学/比较/逻辑/搬移/旋转 与官方枚举名一一对应
  5. END 保留区（第 2 格）原样保留，不被清零
  6. 计数器预设 16 位（官方 CounterConverter 用 BytesToUShort）
  7. 比较块 op1 是常数还是寄存器，随 opcode 走（CMPx_ConstantToR vs CMPx_RtoR）
  8. 流程块渲染成 FEND / RTS / JSR n / LAB n，不是 FLOW4 / FLOW8
  9. 真机语料全覆盖：任何单元都不会落进「未知操作码」

用法:
    python tools/verify_official.py
    python tools/verify_official.py a.lad b.lad     # 额外指定要扫的语料
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "src"), os.path.join(os.path.dirname(_HERE), "src")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

import syntec_lad as L
import syntec_parse as P
import syntec_re as R
import syntec_layout as Y
import syntec_read as RD

OK, FAIL = "[OK  ]", "[FAIL]"
CHECKS = []


def chk(msg, cond, detail=""):
    CHECKS.append((msg, bool(cond), detail))
    print("  %s %s" % (OK if cond else FAIL, msg))
    if not cond and detail:
        print("        %s" % str(detail)[:300])


# ------------------------------------------------------------------ 1. 官方快照
# 逐字来自 EOpcode_V1.cs（顺序已按数值重排）
OFFICIAL = {
    0x00: 'Empty', 0x01: 'NormalOpenContact', 0x03: 'NormalCloseContact',
    0x05: 'PosEdgeTriggerCoil', 0x07: 'NegEdgeTriggerCoil',
    0x09: 'NormalOpenContact_Timer', 0x0a: 'NormalCloseContact_Timer',
    0x0b: 'NormalOpenContact_Counter', 0x0c: 'NormalCloseContact_Counter',
    0x0d: 'Line', 0x0e: 'NormalOpenCoil', 0x10: 'NormalCloseCoil',
    0x12: 'LatchCoil', 0x14: 'UnLatchCoil',
    0x21: 'ADD_RtoR', 0x27: 'ADD_ConstantToR',
    0x33: 'SUB_RtoR', 0x39: 'SUB_ConstantToR',
    0x45: 'MUL_RtoR', 0x4b: 'MUL_ConstantToR',
    0x57: 'DIV_RtoR', 0x5d: 'DIV_ConstantToR',
    0x5e: 'CMPG_RtoR', 0x6a: 'CMPG_ConstantToR',
    0x62: 'CMPL_RtoR', 0x6c: 'CMPL_ConstantToR',
    0x66: 'CMPE_RtoR', 0x6e: 'CMPE_ConstantToR',
    0x70: 'Move_ConstantToR', 0x72: 'Move_RtoR',
    0x81: 'AND_RtoR', 0x87: 'AND_ConstantToR',
    0x93: 'OR_RtoR', 0x99: 'OR_ConstantToR',
    0xa5: 'XOR_RtoR', 0xab: 'XOR_ConstantToR',
    0xb0: 'ROT',
    0xb8: 'AXRUN_Constant', 0xb9: 'AXRUN_R', 0xbb: 'AXSTOP', 0xbc: 'AXMOVE',
    0xbd: 'KEYSCAN', 0xbe: 'TchFile',
    0xc2: 'TIM_1ms_Constant', 0xc3: 'TIM_10ms_Constant',
    0xc4: 'TIM_100ms_Constant', 0xc5: 'TIM_1000ms_Constant',
    0xc6: 'CNTUP_Constant', 0xc7: 'CNTDOWN_Constant', 0xc9: 'CNTRESET',
    0xca: 'JMP', 0xcb: 'JSR', 0xcf: 'END', 0xd0: 'RTS', 0xd4: 'MSG', 0xd5: 'LAB',
    0xd7: 'ExtFunc', 0xd8: 'RS232', 0xd9: 'ASCToBIN', 0xda: 'BINToASC',
    0xdb: 'PutChar', 0xdc: 'GetChar', 0xdd: 'HexToDec', 0xde: 'MODR',
    0xdf: 'MODW',
    0xe0: 'CNTRINGUP_Constant', 0xe1: 'CNTRINGDOWN_Constant',
    0xe2: 'TIM_10ms_R', 0xe3: 'TIM_100ms_R', 0xe4: 'TIM_1000ms_R',
    0xe5: 'CNTUP_R', 0xe6: 'CNTDOWN_R', 0xe7: 'TIM_1ms_R',
    0xe9: 'CNTRINGUP_R', 0xea: 'CNTRINGDOWN_R',
    0xeb: 'MODRS', 0xec: 'SRI', 0xf0: 'BGNDRun', 0xf1: 'BGNDStop', 0xfd: 'FEND',
}

# 真机上 RTS 只占 1 格（第 2 格是横线 0x0d），其余 bi 码占 2 格
WIDTH_EXCEPTION = {0xd0}


def cell_bytes(op, wide):
    """造一个该操作码的 8/4 字节单元"""
    if wide:
        return bytes([0, op, 1, 0, 2, 0, 0, 0x80])
    return bytes([0, op, 1, 0])


def one_row(cell, wide):
    """把单元放到 10 格的一行里, 其余填横线, 正好 40 字节"""
    tail = bytes([0, 0x0d, 0, 0]) * 9
    return (cell + tail)[:40]


def check_snapshot():
    print("\n1. 操作码快照 vs EOpcode_V1.cs")
    chk("官方码共 80 个", len(OFFICIAL) == 80, len(OFFICIAL))
    # syntec_re.EOF_NAME 是我们抄的一份, 必须与官方逐条相同
    bad = [(op, OFFICIAL[op], R.EOF_NAME.get(op)) for op in OFFICIAL
           if R.EOF_NAME.get(op) != OFFICIAL[op]]
    chk("syntec_re.EOF_NAME 与官方逐条一致", not bad, bad[:6])
    # Type4/Type8 不能出现官方没有的码
    extra8 = [hex(x) for x in L.TYPE8 if x not in OFFICIAL]
    extra4 = [hex(x) for x in L.TYPE4 if x not in OFFICIAL and x != 0xcf]
    chk("TYPE8 没有自造码", not extra8, extra8)
    chk("TYPE4 没有自造码", not extra4, extra4)


def check_coverage():
    print("\n2. 覆盖：每个官方码都要能解码（含官方标 none 的遗留码）")
    crash = []
    for op in sorted(OFFICIAL):
        wide = bool(R.PLCOP_RAW[op] & 0x200) and op not in WIDTH_EXCEPTION
        try:
            row = P.decode_row(one_row(cell_bytes(op, wide), wide))
            el = row[0][1]
            L.enc_el(el)
        except Exception as e:
            crash.append((hex(op), OFFICIAL[op], type(e).__name__, str(e)[:40]))
    chk("80 个码全部可解码/可编码", not crash, crash[:6])
    # 遗留的 Function fn11~fn15 (0xa0~0xa4) 官方标题是 "none", 必须当 RAW 而不是崩
    legacy = [op for op in (0xa0, 0xa1, 0xa2, 0xa3, 0xa4)]
    got = []
    for op in legacy:
        row = P.decode_row(one_row(cell_bytes(op, True), True))
        got.append(row[0][1][0])
    chk("0xa0~0xa4 走 RAW 分支（官方无标题）", all(g == 'RAW' for g in got), got)


def check_width():
    print("\n3. 宽度：编码字节数 = 官方 isBiCell")
    bad = []
    for op in sorted(OFFICIAL):
        bi = bool(R.PLCOP_RAW[op] & 0x200)
        want = 4 if op in WIDTH_EXCEPTION else (8 if bi else 4)
        wide = want == 8
        el = P.decode_row(one_row(cell_bytes(op, wide), wide))[0][1]
        n = len(L.enc_el(el))
        if n != want:
            bad.append((hex(op), OFFICIAL[op], "bi=%s" % bi, "期望%d 实得%d" % (want, n)))
    chk("全部宽度对齐", not bad, bad[:6])
    chk("FEND 是双格（真机第 2 格是保留区）",
        len(L.enc_el(P.decode_row(one_row(bytes([0, 0xfd, 0, 0, 0, 0, 0, 0]), True))[0][1])) == 8)
    chk("RTS 是单格（真机第 2 格是横线 0x0d）",
        len(L.enc_el(P.decode_row(one_row(bytes([0, 0xd0, 0, 0]), False))[0][1])) == 4)


def check_mnemonics():
    print("\n4. 助记符 / 精度 / 方向 与官方枚举名对应")
    rev = {v: k for k, v in OFFICIAL.items()}

    def one(table, expect):
        bad = []
        for key, op in table.items():
            want = rev.get(expect.get(key)) if expect.get(key) else None
            if want != op:
                bad.append((key, hex(op), expect.get(key), hex(want) if want else None))
        return bad

    T = L.TIMER_TYPE
    chk("定时器 8 种变体", not one(T, {
        ('1s', 'K'): 'TIM_1000ms_Constant', ('0.1s', 'K'): 'TIM_100ms_Constant',
        ('0.01s', 'K'): 'TIM_10ms_Constant', ('0.001s', 'K'): 'TIM_1ms_Constant',
        ('1s', 'R'): 'TIM_1000ms_R', ('0.1s', 'R'): 'TIM_100ms_R',
        ('0.01s', 'R'): 'TIM_10ms_R', ('0.001s', 'R'): 'TIM_1ms_R'}))
    chk("计数器 9 种变体", not one(L.CNTR_TYPE, {
        ('UP', 'K'): 'CNTUP_Constant', ('UP', 'R'): 'CNTUP_R',
        ('DOWN', 'K'): 'CNTDOWN_Constant', ('DOWN', 'R'): 'CNTDOWN_R',
        ('RESET', 'K'): 'CNTRESET',
        ('RING_UP', 'K'): 'CNTRINGUP_Constant', ('RING_UP', 'R'): 'CNTRINGUP_R',
        ('RING_DOWN', 'K'): 'CNTRINGDOWN_Constant', ('RING_DOWN', 'R'): 'CNTRINGDOWN_R'}))
    chk("数学 8 种变体", not one(L.MATH_TYPE, {
        'ADD': 'ADD_RtoR', 'ADD_IMM': 'ADD_ConstantToR',
        'SUB': 'SUB_RtoR', 'SUB_IMM': 'SUB_ConstantToR',
        'MUL': 'MUL_RtoR', 'MUL_IMM': 'MUL_ConstantToR',
        'DIV': 'DIV_RtoR', 'DIV_IMM': 'DIV_ConstantToR'}))
    chk("比较 6 种变体", not one(L.CMP_TYPE, {
        'GT': 'CMPG_RtoR', 'LT': 'CMPL_RtoR', 'EQ': 'CMPE_RtoR',
        'GTK': 'CMPG_ConstantToR', 'LTK': 'CMPL_ConstantToR', 'EQK': 'CMPE_ConstantToR'}))
    chk("逻辑 6 种变体", not one(L.LOGIC_TYPE, {
        'AND': 'AND_RtoR', 'AND_IMM': 'AND_ConstantToR',
        'OR': 'OR_RtoR', 'OR_IMM': 'OR_ConstantToR',
        'XOR': 'XOR_RtoR', 'XOR_IMM': 'XOR_ConstantToR'}))
    chk("搬移 2 种变体", not one(L.MOVE_TYPE,
                                 {'MOV': 'Move_RtoR', 'MOV_IMM': 'Move_ConstantToR'}))
    chk("旋转 ROT", L.TOOL_TYPE.get('ROT') == 0xb0)


def check_end_tail():
    print("\n5. END 保留区原样保留")
    for tail, name in ((b'\x00\x00\x00\x00', '全 0 (cnc.lad)'),
                       (b'\x00\x00\x00\x80', '末字节 0x80 (M2I1653)')):
        raw = bytes([0, 0xcf, 0, 0]) + tail
        el = P.decode_row(one_row(raw, True))[0][1]
        chk("END %s 不被清零" % name, L.enc_el(el)[4:8] == tail, L.enc_el(el).hex(' '))


def check_counter_preset():
    print("\n6. 计数器预设是 16 位")
    for preset in (50, 300, 65535):
        raw = L.enc_counter('UP', 'K', 3, preset)
        el = P.decode_row(one_row(raw, True))[0][1]
        back = el[5][0] | (el[5][1] << 8)
        chk("预设 %d 往返不丢" % preset, back == preset, "%s -> %d" % (raw.hex(' '), back))
    # 寄存器源也一样 (R400 = 400)
    raw = L.enc_counter('UP', 'R', 3, 400)
    el = P.decode_row(one_row(raw, True))[0][1]
    chk("寄存器预设 R400 不截断", (el[5][0] | (el[5][1] << 8)) == 400, raw.hex(' '))


def check_cmp_operand():
    print("\n7. 比较块 op1 类型随 opcode")
    cases = [
        (0x5e, 961, 2011, 'R961>R2011'),      # CMPG_RtoR  -> op1 是寄存器
        (0x62, 36, 52, 'R36<R52'),            # CMPL_RtoR
        (0x66, 50, 51, 'R50==R51'),           # CMPE_RtoR
        (0x6a, 0, 701, '#0>R701'),            # CMPG_ConstantToR -> op1 是常数
        (0x6c, 1, 702, '#1<R702'),
        (0x6e, 0, 801, '#0==R801'),
    ]
    for op, a, b, want in cases:
        raw = (bytes([0, op]) + bytes([a & 0xff, a >> 8])
               + bytes([b & 0xff, b >> 8]) + b'\x00\x80')
        el = P.decode_row(one_row(raw, True))[0][1]
        got = Y.el_label(el).replace(' ', '')
        chk("0x%02x -> %s" % (op, want), got == want, got)
    # MCP 的结构化输出也要一致
    raw = bytes([0, 0x5e]) + bytes([961 & 0xff, 961 >> 8]) + b'\x02\x00\x00\x80'
    d = RD.el_to_dict(P.decode_row(one_row(raw, True))[0][1])
    chk("el_to_dict 的 A 侧是寄存器", d['A'].startswith('R'), d)


def check_flow_render():
    print("\n8. 流程块渲染出名字，不是 FLOW4/FLOW8")
    cases = [
        (('FLOW8', 0xcb, b'1\x00\x00\x00\x00\x00'), 'JSR 1'),
        (('FLOW8', 0xd5, b'001\x00\x00\x00'), 'LAB 001'),
        (('FLOW4', 0xd0), 'RTS'),
        (('FLOW8', 0xfd, b'\x00' * 6), 'FEND'),
        (('END', b'\x00\x00\x00\x00'), 'END'),
        (('FLOW8', 0xca, b'L9\x00\x00\x00\x00'), 'JMP L9'),
    ]
    for el, want in cases:
        got = Y.el_label(el)
        chk("%s" % want, got == want, got)
    chk("不再出现 FLOW4/FLOW8 字样",
        not any('FLOW' in Y.el_label(el) for el, _w in cases))


CORPUS = [
    r'C:/Users/panming/Documents/xwechat_files/wxid_acyj809yx1d521_fc20/msg/file/2026-11/M4R24179_20260715_MBL_05EA6BEF/Ladder/cnc.lad',
    r'C:/Users/panming/Desktop/M2I1653_20261104_MB_E3F2D114/Ladder/cnc.lad',
    r'C:/Users/panming/Downloads/cnc_2.lad',
]


def check_corpus(extra):
    print("\n9. 真机语料全覆盖（不许出现未知操作码）")
    files = [p for p in (CORPUS + list(extra)) if os.path.isfile(p)]
    for p in sorted(os.path.join(_HERE, '..', 'samples', x) for x in ()):
        pass
    for d in (os.path.join(os.path.dirname(_HERE), 'samples'),):
        if os.path.isdir(d):
            files += [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith('.lad')]
    if not files:
        print("  (没有可用语料, 跳过)")
        return
    for p in files:
        logic, _o, _t = RD.split_records(open(p, 'rb').read())
        unknown, cells = [], 0
        for rec in logic:
            for c in P.decode_row(rec):
                if c is None:
                    continue
                cells += 1
                if c[1][0] == 'RAW':
                    unknown.append(c[1][1].hex(' ')[:23])
        chk("%s  %d 个单元" % (os.path.basename(p), cells), not unknown,
            "未知: " + ", ".join(unknown[:5]))


def main():
    print("=" * 70)
    print("与官方编辑器一致性回归 (基准: 反编译 MLCEdit.exe)")
    print("=" * 70)
    check_snapshot()
    check_coverage()
    check_width()
    check_mnemonics()
    check_end_tail()
    check_counter_preset()
    check_cmp_operand()
    check_flow_render()
    check_corpus(sys.argv[1:])
    bad = [c for c in CHECKS if not c[1]]
    print("\n" + "=" * 70)
    print("%d 项检查, %d 项通过, %d 项失败" % (len(CHECKS), len(CHECKS) - len(bad), len(bad)))
    if bad:
        print("失败项:")
        for m, _ok, d in bad:
            print("  - %s  %s" % (m, str(d)[:120]))
        return 1
    print("全部通过   [PASS]")
    return 0


if __name__ == '__main__':
    sys.exit(main())
