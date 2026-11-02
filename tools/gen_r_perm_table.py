# -*- coding: utf-8 -*-
"""生成 R512~R1023 逐条权限表（手册 1-1.4.4 + 1-1.4.3 对账）。

背景：资源分配表(1-1.4.3) 对这一段的写法是「阶梯程序：依下表定义之」，
      不是只读。真正的权限在 1-1.4.4「接口说明」里逐条定义。
      把 R512~R1023 整片判成只读，会让 R590.2（PLC提示讯息）、R603（禁止轴移动）
      这类正常写法被工具报成错误。

数据来源（不手抄）：
    python tools/chm_r_interface.py --dir <解包目录> --out r_iface.json
    python tools/gen_r_perm_table.py --iface r_iface.json --lad cnc.lad --out docs/r512-r1023.md

手册没写「PLC读写规则」的条目（本段 40 条）由 INFER 表逐条补，标注来源为
「推断」，供人工复核 —— 不混进「手册」档。
"""
import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

# ---------------------------------------------------------------------------
# 手册未写权限的条目：按「功能说明」推断。
# (阶梯权限, 依据)。阶梯权限取值: 只读 / 唯写 / 读写 / 保留
# ---------------------------------------------------------------------------
INFER = {
    "R514": ("只读", "人机每 3 秒循环更新现值警报数据，阶梯只取"),
    "R515": ("只读", "同上，人机写入"),
    "R516": ("只读", "同上，人机写入"),
    "R517": ("只读", "同上，人机写入"),
    "R518": ("唯写", "决定手动命令参考哪个坐标系，由阶梯设定"),
    "R519": ("保留", "系统保留区"),
    "R560~R579": ("保留", "系统保留区"),
    "R580": ("唯写", "主轴 PLC 控制模式，阶梯置位选定"),
    "R588": ("只读", "刚攻模式「正在」状态，由核心回报"),
    "R589": ("只读", "提供当前 M/S/T 由哪个轴群发出，属回报讯息"),
    "R590~R599": ("唯写", "PLC 提示讯息区，阶梯逐位点亮"),
    "R601": ("唯写", "PLC 轴手轮模拟旗标，阶梯设定"),
    "R602": ("唯写", "各主轴 Y-Delta 要求，阶梯发要求"),
    "R603": ("唯写", "禁止指定轴移动，阶梯发命令"),
    "R604": ("唯写", "教导画面点输入命令区，阶梯触发"),
    "R605": ("唯写", "刀具长度量测写入命令，阶梯触发"),
    "R608": ("读写", "Modbus 通讯握手：R608.0 由阶梯触发，.1/.2/.3/.10 只读状态"),
    "R609": ("只读", "轴耦合状态回报"),
    "R611": ("只读", "各轴运动状态显示"),
    "R612": ("唯写", "机械正向锁定命令"),
    "R613": ("唯写", "机械负向锁定命令"),
    "R614": ("唯写", "轴耦合状态开关，由阶梯决定"),
    "R615~R618": ("读写", "M/S/T 执行通道：控制位阶梯写、完成位核心回报"),
    "R619~R622": ("读写", "同上"),
    "R623~R626": ("读写", "同上"),
    "R631~R639": ("保留", "系统保留区"),
    "R700": ("只读", "合成进给速度实际值"),
    "R831~R840": ("只读", "MLC 参数 3451~3460，参数画面设定、阶梯只读"),
    "R841~R844": ("只读", "轴群程序停止原因回报"),
    "R845~R850": ("保留", "保留"),
    "R851~R856": ("唯写", "个别主轴转速百分比，由阶梯设定"),
    "R861~R870": ("只读", "加工暂停点机械坐标回报"),
    "R926": ("保留", "保留"),
    # R961~R976 手册只有一句「原点极限开关偏移量，单位 0.01 圈/0.01mm」,
    # 没写谁写。原本按「偏移量必由阶梯设定」推成唯写, 属猜, 改标待确认。
    "R1004": ("只读", "总工件数，核心维护"),
    "R1009": ("只读", "开机时间(毫秒)，核心维护"),
}

# 手册原文里「唯写」和「读写」两种写法都出现过, 统一成四档
NORM = {"只读": "只读", "唯写": "唯写", "读写": "读写", "读/写": "读写", "": ""}

# 手册里名称列留空的行（靠前一条的说明补全, 不自己编名字）
NAME_FIX = {
    "R630": "Axis M code complete（见 R629）",
    "R1020~1023": "PLC File System",
    # 这两条手册都叫「开机时间」, 区别只在单位, 不写进名称会像上一轮 R1014 那样被当成重复项
    "R1009": "Power-on time (ms，71 分钟回绕)",
    "R1012": "Power-on time (s)",
}


def _axis_groups():
    """R520~R559 四个轴群命令缓存器。

    手册在这一条里把内部布局逐个写清楚了:R520 命令 / R521 状态 / R522 主程序号 /
    R523 切削% / R524 快动% / R525 目标刀号 / R526 单节剩余距离 / R527~529 保留。
    整段判「读写」会把「写状态寄存器」也放过去 —— 状态是核心写的, 阶梯只能读。
    """
    out = {}
    layout = [(0, 0, "命令缓存器", "唯写"),
              (1, 1, "状态缓存器", "只读"),
              (2, 2, "主程序号码(0~999999)", "唯写"),
              (3, 3, "切削进给百分比", "唯写"),
              (4, 4, "快动进给百分比", "唯写"),
              (5, 5, "目标刀号", "唯写"),
              (6, 6, "执行中单节剩余距离", "只读"),
              (7, 9, "保留扩充用", "保留")]
    for gi in range(4):
        base = 520 + gi * 10
        out[f"R{base}~R{base + 9}"] = [
            (base + d0, base + d1, f"AX{gi + 1} {nm}", pm) for d0, d1, nm, pm in layout
        ]
    return out


SUB_SPLIT = _axis_groups()

# 区段内掉电保持: 1-1.4.3 给的是「否」, 但 1-1.4.4 里明确写「关机保留」的按条目走
KEEP_HINT = ("关机保留", "永久保存")


def addr_span(lo, hi):
    return f"R{lo}" if lo == hi else f"R{lo}~R{hi}"


def load_iface(path):
    with open(path, encoding="utf-8") as f:
        rows = json.load(f)
    out = []
    for x in rows:
        if x["hi"] < 512 or x["lo"] > 1023:
            continue
        lo, hi = max(x["lo"], 512), min(x["hi"], 1023)
        out.append(dict(x, lo=lo, hi=hi))
    out.sort(key=lambda x: (x["lo"], x["hi"]))
    return out


def lad_used(path):
    """扫一份 .lad, 返回它真正碰过的 R 地址集合 (512~1023)"""
    import syntec_read as RD
    used = set()

    def walk(els):
        for e in els or []:
            if e["kind"] == "parallel":
                for b in e["branches"]:
                    walk(b)
                continue
            for key in ("addr", "A", "B"):
                v = e.get(key)
                if not v:
                    continue
                m = re.match(r"^R(\d+)(?:\.(\d+))?$", v)
                if m and 512 <= int(m.group(1)) <= 1023:
                    used.add(int(m.group(1)))

    for r in RD.read_ladder(path)["rungs"]:
        walk(r["elements"])
    return used


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--iface", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--lad", action="append", default=[],
                    help="附上实际用到该地址的样本程序(可多次)")
    a = ap.parse_args(argv)

    rows = load_iface(a.iface)
    used = set()
    for p in a.lad:
        used |= lad_used(p)

    # 覆盖检查: 512~1023 里手册没列到的
    cov = [0] * 1024
    for x in rows:
        for i in range(x["lo"], x["hi"] + 1):
            cov[i] += 1
    missing = [i for i in range(512, 1024) if cov[i] == 0]

    # 表体
    lines = []
    stat = {"手册": 0, "推断": 0, "未列明": 0}
    writable = []
    perm_of = {}          # 地址 -> (权限, 依据), 供第五节/第六节复用, 避免两处各推一遍
    for x in rows:
        tag = x["addr"].replace(" ", "")
        # 手册只给整段说明、内部却是「命令区 + 状态区」混排的, 按明细拆行
        subs = SUB_SPLIT.get(tag)
        if subs:
            stat["推断"] += 1
            for lo, hi, sname, sperm in subs:
                disp = addr_span(lo, hi)
                hit = "✓" if any(lo <= u <= hi for u in used) else ""
                note = ("按手册明细拆分（%s）；权限依用途推定：状态与剩余距离由核心写、"
                        "命令类由阶梯写" % x["name"][:28] if sperm != "保留"
                        else "手册原文标「保留扩充用」")
                lines.append(f"| `{disp}` | {sname} | {sperm} | 是 | 否 | {hit} | 推断 | {note} |")
                for i in range(lo, hi + 1):
                    perm_of[i] = (sperm, "推断")
                if sperm in ("唯写", "读写"):
                    writable.append((disp, sname, sperm))
            continue
        perm = NORM.get(x["perm"].strip(), "")
        why = ""
        if perm:
            src = "手册"
        else:
            got = INFER.get(tag)
            perm, why = (got if got else ("待确认", ""))
            src = "推断" if got else "待确认"
        stat[src] = stat.get(src, 0) + 1
        bits = "是" if x["lo"] <= 639 else "否"
        keep = "是" if any(k in x["desc"] for k in KEEP_HINT) else "否"
        hit = "✓" if any(x["lo"] <= u <= x["hi"] for u in used) else ""
        disp = addr_span(x["lo"], x["hi"])
        name = NAME_FIX.get(tag) or x["name"][:44]
        note = (why if src == "推断" else x["desc"].split("。")[0][:60]).replace("|", "／")
        lines.append(f"| `{disp}` | {name} | {perm} | {bits} | {keep} | {hit} | {src} | {note} |")
        for i in range(x["lo"], x["hi"] + 1):
            perm_of[i] = (perm, src)
        if perm in ("唯写", "读写"):
            writable.append((disp, name, perm))

    md = []
    md.append("# R512~R1023 权限表\n")
    md.append("> 来源：`CNC and PLC Interface` 1-1.4.4「接口说明」逐条 + 1-1.4.3 资源分配表区段属性。")
    md.append("> 生成：`tools/chm_r_interface.py` → `tools/gen_r_perm_table.py`，不手抄。\n")
    md.append("## 一、区段性质（1-1.4.3 原文）\n")
    md.append("| 区段 | 宏程序/人机 | 阶梯程序 | 位存取 | 掉电保持 |")
    md.append("|---|---|---|---|---|")
    md.append("| `R512~R639` | 只读 | **依下表定义之** | 是 | 否 |")
    md.append("| `R640~R1023` | 只读 | **依下表定义之** | 否 | 否 |\n")
    md.append("两点结论：\n")
    md.append("1. 「依下表定义之」= 权限不在这张表里，要翻 1-1.4.4 逐条看。整片判只读是错的。")
    md.append("2. `R640` 以上**不能按位寻址**（`R700.0` 非法），512~639 可以（`R590.2` 合法）。\n")
    md.append(f"## 二、逐条（手册 {len(rows)} 条）\n")
    md.append(f"手册明写权限 {stat.get('手册',0)} 条，手册留空另行推断 {stat.get('推断',0)} 条，"
              f"待确认 {stat.get('待确认',0)} 条。")
    if len(lines) != len(rows):
        md.append(f"其中 `R520~R559` 四个轴群缓存器按手册明细拆成 "
                  f"{len(lines) - len(rows) + 4} 行，故下表共 {len(lines)} 行。")
    md.append("")
    md.append("| 地址 | 名称 | 阶梯程序 | 位存取 | 保持 | 样本用到 | 依据 | 说明 |")
    md.append("|---|---|---|---|---|---|---|---|")
    md.extend(lines)
    md.append("")
    md.append("> 「样本用到」= 在附带的 `.lad` 里出现过该地址，可作为「这个权限确实在用」的旁证。")
    md.append("> 「保持」= 1-1.4.4 说明里写了「关机保留」的条目，其余按 1-1.4.3 的区段值（否）。\n")

    md.append("## 三、阶梯可写清单（含唯写）\n")
    md.append("| 地址 | 名称 | 权限 |")
    md.append("|---|---|---|")
    for ad, nm, pm in writable:
        md.append(f"| `{ad}` | {nm} | {pm} |")
    md.append("")

    md.append("## 四、手册未列明的地址（视为保留）\n")
    md.append(f"共 {len(missing)} 个：")
    # 压缩成区间
    runs, start = [], None
    for i in missing:
        if start is None:
            start = prev = i
        elif i == prev + 1:
            prev = i
        else:
            runs.append((start, prev))
            start = prev = i
    if start is not None:
        runs.append((start, prev))
    md.append("、".join(addr_span(s, e) for s, e in runs) + "\n")

    live = [i for i in missing if i in used]
    if live:
        md.append(f"**注意：其中 {len(live)} 个在样本程序里被用到，手册却没有定义** —— "
                  f"{'、'.join('R%d' % i for i in live)}。")
        md.append("要么手册版本比 CNC 版本旧，要么是厂商自定义后占用了保留区。"
                  "工具对这几个地址不做权限判定，也不要当成保留区报错。\n")

    md.append("## 五、需要你确认的地方\n")
    md.append("判「只读」推错了会误报，程序一跑就露馅；判「可写」推错了是**静默放行**——"
              "写进只读区不报错、只是不生效。所以这里按风险排：先列判不了的，"
              "再列所有推断成可写的。推断成只读的不列，它们在第二节能直接看出来。\n")

    md.append("### 5.1 手册没写谁写，本表不判定\n")
    dash = sorted({i for i, (pm, sc) in perm_of.items() if sc == "待确认"})
    if not dash:
        md.append("无。\n")
    else:
        runs, st, pv = [], None, None
        for i in dash:
            if st is None:
                st = pv = i
            elif i == pv + 1:
                pv = i
            else:
                runs.append((st, pv)); st = pv = i
        if st is not None:
            runs.append((st, pv))
        for lo, hi in runs:
            md.append(f"- `{addr_span(lo, hi)}` —— 手册原文只有一句功能描述，"
                      f"一个字没提谁设定。**不判**：工具遇到它既不报错也不放行。")
        md.append("")

    md.append("### 5.2 手册留空、按用途推成可写\n")
    for x in rows:
        tag = x["addr"].replace(" ", "")
        if SUB_SPLIT.get(tag):
            continue
        pm, sc = perm_of.get(x["lo"], ("", ""))
        if sc == "推断" and pm in ("唯写", "读写"):
            why = INFER.get(tag, ("", ""))[1]
            md.append(f"- `{addr_span(x['lo'], x['hi'])}` **{pm}** —— {why}；"
                      f"手册原文：{x['desc'][:70]}")
    if SUB_SPLIT:
        md.append("- `R520~R559` **唯写（各组命令类）/ 只读（状态类）** —— 手册给了组内明细"
                  "（命令缓存器 / 状态缓存器 / 主程序号码 / 切削% / 快动% / 目标刀号 / "
                  "单节剩余距离 / 保留），但没给权限。我按「状态与剩余距离只可能是核心写、"
                  "命令类只可能是阶梯写」拆成 32 项。**这一组请重点看**，因为一份程序里"
                  "写轴群命令的写法很常见。")
    md.append("")

    # ---- 与现有地址库对账 ----
    md.append("## 六、和现有地址库（syntec_address_db.py）的差异\n")
    try:
        import syntec_address_db as DB
        bad = []
        # 按手册条目聚合: 同一条目里结论相同的连续地址压成一段, 否则表格会有 160 行
        def squash(idxs):
            runs, st, pv = [], None, None
            for i in idxs:
                if st is None:
                    st = pv = i
                elif i == pv + 1:
                    pv = i
                else:
                    runs.append((st, pv)); st = pv = i
            if st is not None:
                runs.append((st, pv))
            return "、".join(addr_span(x, y) for x, y in runs)

        for row in rows:
            seg = [(i, perm_of[i][0]) for i in range(row["lo"], row["hi"] + 1)
                   if i in perm_of and perm_of[i][0] not in ("待确认", "保留")]
            by_perm = {}
            for i, pm in seg:
                by_perm.setdefault(pm, []).append(i)
            for pm, idxs in by_perm.items():
                lvl, _ = DB.check_write("R%d" % idxs[0])
                if (lvl is None) != (pm in ("唯写", "读写")):
                    bad.append((squash(idxs), pm, lvl or "可写"))
        if bad:
            md.append(f"地址库把 `R512~R1023` 整片当成「阶梯只读」，与本表冲突 "
                      f"**{len(bad)} 条**：\n")
            md.append("| 地址 | 本表权限 | 地址库现在认为 |")
            md.append("|---|---|---|")
            for tag, perm, db in bad:
                md.append(f"| `{tag}` | {perm} | {db} |")
            md.append("")
            md.append("这些是当前 `check_write` 的**误报**来源：正常写法会被报成"
                      "「写了只读地址」。修法见下节。\n")
        else:
            md.append("无冲突。\n")
    except Exception as e:                        # noqa: BLE001
        md.append(f"（跳过对账：{e}）\n")

    md.append("## 七、落地方式（待批）\n")
    md.append("不要把这 102 条摊进 `R_ZONES`（那张表是区段级，摊开会破坏区间查找）。"
              "建议保留区段默认，另加一张逐条例外表：\n")
    md.append("```python")
    md.append("R_IFACE = [                       # (起, 止, 阶梯可读, 阶梯可写, 说明)")
    md.append("    (590, 599, True, True,  'PLC 提示讯息区'),")
    md.append("    (603, 603, True, True,  '禁止指定轴移动'),")
    md.append("    ...")
    md.append("]")
    md.append("")
    md.append("def check_write(addr):")
    md.append("    # 先查 R_IFACE 逐条, 查不到再落 R_ZONES 区段默认")
    md.append("```")
    md.append("")
    md.append("这样 `R590.2` 判可写、`R601` 判只读，而 `R640` 以上仍按区段守住位存取=否。")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")
    print("写出 %s：%d 条，可写 %d 条，未列明 %d 个"
          % (a.out, len(rows), len(writable), len(missing)))


if __name__ == "__main__":
    main()
