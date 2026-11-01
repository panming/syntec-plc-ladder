# samples/ 里都是什么

这里的 11 个文件全部是**用新代编辑器手工造出来的最小样本**，
每个文件只放一类元件，一行一种变体。造样本的目的很单纯：

> 编辑器摆一个元件 → 存盘 → 看字节变了什么 → 反推这个元件的编码。

因为每行只有一个元件、地址都是刻意选的简单值，差分时不会互相干扰。

## 清单

| 文件 | 验证内容 | 对应文档 |
|---|---|---|
| `B_contacts.lad` | 常开/常闭触点 | [§5.2](../TECHNICAL.md#52-触点) |
| `B_coils.lad` | 线圈 6 种变体（`=` `/` `^` `v` `S` `R`） | [§5.3](../TECHNICAL.md#53-线圈) |
| `B_math.lad` | 算术：ADD / SUB / MUL / DIV，含常数变体 | [§5.5](../TECHNICAL.md#55-算术) |
| `B_logic.lad` | 逻辑：AND / OR / XOR（寄存器与常数两种） | [§5.6](../TECHNICAL.md#56-逻辑运算) |
| `B_compare.lad` | 比较：GT / LT / EQ / GTK / EQK | [§5.7](../TECHNICAL.md#57-比较) |
| `B_move.lad` | 搬移：MOV / MOV_IMM | [§5.8](../TECHNICAL.md#58-搬移) |
| `B_timer.lad` | 定时器：4 种精度 × 2 种参数源 = 8 个变体 | [§5.9](../TECHNICAL.md#59-定时器) |
| `B_counter.lad` | 计数器：5 方向 × 2 源 = 9 个变体 | [§5.10](../TECHNICAL.md#510-计数器) |
| `B_flow.lad` | 流程：JMP / JSR / LAB / RTS / END / FEND | [§5.11](../TECHNICAL.md#511-流程控制) |
| `B_branch.lad` | 并联两分支 + 竖线连接位 | [§7.7](../TECHNICAL.md#77-一个完整的演算) |
| `demo_parallel.lad` | 五分支并联 / 输出并联 / 串联后并联 | [§8.2](../TECHNICAL.md#82-三条必须实测才发现的规则) |

## 怎么用

`tools/verify_samples.py` 会拿每个样本当**标准答案**，
用本项目的编码器重新生成同一个单元，再逐字节比对：

```
python tools/verify_samples.py
```

`B_timer.lad` 和 `B_counter.lad` 一个文件里塞了 8 / 9 个变体，
这是靠「同一行只换一个参数、其余全同」的方式做的差分——
否则光看字节分不清哪个字节是精度、哪个是预设值。

## 为什么示例是 `B_branch.lad`

它只有 122 字节、3 条记录，却同时包含了**触点、横线、线圈、并联竖线、END**
五样东西，是看懂整个格式的最短路径：

```
R1: 02 01 64 00 | 08 0d 00 00 | 00 0d 00 00 | ... | 00 0e c8 02
R2: 01 01 65 00 | 04 00 00 00 | 00 00 00 00 | ... | 00 00 00 00
R3: 00 cf 00 00 00 00 00 00 | 00 0d 00 00 | ...（END）
```

逐格拆解见 [TECHNICAL.md §7.7](../TECHNICAL.md#77-一个完整的演算)。
