#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新代(SYNTEC) PLC 梯形图 MCP Server  —— 纯 Python 实现, 零依赖。

通过 stdio(JSON-RPC 2.0, 换行分隔) 与 MCP 客户端(Claude Desktop / Cursor / 自研)通信。
让 AI 直接以「梯形图语义」构建工程并写出合法 .lad 文件, 无需操作编辑器 GUI。

启动方式(客户端 mcp.json):
  {
    "mcpServers": {
      "syntec-ladder": {
        "command": "python3",
        "args": ["/绝对路径/mcp_server.py"]
      }
    }
  }

注意: 本文件所在目录必须能被导入(syntec_lad.py / syntec_model.py / syntec_address_db.py)。
      脚本已自动把自身所在目录加入 sys.path。
"""
import os
import sys
import json

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import syntec_model as M
import syntec_read as RD

# 全局工程状态
PROJECT = M.LadderProject()

# ---------------------------------------------------------------------------
# 工具定义
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "name": "new_ladder",
        "description": "新建/重置一个梯形图工程(清空内存中的全部行与批注)。可选指定后续 save 的默认路径。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "可选, 默认保存路径, 如 C:\\\\Users\\\\panming\\\\Desktop\\\\cnc_generated.lad"}
            }
        },
    },
    {
        "name": "load_lad",
        "description": (
            "读入一个已有的 .lad 程序, 载入到当前工程(之后可 add_rung 追加 / 直接 save 写回)。\n"
            "默认 keep_geometry=true: 逐条比对'用语义模型重新生成的字节', 完全一致才转成可编辑元件,\n"
            "否则锁定为原始字节 —— 因此'载入后立刻保存'与原文件逐字节相同, 改动只影响你真编辑过的行。\n"
            "返回: 总 rung 数 / 可编辑数 / 锁定数 / 并联统计, 并列出锁定的 rung 号。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": ".lad 文件路径"},
                "keep_geometry": {"type": "boolean",
                                  "description": "默认 true: 布局有差异的行锁定原样(保证无损); false: 全部转语义(可全改, 会重排版)"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_ladder",
        "description": (
            "只读解析 .lad(不载入工程、不修改任何东西)。用于'先看懂别人的程序再动'。\n"
            "默认返回紧凑的梯形图文本(一行 rung 造一行文本, 竖线用 ╷│╵ 表示分叉/穿过/汇合),\n"
            "这是给 AI 快速理解拓扑用的, 不是给人审图的 —— 审图请在新代编辑器里打开。\n"
            "要精确改写某条 rung 时用 format=json 拿元件列表。\n"
            "可用 start/end 指定 rung 范围, limit 限制条数(默认 20)。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": ".lad 文件路径"},
                "start": {"type": "integer", "description": "起始 rung 号 (1 基, 含)"},
                "end": {"type": "integer", "description": "结束 rung 号 (含)"},
                "limit": {"type": "integer", "description": "最多返回几条 (默认 20)"},
                "format": {"type": "string", "enum": ["text", "json", "both", "ladder"],
                           "description": "text(或 ladder, 默认)=紧凑的梯形图文本, 看结构最省; "
                                          "json=精确元件列表, 要改写时用; both=两者"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "dump_rungs",
        "description": "把当前工程里的 rung 导出成元件列表(JSON), 便于核对、复制或在别处重建。可用 start/end/limit 限定范围。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "integer", "description": "起始 rung 号 (1 基, 含)"},
                "end": {"type": "integer", "description": "结束 rung 号 (含)"},
                "limit": {"type": "integer", "description": "最多返回几条 (默认 20)"},
            },
        },
    },
    {
        "name": "lookup_address",
        "description": "按地址或中文/英文关键词查询新代标准 C/S/R 接口含义。例如查 'C36'、'急停'、'主轴倍率'、'JOG'。返回匹配的标准地址与说明, 帮助 AI 选对接口地址。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "地址(如 C36) 或关键词(如 急停 / 主轴倍率 / JOG / 行程极限)"}
            },
            "required": ["query"],
        },
    },
    {
        "name": "add_rung",
        "description": (
            "在梯形图末尾追加一行(rung)。两种用法二选一:\n"
            "  1) 传 condition(串联条件, 从左往右) + action(结果元件, 从条件右侧往右);\n"
            "  2) 直接传 elements: 按视觉从左到右排列的完整元件列表。\n"
            "元件格式(对象):\n"
            "  {kind:'contact', norm:'NO'|'NC', addr:'I132'}              // 触点, addr 可为 I/O/A/C/S/R + 数字\n"
            "      // 位元件 0..511; S 段是核心->阶梯图的只读状态(如 S0=加工中), 只能当触点;\n"
            "      // 中间继电器用 A 段(A0~A511), 不要拿 R 的位当标志\n"
            "  {kind:'coil', norm:'NO'|'NC'|'RP'|'FP'|'LATCH'|'UNLATCH', addr:'O10'}\n"
            "  {kind:'contact_t', norm:'NO'|'NC', index:27}   // 定时器触点 TM27\n"
            "  {kind:'contact_c', norm:'NO'|'NC', index:5}    // 计数器触点 CT5\n"
            "  {kind:'timer', name:'TM100', precision:'1s'|'0.1s'|'0.01s'|'0.001s', source:'K'|'R', preset:60}\n"
            "      // precision=精度; source='K' 预设常数 / 'R' 预设取寄存器(此时 preset 填寄存器号, 如 300=R300)\n"
            "      // 要给操作员改的时间用参数区: {source:'R', preset:'R81'} = 系统参数 3401, 阶梯只读\n"
            "  {kind:'counter', name:'CT3', direction:'UP'|'DOWN'|'RESET'|'RING_UP'|'RING_DOWN', source:'K'|'R', preset:50}\n"
            "  {kind:'math', op:'ADD'|'SUB'|'MUL'|'DIV'|'ADD_IMM', A:'R200', B:'R201'}  // 语义: B = B op A\n"
            "  {kind:'move', op:'MOV'|'MOV_IMM', A:'R220', B:'R221'}      // 语义: B = A\n"
            "  {kind:'logic', op:'AND'|'OR'|'XOR', A:'R230', B:'R231'}   // 语义: B = B op A\n"
            "  {kind:'compare', op:'GT'|'LT'|'EQ'|'GTK'|'EQK', A:'R210', B:'R211'}  // 比较块(作触点): A op B; 带 K 为与常数比较(A 写 #N)\n"
            "  {kind:'parallel', branches:[[元件...],[元件...], ...]}   // 并联分支, 至少 2 个; 每个分支内部是串联, 可再嵌 parallel\n"
            "      // 例: I100 串联 (I101 | I102) 后驱动 O200\n"
            "      //   elements:[{contact I100}, {parallel branches:[[{contact I101}],[{contact I102}]]}, {coil O200}]\n"
            "      // 例: (I100 | I101) 直接驱动 O200\n"
            "      //   elements:[{parallel branches:[[{contact I100}],[{contact I101}]]}, {coil O200}]\n"
            "      // 并联会自动展开成多行; 一条 rung 最多 64 行, 每行 10 列\n"
            "  {kind:'jsr', label:'001'}   // 调用子程序(标签≤6 字节 ASCII, 与 LAB 成对)\n"
            "  {kind:'lab', label:'001'}   // 子程序入口标签(单独一行)\n"
            "  {kind:'rts'}                // 子程序返回(单独一行)\n"
            "  {kind:'fend'}               // 主程序结束(多程序段时用)\n"
            "  {kind:'end'}                // 程序结束(最后一行必用)\n"
            "  {kind:'raw', hex:'00 d0 00 00'}   // 原样字节单元(读入时无法语义化的部分)\n"
            "提示: A/B 若为立即数, 写 '#100'。最后一行务必用 {kind:'end'} 收尾。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "condition": {
                    "type": "array",
                    "description": "串联条件元件列表(触点/比较块), 从左到右",
                    "items": {"type": "object"},
                },
                "action": {
                    "type": "array",
                    "description": "结果元件列表(线圈/定时器/运算块), 从条件右侧往右",
                    "items": {"type": "object"},
                },
                "elements": {
                    "type": "array",
                    "description": "直接给出整行元件(从左到右)",
                    "items": {"type": "object"},
                },
                "comment": {"type": "string", "description": "可选, 给本行首个带地址元件加的批注"},
            },
        },
    },
    {
        "name": "set_comment",
        "description": (
            "给某地址加设备变量注释(ct=4, 挂在地址上, 不占行、不影响梯形图布局), 保存后写入 .lad。\n"
            "addr 如 'C36' / 'O10' / 'TM0'。\n"
            "重要: .lad 内部注释固定用 cp950(Big5) 编码, 与编辑器界面语言无关 —— "
            "简体字「润/压/锁/电」写不进去, 必须用繁体「潤/壓/鎖/電」, 否则编辑器里是问号。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "addr": {"type": "string", "description": "地址, 如 C36"},
                "short": {"type": "string", "description": "短批注 (编辑器里挂在元件旁, 建议 4~8 字)"},
                "long": {"type": "string", "description": "长批注 (交叉引用里显示, 可写全, 单条 ≤255 字节)"},
            },
            "required": ["addr"],
        },
    },
    {
        "name": "add_comment_line",
        "description": (
            "在梯形图之前加一条整行注释(ct=1, 编辑器里占一行显示), 常用于程序标题、参数说明、I/O 速查。\n"
            "注意: 这类注释**占编辑器的行号**, 加几条, 后面所有梯形图行的行号就往后挪几行。\n"
            "只放在所有梯形图之前 —— END 之后放注释行会让编辑器认为 END 不是最后一行。\n"
            "编码同样是 cp950, 简体字要转繁体。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "注释内容 (单条 ≤255 字节, 约 120 个汉字)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "validate",
        "description": "对当前工程做结构校验, 返回警告列表(类似编辑器'不合理输出'提示): 是否缺 END、地址是否越界、行是否无输出元件、地址能不能写(写 S 段/写只读 R 区/位存取非法)等。",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "preview",
        "description": "以可读文本(带竖线)回显当前工程的梯形图, 便于 AI 与人工核对。可用 start/end 指定 rung 范围, limit 限制条数。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "start": {"type": "integer", "description": "起始 rung 号 (1 基, 含)"},
                "end": {"type": "integer", "description": "结束 rung 号 (含)"},
                "limit": {"type": "integer", "description": "最多显示几条 rung"},
            },
        },
    },
    {
        "name": "save",
        "description": "将当前工程写出为 .lad 文件并返回路径与字节数。默认保存到桌面(无桌面则用户主目录)的 cnc_generated.lad; 可传 path 覆盖。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "输出 .lad 路径"}
            },
        },
    },
    {
        "name": "explain_format",
        "description": "返回已逆向验证的 .lad 格式要点与已知限制, 供 AI 编写前参考(哪些块已支持、哪些待验证)。",
        "inputSchema": {"type": "object", "properties": {}},
    },
]

TOOL_HANDLERS = {}  # name -> fn(args)->str


# ---------------------------------------------------------------------------
# 各工具实现
# ---------------------------------------------------------------------------
def h_new_ladder(args):
    p = args.get("path")
    PROJECT.reset(keep_path=False)
    if p:
        PROJECT.set_path(p)
    return f"已重置工程。默认保存路径: {PROJECT.path}"


def h_load_lad(args):
    path = args.get("path")
    if not path or not os.path.exists(path):
        return f"文件不存在: {path}"
    keep = args.get("keep_geometry", True)
    info, kept = RD.load_into(PROJECT, path, keep_geometry=keep)
    editable = sum(1 for x in PROJECT.rungs if x is not None)
    st = info['stats']
    lines = [
        f"已载入 {info['path']}",
        f"  大小 {info['size']} 字节 / 逻辑行 {info['logic_rows']} / rung {info['rung_count']}"
        f" / 文件版本 {info['version']}",
        f"  并联块 {st['parallel_blocks']} 个 (分支 {st['branches']}, 最多 {st['max_branch']} 路)",
        f"  设备变量注释 {len(info['comments'])} 条",
        f"  可编辑 rung {editable} 条 / 锁定原样 {info['rung_count'] - editable} 条",
    ]
    if kept:
        why = {}
        for _i, w in kept:
            why[w.split(' ')[0]] = why.get(w.split(' ')[0], 0) + 1
        lines.append("  锁定原因: " + ", ".join(f"{k}×{v}" for k, v in why.items()))
        nums = [str(i) for i, _w in kept[:30]]
        lines.append("  锁定 rung: " + ", ".join(nums) + (" ..." if len(kept) > 30 else ""))
        lines.append("  (锁定行保存时原样写回; 要改它们请在编辑器里改, 或用 keep_geometry=false 全量重排)")
    lines.append("提示: 载入后直接 save 会与原文件逐字节相同; add_rung 会追加到末尾。")
    return "\n".join(lines)


def h_read_ladder(args):
    path = args.get("path")
    if not path or not os.path.exists(path):
        return f"文件不存在: {path}"
    start = int(args.get("start") or 1)
    end = args.get("end")
    limit = int(args.get("limit") or 20)
    # 容错: AI 常写成 ladder / Ladder / JSON 等; 认不出的一律按 both 处理,
    # 否则会静默返回空内容 (只有一行文件头), 排查起来很费劲。
    fmt = str(args.get("format") or "text").strip().lower()
    if fmt in ("ladder", "ladder_text", "graph", "draw"):
        fmt = "text"
    if fmt not in ("text", "json", "both"):
        fmt = "both"

    info = RD.read_ladder(path)
    sel = [r for r in info['rungs']
           if r['index'] >= start and (end is None or r['index'] <= int(end))][:limit]
    out = [f"{info['path']}  ({info['size']} 字节, {info['rung_count']} 条 rung, "
           f"{info['logic_rows']} 逻辑行, 版本 {info['version']})"]
    if fmt in ("text", "both"):
        out.append(RD.render_file(path, start=sel[0]['index'] if sel else start,
                                 end=sel[-1]['index'] if sel else start))
    if fmt in ("json", "both"):
        brief = []
        for r in sel:
            brief.append({"rung": r['index'], "row": f"{r['row_start']}-{r['row_end']}",
                          "ok": r['ok'],
                          "elements": r['elements'] if r['ok'] else None,
                          **({"note": r['note']} if not r['ok'] else {})})
        out.append(json.dumps(brief, ensure_ascii=False, indent=1))
    if len(info['rungs']) > (sel[-1]['index'] if sel else 0):
        out.append(f"... 共 {info['rung_count']} 条, 用 start/end/limit 查看更多")
    return "\n".join(out)


def h_dump_rungs(args):
    start = int(args.get("start") or 1)
    end = args.get("end")
    limit = int(args.get("limit") or 20)
    out = []
    n = 0
    for i, els in enumerate(PROJECT.rungs, 1):
        if i < start or (end is not None and i > int(end)):
            continue
        if n >= limit:
            out.append(f"... 还有 {len(PROJECT.rungs) - i + 1} 条未显示")
            break
        n += 1
        if els is None:
            out.append(json.dumps({"rung": i, "locked": True,
                                   "note": "原样保留的原始行, 不可用元素列表表达"},
                                  ensure_ascii=False))
        else:
            out.append(json.dumps({"rung": i, "elements": els},
                                  ensure_ascii=False, indent=1))
    return "\n".join(out) if out else "当前工程为空。"


def h_lookup_address(args):
    q = args.get("query", "")
    if not q:
        return "请提供 query(地址或关键词)。"
    results, panel = M.lookup_address(q)
    if not results and not panel:
        return f"未找到与 {q!r} 匹配的标准地址。可尝试更通用的关键词(如 '倍率' / 'JOG' / '原点')。"
    lines = [f"查询 {q!r} 的结果:"]
    for addr, meanings in results:
        for m in meanings:
            lines.append(f"  {addr}: {m}")
    if panel:
        lines.append("  相关面板功能:")
        for fn, desc in panel:
            lines.append(f"    - {fn}: {desc}")
    return "\n".join(lines)


def h_add_rung(args):
    idx = PROJECT.add_rung(
        condition=args.get("condition"),
        action=args.get("action"),
        elements=args.get("elements"),
        comment=args.get("comment"),
    )
    n = PROJECT.rung_row_count()[-1]
    total = sum(PROJECT.rung_row_count())
    extra = f" (含并联, 展开为 {n} 行)" if n > 1 else ""
    return (f"已添加第 {idx} 条 rung{extra}。"
            f"当前共 {len(PROJECT.rungs)} 条 rung / {total} 个编辑器行。")


def h_add_comment_line(args):
    text = args["text"]
    import syntec_lad as _L
    try:
        PROJECT.add_header_comment(text)
        n = len(_L.enc_comment(text, 1)) // 40
    except Exception as e:
        return f"添加注释失败: {e}"
    return (f"已添加注释行（{n} 条记录）：{text}\n"
            f"当前 {len(PROJECT.rungs)} 条 rung，编辑器里梯形图从第 "
            f"{len(PROJECT.header_comments) + 1} 行开始。")


def h_set_comment(args):
    addr = args["addr"]
    PROJECT.set_comment(addr, args.get("short"), args.get("long"))
    # 同时也写成设备变量注释 (ct=4), 这样 save 时才真的落盘到 .lad;
    # 只调 set_comment 的话它只存在内存里, 存文件不会有任何变化。
    s, l = PROJECT.comments.get(str(addr).upper(), ("", ""))
    PROJECT.add_varcmt(addr, s, l)
    return (f"已为 {addr} 设置批注 (短={s!r} 长={l!r})，保存时写入文件。\n"
            f"提示: .lad 内部注释固定用 cp950(Big5) 编码，简体的「润/压/锁」"
            f"写不进去，请用「潤/壓/鎖」，否则编辑器里显示成问号。")


def h_validate(args):
    warns = PROJECT.validate()
    if not warns:
        return "校验通过: 无警告。"
    return "校验发现以下警告:\n" + "\n".join(f"  - {w}" for w in warns)


def h_preview(args):
    return PROJECT.preview_range(
        start=int(args.get("start") or 1),
        end=int(args["end"]) if args.get("end") else None,
        limit=int(args["limit"]) if args.get("limit") else None,
    )


def h_save(args):
    path = PROJECT.path if not args.get("path") else args["path"]
    if args.get("path"):
        PROJECT.set_path(args["path"])
    path, n = PROJECT.save()
    locked = sum(1 for x in PROJECT.rungs if x is None)
    tail = f"\n锁定原样的 rung: {locked} 条 (按原始字节写回)" if locked else ""
    return (f"已保存: {path}\n字节数: {n}\n共 {len(PROJECT.rungs)} 条 rung{tail}\n"
            f"(请用新代 PLC 编辑器打开核对; 控制器实际加载路径为 DiskC\\OpenCNC\\Ladder\\cnc.lad)")


def h_explain_format(args):
    return (
        "【能力总览】\n"
        "  读: read_ladder(只读解析) / load_lad(载入工程, 可无损写回)\n"
        "  写: new_ladder / add_rung / save —— 产出本地 .lad 文件\n"
        "  注意: 本工具只生成文件, 不会、也不能直接写控制器。上机流程是\n"
        "        生成 -> 编辑器打开核对 -> 人工确认 -> 拷贝到 DiskC\\OpenCNC\\Ladder\\cnc.lad -> 重启加载。\n\n"
        "【文件格式】\n"
        "1. 固定 10 列网格, 每格 4 字节 (功能块/定时器占 8 字节 = 2 列), 文件尾 00 fe。\n"
        "2. 逻辑行之外还有批注行(CommentType 1/3)、版本行(2)、设备变量注释(4), 均可出现在任意位置; \n"
        "   本工具载入时按'它前面有几条逻辑行'定位, 写回时保持原有顺序。\n"
        "3. 已验证元件编码:\n"
        "   - 触点: 常开 0x01 / 常闭 0x03; 定时器触点 0x09/0x0a, 计数器触点 0x0b/0x0c (编号只占 1 字节)\n"
        "   - 线圈: 常开 0x0e / 常闭 0x10 / 正缘脉冲 0x05 / 负缘脉冲 0x07 / Latch 0x12 / Unlatch 0x14\n"
        "   - 算术 (语义 B = B op A): ADD 0x21/0x27(IMM) SUB 0x33/0x39 MUL 0x45/0x4b DIV 0x57/0x5d\n"
        "   - 搬移 MOV 0x72 / MOV_IMM 0x70;  逻辑 AND 0x81/0x87 OR 0x93/0x99 XOR 0xa5/0xab\n"
        "   - 比较 GT 0x5e / LT 0x62 / EQ 0x66 / GTK 0x6a / LTK 0x6c / EQK 0x6e (K=与常数比较)\n"
        "   - 旋转 ROT 0xb0\n"
        "   - 定时器(8字节): 精度×源 共 8 种 opcode, 参数块=[值低,值高,值低,0x80] 16位小端\n"
        "       1s: K 0xc5 / R 0xe4    0.1s: K 0xc4 / R 0xe3\n"
        "       0.01s: K 0xc3 / R 0xe2  0.001s: K 0xc2 / R 0xe7\n"
        "   - 计数器(8字节): UP 0xc6/0xe5 DOWN 0xc7/0xe6 RESET 0xc9 RING_UP 0xe0/0xe9 RING_DOWN 0xe1/0xea\n"
        "   - 流程: JMP 0xca / JSR 0xcb / MSG 0xd4 / LAB 0xd5 / RTS 0xd0 / END 0xcf / FEND 0xfd\n"
        "【8 类元件: 先认元件, 再挑地址】\n"
        "   I 实体输入接点(Input)      O 实体输出接点(Output)\n"
        "   A 虚拟辅助接点(Auxiliary) A0~A511 共512 —— 中间继电器/过程标志就放这里\n"
        "   C 阶梯图发送指令给核心    C0~C511 共512(如 C0 起动/C36 急停/C6 X轴JOG+)\n"
        "                             —— 能写, 但每个点都接内核, 不是自由内存\n"
        "   S 核心传送系统状态给阶梯图 S0~S511 共512(如 S0 加工中/S1 暂停/S32 Reset)\n"
        "                             —— 只读, 不能写线圈\n"
        "   R 阶梯图与核心双向沟通    32 位元寄存器, 可存数值或拆开成位元使用\n"
        "                             R0~R65535 —— 用来存数, 不是继电器\n"
        "   CT 虚拟辅助计数器 CT0~CT255 (256)   TM 虚拟辅助计时器 TM0~TM255 (256)\n"
        "   内部标志一律用 A 段; 写 R50.x 这类位置能跑, 但工具会给 warn 提示改用 A。\n"
        "   跨断电要记住的是数值, 放 R 保持区 R193~R255 (避开 R103~R192 刀号)。\n"
        "   要给操作员改的参数(时长/间隔/次数)放 R81~R100 = 系统参数 3401~3420,\n"
        "     掉电保持、阶梯只读: 定时器 source:'R' preset:'R81' 直接读;\n"
        "     别写死常数, 也别写 R81(写它报 error, 改参数在参数画面 3401~3420)。\n"
        "   注意 R1033 以上 位存取=否, 不能写 R1200.0 这种。\n"
        "   查元件定义: lookup_address('A') / lookup_address('S') 直接返回手册口径。\n"
        "4. 标准地址(C/S/R) 602 条已入库, 用 lookup_address 查。\n\n"
        "【并联(竖线)编码 —— 已对 1188 条真实 rung 全量验证】\n"
        "   连接字节 4 位 = 前后两条列边界上的竖线: bit2/bit3 = 左边界上/下半段, bit0/bit1 = 右边界上/下半段。\n"
        "   一条竖线在列边界 B 上跨 r0..r1 行: r0 只置下半段, 中间行上下都置, r1 只置上半段。\n"
        "   分支布局是【左对齐】: 各分支从块左边界起排, 短分支用 0x0d 横线从'最后一个元件的右边缘'\n"
        "   补到汇合点; 元件之前的空白保持 0x00。\n"
        "   分支靠上对齐: 并联块的汇合竖线只跨 0..最后分支的所在行, 块底下的余量是死端, 不能补线\n"
        "   (补了就把上分支短接到汇合点, 逻辑就变了)。\n\n"
        "【验证结论 (13 个文件 / 2139 编辑行 / 1188 条 rung / 705 个并联块 / 1793 个分支)】\n"
        "   结构往返(解码 -> 重新生成 -> 再解码, 树完全相同): 1187/1187\n"
        "   自检(生成结果满足编辑器 AutoFix 规则): 1188/1188\n"
        "   几何与原件完全一致: 778/1188 (其中逐字节相同 751)\n"
        "   差的那部分是'人在编辑器里手工摆放的列位与留白'—— 编辑器不做自动排版,\n"
        "   所以任意文件重排后逐字节相同在原理上做不到; 载入时这类行会自动锁定原样。\n\n"
        "【已知限制】\n"
        "  - 一条 rung 最多 64 行 (实测最大 59 行/52 分支)、每行 10 列; 超限报错。\n"
        "  - 桥式(非串并联)拓扑无法写成 SERIES/PARALLEL 树 —— 读取时原样保留并标注,\n"
        "    不能用 add_rung 重建 (cnc.lad R324-R326 是这种)。\n"
        "  - 刀库/CNC 组功能块、RS232、MODBUS、背景运算、间接定址: 样本中未出现, 编码未知。\n"
        "  - JMP/MSG/ROT 能读能原样保留, 但还没有生成参数 (用 raw 形式)。\n\n"
        "【写入前的自检】\n"
        "  validate 会查出: 末行无 END / 地址越界 / 只有条件无输出 / 双线圈 / 定时器重号 / 计数器重号\n"
        "                  / 写 S 段(只读) / 写 A512 以上 / 写只读 R 区 / R 位存取非法\n"
        "                  / 拿 R50.x 当中间继电器(warn, 建议改 A)。\n"
        "  双线圈在编辑器打开时同样会报警, 且实际只有一处生效 —— 务必先改掉再保存。\n"
    )


TOOL_HANDLERS = {
    "new_ladder": h_new_ladder,
    "load_lad": h_load_lad,
    "read_ladder": h_read_ladder,
    "dump_rungs": h_dump_rungs,
    "lookup_address": h_lookup_address,
    "add_rung": h_add_rung,
    "set_comment": h_set_comment,
    "add_comment_line": h_add_comment_line,
    "validate": h_validate,
    "preview": h_preview,
    "save": h_save,
    "explain_format": h_explain_format,
}


# ---------------------------------------------------------------------------
# MCP stdio(JSON-RPC 2.0, 换行分隔) 传输层
# ---------------------------------------------------------------------------
def send(obj):
    if "jsonrpc" not in obj:
        obj = {"jsonrpc": "2.0", **obj}
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_request(req):
    method = req.get("method")
    rid = req.get("id")
    params = req.get("params") or {}

    body = _dispatch(method, rid, params)
    if body is None:
        return None
    # JSON-RPC 2.0 响应必须是 {jsonrpc, id, result} 或 {jsonrpc, id, error};
    # 缺 result 包裹层会被 Claude Desktop / Cursor 判为非法响应。
    if "error" in body:
        return {"id": rid, "error": body["error"]}
    return {"id": rid, "result": body}


def _dispatch(method, rid, params):
    if method == "initialize":
        return {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "syntec-ladder", "version": "0.10.0"},
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": TOOLS}
    if method == "tools/call":
        name = params.get("name")
        args = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if not handler:
            return _error(-32601, f"未知工具: {name}")
        try:
            text = handler(args)
            return {"content": [{"type": "text", "text": str(text)}], "isError": False}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"工具执行出错: {e}"}], "isError": True}
    # 未知 method
    if rid is not None:
        return _error(-32601, f"不支持的方法: {method}")
    return None  # 通知类, 不回复


def _error(code, msg):
    return {"error": {"code": code, "message": msg}}


def main():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        # 通知(notification) 没有 id, 不回复
        if "id" not in req:
            # 仍尝试处理 notifications/initialized 等(无需回复)
            continue
        resp = handle_request(req)
        if resp is not None:
            send(resp)


if __name__ == "__main__":
    main()
