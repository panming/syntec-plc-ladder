# -*- coding: utf-8 -*-
"""逻辑体检：把每条 rung 的「负载 <- 使能条件」导出，并做逻辑层面的统计。

和 review_ladder.py 的区别：review 查的是语法/地址/结构；这里查的是
「程序想干什么、条件写得对不对」—— 多处驱动、自保、查表覆盖、定时器、
恒真/恒假通路。输出是给人读的证据，不自动判错。

用法:
    python tools/logic_probe.py <程序.lad> [--out 文件]
"""
import sys
import os
import collections
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import syntec_read as RD
import syntec_parse as P
import syntec_paths as PA
import syntec_layout as Y


def norm_addr(a):
    """把负载标签归一成地址键：=A341 / ^A0 / R68=R103 / TM139 K15 ..."""
    s = str(a).strip()
    s = s.lstrip("=^")
    m = re.match(r"^(R\d+|[A-Za-z]+\d+(?:\.\d+)?)\s*=", s)
    if m:
        return m.group(1)
    m = re.match(r"^([A-Za-z]+\d+(?:\.\d+)?)", s)
    return m.group(1) if m else s


def cond_addrs(terms):
    """一条负载的所有条件项里出现过的地址（用于认自保）。"""
    out = set()
    for t in terms:
        for el in t:
            lit = PA.literal(el)
            if lit:
                out.add(lit[0])
    return out


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    lad = sys.argv[1]
    out_path = None
    if "--out" in sys.argv:
        out_path = sys.argv[sys.argv.index("--out") + 1]

    data = open(lad, "rb").read()
    logic, others, _tail = RD.split_records(data)
    rows = [P.decode_row(r) for r in logic]
    info = RD.read_ladder(lad)
    comments = info["comments"]

    L = []
    L.append("### 全量逻辑：R编号 (编辑器行) | 负载 <- 条件")
    coils = collections.defaultdict(list)   # 地址 -> [(rung, 编辑行, 负载标签, 条件)]
    gates = collections.defaultdict(list)   # 功能块 -> [(rung, 编辑行, 标签, 条件)]
    all_loads = []
    fend_rung = None

    for k, r in enumerate(info["rungs"], 1):
        a, b = r["row_start"] - 1, r["row_end"] - 1
        er = "%d-%d" % (r["editor_row_start"], r["editor_row_end"])
        res = PA.analyze(rows, a, b)
        head = "R%03d (编辑 %s)" % (k, er)
        if not res["loads"]:
            L.append("%s | (无负载)" % head)
            continue
        for x in res["loads"]:
            addr = x["addr"]
            txt = x["text"]
            L.append("%s | %-14s <- %s%s" % (
                head, addr, txt,
                ("  [途经 %s]" % ",".join(x["through"])) if x["through"] else ""))
            key = norm_addr(addr)
            rec = (k, er, addr, txt, x["terms"], x["dead"], x["unreachable"])
            all_loads.append(rec)
            (coils if addr.startswith(("=", "^")) else gates)[key].append(rec)

    # ---------- 统计 ----------
    S = []
    S.append("### 统计")

    S.append("\n--- 1. 同一地址被多处驱动（含功能块写入）---")
    multi = {k: v for k, v in coils.items() if len(v) > 1}
    S.append("被多处线圈驱动的地址: %d 个" % len(multi))
    for key in sorted(multi, key=lambda x: (x[0], int(re.search(r"\d+", x).group()) if re.search(r"\d+", x) else 0)):
        v = multi[key]
        S.append("  %-10s %d 处: %s" % (key, len(v), ", ".join("R%d(行%s)" % (x[0], x[1]) for x in v)))

    S.append("\n--- 2. 同一寄存器被多个功能块写入（MOVE/MATH）---")
    fbw = {k: v for k, v in gates.items() if len(v) > 1}
    S.append("被多处写入的寄存器: %d 个" % len(fbw))
    for key in sorted(fbw, key=lambda x: -len(fbw[x]))[:40]:
        v = fbw[key]
        S.append("  %-10s %d 处: %s" % (key, len(v), ", ".join("R%d" % x[0] for x in v)))

    S.append("\n--- 3. 自保回路（负载地址出现在自己的条件里）---")
    latch = []
    for rec in all_loads:
        k, er, addr, txt, terms, dead, un = rec
        key = norm_addr(addr)
        if not addr.startswith("="):
            continue
        if any(key == a or a == key.lstrip("=^") for a in cond_addrs(terms)):
            latch.append((k, er, addr, txt))
    S.append("自保持线圈: %d 处" % len(latch))
    for k, er, addr, txt in latch:
        S.append("  R%03d(行%s) %-12s <- %s" % (k, er, addr, txt))

    S.append("\n--- 4. 恒真通路（条件为 1，无条件驱动）---")
    always = [(k, er, addr) for k, er, addr, txt, t, d, u in all_loads if txt == "1"]
    S.append("无条件驱动: %d 处" % len(always))
    for k, er, addr in always[:60]:
        S.append("  R%03d(行%s) %s" % (k, er, addr))

    S.append("\n--- 5. 恒假 / 不可达 ---")
    dead = [(k, er, addr, txt) for k, er, addr, txt, t, d, u in all_loads
            if u or txt == "0" or (d and not t)]
    S.append("不可达或恒假: %d 处" % len(dead))
    for k, er, addr, txt in dead[:40]:
        S.append("  R%03d(行%s) %-12s <- %s" % (k, er, addr, txt))

    S.append("\n--- 6. 定时器 / 计数器 清单 ---")
    tm = collections.defaultdict(list)
    ct = collections.defaultdict(list)
    for k, er, addr, txt, t, d, u in all_loads:
        if re.match(r"^TM\d+", addr):
            tm[addr.split()[0]].append((k, er, addr, txt))
        if re.match(r"^C\d+", addr) and not addr.startswith("="):
            ct[addr.split()[0]].append((k, er, addr, txt))
    S.append("定时器 %d 个 / 计数器 %d 个" % (len(tm), len(ct)))
    for key in sorted(tm, key=lambda x: int(x[2:])):
        for k, er, addr, txt in tm[key]:
            S.append("  %-8s R%03d(行%s) %-16s <- %s" % (key, k, er, addr, txt))
    for key in sorted(ct, key=lambda x: int(x[1:])):
        for k, er, addr, txt in ct[key]:
            S.append("  %-8s R%03d(行%s) %-16s <- %s" % (key, k, er, addr, txt))

    S.append("\n--- 7. 比较块查表：按常数值分组（找缺口）---")
    # 比较块是 cond，不会出现在 analyze 的 loads 里，直接从解码后的元件扫。
    rung_of_row = {}
    for i, rg in enumerate(info["rungs"], 1):
        for rr in range(rg["row_start"] - 1, rg["row_end"]):
            rung_of_row[rr] = i
    cmp_k = collections.defaultdict(list)
    fb_all = collections.defaultdict(list)   # rung -> [(行, 标签)]
    for ri, row in enumerate(rows):
        k = rung_of_row.get(ri, 0)
        for cell in row:
            if cell is None or cell[1] is None:
                continue
            el = cell[1]
            if el[0] != "FB":
                continue
            lab = Y.el_label(el)
            fb_all[k].append((ri + 1, lab))
            m = re.search(r"K(-?\d+)\s*(==|>=|<=|>|<)\s*(R\d+)", lab)
            if m:
                cmp_k[m.group(3)].append((int(m.group(1)), m.group(2), k, lab))
    for reg in sorted(cmp_k, key=lambda x: int(x[1:])):
        v = sorted(cmp_k[reg])
        nums = [x[0] for x in v]
        if len(nums) < 2:
            continue
        gaps = [n for n in range(min(nums), max(nums) + 1) if n not in nums]
        S.append("  %-6s %d 个分支 K%d..K%d %s  rung %s" % (
            reg, len(nums), min(nums), max(nums),
            ("缺口 " + str(gaps)) if gaps else "连续无缺口",
            ",".join(str(x[2]) for x in v)))

    S.append("\n--- 7b. 功能块按 rung 分布（定时器/计数器/比较/运算/搬移）---")
    for k in sorted(fb_all):
        labs = [x[1] for x in fb_all[k]]
        S.append("  R%03d (%2d 个): %s" % (k, len(labs), " | ".join(labs)))

    S.append("\n--- 8. 报警区 R40~R49 的线圈写法（手册要求自保）---")
    alarm = [(k, er, addr, txt) for k, er, addr, txt, t, d, u in all_loads
             if addr.startswith("=") and re.match(r"^=R4[0-9]\.", addr)]
    S.append("报警位线圈 %d 处" % len(alarm))
    latch_keys = {(k, addr) for k, er, addr, txt in latch}
    for k, er, addr, txt in sorted(alarm):
        tag = "自保" if (k, addr) in latch_keys else "**无自保**"
        S.append("  R%03d(行%s) %-10s %-12s <- %s" % (k, er, addr, tag, txt))

    S.append("\n--- 8b. 报警汇总覆盖（启发式，手册 1-5.22.46）---")
    # R40.0~R43.31 = 系统内定警报 1~64；R44.0~R49.15 = 自订 Alarm 65~160；
    # R44.16~R49.31 = 自订 Warning 315~410。这些位由 PLC 线圈点亮后控制器才弹窗。
    # 程序通常另有一个「报警汇总」线圈（本机是 A200）去驱动红灯 / Feed Hold /
    # 禁止启动。若某个被驱动的 Alarm 位没进汇总，它就只弹文字、不触发处置链。
    driven_alarm = set()
    for rec in all_loads:
        m = re.match(r"^=R(4[0-9])\.(\d+)$", rec[2])
        if m:
            driven_alarm.add("%s.%s" % (m.group(1), m.group(2)))
    driven_alarm = {"R" + x for x in driven_alarm}
    summaries = []
    for rec in all_loads:
        txt = rec[3]
        regs = set(re.findall(r"K0<R(4[0-9])", txt))
        bits = set(re.findall(r"R4[0-9]\.\d+", txt))
        if len(regs) + len(bits) >= 5:
            summaries.append((rec[0], rec[2], regs, bits))
    S.append("被驱动的 Alarm/Warning 位: %d 个" % len(driven_alarm))
    S.append("识别到报警汇总线圈: %d 个" % len(summaries))
    for k, addr, regs, bits in summaries:
        uncovered = sorted(a for a in driven_alarm
                           if a.split(".")[0][1:] not in regs and a not in bits)
        S.append("  R%03d %-8s 覆盖寄存器 K0<R%s  显式位 %d 个" % (
            k, addr, ",".join(sorted(regs)) or "(无)", len(bits)))
        if uncovered:
            S.append("    ** 未纳入汇总的被驱动位 (%d): %s" %
                     (len(uncovered), ", ".join(uncovered)))
        else:
            S.append("    被驱动位全部纳入汇总")

    S.append("\n--- 9. 地址注释（按段）---")
    for a in sorted(comments, key=lambda x: (x[0], int(re.search(r"\d+", x).group()) if re.search(r"\d+", x) else 0)):
        sh, lo = comments[a]
        if sh or lo:
            S.append("  %-10s %s | %s" % (a, sh or "", lo or ""))

    text = "\n".join(L) + "\n\n" + "\n".join(S) + "\n"
    if out_path:
        open(out_path, "w", encoding="utf-8").write(text)
        print("已写出:", out_path, len(text), "字符")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
