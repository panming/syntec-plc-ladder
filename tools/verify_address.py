#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""地址权限回归：防止把 S 段当中间继电器这条错路再溜回来。

查六件事：
  1. R_ZONES 是否无缝覆盖 0~65535、有没有重叠
  2. check_write 的判定是否符合手册（写 S 拒绝、写只读 R 拒绝、无位存取区拒绝，
     A 段可写且卡在 0~511，参数区 R81~R100 只读）
  3. validate 是否真的会拦下「写 S 段 / 写 R 位当标志」
  4. 真机语料里 S/I 段作为线圈出现了几次（应当为 0），A 段用了多少个
  5. 元件类型表是否覆盖 8 类元件
  6. 参数区 R81~R100：映射 3401~3420、只读、定时器预设可以直接指过去

    python tools/verify_address.py [--samples DIR]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)

import syntec_address_db as ADB          # noqa: E402
import syntec_model as M                 # noqa: E402


def parse_argv(argv):
    d = os.path.join(ROOT, "samples")
    if "--samples" in argv:
        d = argv[argv.index("--samples") + 1]
    elif len(argv) > 1 and not argv[1].startswith("-"):
        d = argv[1]
    elif os.environ.get("SYNTEC_SAMPLES"):
        d = os.environ["SYNTEC_SAMPLES"]
    return d


def chk(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))
    return ok


def main():
    ok_all = True
    print("=" * 66)
    print(" 1. R 区权限表完整性")
    print("-" * 66)
    zones = sorted(ADB.R_ZONES)
    ok_all &= chk("区段数 > 0", len(zones) > 0, f"{len(zones)} 段")
    ok_all &= chk("从 R0 开始", zones[0][0] == 0, f"首段 R{zones[0][0]}")
    gaps = []
    for a, b in zip(zones, zones[1:]):
        if b[0] != a[1] + 1:
            gaps.append((a[1], b[0]))
    ok_all &= chk("区段无空洞/无重叠", not gaps, str(gaps) if gaps else "连贯")

    print()
    print("=" * 66)
    print(" 2. check_write 判定")
    print("-" * 66)
    cases = [
        # (地址, 期望等级)
        ("S0", "error"),          # CNC->PLC 只读
        ("S32", "error"),
        ("I0", "warn"),           # 物理输入, 写无意义
        ("O0", None),
        ("A0", None),             # 虚拟辅助接点: 内部标志的正经落点
        ("A511", None),           # 段尾
        ("A512", "error"),        # 9 位编号上限
        ("C36", None),            # 已知系统命令, 允许写
        ("R50.0", "warn"),        # 能写, 但 R 是数据寄存器 -> 提示改用 A
        ("R50", None),            # 整字写是 R 的正经用途
        ("R210.1", "warn"),       # 用户区(保持); 取位能写, 但应改用 A 段
        ("R30", "error"),         # CNC 接口区只读
        ("R600.1", None),         # 手册标的 C 方向接口位(区段表判只读, 知识库纠正)
        ("R610.1", "error"),      # 手册标的 S 方向接口位, 只读
        ("R1200.0", "error"),     # 用户区但位存取=否
        ("R8000.0", "error"),     # CNC 接口区, 只读
        ("R44.5", None),          # PLC 警报讯息区, 可写
        ("R80", None),            # 用户区末尾: 可读写, 但不保持
        ("R81", "error"),         # 参数传入区: 阶梯只读
        ("R81.0", "error"),       # 参数区取位写也不行
        ("R100", "error"),        # 参数区末位 -> 3420
        ("R101", None),           # 刀具状态, 可写
        # R256~R511 曾被误判成"保留区": 手册里它与 R103~R255 是合并格(rowspan),
        # 说明/阶梯/位存取都继承下来 = 可读可写可位, 只有永久保存是"否"。
        ("R256", None),           # 合并段起点
        ("R300", None),           # 模拟量转存这类数值的正经落点
        ("R511", None),           # 合并段末尾
        ("R300.0", "warn"),       # 可位存取, 但那是数据寄存器 -> 提示用 A
        # R512~R1023 按 1-1.4.4 逐条判, 不再整片只读。四条代表四种结论:
        ("R639", "warn"),         # 手册明写 Reserved for CNC -> 提示不阻断
                                  #   (保留区被厂商占用已有先例, 判 error 会误伤)
        ("R640", None),           # 手册未列明 -> 不判定, 既不报错也不放行
        ("R590.2", None),         # PLC 提示讯息, 阶梯可写
        ("R603", None),           # 禁止指定轴移动, 阶梯可写
        ("R700", "error"),        # 合成进给速度实际值, 核心回报 -> 只读
        ("R700.0", "error"),      # R640 以上位存取=否
        ("R961", "error"),        # Home Dog Shift: 手册没写谁写, 按保守假设只读
        ("R1023", None),          # PLC File System, 阶梯唯写
    ]
    for addr, want in cases:
        got, msg = ADB.check_write(addr)
        ok_all &= chk(f"{addr:9s} -> {str(got):5s}", got == want,
                      (msg or "")[:48])

    print()
    print("=" * 66)
    print(" 3. validate 是否拦下写 S 段")
    print("-" * 66)
    p = M.LadderProject()
    p.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I0"},
                         {"kind": "coil", "norm": "LATCH", "addr": "S0"}])
    p.add_rung(elements=[{"kind": "end"}])
    warns = [w for w in p.validate() if "S 段" in w]
    ok_all &= chk("写 S0 会被 validate 报出", bool(warns), warns[0][:56] if warns else "")

    p2 = M.LadderProject()
    p2.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I0"},
                          {"kind": "coil", "norm": "LATCH", "addr": "R50.0"}])
    p2.add_rung(elements=[{"kind": "end"}])
    got = [w for w in p2.validate() if "R50" in w]
    ok_all &= chk("写 R50.0 不报错, 但提示改用 A 段",
                  len(got) == 1 and "A 段" in got[0], got[0][:60] if got else "无提示")

    p3 = M.LadderProject()
    p3.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "I0"},
                          {"kind": "coil", "norm": "LATCH", "addr": "A0"}])
    p3.add_rung(elements=[{"kind": "end"}])
    clean = [w for w in p3.validate() if "A0" in w or "A 段" in w]
    ok_all &= chk("写 A0 完全不下警告", not clean, str(clean) if clean else "")

    print()
    print("=" * 66)
    print(" 4. 真机语料：S / I 从不作线圈，A 才是内部标志")
    print("-" * 66)
    samples = parse_argv(sys.argv)
    # 显式指定目录（--samples / 位置参数 / 环境变量）时只认它，
    # 不再偷偷拿桌面上的真机程序 —— 否则「换台机器跑同一份回归」结果不一样。
    explicit = ("--samples" in sys.argv or os.environ.get("SYNTEC_SAMPLES")
                or (len(sys.argv) > 1 and not sys.argv[1].startswith("-")))
    files = [os.path.join(samples, f) for f in sorted(os.listdir(samples))
             if f.endswith(".lad")] if os.path.isdir(samples) else []
    real = [] if explicit else [
        p for p in (os.path.join(os.path.expanduser("~"), "Desktop", "cnc.lad"),
                    os.path.join(os.path.expanduser("~"), "Desktop", "cnc_1.lad"))
        if os.path.isfile(p)]
    files = real or files
    if not files:
        print("  [SKIP] 没有可用的 .lad 语料")
    import re
    a_seen = set()
    for f in files:
        import syntec_read as R
        info = R.read_ladder(f)
        cnt = {}
        def walk(els):
            for e in (els or []):
                if e.get("kind") == "parallel":
                    for b in (e.get("branches") or []):
                        walk(b)
                a = e.get("addr")
                if e.get("kind") == "coil" and a:
                    k = re.match(r"[A-Z]+", str(a)).group()
                    cnt[k] = cnt.get(k, 0) + 1
                if a and re.match(r"^A\d+$", str(a)):
                    a_seen.add(int(str(a)[1:]))
        for r in info["rungs"]:
            walk(r["elements"])
        ok_all &= chk(os.path.basename(f), not cnt.get("S") and not cnt.get("I"),
                      "线圈分布 " + ", ".join(f"{k}:{v}" for k, v in sorted(cnt.items())))
    if a_seen:
        mx, n = max(a_seen), len(a_seen)
        ok_all &= chk("A 段落在 0~511 内", mx <= ADB.A_POINTS - 1,
                      f"用了 {n} 个不同编号, 最大 A{mx}")

    print()
    print("=" * 66)
    print(" 5. 元件类型表 (手册 2.1)")
    print("-" * 66)
    ok_all &= chk("覆盖 8 类元件", set(ADB.DEVICE_TYPES) ==
                  {"I", "O", "A", "C", "S", "R", "CT", "TM"},
                  "/".join(sorted(ADB.DEVICE_TYPES)))
    ok_all &= chk("A 定义为虚拟辅助接点", "辅助" in ADB.device_type("A")[0],
                  ADB.device_type("A")[0] + " " + ADB.device_type("A")[2])
    ok_all &= chk("S 定义为核心->阶梯图", "核心" in ADB.device_type("S")[0],
                  ADB.device_type("S")[0])
    ok_all &= chk("R 定义为双向沟通", "双向" in ADB.device_type("R")[0],
                  ADB.device_type("R")[2])

    print()
    print("=" * 66)
    print(" 6. 参数区 R81~R100（对应系统参数 3401~3420）")
    print("-" * 66)
    ok_all &= chk("区间常量", (ADB.PARAM_LO, ADB.PARAM_HI) == (81, 100),
                  f"R{ADB.PARAM_LO}~R{ADB.PARAM_HI} = 参数 {ADB.PARAM_BASE}~"
                  f"{ADB.PARAM_BASE + ADB.PARAM_POINTS - 1}")
    ok_all &= chk("映射线性（R81->3401, R100->3420）",
                  ADB.PARAM_BASE + 81 - ADB.PARAM_LO == 3401 and
                  ADB.PARAM_BASE + 100 - ADB.PARAM_LO == 3420)
    for addr, want in (("R81", "3401"), ("R100", "3420")):
        _lvl, msg = ADB.check_write(addr)
        ok_all &= chk(f"写 {addr} 提示对应参数号", want in (msg or ""), (msg or "")[:56])

    res, _p = M.lookup_address("R81")
    ok_all &= chk("lookup R81 返回参数区说明",
                  bool(res) and "3401" in res[0][1][0] and "只读" in res[0][1][0],
                  res[0][1][0][:56] if res else "无结果")

    # 定时器预设直接指参数区: 合法, 不该报警
    p4 = M.LadderProject()
    p4.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "A1"},
                         {"kind": "timer", "name": "TM0", "precision": "0.1s",
                          "source": "R", "preset": "R81"}])
    p4.add_rung(elements=[{"kind": "end"}])
    w4 = [w for w in p4.validate() if "R81" in w or "预设" in w]
    ok_all &= chk("定时器 source=R preset='R81' 不报警", not w4,
                  w4[0][:56] if w4 else "")

    # 预设指向不存在的寄存器: 要报出来
    p5 = M.LadderProject()
    p5.add_rung(elements=[{"kind": "contact", "norm": "NO", "addr": "A1"},
                          {"kind": "timer", "name": "TM0", "precision": "0.1s",
                           "source": "R", "preset": "R99999"}])
    p5.add_rung(elements=[{"kind": "end"}])
    w5 = [w for w in p5.validate() if "99999" in w or "分配表" in w]
    ok_all &= chk("预设指向不存在的 R99999 会报出", bool(w5),
                  w5[0][:56] if w5 else "无提示")

    print()
    print("=" * 66)
    print(" 7. 同址驱动：双线圈 / 重复元件")
    print("-" * 66)

    def _coil(a, n="NO"):
        return {"kind": "coil", "norm": n, "addr": a}

    def _contact(a, n="NO"):
        return {"kind": "contact", "norm": n, "addr": a}

    def _build(spec):
        """spec: [(触点地址, 线圈地址, 线圈类型), ...]"""
        p = M.LadderProject()
        for cond, co, norm in spec:
            p.add_rung(elements=[_contact(cond), _coil(co, norm)])
        p.add_rung(elements=[{"kind": "end"}])
        return [w for w in p.validate() if "重复" in w or "双线圈" in w or "既当" in w]

    # 实测踩过的坑: 一个地址 1 个置位 + 2 个复位, 编辑器弹「重复元件」。
    w = _build([("I0", "A1", "LATCH"), ("I1", "A1", "UNLATCH"), ("I2", "A1", "UNLATCH")])
    ok_all &= chk("1 置位 + 2 复位 -> 报重复元件",
                  any("重复元件" in x for x in w), w[0][:60] if w else "没报出来")

    # 一置一复是标准锁存用法, 不能误报。
    w = _build([("I0", "A0", "LATCH"), ("I1", "A0", "UNLATCH")])
    ok_all &= chk("1 置位 + 1 复位 -> 不报", not w, w[0][:60] if w else "")

    # 两个置位同样是重复。
    w = _build([("I0", "A2", "LATCH"), ("I1", "A2", "LATCH")])
    ok_all &= chk("2 个置位 -> 报重复元件",
                  any("重复元件" in x for x in w), w[0][:60] if w else "没报出来")

    # 普通输出线圈只能有一个: 后面的会盖掉前面的。
    w = _build([("I0", "O3", "NO"), ("I1", "O3", "NO")])
    ok_all &= chk("2 个输出线圈 -> 报双线圈",
                  any("双线圈" in x for x in w), w[0][:60] if w else "没报出来")

    # 输出线圈每扫描重写, 会把置位/复位的锁存值冲掉。
    w = _build([("I0", "A3", "NO"), ("I1", "A3", "LATCH")])
    ok_all &= chk("输出线圈 + 置位混用 -> 报出",
                  any("既当" in x for x in w), w[0][:60] if w else "没报出来")

    print()
    print("=" * 66)
    print(("全部通过 [PASS]" if ok_all else "有失败项 [FAIL]"))
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
