# -*- coding: utf-8 -*-
"""
新代(SYNTEC) 梯形图高层模型 —— 在 syntec_lad.py(二进制编解码) 之上。

为 MCP 提供「梯形图语义」层: AI 不用关心列布局/字节, 只描述
  condition (串联条件, 触点和比较块)  +  action (结果, 线圈/定时器/运算块)
或一份从左到右的 elements 列表, 本模块负责转成 syntec_lad 的 enc 元组并序列化。

注意: 仅依赖本项目已逆向验证的部分。未验证功能块(CNC/RS232/计数器/流程/背景运算/
复杂竖线分支) 暂不支持, 调用时抛清晰错误。
"""
import os
import re
import syntec_lad as L
import syntec_layout as Y
import syntec_parse as P
import syntec_address_db as ADB


def default_save_path():
    """跨平台默认保存路径: 有桌面就存桌面, 否则存用户主目录。"""
    home = os.path.expanduser("~")
    desk = os.path.join(home, "Desktop")
    base = desk if os.path.isdir(desk) else home
    return os.path.join(base, "cnc_generated.lad")

# ----------------------------------------------------------------------------
# 地址解析
# ----------------------------------------------------------------------------
def parse_addr(s):
    """返回 (kind, value)。
       kind: 'IMM'(立即数 #N) | 'NUM'(纯数字) | 字母(I/O/C/S/A/R/TM/CT...)
       value: 数字或字符串(字母+数字, 如 'I132' / 'C36' / 'R600.1')
    """
    s = str(s).strip()
    if s.startswith('#'):
        return ('IMM', int(s[1:]))
    m = re.match(r'^([A-Za-z]+)\s*(\d+(?:\.\d+)?)$', s)
    if m:
        letter = m.group(1).upper()
        num = m.group(2)
        val = float(num) if '.' in num else int(num)
        return (letter, val)
    try:
        return ('NUM', int(s))
    except ValueError:
        raise ValueError(f"无法解析地址: {s!r}")


DEV_INDEX = {"I": 0, "O": 1, "C": 2, "S": 3, "A": 4}


def addr_number(s):
    """取出编码用的整数地址号。
       位设备(I/O/C/S/A)编码为 16 位 n = (设备索引<<9) | 编号, 与 PLC 内部 PLCBits 一致;
       寄存器(R)与立即数保持数值本身, 由各自的操作数类型决定写法。"""
    kind, val = parse_addr(s)
    if kind in ('IMM', 'NUM'):
        return val
    v = int(val)
    if kind in DEV_INDEX:
        return (DEV_INDEX[kind] << 9) | (v & 0x1FF)
    return v


def addr_bits(s):
    """位元件地址 -> 16 位 PLCBits 编码 (触点/线圈用)
       实测: I100=0x0064  O200=0x02C8  C36=0x0424  A302=0x092E  R44.5=0x1585
       R 寄存器位为 n4<<12 | ((号-(n4-1)*128)<<5 | 位), n4 = 号//128+1"""
    kind, val = parse_addr(s)
    if kind in ('IMM', 'NUM'):
        return val
    if isinstance(val, float):
        base = int(val)
        bit = int(round((val - base) * 10))
    else:
        base, bit = int(val), 0
    if kind in DEV_INDEX:
        # 编号只有 9 位, 超出会被 & 0x1FF 静默截断 (I600 -> I88)。宁可报错。
        if not 0 <= base <= 511:
            raise ValueError(
                f"地址 {s} 越界: {kind} 段编号只编 9 位, 有效范围 0..511, "
                f"写 {base} 会被截断成 {kind}{base & 0x1FF}")
        return (DEV_INDEX[kind] << 9) | (base & 0x1FF)
    if kind == 'R':
        n4 = base // 128 + 1
        n3 = ((base - (n4 - 1) * 128) << 5) | (bit & 0x1F)
        return (n4 << 12) | n3
    return base


# ----------------------------------------------------------------------------
# 元件 dict -> syntec_lad 的 enc 元组
# ----------------------------------------------------------------------------
def _rng(what, v, hi, lo=0):
    """编码前的范围检查。越界一律报错 —— 这些字段都是按位截断写入的,
       截断后文件仍然"合法", 编辑器也能打开, 只是编号悄悄变了另一台设备。
       这种错只能靠现场调试发现, 所以宁可在生成阶段直接拒绝。"""
    v = int(v)
    if not lo <= v <= hi:
        raise ValueError(f"{what} = {v} 超出有效范围 {lo}..{hi}")
    return v


def preset_no(v):
    """定时器/计数器预设值的写法归一: 既接受常数 300, 也接受 'R81' / 'r81'。
       source='R' 时写 'R81' 比写 81 好读, 但底层存的是寄存器号 81。"""
    if isinstance(v, str):
        s = v.strip().upper()
        if s.startswith("R"):
            s = s[1:]
        if not s.isdigit():
            raise ValueError(f"预设值 {v!r} 既不是常数也不是 R 寄存器号")
        return int(s)
    return int(v)


def to_enc(el):
    k = el.get("kind")
    if k == "raw":
        # 读入时无法用语义表达的单元: 原样字节 (保证"读->改->存"不动其它行)
        return ('RAW', bytes.fromhex(str(el["hex"]).replace(" ", "")))
    if k == "contact":
        norm = el.get("norm", "NO")
        return ('CONTACT', norm, addr_bits(el["addr"]))
    if k == "contact_t":
        return ('CONTACT_T', el.get("norm", "NO"),
                _rng("定时器触点编号 TM", el.get("index", 0), 255))
    if k == "contact_c":
        return ('CONTACT_C', el.get("norm", "NO"),
                _rng("计数器触点编号 CT", el.get("index", 0), 255))
    if k == "coil":
        norm = el.get("norm", "NO")
        return ('COIL', norm, addr_bits(el["addr"]))
    if k == "end":
        return ('END',)
    if k == "timer":
        m = re.search(r'\d+', str(el.get("name", el.get("addr", "TM0"))))
        idx = _rng("定时器编号 TM", int(m.group()) if m else 0, 255)
        precision = el.get("precision", "1s")          # '1s'/'0.1s'/'0.01s'/'0.001s'
        source = el.get("source", "K")                 # 'K'=常数  'R'=寄存器
        value = preset_no(el.get("preset", 0))         # 常数预设值 或 寄存器号(R, 显示值即寄存器号)
        typ = L.TIMER_TYPE[(precision, source)]
        # 参数为 16 位小端整数: [值低字节, 值高字节, 值低字节, 0x80]
        v = _rng("定时器预设值", value, 65535)
        param = bytes([v & 0xff, (v >> 8) & 0xff, v & 0xff, 0x80])
        return ('FB', 'TIMER', typ, idx, 0, param)
    if k == "counter":
        m = re.search(r'\d+', str(el.get("name", el.get("addr", "CT0"))))
        idx = _rng("计数器编号 CT", int(m.group()) if m else 0, 255)
        direction = el.get("direction", "UP")          # UP/DOWN/RESET/RING_UP/RING_DOWN
        source = el.get("source", "K")                 # 'K'=预设值#N  'R'=寄存器R
        # 预设值(#N) 或 寄存器号(R)。实测样本的预设值只出现在 byte0
        # (B_counter: CT1 preset 50 -> "32 00 00 80"; cnc.lad: CT1 -> "53 00 00 80"),
        # byte1..2 恒为 0, 与定时器的 16 位写法不同。因此 > 255 的计数预设值
        # 写法尚未验证, 超过就报错而不是猜一个放进去。
        X = _rng("计数器预设值/寄存器号", el.get("preset", 0), 255)
        typ = L.CNTR_TYPE[(direction, source)]
        param = bytes([X & 0xff, 0, 0, 0x80])
        return ('FB', 'CNTR', typ, idx, 0, param)
    if k in ("jsr", "lab", "rts", "fend", "jmp", "msg"):
        # 流程控制块: JSR/LAB/JMP/MSG 带标签(≤6 字节 ASCII, 如 "001"), RTS/FEND 无标签
        return ('FB', 'FLOW', k.upper(), str(el.get("label", "")))
    if k == "math":
        return ('FB', 'MATH', el["op"], addr_number(el["A"]), addr_number(el["B"]))
    if k == "move":
        return ('FB', 'MOVE', el["op"], addr_number(el["A"]), addr_number(el["B"]))
    if k == "logic":
        return ('FB', 'LOGIC', el["op"], addr_number(el["A"]), addr_number(el["B"]))
    if k == "compare":
        return ('FB', 'CMP', el["op"], addr_number(el["A"]), addr_number(el["B"]))
    raise ValueError(f"未知元件 kind={k!r}")


# 已验证支持的功能块 op
SUPPORTED_OPS = {
    "math": set(L.MATH_TYPE.keys()),
    "move": set(L.MOVE_TYPE.keys()),
    "logic": set(L.LOGIC_TYPE.keys()),
    "compare": set(L.CMP_TYPE.keys()),
}


def check_supported(el):
    k = el.get("kind")
    if k == "parallel":
        br = el.get("branches") or []
        if len(br) < 2:
            raise ValueError("parallel 至少需要 2 个分支 (branches)")
        for b in br:
            if not isinstance(b, list) or not b:
                raise ValueError("parallel 的每个分支必须是非空元件列表")
            for e in b:
                check_supported(e)
        return
    if k in SUPPORTED_OPS:
        op = el.get("op")
        if op not in SUPPORTED_OPS[k]:
            raise ValueError(f"{k} 暂不支持 op={op!r}; 可选: {sorted(SUPPORTED_OPS[k])}")


# ----------------------------------------------------------------------------
# 元件 dict -> 布局网络节点 (支持并联)
# ----------------------------------------------------------------------------
def to_node(el):
    """把元件 dict 转成 syntec_layout 的网络节点"""
    if el.get("kind") == "parallel":
        return Y.parallel(*[Y.series(*[to_node(e) for e in br])
                            for br in el["branches"]])
    return Y.leaf(to_enc(el))


def rung_to_node(els):    return Y.series(*[to_node(e) for e in els])


def rung_has_parallel(els):
    for e in els:
        if e.get("kind") == "parallel":
            return True
    return False


def rung_left_anchor(els):
    """单元素行里 END/LAB/RTS/FEND 固定在 col0"""
    if len(els) == 1 and els[0].get("kind") != "parallel":
        return L.is_left_anchored(to_enc(els[0]))
    return False


def _chunks(buf, n):
    return [buf[i:i + n] for i in range(0, len(buf), n) if len(buf[i:i + n]) == n]


def _decode_raw_row(rec):
    """原始 40 字节行 -> render_grid 需要的 [(conn, 元件)] / None"""
    out = []
    for c in P.decode_row(rec):
        out.append(None if c is None else (c[0], c[1]))
    return out


def to_rung_bytes(els, left_anchor=None):
    """一条 rung -> 若干条 40 字节记录 (并联会展开成多行)
    left_anchor 为 None 时按元件自动判断; 读入已有文件时应传入原件的位置,
    否则"原件靠左 / 自动判断靠右"这种差异会让字节对不上。"""
    node = rung_to_node(els)
    la = rung_left_anchor(els) if left_anchor is None else bool(left_anchor)
    grid = Y.to_grid(node, left_anchor=la)
    bad = Y.check_grid(grid)
    if bad:
        raise ValueError("布局自检失败(接线位不闭合): " + "; ".join(bad[:3]))
    return b''.join(Y.emit_grid(g) for g in grid)


# ----------------------------------------------------------------------------
# LadderProject
# ----------------------------------------------------------------------------
def _check_bit_read(addr):
    """读触点时的地址检查。S/C 只读没问题, 但 R 的位不是每个区都能取。"""
    kind, val = parse_addr(addr)
    if kind != 'R':
        return (None, None)
    base = int(val)
    bit = 0 if isinstance(val, int) else int(round((val - base) * 10))
    if bit == 0 and isinstance(val, int):
        return (None, None)          # 整字访问, 不涉及位存取
    z = ADB.r_zone(base)
    if z is None:
        return ("warn", f"{addr}: R{base} 不在权限表里(保留区)，行为未定义")
    if not z["bit"]:
        return ("error", f"{addr}: R{base} 所在的「{z['note']}」不支持位存取，"
                         f"不能用 R{base}.{bit}")
    return (None, None)


class LadderProject:
    def __init__(self):
        self.reset()

    def reset(self, keep_path=False):
        self.rungs = []          # 每行 = 元件 dict 列表; None 表示"原样保留的原始行"
        self.comments = {}       # "C36" -> (short, long)
        # 读入已有文件时保留的非逻辑记录 (版本 / 注释行 / 变量注释)
        self.head_raw = b''      # 版本记录, 置文件最前
        self.tail_raw = b''      # 设备变量注释, 置文件最末
        self.prefix = {}         # rung 序号 -> 该 rung 之前的注释行原始字节
        self.raw_rungs = {}      # rung 序号 -> 原始 40 字节×N (模型表达不了时)
        self.left_anchor = {}    # rung 序号 -> 单元素行是否靠左 (从原件读入时保留)
        # 新建工程时要写出的注释 (读入的注释已经在 head_raw/tail_raw/prefix 里, 不填这两项)
        self.header_comments = []   # [(文本, CommentType)] 放在所有逻辑行之前
        self.varcmts = []           # [(地址, 短注释, 长注释)] 放在文件最末
        if not (keep_path and getattr(self, "path", None)):
            self.path = default_save_path()

    def set_path(self, path):
        # 统一规范化: 用户/AI 常把正反斜杠混着传, 回显时很难看, 也不好复制
        self.path = os.path.normpath(os.path.expanduser(path)) if path else path

    def _la(self, i):
        """第 i 条 rung 是否靠左: 读入时以原件为准, 新建时按元件判断"""
        la = getattr(self, 'left_anchor', {}).get(i)
        if la is not None:
            return la
        els = self.rungs[i]
        return False if not els else rung_left_anchor(els)

    def _build_elements(self, condition, action, elements):
        if elements is not None:
            return list(elements)
        els = []
        if condition:
            els.extend(condition)
        if action:
            els.extend(action)
        if not els:
            raise ValueError("add_rung 需要 condition+action 或 elements 至少其一")
        return els

    def add_rung(self, condition=None, action=None, elements=None, comment=None):
        els = self._build_elements(condition, action, elements)
        for el in els:
            check_supported(el)
        self.rungs.append(els)
        idx = len(self.rungs)
        if comment and els:
            # 取行内第一个带地址的元件作为批注锚点(便于编辑器定位)
            for el in els:
                if el.get("addr"):
                    a = str(el["addr"]).upper()
                    self.comments.setdefault(a, (comment, comment))
                    break
        return idx

    def set_comment(self, addr, short=None, long=None):
        """设置某地址的批注, 并**保证它会写进文件**。

        注意两者的分工: self.comments 是查询用的内存字典(读入时由解析器填充),
        self.varcmts 才是 to_lad_bytes 真正序列化的队列。早期只改 comments 不碰
        varcmts, 结果 set_comment 之后存出来的文件一条注释都没有 —— 调用方完全
        看不出来(set_comment 正常返回, validate 也不报)。

        这里按"是否新地址"决定要不要入队:
          - 读入已有工程时, 老批注由 head_raw/tail_raw 原样带回, 再入队就会重复;
          - 新地址才需要新写一条 ct=4。
        """
        addr = str(addr).upper()
        old_s, old_l = self.comments.get(addr, ("", ""))
        is_new = addr not in self.comments
        new = (short if short is not None else old_s,
               long if long is not None else old_l)
        self.comments[addr] = new

        varcmts = getattr(self, "varcmts", None)
        if varcmts is None:
            return
        for k, (a, _s, _l) in enumerate(varcmts):
            if a == addr:                      # 本工程内第二次设置: 原地更新
                varcmts[k] = (addr, new[0], new[1])
                return
        if is_new:                             # 全新地址: 入队待写
            varcmts.append((addr, new[0], new[1]))

    def add_header_comment(self, text, ct=1):
        """在逻辑行之前加一条注释 (ct=1 占一行显示; ct=2 版本记录; ct=3 同类)。"""
        self.header_comments.append((text, ct))

    def add_varcmt(self, addr, short="", long=""):
        """加一条设备变量注释 (ct=4), 编辑器里挂在地址上, 不占行、不影响梯形图布局。"""
        self.varcmts.append((str(addr).upper(), short, long))

    # ---- 校验 ----
    def validate(self):
        warns = []
        if not self.rungs:
            warns.append("工程为空, 没有任何行。")
            return warns
        # 末尾应为 END (末行若是原样保留的原始行, 内容未知, 不做武断告警)
        last = self.rungs[-1]
        if last is not None:
            has_end = any(e.get("kind") in ("end", "fend", "rts") for e in last)
            if not has_end:
                warns.append("最后一行不是 END/FEND/RTS, 控制器可能无法正常识别"
                             "程序结束。建议追加 end 行。")

        def leaves(els):
            """展开所有元件(含多层嵌套并联)"""
            for e in els:
                if e.get("kind") == "parallel":
                    for br in e.get("branches") or []:
                        for x in leaves(br):
                            yield x
                else:
                    yield e

        # 地址范围
        for ri, els in enumerate(self.rungs, 1):
            if els is None:            # 原样保留的行(空白/桥式)不参与检查
                continue
            for el in leaves(els):
                if el.get("kind") in ("contact", "coil"):
                    a = el.get("addr")
                    if a is None:
                        continue
                    kind, val = parse_addr(a)
                    if kind in ('I', 'O', 'C', 'S', 'A'):
                        if isinstance(val, int) and not (0 <= val <= 511):
                            warns.append(f"R{ri}: 地址 {a} 超出 0~511 范围。")
                    elif kind == 'R':
                        if isinstance(val, int) and not (0 <= val <= 65535):
                            warns.append(f"R{ri}: 寄存器 {a} 超出 0~65535 范围。")
                    elif kind in ('TM', 'CT'):
                        if isinstance(val, int) and not (0 <= val <= 255):
                            warns.append(f"R{ri}: {a} 超出 0~255 范围。")
                    # 地址权限: 写 S 段 / 写只读 R 区 / 位存取非法
                    if el.get("kind") == "coil":
                        lvl, msg = ADB.check_write(a)
                    else:
                        lvl, msg = _check_bit_read(a)
                    if lvl and msg:
                        warns.append(f"R{ri}: {msg}")
                if el.get("kind") in ("timer", "counter"):
                    src = el.get("source", "K")
                    try:
                        p = preset_no(el.get("preset", 0))
                    except ValueError as e:
                        warns.append(f"R{ri}: {e}")
                        p = None
                    if p is not None and src == "R":
                        z = ADB.r_zone(p)
                        if z is None:
                            warns.append(f"R{ri}: 预设值引用 R{p}，该编号不在 R 分配表里。")
                        elif not z["read"]:
                            warns.append(f"R{ri}: 预设值引用 R{p}，但「{z['note']}」阶梯只读，读不到。")
                    elif p is not None and not (0 <= p <= 65535):
                        warns.append(f"R{ri}: 定时器预设 {p} 可能超出范围。")
        # 每行至少含一个输出元件(线圈/运算块/定时器) 或 END
        for ri, els in enumerate(self.rungs, 1):
            if els is None:
                continue
            kinds = [e.get("kind") for e in leaves(els)]
            if "end" in kinds:
                continue
            has_out = any(k in ("coil", "timer", "counter", "math", "move", "logic",
                                "jsr", "lab", "rts", "fend", "jmp", "msg",
                                "raw") for k in kinds)
            if not has_out:
                warns.append(f"R{ri}: 该行只有条件元件(触点/比较), 没有输出(线圈/运算块), 逻辑上不会驱动任何动作(编辑器会报'不合理输出')。")

        # 双线圈 / 定时器 / 计数器 重号 (编辑器打开时也会报, 这里提前查出)
        def _key(s):
            try:
                k, v = parse_addr(s)
                return f"{k}{v}"
            except Exception:
                return str(s).strip().upper()

        driven = {}          # (种类, 规范化地址) -> ([rung 号], 显示用原文)
        def _hit(what, name, ri):
            d = driven.setdefault((what, _key(name)), ([], name))
            d[0].append(ri)

        for ri, els in enumerate(self.rungs, 1):
            if els is None:            # 原样保留的行(空白/桥式)不参与检查
                continue
            for el in leaves(els):
                k = el.get("kind")
                if k == "coil" and el.get("addr"):
                    norm = el.get("norm", "NO")
                    # SET/RESET 是"写指令", 同一地址配一对(一置一复)是标准用法 ——
                    # 锁存报警、多处停车就靠它避开双线圈。但**超过一对**编辑器会报
                    # 「重复元件」: 两个 ⊖A1 或两个 ⊕A1 就是重复, 实测真会弹。
                    if norm in ("NO", "NC", "RP", "FP"):
                        _hit("线圈", el["addr"], ri)
                    elif norm in ("LATCH", "UNLATCH"):
                        _hit("置位" if norm == "LATCH" else "复位", el["addr"], ri)
                elif k == "timer" and el.get("name"):
                    _hit("定时器", el["name"], ri)
                elif k == "counter" and el.get("name"):
                    _hit("计数器", el["name"], ri)
        for (what, _k), (rs, disp) in driven.items():
            if len(rs) > 1:
                where = "+".join(f"R{r}" for r in rs)
                if what in ("置位", "复位"):
                    warns.append(
                        f"{what} {disp} 出现 {len(rs)} 次 ({where}) —— 重复元件, "
                        f"编辑器会报警。同一地址只留一处{what}, "
                        f"多个{what}条件先并联再驱动它。")
                else:
                    warns.append(
                        f"{what} {disp} 被 {len(rs)} 处驱动 ({where}) —— 双{what}, "
                        f"编辑器会报警且实际只有一处生效, 请改用不同地址或合并到一处。")

        # 同一地址既用普通线圈又用 SET/RESET: 每扫描刷新的线圈会盖掉锁存值。
        per_addr = {}
        for ri, els in enumerate(self.rungs, 1):
            if els is None:
                continue
            for el in leaves(els):
                if el.get("kind") == "coil" and el.get("addr"):
                    norm = el.get("norm", "NO")
                    kind = "置位/复位" if norm in ("LATCH", "UNLATCH") else "输出线圈"
                    per_addr.setdefault(_key(el["addr"]), [el["addr"], {}])[1].setdefault(kind, []).append(ri)
        for _k, (disp, kinds) in per_addr.items():
            if len(kinds) > 1:
                detail = "、".join(f"{k} R{v[0]}" for k, v in kinds.items())
                warns.append(
                    f"线圈 {disp} 既当输出线圈又当置位/复位 ({detail}) —— "
                    f"输出线圈每个扫描都重写, 会把锁存值冲掉, 只能选一种。")
        return warns

    # ---- 序列化 ----
    def to_lad_bytes(self):
        out = bytearray()
        out += getattr(self, 'head_raw', b'')
        # 新建工程写的注释: 开头几行说明 + 文件最末的设备变量注释。
        # 读入已有文件时这两项为空, 原注释由 head_raw/prefix/tail_raw 原样带回, 不会重复写。
        for text, ct in getattr(self, 'header_comments', []):
            out += L.enc_comment(text, ct)
        prefix = getattr(self, 'prefix', {})
        raw_rungs = getattr(self, 'raw_rungs', {})
        for i, els in enumerate(self.rungs):
            out += prefix.get(i, b'')
            if els is None:                      # 原样保留的行 (空白/桥式)
                out += raw_rungs.get(i, b'')
            else:
                out += to_rung_bytes(els, getattr(self, 'left_anchor', {}).get(i))
        out += prefix.get(len(self.rungs), b'')  # 文件末尾的注释行
        for addr, short, long_ in getattr(self, 'varcmts', []):
            out += L.enc_varcmt(addr, short, long_)
        out += getattr(self, 'tail_raw', b'')
        out += b'\x00\xfe'
        return bytes(out)

    def rung_row_count(self):
        """每条 rung 实际占用的编辑器行数 (并联会展开多行)"""
        raw = getattr(self, 'raw_rungs', {})
        counts = []
        for i, els in enumerate(self.rungs):
            if els is None:
                counts.append(max(1, len(raw.get(i, b'')) // 40))
            elif rung_has_parallel(els):
                counts.append(len(Y.to_grid(rung_to_node(els),
                                            left_anchor=self._la(i))))
            else:
                counts.append(1)
        return counts

    def save(self, path=None):
        if path:
            # 规范化: 调用方常把 / 和 \ 混着传 (如 C://Users//x/Desktop/...),
            # 直接回显会很别扭, 也不便于用户复制到资源管理器。
            self.path = os.path.normpath(os.path.expanduser(path))
        data = self.to_lad_bytes()
        with open(self.path, 'wb') as f:
            f.write(data)
        return self.path, len(data)

    # ---- 预览(带竖线的梯形图) ----
    def preview(self):
        return self.preview_range()

    def preview_range(self, start=1, end=None, limit=None):
        """渲染指定范围的 rung (1 基, 含端点)"""
        out = []
        row = 1
        raw = getattr(self, 'raw_rungs', {})
        shown = 0
        for i, els in enumerate(self.rungs):
            nrow = self.rung_row_count()[i]
            if i + 1 < start or (end and i + 1 > end):
                row += nrow
                continue
            if limit and shown >= limit:
                out.append(f"... (还有 {len(self.rungs) - i} 条 rung 未显示)")
                break
            shown += 1
            if els is None:
                grid = [list(_decode_raw_row(r)) for r in
                        _chunks(raw.get(i, b''), 40)]
            else:
                grid = Y.to_grid(rung_to_node(els), left_anchor=self._la(i))
            for g in grid:
                top, mid, bot = Y.render_grid(g)
                if top.strip():
                    out.append(f"R{row:<4} {top}")
                else:
                    out.append(f"R{row:<4}")
                out.append(f"      {mid}")
                if bot.strip():
                    out.append(f"      {bot}")
                row += 1
        return "\n".join(out)


# ----------------------------------------------------------------------------
# 便捷: 用标准地址名查询(供 MCP lookup_address 用)
# ----------------------------------------------------------------------------
def lookup_address(query):
    """返回 (results, panel) 二元组。
       results: [(地址, [含义, ...]), ...]  panel: [(功能名, 说明), ...]"""
    q = query.strip()
    # 只给一个字母/短代号: 回答「这类元件是干什么的、有多少点」。AI 常常先问这个。
    dt = ADB.device_type(q)
    if dt:
        name, spec, count = dt
        return [(q.upper(), [f"{name}；{spec}；{count}"])], []
    # 直接是地址
    direct = ADB.lookup(q.upper())
    if direct:
        return [(q.upper(), direct)], []
    # 关键词(中文或英文)模糊匹配: 扫描反向索引所有含义
    results = []
    seen = set()
    qu = q.upper()
    for addr, meanings in ADB.REVERSE_INDEX.items():
        for m in meanings:
            if q.lower() in m.lower() or qu in addr:
                key = (addr, tuple(m))
                if key not in seen:
                    seen.add(key)
                    results.append((addr, [m]))
                break
    # 也扫描 PANEL_FUNCTIONS
    panel = []
    for fn, desc in ADB.PANEL_FUNCTIONS.items():
        if q in fn or q in desc:
            panel.append((fn, desc))
    # 兜底: 查的是「某段的一个具体编号」, 但地址库里没这条标准含义
    m = re.match(r"^(A|I|O|C|S)\s*(\d+)$", q.upper())
    if m and not results:
        letter, num = m.group(1), int(m.group(2))
        name, spec, count = ADB.device_type(letter)
        if letter in ("A", "I", "O"):
            note = f"{name}；{count}；这一号手册没有固定含义，用户可以自由使用"
        else:
            note = f"{name}；{count}；这一号手册里未定义/保留，不要拿来当标志位"
        return [(f"{letter}{num}", [note])], []
    # R 的具体编号: 参数区要说清「谁设定、能不能写」, 其他区给权限摘要
    m = re.match(r"^R\s*(\d+)(?:\.\d+)?$", q.upper())
    if m and not results:
        num = int(m.group(1))
        if ADB.PARAM_LO <= num <= ADB.PARAM_HI:
            no = ADB.PARAM_BASE + num - ADB.PARAM_LO
            return [(f"R{num}",
                     [f"系统参数传入区：对应参数 No.{no}；操作员在参数画面设定；"
                      f"阶梯程序只读；掉电保持。程序里直接读它当预设值/判据，不要写"])], []
        z = ADB.r_zone(num)
        if z:
            hint = "要存开关量标志请用 A 段" if z["note"].startswith("使用者自订") else ""
            parts = [f"R 数据寄存器；{z['note']}；阶梯{'可写' if z['write'] else '只读'}；"
                     f"{'可' if z['bit'] else '不能'}位存取；"
                     f"{'掉电保持' if z['keep'] else '掉电不保持'}"]
            if hint:
                parts.append(hint)
            return [(f"R{num}", ["；".join(parts)])], []
    return results[:20], panel


if __name__ == "__main__":
    p = LadderProject()
    p.add_rung(condition=[{"kind": "contact", "norm": "NO", "addr": "I132"}],
               action=[{"kind": "coil", "norm": "NO", "addr": "O10"}])
    p.add_rung(condition=[{"kind": "contact", "norm": "NC", "addr": "C36"}],
               action=[{"kind": "coil", "norm": "LATCH", "addr": "A0"}])
    p.add_rung(condition=[{"kind": "contact", "norm": "NO", "addr": "I100"}],
               action=[{"kind": "timer", "name": "TM100", "preset": 60}])
    p.add_rung(elements=[{"kind": "end"}])
    print(p.preview())
    w, n = p.save()
    print("saved:", w, n)
