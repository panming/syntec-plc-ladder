#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""回归：2026-11-02 审 cnc.lad(80KB 版) 时查出的 6 个工具缺陷。

1. render_line 把 8 字符标签砍成 7 字符（=R590.14 显示成 =R590.1）
2. AXIAL 里 R7{i} / R9{i} 没补零，lookup('R73') 谎报成「轴3速度」
3. 悬空触点检查把参数区只读位 R100.2 误报成「没人驱动」
4. 所有 warn 一律写成「手册标保留」
5. R40~R49 警报输出位没线圈时被当成普通悬空触点报「警告」
6. 把串联定时器/运算块说成「不阻断、后面每个扫描都执行」(语义反了)

用法: python tools/verify_review_fixes.py
"""
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "src"))
sys.path.insert(0, _HERE)

import syntec_address_db as DB        # noqa: E402
import syntec_layout as Y            # noqa: E402
import syntec_model as M             # noqa: E402
import syntec_read as R              # noqa: E402
import review_ladder as RV           # noqa: E402

CHECKS = []


def chk(name, cond, detail=""):
    CHECKS.append((name, bool(cond), detail))


def main():
    # ---- 1 标签不再被截断 ----
    # '=R590.14' 是 8 字符；旧版 W=8 时单格只能写 7 个，末位被砍掉成
    # '=R590.1'，和真正的 R590.1 撞名。R590.10~R590.14 全都长一样。
    grid = [None] * Y.COLS
    grid[0] = (0, ("COIL", "NO", M.addr_bits("R590.14")))
    line = Y.render_line(grid)
    chk("8 字符线圈标签完整", "=R590.14" in line, line.strip())
    chk("列宽自适应到 9", Y.needed_width(grid) == 9, str(Y.needed_width(grid)))
    # 短标签的行不必加宽，保持原来的对齐
    short = [None] * Y.COLS
    short[0] = (0, ("COIL", "NO", M.addr_bits("R590.1")))
    chk("短标签仍是 8", Y.needed_width(short) == 8, str(Y.needed_width(short)))
    # 两行共用一个 W 时竖线位置要一致
    line2 = Y.render_line(grid, W=Y.needed_width(grid))
    chk("显式传 W 与自适应一致", line == line2)
    # 整份图渲染不炸（demo.lad 在仓库里）
    demo = os.path.join(_HERE, "..", "demo.lad")
    if os.path.isfile(demo):
        txt = R.render_file(os.path.abspath(demo))
        chk("render_file 冒烟", "--- R1" in txt, txt[:80])

    # ---- 2 轴向表地址补零 ----
    chk("R701 = 轴1速度", any("各轴单轴速度" in x for x in DB.lookup("R701")))
    chk("R716 = 轴16速度", any("各轴单轴速度" in x and "轴16" in x for x in DB.lookup("R716")))
    chk("R901 = 轴1温度补偿", any("各轴温度补偿量" in x for x in DB.lookup("R901")))
    chk("R916 = 轴16温度补偿", any("各轴温度补偿量" in x for x in DB.lookup("R916")))
    chk("R73 不再挂轴向含义", not any("速度" in x or "温度" in x for x in DB.lookup("R73")),
        str(DB.lookup("R73")))
    chk("R76 不再挂轴向含义", not any("速度" in x or "温度" in x for x in DB.lookup("R76")),
        str(DB.lookup("R76")))
    # 其它轴向表没被误伤
    chk("R721 仍是程序坐标", any("程序座标" in x for x in DB.lookup("R721")))
    chk("R741 仍是机械坐标", any("机械座标" in x for x in DB.lookup("R741")))
    # JSON 与运行时同源
    jf = os.path.join(_HERE, "..", "src", "syntec_address_db.json")
    if os.path.isfile(jf):
        j = json.load(open(jf, encoding="utf-8"))
        ri = j["reverse_index"]
        chk("JSON 反查表含 R701", any("各轴单轴速度" in x for x in ri.get("R701", [])))
        chk("JSON 反查表不含 R73 速度", not any("速度" in x for x in ri.get("R73", [])))

    # ---- 3 外部维护的只读位不算悬空 ----
    chk("R100.2 是外部维护", RV.externally_driven("R100.2"))
    chk("R701 是外部维护", RV.externally_driven("R701"))
    chk("R33 是外部维护", RV.externally_driven("R33"))
    chk("I5 是外部维护", RV.externally_driven("I5"))
    chk("S0 是外部维护", RV.externally_driven("S0"))
    chk("R43.0 不是外部维护", not RV.externally_driven("R43.0"))
    chk("R44.5 不是外部维护", not RV.externally_driven("R44.5"))
    chk("A300 不是外部维护", not RV.externally_driven("A300"))

    # ---- 4 warn 分类 ----
    w_relay = DB.check_write("R76.1")
    chk("R76.1 判为 relay", w_relay and RV.warn_kind(w_relay[1]) == "relay", str(w_relay))
    chk("保留措辞归 reserved", RV.warn_kind("手册把 R926 标为保留（Reserved）") == "reserved")
    chk("未知编号归 unknown", RV.warn_kind("这个编号地址库里没有") == "unknown")
    chk("输入点归 input", RV.warn_kind("I 是物理输入点，写它不会改变现场信号") == "input")

    # ---- 5 警报输出位不与普通悬空触点混为一谈 ----
    # 手册 1-5：R40~R49 是 PLC 输出位，没有线圈可能只是该警报未启用。
    # 2026-11-02 现场确认 R43.0 / R44.5 属此情形, 不影响程序正确性。
    chk("R43.0 是警报位", RV.is_alarm_bit("R43.0"))
    chk("R44.5 是警报位", RV.is_alarm_bit("R44.5"))
    chk("R44.14 是警报位", RV.is_alarm_bit("R44.14"))
    chk("R50.0 不是警报位", not RV.is_alarm_bit("R50.0"))
    chk("R590.1 不是警报位", not RV.is_alarm_bit("R590.1"))
    rv_src = open(os.path.join(_HERE, "review_ladder.py"), encoding="utf-8").read()
    chk("警报位单独成节且只报提示",
        "alarm_unused" in rv_src and 'rep.add("提示", f"{len(alarm_unused)}' in rv_src)
    chk("不再宣称串联功能块不阻断",
        "不会阻断" not in rv_src and "每个扫描都执行" not in rv_src)

    bad = [c for c in CHECKS if not c[1]]
    for name, ok, detail in CHECKS:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if not ok else ""))
    print()
    if bad:
        print(f"[FAIL] {len(bad)}/{len(CHECKS)} 项未通过")
        return 1
    print(f"[PASS] {len(CHECKS)}/{len(CHECKS)} 项通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
