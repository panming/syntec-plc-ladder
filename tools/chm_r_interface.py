# -*- coding: utf-8 -*-
"""从《CNC and PLC Interface》1-1.4.4.htm 抽出 R 接口逐条定义。

1-1.4.4 是「接口说明」页, 一张表按 rowspan 把多行 R 归到同一个说明/权限下。
手册的 rowspan 表达「这一段与上一段共用同一个说明和读写规则」, 必须按 HTML
本义展开, 否则残行会被当成「手册没写权限」。

用法:
    python tools/chm_r_interface.py --dir <解包目录> [--out x.tsv]
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chm_to_md import TableRows, INHERIT      # noqa: E402


class MultiTableRows(TableRows):
    """原类每遇 </table> 就把 self.rows 覆盖掉, 这里改成按表累积。"""

    def __init__(self):
        super().__init__()
        self.tables = []

    def _expand(self):
        super()._expand()
        if self.rows:
            self.tables.append(self.rows)
        self.rows = []


def read_tables(path):
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
    p = MultiTableRows()
    p.feed(text)
    return p.tables


def parse_range(s):
    """'R512~R1023' -> (512,1023); 'R590.6' -> (590,590) 位地址另记"""
    s = s.replace(" ", "").replace("　", "")
    m = re.match(r"^R(\d+)(?:\.(\d+))?$", s)
    if m:
        n = int(m.group(1))
        return n, n, (int(m.group(2)) if m.group(2) is not None else None)
    m = re.match(r"^R(\d+)[~-]R?(\d+)$", s)
    if m:
        return int(m.group(1)), int(m.group(2)), None
    return None


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="已解包的目录(含 1-1.4.4.htm)")
    ap.add_argument("--out", help="输出 TSV")
    a = ap.parse_args(argv)

    tables = read_tables(os.path.join(a.dir, "1-1.4.4.htm"))
    print("表数 %d, 各表行数 %s" % (len(tables), [len(t) for t in tables]))
    for i, t in enumerate(tables):
        print("--- 表 %d 列数 %d" % (i, len(t[0]) if t else 0))
        for row in t[:3]:
            print("    ", [c.strip()[:30] for c in row])

    if not a.out:
        return

    out = []
    for t in tables:
        for row in t:
            if len(row) < 2:
                continue
            rng = parse_range(row[0].strip())
            if not rng:
                continue
            out.append({
                "addr": row[0].strip(),
                "lo": rng[0], "hi": rng[1], "bit": rng[2],
                "name": row[1].strip().lstrip(INHERIT),
                "desc": row[2].strip().lstrip(INHERIT) if len(row) > 2 else "",
                "perm": row[3].strip().lstrip(INHERIT) if len(row) > 3 else "",
            })
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print("写出 %d 条 -> %s" % (len(out), a.out))


if __name__ == "__main__":
    main()
