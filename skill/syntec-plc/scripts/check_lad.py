#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""新代 .lad 字节级体检。纯 stdlib，不依赖 MCP、不依赖仓库。

查的是"文件本身有没有被改坏"，不查逻辑对不对：
    1. 长度 40N+2、尾部 00 fe
    2. 每个记录 10 格
    3. 8 字节块（定时器/计数器/运算/比较/END…）是否按双格占位
    4. 相邻格连接位是否镜像（编辑器 AutoFix 的判据）
    5. 末行是否为 END/FEND/RTS；END 的第二格不能是横线（全零或 00 00 00 80 都合法）
    6. 注释块能否按 cp950 解码

注意：**不检查参数区末字节是不是 0x80**。那个字节不可靠——编辑器样本常写 0x80，
真机文件里也有 0x00（cnc.lad 的定时器是 0a 00 0a 00），拿它当判据会误报。

用法：
    python check_lad.py 程序.lad
    python check_lad.py 程序.lad -v          # 逐行打印
    python check_lad.py 程序.lad --quiet     # 只报错误
    python check_lad.py *.lad                # 批量

退出码：0 全部通过，1 有错误。
"""
import argparse
import glob
import sys

REC = 40                                   # 每记录字节数
COLS = 10                                  # 每记录格数

# 占 2 格（8 字节）的功能块 opcode
BLOCK8 = {
    # 定时器: 精度 × 源(K/R)
    0xc5, 0xe4, 0xc4, 0xe3, 0xc3, 0xe2, 0xc2, 0xe7,
    # 计数器
    0xc6, 0xe5, 0xc7, 0xe6, 0xc9, 0xe0, 0xe9, 0xe1, 0xea,
    # 算术
    0x21, 0x27, 0x33, 0x39, 0x45, 0x4b, 0x57, 0x5d,
    # 搬移
    0x72, 0x70,
    # 逻辑
    0x81, 0x87, 0x93, 0x99, 0xa5, 0xab,
    # 比较
    0x5e, 0x62, 0x66, 0x6a, 0x6c, 0x6e,
    # 旋转
    0xb0,
    # 流程(带标签)
    0xca, 0xcb, 0xd4, 0xd5,
    # END / FEND: 双格, 第 2 格是保留区
    0xcf, 0xfd,
}
# RTS 是唯一的宽度例外: 官方 plcop_map 把它标成双格, 但真机里 00 d0 00 00
# 后面紧跟的是横线格 00 0d 00 00, 按 8 字节读会吞掉横线、整行右移一格。
# 所以它不进 BLOCK8, 下面的循环自然只吃一格。
FLOW4 = {0xd0}

OPNAME = {
    0x00: "空", 0x0d: "线", 0x01: "触点(常开)", 0x03: "触点(常闭)",
    0x09: "TM触点(常开)", 0x0a: "TM触点(常闭)",
    0x0b: "CT触点(常开)", 0x0c: "CT触点(常闭)",
    0x0e: "线圈", 0x10: "线圈(常闭)", 0x05: "线圈(正缘)", 0x07: "线圈(负缘)",
    0x12: "置位", 0x14: "复位", 0xcf: "END", 0xd0: "RTS", 0xfd: "FEND",
}


def opname(op):
    return OPNAME.get(op, "0x%02x" % op)


def split_comment(recs, i):
    """按编辑器解析逻辑切一个注释块。
       返回 (bytes, ct, 下一个记录下标)。
       首记录从 byte6 起、每 4 字节槽存 2 字节，共 9 槽 = 18B；
       续记录从 byte2 起、10 槽 = 20B。byte2 是字节数不是字符数。"""
    rec = recs[i]
    nbytes, ct = rec[2], rec[3]
    if nbytes == 0:
        return b"", ct, i + 1
    buf = bytearray()
    pos, cur, consumed, got = 6, rec, 0, 0
    while got < nbytes:
        buf.append(cur[pos])
        got += 1
        pos = pos + 1 if (pos % 4 != 3) else pos + 3
        if got < nbytes and pos == 42:
            consumed += 1
            if i + consumed >= len(recs):
                break
            cur = recs[i + consumed]
            pos = 2
    return bytes(buf[:nbytes]), ct, i + 1 + consumed


def check(path, verbose=False):
    """返回 (errors, warns, info)"""
    errors, warns, info = [], [], []

    try:
        data = open(path, "rb").read()
    except OSError as e:
        errors.append(f"读不到文件: {e}")
        return errors, warns, info

    n = len(data) // REC
    body = data[:n * REC]
    tail = data[n * REC:]
    info.append(f"文件 {len(data)} 字节 = {n} 条记录 × 40 + 尾 {len(tail)} 字节")

    # ---- 1. 尾部 ----
    if tail != b"\x00\xfe":
        errors.append(f"文件尾应为 00 fe，实际 {tail.hex(' ') or '(空)'}；"
                      f"长度 {len(data)} 不是 40N+2（差 {len(data) - (n * REC + 2)} 字节）")

    if n == 0:
        errors.append("文件里一条记录都没有")
        return errors, warns, info

    recs = [body[i * REC:(i + 1) * REC] for i in range(n)]

    # ---- 2. 逐记录检查 ----
    logic_rows = 0
    last_logic = None
    comment_stats = {}
    i = 0
    while i < n:
        rec = recs[i]
        if rec[1] == 0 and rec[3] != 0:                  # 注释 / 版本 / 变量注释
            raw, ct, nxt = split_comment(recs, i)
            comment_stats[ct] = comment_stats.get(ct, 0) + 1
            try:
                text = raw.decode("cp950")
            except UnicodeDecodeError:
                # 真机文件里确实有这种: 早年在 Big5 字段里混进了 GBK 字节
                # (如 93 7c 在 GBK 下是"搢")。编辑器里显示乱码, 但不影响程序运行,
                # 所以只警告 —— 硬报错的话两份真机语料都过不了。
                text = raw.decode("cp950", "replace")
                hint = ""
                try:
                    raw.decode("gbk")
                    hint = "，按 GBK 可以解开，像是早年输入法混进来的"
                except UnicodeDecodeError:
                    pass
                warns.append(f"第 {i + 1} 条记录: ct={ct} 注释不是合法 cp950"
                             f"（{raw[:24].hex(' ')}…{hint}）")
            if verbose:
                label = {1: "整行注释", 3: "整行注释", 2: "版本", }.get(ct, "变量注释")
                print(f"  记录{i + 1:>4}  {label}(ct={ct})  {text[:48]!r}")
            i = nxt
            continue

        # 逻辑行: 逐格走，识别 8 字节块
        cells = [(rec[c * 4], rec[c * 4 + 1]) for c in range(COLS)]   # (conn, op)
        occupied = [True] * COLS
        c = 0
        line = []
        while c < COLS:
            conn, op = cells[c]
            if op in BLOCK8:
                param = rec[(c + 1) * 4:(c + 2) * 4] if c + 1 < COLS else b""
                if c + 1 >= COLS:
                    errors.append(f"第 {i + 1} 行: {opname(op)} 在最后一格，"
                                  f"没有位置放参数区（整行错位）")
                else:
                    occupied[c + 1] = False
                    # +7 是保留字节: 编辑器常写 0x80, 但真机文件里也有 0x00
                    # (cnc.lad 的定时器是 "0a 00 0a 00")。所以这里不拿 0x80 做任何判断。
                    line.append(f"{opname(op)}[{param.hex(' ')}]")
                c += 2
                continue
            line.append(opname(op) if op != 0x00 else ".")
            c += 1

        # ---- 连接位镜像: 只比相邻两个"真实格"(参数格不参与) ----
        for c in range(COLS - 1):
            if not (occupied[c] and occupied[c + 1]):
                continue
            a, b = cells[c][0], cells[c + 1][0]
            if bool(a & 0x01) != bool(b & 0x04):
                errors.append(f"第 {i + 1} 行 第{c}→{c + 1}格: 上半段竖线不镜像 "
                              f"(左 conn={a:02x} 右 conn={b:02x})")
            if bool(a & 0x02) != bool(b & 0x08):
                errors.append(f"第 {i + 1} 行 第{c}→{c + 1}格: 下半段竖线不镜像 "
                              f"(左 conn={a:02x} 右 conn={b:02x})")

        if verbose:
            print(f"  记录{i + 1:>4}  " + " ".join(line))
        logic_rows += 1
        last_logic = (i, rec)
        i += 1

    info.append(f"逻辑行 {logic_rows} 行，注释块 {sum(comment_stats.values())} 条"
                + (f"（" + ", ".join(f"ct={k}×{v}" for k, v in sorted(comment_stats.items())) + "）"
                   if comment_stats else ""))

    # ---- 3. 末行必须是 END（双格）----
    if last_logic is None:
        errors.append("文件里没有逻辑行")
    else:
        idx, rec = last_logic
        if rec[1] not in (0xcf, 0xfd, 0xd0):
            # 带子程序的文件末尾是 RTS; 多程序段是 FEND。三者都合法。
            errors.append(f"最后一条逻辑行（第 {idx + 1} 条记录）不是 END/FEND/RTS，"
                          f"是 {opname(rec[1])}；编辑器可能提示程序不完整")
        elif rec[1] == 0xcf and rec[5] == 0x0d:
            # END 占 2 格，第二格是参数区(全零或 00 00 00 80)，绝不是横线。
            # 第二格出现横线 = END 被当成 4 字节写，后面所有格整体错位一格。
            errors.append(f"END 第二格是横线 {rec[4:8].hex(' ')}："
                          f"END 被按 4 字节写入，整行错位一格")

    if not any(r[1] == 0xcf for r in recs if not (r[1] == 0 and r[3] != 0)):
        warns.append("整个文件里没有 END 记录，主程序可能不完整")

    return errors, warns, info


def main(argv=None):
    ap = argparse.ArgumentParser(description="新代 .lad 文件字节级体检")
    ap.add_argument("paths", nargs="+", help="一个或多个 .lad 文件（支持通配符）")
    ap.add_argument("-v", "--verbose", action="store_true", help="逐行打印")
    ap.add_argument("-q", "--quiet", action="store_true", help="只报错误")
    args = ap.parse_args(argv)

    files = []
    for p in args.paths:
        files.extend(sorted(glob.glob(p)) or [p])

    total_err = 0
    for path in files:
        if len(files) > 1 or args.verbose:
            print(f"\n=== {path} ===")
        errors, warns, info = check(path, args.verbose)
        if not args.quiet:
            for line in info:
                print(f"  {line}")
        for w in warns:
            print(f"  [WARN] {w}")
        for e in errors:
            print(f"  [FAIL] {e}")
        if not errors:
            print(f"  [PASS] 结构检查全部通过" + (f"（{len(warns)} 条警告）" if warns else ""))
        total_err += len(errors)

    if len(files) > 1:
        print(f"\n合计 {len(files)} 个文件，{total_err} 个错误")
    return 1 if total_err else 0


if __name__ == "__main__":
    sys.exit(main())
