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
    def __init__(self):
        super().__init__()
        self.rows, self._row, self._cell = [], None, None

    def handle_starttag(self, tag, attrs):
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag):
        if tag in ("td", "th") and self._cell is not None:
            self._row.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


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


def md_r_table(rows):
    """R 分配表: 编号 | 说明 | 阶梯可读 | 阶梯可写 | 位存取 | 掉电保持"""
    lines = ["| 编号 | 说明 | 阶梯读 | 阶梯写 | 位存取 | 掉电保持 |",
             "|---|---|---|---|---|---|"]
    for r in rows:
        cells = [c for c in r]
        if not re.match(r"^R\d", cells[0]):
            continue
        # 手册里 R40~R49 / R256~R511 / R640~R1023 这几行是合并单元格，
        # 解出来的 HTML 只剩 1~2 个 td。不知道缺的是哪一列，就整行标"未列明"，
        # 不要按位置瞎补 —— 补错比留空更糟。
        if len(cells) < 6:
            note = cells[1] if len(cells) > 1 else "—"
            if note in ("是", "否"):
                note = "（未列说明）"      # 只剩一个权限值, 分不清是哪一列
            lines.append("| `%s` | %s | 手册此行未列明 | — | — | — |"
                         % (cells[0], note))
            continue
        note = cells[1].replace("|", "\\|") or "—"
        lines.append("| `%s` | %s | %s | %s | %s | %s |"
                     % (cells[0], note, cells[2], cells[3], cells[4], cells[5]))
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
