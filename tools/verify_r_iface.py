# -*- coding: utf-8 -*-
"""R512~R1023 逐条权限：文档 ↔ 代码 ↔ check_write 三方对账。

这张表有 130 行、四类结论（可写 / 只读 / 保留 / 未列明），任何一处判错都不报
错 —— 它只会在现场表现为「写的地址不生效」或「正常写法被报成错」。所以三件事
必须钉死：

  1. 文档表和 classify() 逐地址一致（两者同源，但同源也会走偏，比如拆行时漏一格）
  2. 512~1023 每个地址恰好落在一类里，不重叠、不留洞
  3. 几条有现场结论的关键地址，结论不能被后来的改动悄悄翻掉

用法: python tools/verify_r_iface.py
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

import syntec_r_iface as RIF          # noqa: E402
import syntec_address_db as ADB       # noqa: E402

DOC = os.path.join(ROOT, "docs", "r512-r1023-权限表.md")
LO, HI = 512, 1023

n_ok = n_bad = 0


def chk(name, cond, detail=""):
    global n_ok, n_bad
    if cond:
        n_ok += 1
        print("  [PASS] %s" % name)
    else:
        n_bad += 1
        print("  [FAIL] %s  %s" % (name, detail))
    return cond


def doc_rows():
    """从文档表格里取出 (lo, hi, 权限)。"""
    out = []
    with open(DOC, encoding="utf-8") as f:
        for line in f:
            m = re.match(r"\|\s*`(R\d+)(?:~R(\d+))?`\s*\|\s*([^|]*?)\s*\|"
                         r"\s*(唯写|读写|只读|保留|待确认)\s*\|", line)
            if m:
                lo = int(m.group(1)[1:])
                hi = int(m.group(2)[1:]) if m.group(2) else lo
                out.append((lo, hi, m.group(4)))
    return out


EXPECT = {                  # 现场确认过的结论，翻掉就是回归
    518: "write",           # Manuel Coordinate
    521: "readonly",        # AX1 状态缓存器（核心写）
    526: "readonly",        # AX1 执行中单节剩余距离
    520: "write",           # AX1 命令缓存器
    590: "write",           # PLC 提示讯息
    603: "write",           # 禁止指定轴移动
    640: "undefined",       # 手册未列明 -> 不判
    700: "readonly",        # 合成进给速度实际值
    831: "write",           # MLC 参数：操作工/编程工程师可改
    840: "write",
    926: "reserved",
    938: "undefined",       # 手册没有, 但现场在用 -> 不判
    939: "undefined",
    940: "undefined",
    961: "readonly",        # 手册没写谁写, 按保守假设
    976: "readonly",
    1004: "readonly",
    1023: "write",          # PLC File System
}


def main():
    print("=" * 66)
    print(" R512~R1023 逐条权限对账")
    print("=" * 66)

    # ---- 1 覆盖：每个地址恰好一类 ----
    print("\n1. 覆盖与互斥")
    print("-" * 66)
    owner = {}
    dup = []
    for tag, table in (("write", RIF.WRITE), ("readonly", RIF.READONLY),
                       ("reserved", RIF.RESERVED), ("undefined", RIF.UNDEFINED)):
        for lo, hi, _ in table:
            for i in range(lo, hi + 1):
                if i in owner:
                    dup.append((i, owner[i], tag))
                owner[i] = tag
    hole = [i for i in range(LO, HI + 1) if i not in owner]
    chk("512~1023 无空洞", not hole, str(hole[:12]))
    chk("无地址被两条以上覆盖", not dup, str(dup[:6]))
    out_of_range = [i for i in owner if not LO <= i <= HI]
    chk("表里没有 512~1023 之外的地址", not out_of_range, str(out_of_range[:8]))

    # ---- 2 文档表与代码一致 ----
    print("\n2. 文档表 vs classify()")
    print("-" * 66)
    rows = doc_rows()
    chk("文档表解析到条目", len(rows) >= 100, "只拿到 %d 条" % len(rows))
    MAP = {"唯写": "write", "读写": "write", "只读": "readonly",
           "保留": "reserved", "待确认": "undefined"}
    mismatch = []
    for lo, hi, perm in rows:
        want = MAP[perm]
        for i in range(lo, hi + 1):
            got = RIF.classify(i)[0]
            if got != want:
                mismatch.append((i, perm, got))
    chk("逐地址一致", not mismatch,
        "%d 处不一致, 前几个 %s" % (len(mismatch), mismatch[:6]))

    # ---- 3 关键结论 ----
    print("\n3. 现场确认过的结论")
    print("-" * 66)
    for no, want in sorted(EXPECT.items()):
        got, name = RIF.classify(no)
        chk("R%-5d = %-9s" % (no, want), got == want, "实际 %s (%s)" % (got, name))

    # ---- 4 check_write 的行为 ----
    print("\n4. check_write 的实际返回")
    print("-" * 66)
    cases = [
        ("R590.2", None),        # 提示讯息, 可写
        ("R603.4", None),        # 禁止轴移动, 可写
        ("R521", "error"),       # 状态缓存器, 只读
        ("R700", "error"),
        ("R700.0", "error"),     # R640 以上位存取=否
        ("R831", None),          # MLC 参数, 可写
        ("R961", "error"),       # 保守判只读
        ("R938", None),          # 未列明 -> 不判
        ("R640", None),
        ("R519", "warn"),        # 保留 -> 提示
        ("R1023", None),         # PLC 文件系统, 唯写
    ]
    for addr, want in cases:
        got, msg = ADB.check_write(addr)
        chk("%-8s -> %-5s" % (addr, str(want)), got == want, (msg or "")[:60])

    # ---- 5 位存取边界 ----
    print("\n5. 位存取边界（R639 可以 / R640 不行）")
    print("-" * 66)
    chk("RIF.BIT_MAX == 639", RIF.BIT_MAX == 639, str(RIF.BIT_MAX))
    chk("R639.0 位合法", RIF.bit_ok(639))
    chk("R640.0 位非法", not RIF.bit_ok(640))

    print("\n" + "=" * 66)
    if n_bad:
        print("失败 %d / %d —— 权限表与代码走偏了" % (n_bad, n_ok + n_bad))
        return 1
    print("全部通过（%d 项）" % n_ok)
    return 0


if __name__ == "__main__":
    sys.exit(main())
