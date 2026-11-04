# -*- coding: utf-8 -*-
"""
静态体检一份现成的 .lad 程序。

不判断「工艺对不对」——那不看到机床判不了。这里只找**结构上一定有问题的**：
同一个输出被多处驱动、置位/复位不成对、写只读地址、用了不存在的地址、
定时器预设为 0、触点永远为真/为假这类。

用法：
    python tools/review_ladder.py cnc.lad
    python tools/review_ladder.py cnc.lad --json report.json
"""
import argparse
import collections
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

import syntec_address_db as DB      # noqa: E402
import syntec_read as R            # noqa: E402


# ---------------------------------------------------------------- 元件遍历

def walk(els, path=""):
    """产出 (element, 位置串)。并联块递归进去。"""
    for i, e in enumerate(els or []):
        here = f"{path}{i}"
        yield e, here
        if e.get("kind") == "parallel":
            for bi, br in enumerate(e.get("branches") or []):
                for x in walk(br, f"{here}.{bi}."):
                    yield x
        elif e.get("kind") in ("not", "invert"):
            for x in walk(e.get("inner") or [], f"{here}."):
                yield x


def norm_coil(e):
    """把各种写法归一成 'NO' / 'NC' / 'SET' / 'RST'。"""
    n = (e.get("norm") or "NO").upper()
    if n in ("SET", "LATCH", "+"):
        return "SET"
    if n in ("RST", "RESET", "UNLATCH", "-"):
        return "RST"
    if n in ("NC", "/"):
        return "NC"
    return "NO"


# ---------------------------------------------------------------- 检查项

def collect(d, rows):
    """按**字节行**收集线圈/触点，不依赖串并联树。

    桥式 rung 折不成树（elements=None），但线圈仍在行里；
    只走树会漏掉这些驱动，后面的“没人驱动”全是误报。
    """
    coils = collections.defaultdict(list)      # addr -> [(kind, rung)]
    contacts = collections.defaultdict(list)   # addr -> [(norm, rung)]
    cmps = []
    timers = []
    moves = collections.defaultdict(list)      # 寄存器 -> [(rung, 类别, 源)]

    # 行号 -> rung 号
    row2rung = {}
    for r in d["rungs"]:
        for i in range(r["row_start"], r["row_end"] + 1):
            row2rung[i] = r["index"]

    for lineno, cells in enumerate(rows, 1):
        ri = row2rung.get(lineno)
        if ri is None:
            continue
        for cell in cells:
            if not cell or cell[1] is None:
                continue
            el = cell[1]
            tag = el[0]
            if tag == "COIL":
                coils[R.bits_to_addr(el[2])].append((norm_from_bits(el), ri))
            elif tag == "CONTACT":
                contacts[R.bits_to_addr(el[2])].append(
                    ("NC" if el[1] in ("NC", 1, True) else "NO", ri))
            elif tag == "FB":
                cat, op, A, B = el[1], el[2], el[3], el[4]
                if cat == "CMP":
                    cmps.append((ri, op, A, B))
                elif cat in ("MOVE", "MATH"):
                    # MOVE K1→R15 / MATH +K1→R15：A=源、B=目标寄存器
                    moves.setdefault(R.num_to_operand(B, False), []).append((ri, cat, A))
            elif tag in ("TIMER", "CNT"):
                timers.append((ri, tag, el))
    return coils, contacts, cmps, timers, moves


def norm_from_bits(el):
    """COIL 元件的极性：字节层只有类别字段, 借用 model 的归一规则。"""
    v = el[1]
    if v in ("SET", "LATCH"):
        return "SET"
    if v in ("RST", "RESET", "UNLATCH"):
        return "RST"
    if v in ("NC", 1, True):
        return "NC"
    return "NO"


def check_coils(coils, rep):
    """同一个输出被多处驱动。"""
    bad = []
    for a, uses in sorted(coils.items()):
        no = [r for k, r in uses if k == "NO"]
        nc = [r for k, r in uses if k == "NC"]
        st = [r for k, r in uses if k == "SET"]
        rs = [r for k, r in uses if k == "RST"]

        if len(no) > 1:
            bad.append(f"`{a}` 用普通线圈驱动了 {len(no)} 次（{eds(no)}）"
                       f"—— 后一条会把前一条覆盖掉")
        if len(st) > 1:
            bad.append(f"`{a}` 置位 {len(st)} 次（{eds(st)}）—— 多余，只会增加读图难度")
        if len(rs) > 1:
            bad.append(f"`{a}` 复位 {len(rs)} 次（{eds(rs)}）")
        if st and no:
            rep.add("警告", f"`{a}` 同时用置位和普通线圈",
                    f"置位在 {eds(st)}，普通线圈在 {eds(no)}")
        if no and nc:
            bad.append(f"`{a}` 既有常开线圈（{eds(no)}）又有常闭线圈（{eds(nc)}）"
                       f"—— 典型是复制粘贴后忘了改地址")
    return bad


def fmt(rows):
    return "、".join(str(x) for x in rows)


# ---- rung 号 -> 编辑器行号 ----
# 报告是给人看的, 人只在编辑器里按行号找位置; "rung 137" 对现场没有意义。
# 所有对外输出统一走 ed()/eds(), 内部仍用 rung 索引做去重和排序。
EROW = {}


def ed(ri):
    """单个 rung -> '行 1097' / '行 1097-1122'"""
    r = EROW.get(ri)
    if not r:
        return f"R{ri}"
    a, b = r
    return f"行 {a}" if a == b else f"行 {a}-{b}"


def eds(ris):
    """一组 rung -> '行 1097、行 1102'"""
    return "、".join(ed(x) for x in sorted(set(ris)))


# check_write 的 warn 有好几种成因, 得分别给标题和建议, 不能一锅端。
WARN_TITLE = {
    "reserved": "手册标「保留」的地址",
    "relay":    "把 R 的位当内部中间继电器用",
    "unknown":  "地址库里没有这个编号",
    "input":    "写入物理输入点",
}
WARN_DETAIL = {
    "reserved": "只提示不阻断：保留区被厂商占用已有先例（R938~R940），"
                "若现场确认可用就照用。",
    "relay":    "手册这一段是「使用者自订、可位存取」，写进去是合法的。"
                "只是 R 是 32 位数据寄存器，逐位当辅助继电器用不好读；"
                "新写的代码建议改用 A 段，老程序照原样保留即可。",
    "unknown":  "这个编号地址库里查不到，先翻手册确认真是空位再用。",
    "input":    "I 是现场输入，写它不会改变实际信号。",
}


def warn_kind(msg):
    """把 check_write 的说明归到上面几类。"""
    if "保留" in msg or "行为未定义" in msg:
        return "reserved"
    if "内部中间继电器" in msg:
        return "relay"
    if "物理输入点" in msg:
        return "input"
    return "unknown"


def externally_driven(addr):
    """这个触点地址是不是「本来就不该由阶梯程序驱动」的？

    I/C/S 是外部给的。R 段里还有一批阶梯只读的地址：系统参数传入区
    (R81~R100 对应参数 3401~3420)、CNC 系统接口区、1-1.4.4 列明只读的
    寄存器。它们由核心或参数画面写入，全文没有线圈是正常的。
    典型误报：R100.2「寸动模式」被当成「没人驱动的悬空触点」。
    """
    a = str(addr).upper()
    if a[0] in ("I", "C", "S"):
        return True
    if a[0] != "R":
        return False
    res = DB.check_write(a)
    return bool(res and res[0] == "error" and "只读" in res[1])


def is_alarm_bit(addr):
    """R40~R49 是 PLC 警报/警告输出位 (手册 1-5.21 / 1-5.22)。

    R40~R43 = 系统内定警报(编号 1~64)，R44~R49 = 自订警报/警告。
    这些位按手册是「PLC 输出」，由阶梯程序线圈驱动后控制器才弹警报窗口。
    全文没有线圈可能只是该警报在这台机上未启用，不能和普通悬空触点
    一样当成「结构错误」—— 2026-11-02 现场确认 R43.0 / R44.5 属此情形。
    """
    m = re.match(r"^R(\d+)\.(\d+)$", str(addr).upper())
    return bool(m and 40 <= int(m.group(1)) <= 49)


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, title, detail=""):
        self.items.append((level, title, detail))

    def dump(self):
        order = {"错误": 0, "警告": 1, "提示": 2}
        self.items.sort(key=lambda x: order.get(x[0], 9))
        n = collections.Counter(l for l, _, _ in self.items)
        for level, title, detail in self.items:
            mark = {"错误": "[×]", "警告": "[!]", "提示": "[·]"}.get(level, "[?]")
            print(f"{mark} {title}")
            if detail:
                for line in detail.splitlines():
                    print(f"      {line}")
        print()
        print("合计：错误 %d、警告 %d、提示 %d"
              % (n["错误"], n["警告"], n["提示"]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("lad")
    ap.add_argument("--json")
    args = ap.parse_args()

    d = R.read_ladder(args.lad)
    rep = Report()
    EROW.clear()
    EROW.update({r["index"]: (r["editor_row_start"], r["editor_row_end"])
                 for r in d["rungs"]})

    # 行级数据：桥式 rung 也要采集线圈，否则会误报「没人驱动」
    import syntec_parse as PT
    _logic, _others, _tail = R.split_records(open(args.lad, "rb").read())
    rows = [PT.decode_row(r) for r in _logic]

    print("=" * 78)
    print(os.path.basename(args.lad))
    print("%d 段程序、%d 行逻辑、%d 个并联块（最大 %d 分支）"
          % (len(d["rungs"]), d["logic_rows"],
             d["stats"]["parallel_blocks"], d["stats"]["max_branch"]))
    print("=" * 78)
    print()

    coils, contacts, cmps, timers, moves = collect(d, rows)
    for reg, uses in sorted(moves.items()):
        if len(uses) > 1:
            rep.add("警告", f"`{reg}` 被 {len(uses)} 处数据写入驱动",
                    "、".join(dict.fromkeys(f"{ed(r)}({c})" for r, c, _ in uses))
                    + " —— 靠扫描顺序决定最终值，条件互斥才安全")

    # 1 解析失败的 rung
    bad_rungs = [r for r in d["rungs"] if not r["ok"]]
    if bad_rungs:
        multi = [r for r in bad_rungs if r.get("shape") == "multi"]
        rep.add("提示",
                f"{len(bad_rungs)} 段程序折不成串并联树"
                + (f"（{len(multi)} 条是多负载共用一段条件）" if multi else ""),
                "已用路径枚举读出每个负载的条件，不再是盲区；"
                "保存时这几条原样保留字节，不会被重排\n"
                "编辑器行 " + fmt([str(r["editor_row_start"]) for r in bad_rungs]))

    # 2 多驱动
    bad = check_coils(coils, rep)
    for b in bad:
        rep.add("错误", b)

    # 3 写只读地址
    #    注意 R512 以上：手册资源分配表写的是「阶梯程序：依下表定义之」，
    #    不是只读。具体权限在 1-1.4.4 里逐条定义，例如
    #    R590~R599 = PLC 提示讯息（阶梯写）、R603 = 禁止轴移动命令（阶梯写）。
    #    拿区段表一刀切成"只读"会把正常接口位全判成错，所以这里分开处理。
    ro, warns = [], collections.defaultdict(list)
    for a, uses in sorted(coils.items()):
        kind = a[0].upper()
        rows_used = [r for _, r in uses]
        if kind in ("S", "T", "M"):
            ro.append(f"`{a}` 是 `{kind}` 段（核心→阶梯，只读），"
                      f"{eds(rows_used)} 却在驱动它")
        elif kind == "I":
            ro.append(f"`{a}` 是输入点，{eds(rows_used)} 却在驱动它")
        elif kind == "R":
            # R512~R1023 现在有逐条表(syntec_r_iface), 直接问 check_write 就行。
            # 以前这里单独攒一批「请人工核对 1-1.4.4」—— 那张表做完之后这句提示
            # 就成了噪音: 22 个地址里 21 个是 R590 提示讯息 / R603 禁止轴移动,
            # 本来就是阶梯该写的。剩下判不了的是"手册未列明", check_write 返回
            # None, 这里也不报 —— 手册没定义不等于 CNC 不认。
            res = DB.check_write(a)
            if res and res[0] == "error":
                ro.append(f"`{a}`：{res[1]}（{eds(rows_used)}）")
            elif res and res[0] == "warn":
                warns[warn_kind(res[1])].append(f"`{a}`（{eds(rows_used)}）")
    for x in ro:
        rep.add("错误", x)
    # 别把所有 warn 一律说成「保留区」：cnc.lad 的 13 条其实是「拿 R 的位
    # 当中间继电器用」, 手册 R50~R80 明明是使用者自订可写。措辞错了会把
    # 人引去查一份根本不存在的保留区文档。
    for k, items in sorted(warns.items()):
        rep.add("提示", f"{len(items)} 处写入：{WARN_TITLE[k]}",
                WARN_DETAIL[k] + "\n" + "、".join(items))

    # 4 触点用到的地址从不被驱动（只在 R/A 有意义；I/C/S 是外部给的）
    #    整字写入（MOVE/MATH）也算驱动了它的每一位，否则 R53.0 这种会误报
    #    另外 R 段里「阶梯只读」的地址由核心/参数画面写入，阶梯本来就不会
    #    有线圈 —— 典型是 R100.2(参数 3420 的寸动模式位)，不排除就会误报成
    #    「没人驱动」。判据直接问 check_write：写了不生效的，就不是阶梯该驱动的。
    driven = set(coils)
    for reg, uses in moves.items():
        driven.add(reg)
        base = reg.split(".")[0]
        for bit in range(32):
            driven.add(f"{base}.{bit}")
    dangling, alarm_unused = [], []
    for a, uses in sorted(contacts.items()):
        if a in driven or externally_driven(a):
            continue
        line = (f"`{a}` 被当作触点用了 {len(uses)} 次"
                f"（{eds(sorted({r for _, r in uses}))}），"
                f"但全文没有任何一处驱动它")
        (alarm_unused if is_alarm_bit(a) else dangling).append(line)
    for x in dangling:
        rep.add("警告", x)
    if alarm_unused:
        rep.add("提示", f"{len(alarm_unused)} 个 PLC 警报输出位没有线圈驱动",
                "\n".join(alarm_unused) + "\n"
                "手册 1-5：R40~R43 是系统内定警报、R44~R49 是自订警报，"
                "由阶梯程序线圈驱动后控制器才弹警报窗口。\n"
                "若该警报在本机未启用（现场已确认不影响程序正确性），属正常；"
                "否则要补上驱动它的检测逻辑。工具只列事实，不判对错。")

    # 5 比较块槽位: A 槽是常数还是寄存器由 opcode 决定 (官方 CMPx_ConstantToR vs CMPx_RtoR),
    #   常数变体的 A 必须真是常数、B 必须真是寄存器。
    CMP_NAME = {0x5e: "CMP >", 0x62: "CMP <", 0x66: "CMP =",
                0x6a: "CMP >(常数)", 0x6c: "CMP <(常数)", 0x6e: "CMP =(常数)"}
    CMP_CONST_OP = (0x6a, 0x6c, 0x6e)
    for ri, op, A, B in cmps:
        name = CMP_NAME.get(op, f"0x{op:02x}")
        an, bn = R.num_to_operand(A, True), R.num_to_operand(B, False)
        if op in CMP_CONST_OP:
            if not str(an).startswith("#"):
                rep.add("错误", f"{ed(ri)} 比较块 `{name}` 的 A 槽是 `{an}`，应为常数",
                        "编辑器里 A 槽固定当常数，写成地址会变成「常数 = 地址号」")
            if str(bn).startswith("#"):
                rep.add("错误", f"{ed(ri)} 比较块 `{name}` 的 B 槽是 `{bn}`，应为寄存器")

    # 6 定时器 / 计数器
    tpreset = collections.defaultdict(list)
    for ri, tag, el in timers:
        tpreset[str(el[3])].append((ri, tag, el))
    for k, uses in sorted(tpreset.items()):
        if len(uses) > 1:
            rep.add("错误", f"TM/CT {k} 在 {len(uses)} 处被驱动",
                    "、".join(ed(r) for r in sorted({r for r, _, _ in uses})))
        for ri, tag, el in uses:
            if el[5] == 0:
                rep.add("警告", f"{ed(ri)} 的 TM/CT {k} 预设为 0",
                        "预设 0 等于立即到，通常是想读参数却读空了")

    # 7 参数注释里的参数号是否自洽
    #    R81~R100 = 参数 3401~3420（手册）；R801~R820 = 3421~3440（按 R803=3423 反推）
    #    操作员是照注释去参数画面找号的，注释错了比逻辑错更难查。
    import re as _re
    for a, (short, long) in sorted(d["comments"].items()):
        m = _re.search(r"No\.?\s*(\d{4})", (short or "") + (long or ""))
        if not m:
            continue
        num = int("".join(ch for ch in a.split(".")[0] if ch.isdigit()) or 0)
        if 81 <= num <= 100:
            exp = 3401 + num - 81
        elif 801 <= num <= 820:
            exp = 3421 + num - 801
        else:
            continue
        got = int(m.group(1))
        if got != exp:
            rep.add("警告", f"注释里 `{a}` 标的是参数 {got}，按映射应为 {exp}",
                    "操作员照注释去改参数会改错号")

    # 8 输出条件（路径枚举，覆盖桥式与多负载）
    #    前面几项都是从字节上扫的，不知道「这个输出在什么条件下才会亮」。
    #    路径枚举把每个负载的使能条件算成 OR-of-AND，于是能查出三类死逻辑：
    #    接不到母排（悬空）、所有通路都恒假（永不动作）、一个条件都没有（常亮）。
    import syntec_paths as PA

    unreachable, never, always_on, through = [], [], [], []
    for r in d["rungs"]:
        if r.get("shape") == "blank":
            continue
        res = PA.analyze(rows, r["row_start"] - 1, r["row_end"] - 1)
        for L in res["loads"]:
            er = r["editor_row_start"]
            if L["unreachable"]:
                unreachable.append(f"`{L['addr']}`（行 {er}）")
            elif not L["terms"] and L["dead"]:
                never.append(f"`{L['addr']}`（行 {er}）")
            elif (L["el"][0] == "COIL" and L["el"][1] == "NO"
                  and any(not t for t in L["terms"])):
                always_on.append(f"`{L['addr']}`（行 {er}）")
            if L["through"]:
                through.append((er, L["addr"], L["through"]))

    if unreachable:
        rep.add("错误", f"{len(unreachable)} 个输出接不到左母排",
                "、".join(unreachable) + "\n这条通路根本不通，输出永远不会动作")
    if never:
        rep.add("错误", f"{len(never)} 个输出的所有通路都恒假",
                "、".join(never) + "\n"
                "典型是同一条通路上既有 A 又有 /A（比如两个分支交叉串联），"
                "要去编辑器里看这几行是不是接错了")
    if always_on:
        rep.add("提示", f"{len(always_on)} 个普通线圈没有任何条件（一上电就常亮）",
                "、".join(always_on) + "\n"
                "如果是有意的（比如「总是允许」），可以忽略；"
                "上升沿/置位线圈没有条件是有意义的，不在此列")
    if through:
        rep.add("提示", f"{len(through)} 个负载的上游串着功能块",
                "串联的定时器/运算块是**条件**，不是直通线（手册 1-2.10 / 1-2.7）："
                "只有定时器到达设定时间、或比较/运算结果为真时，才导通后面的负载。\n"
                "路径枚举已把这些块算进下游负载的条件里；这是正常的顺序控制写法，不是错误。\n"
                "涉及行 " + fmt(sorted({e for e, _a, _t in through})))

    # 9 输出点使用情况
    outs = {a for a in coils if a.upper().startswith("O")}
    print("【输出点】共 %d 个被驱动" % len(outs))
    for a in sorted(outs, key=lambda x: int("".join(c for c in x if c.isdigit()) or 0)):
        print("   %-7s  %d 处   %s" % (a, len(coils[a]),
                                       "/".join(sorted({k for k, _ in coils[a]}))))
    print()

    print("【检查结果】")
    rep.dump()

    if args.json:
        json.dump([{"level": l, "title": t, "detail": dt} for l, t, dt in rep.items],
                  open(args.json, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        print("\n已写", args.json)


if __name__ == "__main__":
    main()
