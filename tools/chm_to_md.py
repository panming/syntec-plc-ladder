#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把《CNC and PLC Interface》CHM 里的三张接口表抽成 markdown。

工具链里的地址知识有两个来源:
  - syntec_address_db.py  手工整理的标准地址（带中文反查索引）
  - 本脚本                 从厂商手册直接抽取的完整表（C 512 点 / S 512 点 / R 分配表）

手册更新后重跑一次即可，不用手抄：

    python tools/chm_to_md.py --chm "D:/doc/CNC and PLC Interface-ZH-CN.chm"
    python tools/chm_to_md.py --chm xxx.chm --out skill/syntec-plc/references/address-map.md

CHM 的解包依赖 Windows 自带 hh.exe；其他平台先自己解包，再用 --dir 指向解包目录。
"""
import argparse
import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser

# 手册里三张表所在的文件名
PAGE_C = "1-1.1.htm"      # C Bit Interface (From PLC To CNC)
PAGE_S = "1-1.2.htm"      # S Bit Interface (From CNC To PLC)
PAGE_R = "1-1.4.3.htm"    # 资源分配表

MARK_C = ("<!-- BEGIN C -->", "<!-- END C -->")
MARK_S = ("<!-- BEGIN S -->", "<!-- END S -->")
MARK_R = ("<!-- BEGIN R -->", "<!-- END R -->")

# rowspan 带下来的格子加这个前缀, 用来区分「手册合并」和「手册本来就这么写」
INHERIT = "\x01"


# --------------------------------------------------------------------------
# CHM -> html
# --------------------------------------------------------------------------
def decompile(chm, outdir):
    """用 hh.exe 解包。注意 hh.exe 对带空格的长路径会静默失败，先复制成短名。"""
    if not os.path.isfile(chm):
        raise SystemExit("找不到 CHM: %s" % chm)
    tmp = os.path.join(tempfile.gettempdir(), "chm_src.chm")
    with open(chm, "rb") as f, open(tmp, "wb") as g:
        g.write(f.read())
    os.makedirs(outdir, exist_ok=True)
    subprocess.run(["hh.exe", "-decompile", outdir, tmp], check=False)
    if not os.path.isfile(os.path.join(outdir, PAGE_C)):
        raise SystemExit(
            "hh.exe 没有解出内容。手动解包后改用 --dir 指定目录:\n"
            "  hh.exe -decompile <目录> <文件.chm>")


# --------------------------------------------------------------------------
# html 表格 -> 行
# --------------------------------------------------------------------------
class TableRows(HTMLParser):
    """把 <table> 解成二维网格，**按 rowspan / colspan 展开**。

    手册的 R 分配表用 rowspan 表达「这一段与上一段共用同一个说明和权限」：
    R103~R255 的说明/宏程序/阶梯/位存取四格是 rowspan=2，一直盖到 R256~R511。
    不展开就只能拿到一个 td 的残行，之前正是把残行当成「手册未列明」，
    进而把 R256~R511（实际是使用者自订、可读可写可位）误判成保留区。
    按 HTML 的本义展开，比按位置猜或留空都可靠。
    """

    def __init__(self):
        super().__init__()
        self.rows = []          # 展开后的网格
        self._raw = []          # [(text, rowspan, colspan), ...]
        self._row, self._cell, self._attrs = None, None, {}

    @staticmethod
    def _span(v):
        try:
            return max(1, int(str(v).strip()))
        except (TypeError, ValueError):
            return 1

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): v for k, v in attrs}
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell, self._attrs = [], a

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            text = re.sub(r"\s+", " ", "".join(self._cell)).strip()
            self._row.append((text, self._span(self._attrs.get("rowspan")),
                              self._span(self._attrs.get("colspan"))))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self._raw.append(self._row)
            self._row = None
        elif tag == "table":
            self._expand()

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)

    def _expand(self):
        """把 _raw 展开成矩形网格；跨行格子在后续行按列位置继承。

        继承来的格子加 INHERIT 前缀，好让下游知道「这一格是 rowspan 带下来的」，
        而不是手册真的在下一行重写了一遍。
        """
        grid, pend = [], {}          # pend: col -> [文本, 剩余行数]
        for cells in self._raw:
            line, col = {}, 0
            for text, rs, cs in cells:
                while pend.get(col, [None, 0])[1] > 0:
                    line[col] = INHERIT + pend[col][0]
                    pend[col][1] -= 1
                    col += 1
                for k in range(cs):
                    line[col + k] = text
                    if rs > 1:
                        pend[col + k] = [text, rs - 1]
                col += cs
            while pend.get(col, [None, 0])[1] > 0:
                line[col] = INHERIT + pend[col][0]
                pend[col][1] -= 1
                col += 1
            width = max(line) + 1 if line else 0
            grid.append([line.get(i, "") for i in range(width)])
        self.rows = grid
        self._raw = []


def read_table(path):
    with open(path, "rb") as f:
        raw = f.read()
    for enc in ("cp936", "utf-8", "big5"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise SystemExit("无法解码 %s" % path)
    p = TableRows()
    p.feed(text)
    return p.rows


# --------------------------------------------------------------------------
# 行规整
# --------------------------------------------------------------------------
def norm_addr(s):
    """'S171~ S186' -> 'S171~S186'; 'C006®' -> ('C006', True)"""
    s = s.replace(" ", "").replace("~", "~")
    realtime = "®" in s
    s = s.replace("®", "").replace("&reg;", "")
    s = re.sub(r"^~", "", s)
    return s, realtime


def collapse(rows, letter):
    """无名称的连续单点合并成区间；返回 [(地址, 名称, 说明, 是否实时)]"""
    out = []
    pending = []

    def flush():
        if not pending:
            return
        if len(pending) == 1:
            out.append((pending[0], "（未定义）", "", False))
        else:
            out.append((f"{pending[0]}~{pending[-1]}", "（未定义）", "",
                        False))
        pending.clear()

    for r in rows:
        r = [c.lstrip(INHERIT) for c in r]      # C/S 表无合并, 这里只是兜底
        addr = r[0].strip()
        if not re.match(r"^[CS]?\d", addr.replace("~", "").replace(" ", "")
                        or "x") and not re.match(r"^[CS]", addr):
            continue                      # 表头
        name = r[1].strip() if len(r) > 1 else ""
        desc = r[2].strip() if len(r) > 2 else ""
        a, rt = norm_addr(addr)
        single = re.match(r"^%s(\d+)$" % letter, a)
        if single and not name:
            pending.append(a)
            continue
        flush()
        out.append((a + ("®" if rt else ""), name or "（未定义）", desc, rt))
    flush()
    return out


def md_table(rows):
    lines = ["| 地址 | 名称 | 说明 |", "|---|---|---|"]
    for addr, name, desc, _rt in rows:
        d = desc.replace("|", "\\|").replace("\n", " ")
        n = name.replace("|", "\\|")
        lines.append(f"| `{addr}` | {n} | {d} |")
    return "\n".join(lines)


# 手册 1-1.4.3 的 R 表在 R1014 处连着列了两行，编号相同、名称不同
# （「累计开机时间」和「安装累计加工时间」）。现场对过：R1013 累计加工时间、
# R1014 累计开机时间，「安装累计加工时间」这一行是排版错误，实际不存在这个量。
# 直接略去，否则表里会出现两个 R1014，谁也不知道该信哪个。
TYPO_ROWS = {("R1014", "安装累计加工时间")}


def md_r_table(rows):
    """R 分配表。

    列名照手册原文：第 3 列是「宏程序或人机界面」、第 4 列才是「阶梯程序」。
    这两列权限并不总是相同（例如 R8000~R8255 宏程序读/写、阶梯只读），
    把第 3 列写成「阶梯读」会让人以为阶梯能读能写，正好反过来。
    """
    lines = ["| 编号 | 说明 | 宏程序/人机界面 | 阶梯程序 | 位存取 | 掉电保持 |",
             "|---|---|---|---|---|---|"]
    seen, dup, typo = set(), [], []
    for r in rows:
        cells = [c.lstrip(INHERIT) for c in r]
        merged = [c.startswith(INHERIT) for c in r]
        if not cells or not re.match(r"^R\d", cells[0]):
            continue
        cells += [""] * (6 - len(cells))
        merged += [False] * (6 - len(merged))
        addr = cells[0].replace("|", "\\|")
        if (cells[0], cells[1].strip()) in TYPO_ROWS:
            typo.append((cells[0], cells[1].strip()))
            continue
        # 只有「单点编号重复」才是排版错。R2050~R2090 这种重复是手册有意列的
        # 条件行（Pr3810=0 / Pr3810=1 两种权限），不能当成错误。
        if "~" not in cells[0]:
            if cells[0] in seen:
                dup.append(cells[0])
            seen.add(cells[0])
        note = cells[1].replace("|", "\\|") or "—"
        if merged[1]:
            # 这一格的说明是上一行 rowspan 带下来的。照抄会让 R256~R511 读起来像
            # 「刀号区」（它继承的是 R103~R255 那句），只保留主句并标明来源。
            note = note.split(" (")[0].split("（")[0] + "（手册与上一行合并成一格）"
        vals = [("—" if not c.strip() else c.strip()) for c in cells[2:6]]
        lines.append("| `%s` | %s | %s | %s | %s | %s |"
                     % (addr, note, vals[0], vals[1], vals[2], vals[3]))
    if typo:
        names = "、".join("「%s」" % n for _, n in typo)
        addrs = "、".join("`%s`" % a for a, _ in typo)
        lines += ["",
                  "> 注：手册原文在 %s 处多列了一行%s，编号与上一行相同。"
                  "现场核对确认这是排版错误，已略去。" % (addrs, names)]
    if dup:
        uniq = "、".join(sorted(set(dup)))
        lines += ["",
                  "> ⚠️ 手册原文里 `%s` 出现了两次（编号重复，两个名称不同），"
                  "抽取按原样保留、没有替你选一个 —— 先当排版错处理，别把这一格当用户区用。"
                  % uniq]
    return "\n".join(lines)


def replace_section(text, marks, body):
    begin, end = marks
    i, j = text.find(begin), text.find(end)
    if i < 0 or j < 0:
        raise SystemExit("模板里缺少标记 %s / %s" % (begin, end))
    return text[:i + len(begin)] + "\n" + body + "\n" + text[j:]


def main(argv=None):
    ap = argparse.ArgumentParser(description="CHM 接口表 -> markdown")
    ap.add_argument("--chm", help="CHM 文件路径")
    ap.add_argument("--dir", help="已解包的目录(含 1-1.1.htm)")
    ap.add_argument("--out", default=os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "skill", "syntec-plc", "references", "address-map.md"))
    ap.add_argument("--tables-only", action="store_true",
                    help="只打印三张表, 不改文件")
    args = ap.parse_args(argv)

    src = args.dir
    if not src:
        if not args.chm:
            raise SystemExit("要么给 --chm, 要么给 --dir")
        src = os.path.join(tempfile.gettempdir(), "syntec_chm")
        decompile(args.chm, src)

    c_rows = collapse(read_table(os.path.join(src, PAGE_C))[1:], "C")
    s_rows = collapse(read_table(os.path.join(src, PAGE_S))[1:], "S")
    r_rows = read_table(os.path.join(src, PAGE_R))

    c_md = md_table(c_rows)
    s_md = md_table(s_rows)
    r_md = md_r_table(r_rows)

    if args.tables_only:
        for title, body in (("C", c_md), ("S", s_md), ("R", r_md)):
            print("=" * 20, title, "=" * 20)
            print(body)
        return 0

    with open(args.out, encoding="utf-8") as f:
        text = f.read()
    text = replace_section(text, MARK_C, c_md)
    text = replace_section(text, MARK_S, s_md)
    text = replace_section(text, MARK_R, r_md)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)

    print(f"已写入 {args.out}")
    print(f"  C {len(c_rows)} 行 / S {len(s_rows)} 行 / R {len(r_rows) - 1} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())
