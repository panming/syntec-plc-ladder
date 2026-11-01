#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编码器逐字节复验: 定时器(4 精度 × 2 源) / 计数器(5 方向 × 2 源) / 流程块(JSR/LAB/RTS)。

方法: 拿"标准答案"文件——B_timer.lad / B_counter.lad / B_flow.lad 是在 SYNTEC 编辑器里
手工点出来的样本, cnc_1.lad 是真实机床程序——取出对应的 40 字节记录,
用本项目编码器重新生成同一条, 逐字节比对。

判据: 完全相同 = opcode、编号、参数块、列布局全部正确。

用法:
    python verify_samples.py                  # 样本默认在桌面
    python verify_samples.py --samples DIR    # 换个目录
    python verify_samples.py DIR              # 只给一个目录也可以

环境变量 SYNTEC_SAMPLES 同样生效。
"""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "src"), os.path.join(os.path.dirname(_HERE), "src")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)          # 兼容 平铺 / src+tools 两种布局


def _default_samples():
    """样本目录: $SYNTEC_SAMPLES > 旁边的 samples/ (仓库布局) > 桌面"""
    env = os.environ.get("SYNTEC_SAMPLES")
    if env:
        return os.path.abspath(os.path.expanduser(env))
    for d in (os.path.join(_HERE, "samples"),
              os.path.join(os.path.dirname(_HERE), "samples")):
        if os.path.isdir(d):
            return os.path.abspath(d)
    return os.path.abspath(os.path.join(os.path.expanduser("~"), "Desktop"))


import syntec_lad as L
import syntec_model as M

DESK = _default_samples()


def parse_argv(argv):
    """--samples DIR / 单个位置参数目录 / 环境变量, 三者任一"""
    global DESK
    args = list(argv)
    if "--samples" in args or "-s" in args:
        flag = "--samples" if "--samples" in args else "-s"
        i = args.index(flag)
        if i + 1 >= len(args):
            sys.exit(f"{flag} 后面要跟一个目录")
        DESK = os.path.abspath(os.path.expanduser(args[i + 1]))
    elif args and os.path.isdir(args[0]):
        DESK = os.path.abspath(os.path.expanduser(args[0]))
    elif args:
        sys.exit(f"不认识参数: {' '.join(args)}\n用法: python verify_samples.py [--samples DIR]")
    return DESK

# (文件, 行号, TM编号, precision, source, 预设值或寄存器号)
TIMERS = [
    ("B_timer.lad", 1, 1, '1s',     'K', 60),
    ("B_timer.lad", 2, 1, '1s',     'K', 100),
    ("B_timer.lad", 3, 2, '1s',     'R', 300),
    ("B_timer.lad", 4, 3, '0.1s',   'R', 301),
    ("B_timer.lad", 5, 4, '0.01s',  'R', 302),
    ("B_timer.lad", 6, 5, '0.001s', 'R', 303),
    ("B_timer.lad", 7, 6, '0.1s',   'K', 60),
    ("B_timer.lad", 8, 7, '0.01s',  'K', 60),
    ("B_timer.lad", 9, 8, '0.001s', 'K', 60),
]

# (文件, 行号, CT编号, direction, source, 预设值或寄存器号)
COUNTERS = [
    ("B_counter.lad", 1, 1, 'UP',        'K', 50),
    ("B_counter.lad", 2, 2, 'DOWN',      'K', 51),
    ("B_counter.lad", 3, 3, 'RESET',     'K', 52),
    ("B_counter.lad", 4, 4, 'RING_UP',   'K', 53),
    ("B_counter.lad", 5, 5, 'RING_DOWN', 'K', 54),
    ("B_counter.lad", 6, 6, 'UP',        'R', 55),
    ("B_counter.lad", 7, 7, 'DOWN',      'R', 56),
    ("B_counter.lad", 8, 8, 'RING_UP',   'R', 57),
    ("B_counter.lad", 9, 9, 'RING_DOWN', 'R', 58),
]

# (文件, 行号, 元件, 说明)
# (文件, 定位用前缀(该记录开头应是这些字节), 元件)
# 说明: cnc_1.lad 的 1339/1352 是"编辑器行号"(含注释行), 与裸记录下标不同,
#       所以这里按记录开头字节定位, 不按行号。
# (文件, 定位字节, 'start'=记录开头 / 'any'=记录内任意位置, 元件)
FLOWS = [
    ("B_flow.lad",  b"\x00\xcb", "any",   {"kind": "jsr", "label": "HI"}),
    ("cnc_1.lad",   b"\x00\xd5\x30\x30\x31", "start", {"kind": "lab", "label": "001"}),
    ("cnc_1.lad",   b"\x00\xd0\x00\x00\x00\x0d", "start", {"kind": "rts"}),
]


def records(path):
    d = open(path, "rb").read()
    body = d[:-2]
    return [body[i:i + 40] for i in range(0, len(body), 40)]


def gen_row(elements):
    return L.emit_row(L.place_rung([M.to_enc(e) for e in elements]))


def diff_marks(a, b):
    return " ".join(f"{x:02x}" if x == y else f"[{x:02x}/{y:02x}]"
                    for x, y in zip(a, b))


# 真机程序(客户机床上直接导出的 .lad)不随仓库分发: 里面是具体的刀库/CNC 逻辑。
# 缺失时记 SKIP 而不是 FAIL —— 但只在"可选语料"这一个白名单内, 其余缺了照样算失败。
OPTIONAL = ("cnc.lad", "cnc_1.lad")
SKIPPED = [0]


def is_optional(fn):
    return os.path.basename(fn).lower() in OPTIONAL


def fetch(path):
    """读样本; 缺失返回 None。可选语料 -> SKIP, 其余 -> 调用方记失败"""
    if not os.path.isfile(path):
        if is_optional(path):
            print(f"  - SKIP(未附带真机语料) {os.path.basename(path)}")
            SKIPPED[0] += 1
        else:
            print(f"  ! 缺少样本 {os.path.basename(path)}  ({os.path.dirname(path)})")
        return None
    return records(path)


def section(title, cases, build, tagfn, off, note):
    print(f"\n=== {title} ===")
    print(f"  {note}")
    print(f"  {'行':<6}{'用例':<26}{'编辑器字节':<16}{'本项目生成':<16}结果")
    good = total = 0
    for (fn, row, *args) in cases:
        recs = fetch(os.path.join(DESK, fn))
        if recs is None:
            if not is_optional(fn):
                total += 1              # 非可选样本缺失 -> 算失败
            continue
        if row > len(recs):
            print(f"  ! {fn} 只有 {len(recs)} 条记录, 取不到第 {row} 行")
            total += 1
            continue
        want = recs[row - 1]
        got = build(*args)
        ok = want == got
        total += 1
        good += ok
        blk_w, blk_g = want[off:off + 4], got[off:off + 4]
        print(f"  {fn.split('.')[0]} R{row:<4}{tagfn(*args):<26}"
              f"op={want[off+1]:02x} {blk_w.hex():<10}op={got[off+1]:02x} {blk_g.hex():<10}"
              f"{'一致' if ok else '不一致'}")
        if not ok:
            print("     差异: " + diff_marks(want, got))
    print(f"  -> {good}/{total} 条逐字节一致")
    return good, total


def main():
    print(f"样本目录: {DESK}")
    print("复验方法: 用编辑器手工产出的样本当标准答案, 本项目编码器重新生成同一行, 逐字节比对")
    print("          op = 该功能块的 opcode, 后 4 字节 = 参数块")

    t = section(
        "定时器 4 精度 × 2 源 (K 常数 / R 寄存器)", TIMERS,
        lambda idx, prec, src, val: gen_row([
            {"kind": "contact", "norm": "NO", "addr": "I100"},
            {"kind": "timer", "name": f"TM{idx}", "precision": prec,
             "source": src, "preset": val}]),
        lambda idx, prec, src, val: f"TM{idx} {prec} {src}{val}",
        32, "定时器单元在 col8(偏移 32), 前面的触点/连接线一并比对")

    c = section(
        "计数器 5 方向 × 2 源", COUNTERS,
        lambda idx, d, src, val: gen_row([
            {"kind": "contact", "norm": "NO", "addr": "I100"},
            {"kind": "counter", "name": f"CT{idx}", "direction": d,
             "source": src, "preset": val}]),
        lambda idx, d, src, val: f"CT{idx} {d} {src}{val}",
        32, "计数器单元在 col8(偏移 32)")

    print("\n=== 流程控制块 ===")
    print("  整行 40 字节全部比对(含列位置); 标准答案按记录开头字节定位")
    print(f"  {'样本':<14}{'用例':<22}{'编辑器字节':<26}{'本项目生成':<26}结果")
    fg = ft = 0
    for (fn, prefix, mode, el) in FLOWS:
        recs = fetch(os.path.join(DESK, fn))
        if recs is None:
            if not is_optional(fn):
                ft += 1                 # 非可选样本缺失 -> 算失败
            continue
        pick = (lambda r: r.startswith(prefix)) if mode == "start" else (lambda r: prefix in r)
        want = next((r for r in recs if pick(r)), None)
        if want is None:
            print(f"  ! {fn} 中找不到含 {prefix.hex()} 的记录")
            continue
        got = gen_row([el])
        ok = want == got
        ft += 1
        fg += ok
        tag = el["kind"].upper() + ' "' + el.get("label", "") + '"'
        print(f"  {fn:<14}{tag:<22}{want[:8].hex():<26}{got[:8].hex():<26}"
              f"{'一致' if ok else '不一致'}")
        if not ok:
            print("     差异: " + diff_marks(want, got))
    print(f"  -> {fg}/{ft} 条逐字节一致")
    f = (fg, ft)

    good = sum(x[0] for x in (t, c, f))
    total = sum(x[1] for x in (t, c, f))
    ok = bool(total) and good == total
    print(f"\n合计 {good}/{total} 逐字节一致" + ("   [PASS]" if ok else "   [FAIL]")
          + (f"   (另有 {SKIPPED[0]} 项因未附带真机语料而跳过)" if SKIPPED[0] else ""))
    return 0 if ok else 1


if __name__ == "__main__":
    parse_argv(sys.argv[1:])
    sys.exit(main())
