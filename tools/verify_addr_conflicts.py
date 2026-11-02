#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核对地址：手册 / 文档 / 代码三方是否对得上，有没有同址异义。

背景：地址只要有一处说岔，生成的程序就会「写进只读区」或者「两个功能共用一个点」，
现场表现是信号自己抖动、写进去没反应。这个脚本把三份来源摆在一起逐段比：

    手册  《CNC and PLC Interface-ZH-CN》1-1.4.3 资源分配表（按 rowspan 展开）
    文档  skill/syntec-plc/references/address-map.md 的 §5 表
    代码  src/syntec_address_db.py 的 R_ZONES

用法：

    python tools/verify_addr_conflicts.py                  # 查文档与代码
    python tools/verify_addr_conflicts.py --chm xxx.chm    # 连手册一起查（需 hh.exe）
    python tools/verify_addr_conflicts.py --dir /tmp/syntec_chm

退出码：0 全过 / 1 有冲突。`--skip-doc` 只查代码自洽。
"""
import argparse
import collections
import importlib.util
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)

import chm_to_md as C  # noqa: E402

ADDR_MAP = os.path.join(ROOT, "skill", "syntec-plc", "references", "address-map.md")
DB_PY = os.path.join(ROOT, "src", "syntec_address_db.py")

OK, WARN, BAD, SKIP = "ok", "warn", "bad", "skip"
_ICON = {OK: "  ok ", WARN: " warn", BAD: " FAIL", SKIP: " skip"}


class Report:
    def __init__(self):
        self.items = []

    def add(self, level, title, detail=""):
        self.items.append((level, title, detail))

    def count(self, level):
        return sum(1 for i in self.items if i[0] == level)

    def dump(self):
        for level, title, detail in self.items:
            print(f"[{_ICON[level]}] {title}")
            if detail:
                for line in detail.splitlines():
                    print(f"         {line}")
        print()
        print("=" * 72)
        print(f"通过 {self.count(OK)} / 提示 {self.count(WARN)} / "
              f"失败 {self.count(BAD)} / 跳过 {self.count(SKIP)}")
        return 0 if self.count(BAD) == 0 else 1


# --------------------------------------------------------------------------
# 三方数据
# --------------------------------------------------------------------------
def load_db():
    spec = importlib.util.spec_from_file_location("syntec_address_db", DB_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_span(text):
    """'R256~R511' -> (256, 511); 'R1000' -> (1000, 1000); 不能解析返回 None"""
    m = re.match(r"^R(\d+)\s*~\s*R?(\d+)$", text.strip())
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.match(r"^R(\d+)$", text.strip())
    if m:
        return int(m.group(1)), int(m.group(1))
    return None


def perm_write(cell):
    """阶梯程序列 -> True/False/None(依下表定义之, 由子表决定)"""
    c = cell.strip()
    if c in ("读/写", "讀/寫"):
        return True
    if c in ("只读", "只讀"):
        return False
    return None                      # 依下表定义之 / 空


def perm_bit(cell):
    c = cell.strip()
    return True if c == "是" else (False if c == "否" else None)


def manual_rows(rows):
    """CHM 展开后的行 -> [(lo, hi, note, write, bit, keep)]"""
    out = []
    for r in rows:
        cells = [c.lstrip(C.INHERIT) for c in r]
        if not cells or not re.match(r"^R\d", cells[0]):
            continue
        cells += [""] * (6 - len(cells))
        span = parse_span(cells[0])
        if not span:
            continue
        out.append((span[0], span[1], cells[1], perm_write(cells[3]),
                    perm_bit(cells[4]), cells[5].strip()))
    return out


def doc_rows():
    """address-map.md §5 表 -> 同 manual_rows 的结构; 找不到返回 None"""
    if not os.path.isfile(ADDR_MAP):
        return None
    text = open(ADDR_MAP, encoding="utf-8").read()
    m = re.search(r"<!-- BEGIN R -->(.*?)<!-- END R -->", text, re.S)
    if not m:
        return None
    out = []
    for line in m.group(1).splitlines():
        if not line.startswith("|"):
            continue
        cells = [c.strip().strip("`") for c in line.strip().strip("|").split("|")]
        if len(cells) < 6 or not re.match(r"^R\d", cells[0]):
            continue
        span = parse_span(cells[0])
        if not span:
            continue
        out.append((span[0], span[1], cells[1], perm_write(cells[3]),
                    perm_bit(cells[4]), cells[5]))
    return out


# --------------------------------------------------------------------------
# 检查项
# --------------------------------------------------------------------------
def check_zones_cover(db, rep):
    z = db.R_ZONES
    prev, holes, overlaps = -1, [], []
    for lo, hi, *_ in z:
        if lo == prev + 1:
            pass
        elif lo <= prev:
            overlaps.append((lo, hi))
        else:
            holes.append((prev + 1, lo - 1))
        prev = max(prev, hi)
    if holes or overlaps:
        rep.add(BAD, "R 权限表不连续",
                f"空洞 {holes} / 重叠 {overlaps} —— 落在洞里的地址会走「保留区」兜底")
    else:
        rep.add(OK, f"R 权限表覆盖 0~{prev} 连续无重叠（{len(z)} 段）")
    return prev


def check_manual_vs_code(db, manual, rep):
    """手册逐行与 R_ZONES 比。R_ZONES 是区段，手册行可能比区段细（R1000 等单点）。

    「阶梯程序 / 位存取」不一致算 FAIL —— 那直接决定能不能写。
    「掉电保持」不一致只算 WARN —— 代码里 keep 对只读段没有意义，而且
    R2100~R3100 这种 Pr 开关区，手册自己就给了两个值（Pr3228=0 否 / =1 是），
    单一布尔表达不了，代码取保守的「否」。
    """
    bad, soft = [], []
    for lo, hi, note, write, bit, keep in manual:
        z = db.r_zone(lo)
        if not z or z["hi"] < hi:
            bad.append(f"R{lo}~R{hi}: 代码里没有对应区段（或区段没盖住）")
            continue
        tag = f"R{lo}~R{hi}" if lo != hi else f"R{lo}"
        if write is not None and z["write"] != write:
            bad.append(f"{tag}: 阶梯程序手册「{'读/写' if write else '只读'}」"
                       f"→ 代码 {'可写' if z['write'] else '只读'}")
        if bit is not None and z["bit"] != bit:
            bad.append(f"{tag}: 位存取手册「{'是' if bit else '否'}」"
                       f"→ 代码 {'允许' if z['bit'] else '拒绝'}")
        if keep in ("是", "否") and z["keep"] != (keep == "是"):
            soft.append(f"{tag}: 手册「{keep}」/ 代码 {'是' if z['keep'] else '否'}")
    if bad:
        rep.add(BAD, f"手册与 R_ZONES 有 {len(bad)} 处写权限不一致", "\n".join(bad))
    else:
        rep.add(OK, f"手册 R 分配表与 R_ZONES 的写权限/位存取逐行一致（{len(manual)} 行）")
    if soft:
        rep.add(WARN, f"掉电保持有 {len(soft)} 处与手册字面不同（不影响可写判定）",
                "\n".join(soft) + "\n代码统一取保守值；R1000~R1014 是只读系统量，"
                "\nR2100~R3100 的保持属性随 Pr3228 变，单一布尔表达不了。")


def check_doc_vs_code(db, doc, rep):
    if doc is None:
        rep.add(SKIP, "address-map.md §5 表未找到，跳过文档比对")
        return
    bad = []
    for lo, hi, note, write, bit, keep in doc:
        z = db.r_zone(lo)
        if not z:
            bad.append(f"R{lo}: 文档有、代码没有")
            continue
        tag = f"R{lo}~R{hi}" if lo != hi else f"R{lo}"
        if write is not None and z["write"] != write:
            bad.append(f"{tag}: 文档{'可写' if write else '只读'} / 代码{'可写' if z['write'] else '只读'}")
        if bit is not None and z["bit"] != bit:
            bad.append(f"{tag}: 文档位存取{'是' if bit else '否'} / 代码{'允许' if z['bit'] else '拒绝'}")
    if bad:
        rep.add(BAD, f"文档 §5 与 R_ZONES 有 {len(bad)} 处不一致", "\n".join(bad))
    else:
        rep.add(OK, f"文档 §5 与 R_ZONES 一致（{len(doc)} 行）")


def check_manual_dups(manual, rep):
    """单点编号重复 = 手册排版错；区间重复 = 有意的条件行（Pr 开关）"""
    seen = collections.Counter()
    for lo, hi, note, *_ in manual:
        if lo == hi:
            seen[lo] += 1
    dups = [n for n, c in seen.items() if c > 1]
    if dups:
        rep.add(WARN, "手册里有单点编号重复（排版错，按原样保留并已在文档标注）",
                "、".join(f"R{n}" for n in sorted(dups)))
    else:
        rep.add(OK, "手册单点编号无重复")
    spans = collections.Counter((lo, hi) for lo, hi, *_ in manual if lo != hi)
    cond = [f"R{a}~R{b}" for (a, b), c in spans.items() if c > 1]
    if cond:
        rep.add(OK, "手册里的区间重复都是条件行（Pr 开关切换权限）", "、".join(sorted(cond)))


def check_cs_dups(rep):
    if not os.path.isfile(ADDR_MAP):
        rep.add(SKIP, "address-map.md 不存在，跳过 C/S 表检查")
        return
    text = open(ADDR_MAP, encoding="utf-8").read()
    for tag in ("C", "S"):
        m = re.search(r"<!-- BEGIN %s -->(.*?)<!-- END %s -->" % (tag, tag), text, re.S)
        if not m:
            rep.add(WARN, f"{tag} 段表未找到")
            continue
        cnt = collections.Counter()
        for line in m.group(1).splitlines():
            if not line.startswith("|"):
                continue
            first = line.strip().strip("|").split("|")[0].strip().strip("`")
            for a in re.findall(r"\b%s\d+\b" % tag, first):
                cnt[a] += 1
        dups = sorted(a for a, c in cnt.items() if c > 1)
        if dups:
            rep.add(BAD, f"{tag} 段表有重复编号（同址异义）", "、".join(dups))
        else:
            rep.add(OK, f"{tag} 段表无重复编号（{sum(cnt.values())} 个地址）")


def check_db_conflicts(db, rep):
    """地址库内部：同一地址挂到两个不同功能名下 = 反查会给错答案"""
    for name in ("AXIAL", "MST"):
        d = getattr(db, name, None)
        if not d:
            continue
        rev = collections.defaultdict(set)
        for k, v in d.items():
            if not isinstance(v, dict):
                continue
            for a in (v.get("axes") or []):
                if a:
                    rev[a].add(k)
            for a in (v.get("ch") or {}).values():
                if a:
                    rev[a].add(k)
        bad = {a: sorted(s) for a, s in rev.items() if len(s) > 1}
        if bad:
            detail = "\n".join(f"{a} -> {s}" for a, s in list(bad.items())[:10])
            rep.add(BAD, f"{name} 有 {len(bad)} 个同址异义", detail)
        else:
            rep.add(OK, f"{name} 无同址异义（{len(rev)} 个地址）")


def check_skill_examples(db, rep):
    """技能文档里的示例线圈，目标地址必须是能写的 —— 示例自己踩雷最坑人"""
    problems = []
    files = [
        os.path.join(ROOT, "skill", "syntec-plc", "references", "patterns.md"),
        os.path.join(ROOT, "skill", "syntec-plc", "references", "element-grammar.md"),
    ]
    pat = re.compile(r'(?:COIL|SET|RST)\("([A-Z]+\d+(?:\.\d+)?)"')
    seen = set()
    for f in files:
        if not os.path.isfile(f):
            continue
        for i, line in enumerate(open(f, encoding="utf-8"), 1):
            if line.lstrip().startswith(">"):        # 引用块是"反面例子"
                continue
            for addr in pat.findall(line):
                if "❌" in line:
                    continue
                key = (os.path.basename(f), addr)
                if key in seen:
                    continue
                seen.add(key)
                level, why = db.check_write(addr)
                if level == "error":
                    problems.append(f"{os.path.basename(f)}:{i} {addr} —— {why}")
    if problems:
        rep.add(BAD, "技能文档示例里有写不进去的地址", "\n".join(problems))
    else:
        rep.add(OK, f"技能文档示例的线圈地址都可写（查了 {len(seen)} 个）")


# --------------------------------------------------------------------------
def main(argv=None):
    ap = argparse.ArgumentParser(description="核对地址三方一致性 / 同址异义")
    ap.add_argument("--chm", help="手册 CHM，现场解包后比对（需 hh.exe）")
    ap.add_argument("--dir", help="已解包目录（含 1-1.4.3.htm）")
    ap.add_argument("--skip-doc", action="store_true", help="只查代码自洽")
    args = ap.parse_args(argv)

    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    db = load_db()
    rep = Report()

    check_zones_cover(db, rep)
    check_db_conflicts(db, rep)

    manual = None
    src = args.dir
    if not src and args.chm:
        src = os.path.join(tempfile.gettempdir(), "syntec_chm")
        print(f"解包 {args.chm} -> {src}")
        C.decompile(args.chm, src)
    if src:
        page = os.path.join(src, C.PAGE_R)
        if os.path.isfile(page):
            manual = manual_rows(C.read_table(page))
            check_manual_dups(manual, rep)
            check_manual_vs_code(db, manual, rep)
        else:
            rep.add(SKIP, f"{page} 不存在，跳过手册比对")
    else:
        rep.add(SKIP, "没给 --chm/--dir，跳过手册比对（最权威的那份没查）")

    if not args.skip_doc:
        check_cs_dups(rep)
        check_doc_vs_code(db, doc_rows(), rep)
        check_skill_examples(db, rep)

    print()
    print("地址核对 —— 手册 / 文档 / 代码")
    print("=" * 72)
    return rep.dump()


if __name__ == "__main__":
    sys.exit(main())
