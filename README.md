# syntec-plc-ladder

**当前版本** `v0.13.3` ｜ [验证结果.txt](验证结果.txt) 是全部回归的原始输出

> 配套的 AI 技能包（教 AI 怎么写才不炸）已随仓库发布，在 [`skill/syntec-plc/`](skill/syntec-plc/)，
> 见[下文](#配套技能包)。

让 AI 读懂、修改、生成 **新代（SYNTEC）CNC 梯形图 `.lad` 文件**的 MCP 服务，
外加一份完整的[文件格式逆向文档](TECHNICAL.md)。

- **读**：把 `.lad` 解析成梯形图（元件 + 串并联结构 + 可读文本图），
  并且做到「读进来再存回去，逐字节完全一样」
- **写**：用自然语言让 AI 拼出合法的二进制 `.lad`，用新代 PLC 编辑器打开就能看
- **纯 Python 标准库**，零依赖，Windows / macOS / Linux 都能跑

> 这个项目是**逆向**的产物：没有官方格式文档。结论来自两条互相校验的路线：
> 「编辑器造样本 → 十六进制差分 → 全量真实程序回归验证」，以及
> **反编译官方编辑器 `MLCEdit.exe` 直接读它的操作码表和元件类**。
> 两者冲突时以官方程序集为准，再回去找字节证据解释差异。
> 逆向过程、编码表、排版规则都写在 [TECHNICAL.md](TECHNICAL.md) 里，
> 对齐留档在 [§9.5](TECHNICAL.md#95-与官方编辑器反编译实现的对齐)。

---

## 目录

```
├── TECHNICAL.md                      # .lad 文件格式技术文档（重点）
├── 验证结果.txt                       # 本机跑完全部回归的原始输出
├── syntec-ladder-mcp-standalone.py   # 单文件版，直接能用（零依赖）
├── mcp-config.example.json           # MCP 客户端配置模板
├── src/                              # 源码
│   ├── mcp_server.py                 # MCP 服务端（13 个工具）
│   ├── syntec_lad.py                 # 单元编码 / 解码
│   ├── syntec_layout.py              # 布局引擎：网络树 → 网格
│   ├── syntec_parse.py               # 反序列化：网格 → 网络树
│   ├── syntec_read.py                # 整文件读取 / 无损载入
│   ├── syntec_paths.py               # 路径枚举：母排→负载全部通路，桥式/多负载求值
│   ├── syntec_model.py               # 工程模型 + validate + 地址查询
│   ├── syntec_address_db.py/.json    # 8 类元件 / 602 条标准地址 / C-S 方向 / R 区权限
│   ├── syntec_r_iface.py             # R512~R1023 逐条权限（由手册 1-1.4.4 生成，勿手改）
│   ├── syntec_re.py                  # 早期解码器（报告用）
│   ├── syntec_annotation.py          # 解析编辑器导出的注解档 CUSCMT_*.dat
│   └── build_bundle.py               # 打包单文件版
├── tools/                            # 验证脚本 + 打包脚本
├── skill/syntec-plc/                 # 配套 AI 技能包：SKILL.md + 7 份参考 + 2 个脚本 + 模板
├── samples/                          # 10 个编辑器样本 + 1 个生成的并联演示
└── docs/                             # 逆向过程记录
```

---

## 快速开始

### 方式 A：单文件版（推荐）

只拿一个文件 `syntec-ladder-mcp-standalone.py`，放到不会被删的目录，先自检：

```bash
python syntec-ladder-mcp-standalone.py --selftest
```

看到 `[PASS] 11/11` 就说明环境没问题。

### 方式 B：源码版

```bash
git clone https://github.com/panming/syntec-plc-ladder.git
cd syntec-plc-ladder
python tools/selftest.py
```

不需要 `pip install` 任何东西。

### 配置到 MCP 客户端

在客户端的 MCP 配置里加一个 stdio 服务，`args` 指向文件的绝对路径：

```json
{
  "mcpServers": {
    "syntec-ladder": {
      "command": "python",
      "args": ["C:/Tools/syntec-ladder-mcp-standalone.py"]
    }
  }
}
```

各客户端配置文件位置：

| 客户端 | 路径 |
|---|---|
| Claude Desktop | Windows `%APPDATA%\Claude\claude_desktop_config.json`；macOS `~/Library/Application Support/Claude/` |
| Cursor | 项目内 `.cursor/mcp.json`，或全局 `~/.cursor/mcp.json` |
| Claude Code | `claude mcp add syntec-ladder -- python "路径"` |
| WorkBuddy | `~/.workbuddy/mcp.json`，然后在连接器管理页点「信任」 |

> Windows 路径在 JSON 里要写成双反斜杠，或者干脆全用正斜杠 `/`（Python 同样认）。
> 如果提示找不到 `python`，把 `command` 换成 `py`（Windows 启动器）或 `python3`。

### 装好之后，用一句话确认

改完配置要**重启客户端**，然后新开对话说：

> 用 syntec-ladder 新建一个梯形图：I100 串 (I101 | I102) 驱动 O200，加 END，存到 D:/tmp/test.lad

能返回「已在末尾添加第 N 段」并真的写出文件，就说明 MCP 通了。
如果 AI 说没有这个工具，先看客户端日志里 MCP 有没有启动失败（多半是 `python` 路径不对）。

---

## 13 个工具

| 工具 | 作用 |
|---|---|
| `new_ladder` | 新建/清空工程，可指定默认保存路径 |
| `load_lad` | **读入**已有 `.lad`；不改动的行原样锁定，保存后逐字节相同 |
| `read_ladder` | **只读**解析任意 `.lad`：结构文本或元件列表（JSON） |
| `dump_rungs` | 把当前工程的程序段导出成元件列表（带编辑器行号） |
| `lookup_address` | 查标准地址含义（`C36`、`急停`、`主轴倍率`），给裸字直接返回元件定义（`A`、`S`、`R`、`CT`、`TM`） |
| `add_rung` | 追加一段：串联条件 + 结果元件，或给完整元件列表（含并联） |
| `set_comment` | 给地址加设备变量注释（ct=4，挂在地址上，不占行）|
| `add_comment_line` | 在梯形图前加整行注释（ct=1，占编辑器行号）|
| `validate` | 结构校验：缺 END、地址越界、无输出元件、双线圈 / 重复元件、定时器重号 |
| `preview` | 把当前工程回显成文本 |
| `save` | 写出 `.lad`，返回路径与字节数 |
| `explain_rung` | **解释一段程序什么时候才动作**：逐个负载给出布尔表达式（路径枚举，桥式/多线圈也能算）|
| `explain_format` | 返回格式要点与已知限制 |

---

## 配套技能包

MCP 只提供**能力**（读写 `.lad` 的 13 个工具），不给**判断力**。
同一个工具，AI 可能写出「一个 `O` 挂三个线圈」，也可能拿 `R` 的位当中间继电器——
这两类错都能生成**语法合法**的文件，到现场才炸。

配套技能包就是补这部分：把「怎么写才对」固化下来——硬约束表、8 类元件分工、
12 个已验证的机床工艺模式、注释编码规则、强制三层验证流程，以及从四台真机程序
反推出来的现场约定（地址怎么分、报警怎么锁、手自动怎么共存）。

**用法**：把整个目录拷进支持 `SKILL.md` 的客户端技能目录。

```bash
cp -r skill/syntec-plc ~/.workbuddy/skills/
```

`SKILL.md` 开头的 `description` 决定触发时机：提到新代 / `.lad` / 梯形图 / PLC 程序，
或具体功能（润滑、液压站、排屑、刀库、M 码、报警锁存）时会自动加载。

| 文件 | 管什么 |
|---|---|
| `SKILL.md` | 给模型的执行指令：地址三分法、硬约束、三层注释、三层验证、21 条反模式 |
| `references/function-library.md` | 功能写法库：润滑 / 液压站 / 排屑与 9 件冷却辅机 / 刀库刀塔 / M 码 |
| `references/project-conventions.md` | 现场约定：地址分区、`I`/`O` 一点一义、`R13`~`R18`、程序骨架 |
| `references/patterns.md` | 12 个工艺模式：自保持、手自动、锁存报警、单次动作、互锁… |
| `references/element-grammar.md` | `add_rung` 的元件字段与并联嵌套写法 |
| `references/address-map.md` | C/S 全表（各 512 点）、R 区权限、内部标志该放哪 |
| `references/comment-encoding.md` | cp950 规则与简繁对照 |
| `references/lad-format.md` | 字节结构，排错时用 |
| `scripts/check_lad.py` · `zh_tw.py` | 字节体检 / 注释转繁体，零依赖 |
| `assets/build_program.py` | MCP 不可用时的离线生成模板 |

完整的文件说明、依据分级、覆盖范围见 [`skill/syntec-plc/README.md`](skill/syntec-plc/README.md)。

### 它挡掉了哪些坑

| 坑 | 技能里的对策 |
|---|---|
| 生成合法但逻辑错的程序 | 硬约束表 + 12 个已验证工艺模式 |
| 认错元件（`A`/`C`/`S`/`R` 各干什么） | 手册 2.1 的 8 类元件表 + `lookup_address('A')` 直达定义 |
| 拿 `C` 段当中间继电器（撞系统急停/倍率） | 开写前必须 `lookup_address` 查 |
| 拿 `S` 段当内部标志（`S` 是核心→阶梯图的只读状态） | 地址方向表 + `validate` 直接拦写 `S` |
| 拿 `R` 的位当中间继电器（能跑，但那是数据寄存器） | 明确「标志用 `A0`~`A511`」，`validate` 给 warn |
| 参数写死在程序里、或放 `R50~R80`（掉电丢失） | 参数一律走 `R81~R100`（系统参数 `3401~3420`），定时器 `source:"R"` 直接读 |
| 一个地址挂多个线圈（含多个置位/多个复位） | 「普通线圈 1 处、置位/复位各 1 处」，`validate` 报双线圈 / 重复元件 |
| 注释用简体，编辑器显示问号 | `zh_tw.py` + 前置检查 |
| 地址超 511 被静默截断 | 硬约束表写明，工具已改为直接报错 |
| 地址表抄错（把 `R256~R511` 当保留区、把两列权限看反） | `verify_addr_conflicts.py` 拿手册逐行对账；`tools/chm_to_md.py` 按 `rowspan` 展开，不靠手抄 |
| 轴号拼字符串没补零（`R71` 当 `R701`） | `verify_addr_conflicts.py` + `verify_review_fixes.py` 锁住 `R701~R716` / `R901~R916` |
| 文本图把 `=R590.14` 砍成 `=R590.1`，五个位看着像一个 | `render_file` 整份图统一列宽；`verify_review_fixes.py` 回归 |
| 报警文字与线圈对不上（含删逻辑后留下的文字残留） | `verify_alarm_xml.py` 拿 `AlarmPLC_CHS.xml` 和梯形图对账；只列事实，不判「保护失效」 |
| 把串联定时器/运算块当恒通，下游条件少一个 AND 项 | 手册 1-2.10 / 1-2.7：定时器到时、运算为真才导通；`verify_series_blocks.py` 用真值表锁住 |
| `R40~R49` 警报输出位没线圈，被误报成悬空触点 | 手册 1-5：警报未启用属正常，工具降为提示 |
| 报警汇总只覆盖到 `R46`，后加的 `R47/R49` 报警只弹文字、不亮红灯/不 Feed Hold | `logic_probe.py` §8b 列出「被驱动但未纳入汇总」的报警位（`K0<R4x` 只写到 R46 是历史累加） |
| 「无报警」信号（条件全为取反的报警位）被误识别成报警汇总，22 条纯噪音 | §8b 区分正/负触点；all-clear 单列并反报「哪些报警亮起时不拦截」，`verify_review_fixes.py` 回归 |
| 只看格式通过就说「验证完了」 | 强制三层验证：validate → 文本回读 → 时序仿真 |
| 把「正转自保持、反转点动」当不一致去统一 | 排屑反转是清屑点动，松手即停是安全要求；`function-library.md` §3.2 说明为什么不该改，也不该往点动里加超时 |
| 油冷机跟着 `M30` / 急停一起停 | 主轴停了温度还要降，油冷跟着停会把热变形留在主轴和刀柄上——它是辅机里唯一的例外 |
| 辅机漏挂 `M09` / `M30`，程序跑完泵还在转 | 每件水气的输出链上都要串；`function-library.md` §3.4 |
| 按「某功能必须占某段地址」硬排 | 只要求同功能点位连成一段、功能之间不重叠；`A200`~`A299` 内部怎么切没有规定 |
| 过载信号直接进报警位，启动瞬间跳假报警 | 热继电器上电会抖几个扫描周期，先过 2 秒定时器 |
| 报警只自锁不切断，或只切断不自锁 | 两样都要：条件串在输出链上 + 报警位锁存到复位 |

---

## 用法示例

### 读一个现成的程序

> 看看 samples/B_branch.lad 是怎么接的。

`read_ladder` 返回：

```
--- R1  (编辑器行 1-2) ---
   1  I100   ╷─────── ─────── ─────── ─────── ─────── ─────── ─────── ─────── =O200
   2  I101   ╵
--- R2  (编辑器行 3-3) ---
   3  FLOW8           ─────── ─────── ─────── ─────── ─────── ─────── ─────── ───────
```

`╷` 分叉、`│` 穿过、`╵` 汇合。这段读作 `(I100 | I101) → O200`。

> **这份文本是给 AI 读的，不是给人审图的。** 你要看图，直接在新代编辑器里
> 打开 `.lad` —— 那才是标准答案。工具里的文本只解决一个问题：
> AI 看不见二进制，需要一个能理解拓扑的表示。
>
> 顺带说个体积账：真实程序里最大的那条 rung（52 个分支）用 JSON 表示是 8147 个字符，
> 这种文本是 1908 个字符。所以 `read_ladder` 默认返回文本，
> 只有要精确改写某条 rung 时才用 `format=json`。

### 写一段新程序

> 写一行：`I100` 串上 `(I101 | I102)`，驱动线圈 `O200`，最后加 END。

AI 会调 `add_rung` → `validate` → `save`。并联会自动展开成两行。

### 问「这行为什么不亮」

> 这份程序第 405 行，C1 和 R590.17 分别在什么条件下动作？

`explain_rung` 返回：

```
编辑器行 405-407  (shape=multi, 6 个元件, 枚举 3 条通路)

  =C1  ←  I113·/A18 + A9
      2 条通路
        通路1: I113·/A18
        通路2: A9

  =R590.17  ←  I113·A18
      1 条通路
```

这就是「一条 rung 多个线圈」——两个输出挤在一条 rung 里，靠共享的
`I113` 和一条竖线分开。串并联树装不下这种结构，工具改用路径枚举：
从左边母排出发，把通往每个线圈的所有通路都走一遍，取 OR-of-AND。
`+` 是或、`·` 是与、前缀 `/` 是常闭；**线圈本身不参与条件**（它是负载，不是开关）。

### 在已有程序上改

> 把 cnc.lad 读进来，在第 20 行后面加一行急停常闭串线圈 O10，另存为 cnc_new.lad。

AI 会调 `load_lad` → `add_rung` → `validate` → `save`。

`load_lad` 会先**逐条试算**：能完整复现的行才转成可编辑元件，
原件是人工摆放、重排后会变样的行则**锁定为原始字节**。
所以保存出来只包含你真正改过的那几行差异，其余字节一个不动。

实测（87042 字节和 99402 字节的两份真实机床程序）：
读入后不做任何修改直接保存，**逐字节相同**。

### 审核环节在编辑器里

`validate` 只做「别生成明显错的东西」的护栏——缺 END、地址越界、只有条件没输出、
双线圈、重复元件（同一地址置位/复位超一对）、定时器/计数器重号。这些是新代编辑器打开时会报警的问题，提前挡住能省一轮来回。

真正的确认永远是：**保存 → 编辑器打开 → 人看。**

---

## 验证

四层指标 + 一层官方对账。**仓库自带的 11 个样本（clone 下来就能复跑）**：

```
11 个文件 / 69 编辑行 / 60 条 rung / 6 个并联块 / 15 个分支

结构往返一致   60 / 60
自检通过       60 / 60
几何与原件相同  58 / 60   （其中逐字节相同 51）
```

开发环境另加 2 份真实机床程序（87 KB / 99 KB，不在仓库），合计 13 个文件 / 2139 编辑行：

```
1188 条 rung / 705 个并联块 / 1793 个分支

结构往返一致   1187 / 1187   （另 1 条桥式，原样保留）
自检通过       1188 / 1188
几何与原件相同  778 / 1188
其中逐字节相同  751
```

结构 100%、自检 100%。几何 65% 是**原理性上限**：新代编辑器不做自动排版，
元件摆在哪一列、哪里画横线、右边留几格全由人决定，同一个逻辑可以画成无数种合法布局。
所以本项目采取的策略是「能复现的原样复现，不能复现的锁定原样」，而不是硬凑字节。

在此之上还有一层**官方对账**：`tools/verify_official.py` 的期望值不写自己的假设，
直接抄反编译出来的官方常量表（`EOpcode_V1` 的 80 个操作码、`plcop_map[256]`、
各 `*Converter` 的字段布局）。9 组 50 项，含 85 个官方码逐个解码/编码不崩、
以及 3 份真机 + 11 个样本共 24 765 个单元零未知。

这一层挡掉过的真错（细节见 [TECHNICAL.md §9.5](TECHNICAL.md#95-与官方编辑器反编译实现的对齐)）：

| 错法 | 后果 |
|---|---|
| `FEND` 当成 4 字节 | 吞掉后面的横线格，整行往右错一格 |
| `END` 第 2 格当空格 | 保留区被清零，编辑器打开后文件被改写 |
| 计数器预设只写 1 字节 | 预设 >255 截断成错值 |
| 比较块第一个操作数一律当常数 | `R961` 显示成 `#961`，条件读反 |
| `0x33` 标成加号 | 减法显示成加法——最危险的一类 |

自己复跑：

```bash
python tools/selftest.py                        # 自带数据，不需要样本
python tools/verify_official.py                 # 与官方反编译表逐条对账（50 项）
python tools/roundtrip_full.py                  # 用 samples/ 里的语料
python tools/verify_samples.py                  # 元件逐字节验证
python tools/verify_parallel.py                 # 并联结构验证
python tools/verify_comments.py                 # 注释编码验证(自带样例 + 真机语料)
python tools/verify_address.py                  # 地址权限 / 同址驱动回归
python tools/verify_addr_conflicts.py           # 手册/文档/代码 三方地址核对
python tools/verify_addr_conflicts.py --chm "CNC and PLC Interface-ZH-CN.chm"   # 连手册一起查
python tools/verify_paths.py                    # 路径枚举 vs 串并联树
python tools/verify_multi_coil.py               # 一段程序多个线圈
python tools/verify_r_iface.py                  # R512~R1023 逐条权限
python tools/verify_review_fixes.py             # 审查工具自身的七个历史缺陷回归
python tools/verify_alarm_xml.py --selftest     # 报警 XML 对账（合成用例）
python tools/verify_series_blocks.py            # 串联功能块是条件（真值表）
python tools/review_ladder.py 我的程序.lad       # 静态体检一份现成程序（语法/地址/结构）
python tools/logic_probe.py 我的程序.lad --out _logic_dump.txt  # 程序逻辑体检：逐负载条件、自保、查表、报警汇总覆盖
python tools/verify_alarm_xml.py --lad 我的程序.lad   # 同目录要有 AlarmPLC_CHS.xml

# 换成自己的样本目录
python tools/roundtrip_full.py --samples D:/my_lad
python tools/verify_address.py --samples D:/my_lad
set SYNTEC_SAMPLES=D:/my_lad
```

缺样本**不会**静默跳过：非可选样本缺失记 FAIL 并返回非 0 退出码；
真机程序是可选的，缺失只记 SKIP。

推上去之后，GitHub Actions 会在 **Ubuntu / Windows × Python 3.10 / 3.12** 上
跑同一套脚本（`.github/workflows/ci.yml`）。

---

## 打包

改完代码要发人时，别手动挑文件：

```bash
python tools/package.py                  # 产物出到 dist/
python tools/package.py --out ~/Desktop  # 出到桌面，方便发给别人
```

发出去的是 `dist/` 下的 zip：

| 文件 | 内容 |
|---|---|
| `syntec-plc-ladder-v<ver>.zip` | 整个仓库（不含 `.git` / `dist` / `__pycache__`），拿到就能跑 |

版本号读 `src/build_bundle.py` 的 `VERSION`，不用手填。
打完会解压到临时目录实跑两遍：`--selftest` 和 `tools/e2e_mcp.py`——
**zip 打得开不算数，能从压缩包里起服务、写文件、读回来才算**。

> 如果本地存在 `skill/syntec-plc/`（作者的开发环境才有），脚本会额外出一个
> `syntec-plc-skill-v<ver>.zip`。`git clone` 下来的仓库没有这个目录，脚本会跳过，
> 只出上面那一个包——不会报错。

> zip 里的中文文件名按 UTF-8 记录（`0x800` 标志）。Windows 资源管理器、7-Zip、
> macOS 归档工具都正常；Git Bash 自带的老版 Info-ZIP `unzip`（6.00, 2009）不认这个标志，
> 会把 `验证结果.txt` 显示成乱码 —— 加 `unzip -O UTF-8` 或换 7-Zip 即可。

---

## 关于 samples/

`samples/` 里是 **10 个用新代编辑器手工造出来的最小样本**，每个文件只验证一类元件
（触点 / 线圈 / 算术 / 逻辑 / 比较 / 搬移 / 定时器 / 计数器 / 流程 / 并联），
外加 **1 个由本工具生成的** `demo_parallel.lad`。

最后这个要单独说明：它是我们自己的产物，只能验证「写出去再读回来一致」，
**不能**当「编辑器认可的排版」的标准答案 —— 那是自我循环。
涉及排版的结论都以编辑器样本和真机程序为准。

真实机床程序（约 87KB 和 99KB 的两份 `cnc.lad`）**不在仓库里**——
那里面是具体的刀库和 CNC 逻辑，属于设备资产，不适合公开。
验证脚本不依赖它们，缺失时记 SKIP 而不是 FAIL。

要验证真实程序，把自己的 `.lad` 放进任意目录：

```bash
python tools/roundtrip_full.py --samples D:/my_ladder_backup
```

---

## 已知限制

| 限制 | 说明 |
|---|---|
| 折不成树的行 | 桥式跨接 / 多负载共用条件段：**读得出每个负载的条件**（路径枚举），但生成不了、写回时原样保留。多线圈可用「前缀 + parallel」正常生成，见 [TECHNICAL §8.1](TECHNICAL.md#81-生成流程) |
| 刀库 / CNC 组 / RS232 / MODBUS / 背景运算 | 样本和真机程序里从未出现，编码未知 |
| 比较 `LE` / `GE` | 没找到编码，可能要靠交换操作数实现 |
| 单条 rung | 最多 256 行（编辑器实测 256 行可开；真机最长 59 行 / 52 分支） |
| 间接定址 | 掩码位已定位，无实测用例 |
| `A` 段掉电行为 | 手册只写「只有 On/Off 两态」，没写是否保持；要跨断电记住的**数值**请用 `R` 保持区 |
| `R512~R1023` 有 86 个地址手册没定义 | **不判定**：不报错也不放行。写程序时别用，审别人的程序时用了不算错（`R938~R940` 就是现场实例）。详见 [权限表](docs/r512-r1023-权限表.md) |
| `R961~R976`（Home Dog Shift）谁写 | 手册没写，新代工程师也没答复。按最保守假设判只读——判错只会在写的时候当场暴露 |

更细的边界见 [TECHNICAL.md 第 10 节](TECHNICAL.md#10-未知与限制)。

---

## 参考

- [TECHNICAL.md](TECHNICAL.md) —— 文件格式技术文档（坐标系统 / 记录结构 / conn 位 /
  全部 opcode / 注释编码 / 读算法 / 写算法 / 验证方法）
- [docs/samples.md](docs/samples.md) —— `samples/` 里每个文件验的是哪条规则
- [docs/lad_roundtrip_report.md](docs/lad_roundtrip_report.md) —— 全量往返验证报告
- [docs/unknown_inventory.md](docs/unknown_inventory.md) —— 未解编码清单
- [docs/r512-r1023-权限表.md](docs/r512-r1023-权限表.md) —— R512~R1023 逐条权限（含推断依据与风险点）
- [skill/syntec-plc/README.md](skill/syntec-plc/README.md) —— 配套技能包说明：文件地图、
  依据分级（实测 / 手册 / 真机惯例 / 推断 / 已被推翻）、功能覆盖范围、维护约定

## License

MIT。`.lad` 格式本身属于新代（SYNTEC）；本项目是非官方逆向成果，仅供学习和维修参考。
涉及生产设备时请务必在编辑器里人工核对后再上机。
