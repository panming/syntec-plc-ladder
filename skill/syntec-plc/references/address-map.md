# 地址表：I / O / A / C / S / R / CT / TM

> **来源**：元件类型与点数取自《PLC 编辑器操作手册》2.1 阶梯图元件简介；
> 地址含义与权限取自《CNC and PLC Interface-ZH-CN》CHM（新代，2024-05-16 版）。
> **生成**：C / S / R 三张表由 `tools/chm_to_md.py` 从 CHM 直接抽取，不是手抄。
> **用途**：动手写一行之前，确认「这个地址能不能写、写了 CNC 认不认」。

---

## 1. 八类元件，各干一件事

| 段 | 定义 | 规格 | 数量 | 谁能改 |
|---|---|---|---|---|
| `I` | 实体输入接点（Input） | 依所选 I/O 卡，只有 On/Off 两态 | 依 I/O 卡 | 现场接线（阶梯只读） |
| `O` | 实体输出接点（Output） | 同上 | 依 I/O 卡 | **阶梯程序** |
| `A` | **虚拟辅助接点（Auxiliary）** | 只有 On/Off 两态 | `A0`~`A511` 共 512 个 | **阶梯程序** |
| `C` | 由阶梯图发送指令给核心 | 只有 On/Off 两态 | `C0`~`C511` 共 512 个 | **阶梯程序**（但每个都接到内核） |
| `S` | 由核心传送系统状态给阶梯图 | 只有 On/Off 两态 | `S0`~`S511` 共 512 个 | 控制器（**阶梯只读**） |
| `R` | 阶梯图与核心双向沟通 | 32 位元寄存器，可存数值，也可拆开成位元使用 | `R0`~`R65535`（DOS 仅 `R0`~`R7999`） | 按区段（见 §5） |
| `CT` | 虚拟辅助计数器（Counter） | 上数 / 下数 / 循环计数 | `CT0`~`CT255` 共 256 个 | 阶梯程序 |
| `TM` | 虚拟辅助计时器（Timer） | 1 秒 / 0.1 秒 / 0.01 秒 / 0.001 秒 | `TM0`~`TM255` 共 256 个 | 阶梯程序 |

一句话记住方向：**`C` 是你对核心说话，`S` 是核心对你说话，`A` 是自言自语，`R` 是两个人共用的白板。**

### 为什么中间继电器是 `A` 而不是 `R`

| | `A` | `R` |
|---|---|---|
| 设计用途 | 内部中间继电器，只有 On/Off | 32 位元数据寄存器，存取数值 |
| 取位 | 本身就是一位，`A5` 直接用 | 要把寄存器拆成位元，`R50.3` 是「借用」 |
| 掉电 | 不保证保持 | 分保持区 / 非保持区 |
| 真机语料（`cnc.lad` + `cnc_1.lad`） | 线圈 **541** 次 | 线圈 132 次：报警区 67、系统接口区 53、用户区 12 |

写 `R50.0` 当标志**能跑**，但那是在数据寄存器上抠一位用；同一件事用 `A0` 做，语义、注释、排查都对得上。
`check_write` 对 `R50.x` 这类写法给 warn；`validate` 会把它转成一条提示（不阻断保存）—— 能跑，但会建议改成 `A`。

> 语料里那 12 处 `R55.x` / `R59.0` / `R60.x` 就是「拿 R 当标志」的老写法：能运行，但和这份
> 手册的元件定义对不上。写新程序不要跟着学。

---

## 2. 内部标志到底放哪

| 想存什么 | 放哪 | 说明 |
|---|---|---|
| 中间继电器、过程标志（本次循环进行中、已建立压力…） | **`A0`~`A511`** | 512 点，随程序扫描 |
| **操作员该能改的参数**（打油时长、间隔、次数、位置…） | **`R81`~`R100`** | 对应系统参数 `3401`~`3420`，掉电保持，**阶梯只读** |
| 需要跨断电记住的**数值**（累计产量、配方号） | `R193`~`R255` | 手册定的掉电保持区，避开 `R103`~`R192` 的刀号 |
| 计数器 / 定时器 | `CT0`~`CT255` / `TM0`~`TM255` | 不要用 `A` 拼计数逻辑 |

`A` 段没有「掉电保持」这一说 —— 需要跨断电记住的东西是**数值**，本来就该放 `R` 的保持区。

### 参数区 `R81`~`R100`：一份梯形图适配不同机床

手册原文（1-1.4.4）：

> **R81~R100 MLC System Parameter** 由系统参数 No.3401 ~ No.3420 的 MLC 参数，
> 以规划同一个 LADDER 可适用于不同的机器上，如换刀….

所以「打油 30 秒」这种数字**不要写进程序**：操作员在参数画面把 3401 设成 300，程序读 `R81`。
换一台机床只改参数，梯形图原样不动。

| 参数号 | 寄存器 | 参数号 | 寄存器 |
|---|---|---|---|
| 3401 | `R81` | 3411 | `R91` |
| 3402 | `R82` | 3412 | `R92` |
| … | … | … | … |
| 3410 | `R90` | 3420 | `R100` |

映射是线性的：`R(n) = 3401 + (n - 81)`。

定时器 / 计数器的预设值可以直接指过来（`source:"R"` 时 `preset` 填寄存器号）：

```python
{"kind":"timer","name":"TM0","precision":"0.1s","source":"R","preset":"R81"}
```

方向是**单向**：参数画面 → `R81~R100` → 阶梯图。**阶梯图写它无效**（写它 `validate` 会点名，提示级、不阻断保存），
所以不要把这里当「掉电保持的标志位」用 —— 那是 `R193`~`R255`。

三条不能碰的红线：

- **`S` 段不能写。** 它是核心的输出，你写进去下一个扫描就被覆盖；更糟的是你可能写到 `S000`（加工中）、`S032`（Reset）这种位，读出来的状态直接是错的。
- **`C` 段不能当通用标志。** `C0` 起动加工、`C36` 急停、`C37` 外部复位、`C6` X 轴 JOG+ —— 随手拿 `C100` 当标志位，等于在给控制器下命令。
- **`R640` 起不能取位，工具也从 `R640` 起一律拒绝。** 手册标「位存取=否」的是 `R640~R1023` 整片、
  `R1000`~`R1014` 那几个单点、`R1024`~`R1032`、以及 `R1033` 起的整片。
  例外是 `R256`~`R511` —— 它**可**位存取（手册里与 `R103~R255` 是同一格），只是掉电不保持。
  写 `R1200.0` 编辑器不认，要位就用 `A`。

---

## 3. C 段全表（PLC → CNC，512 点）

`C` 是阶梯程序写给控制器的。带 ® 的位**同步实时处理**，其余位读入后进堆栈、按顺序异步处理 ——
时序敏感的信号（急停、复位、M/S/T 完成）都带 ®，这也是它们必须带 ® 的原因。

> 手册原文：所有 C 讯号将被同步实时读取，但只有 ® 标记的 C 讯号将被同步实时处理，
> 其他讯号被读取后将被放入堆栈中，然后按照顺序异步被处理。

<!-- BEGIN C -->
| 地址 | 名称 | 说明 |
|---|---|---|
| `C000` | Cycle Start | auto mode 下，此 bit ON 会起动加工 |
| `C001` | Feed Hold | 加工中，此 flag on，会暂停目前的加工状态 |
| `C002~C005` | （未定义） |  |
| `C006®` | X Axis JOG+ | JOG MODE 下，此 FLAG ON，机台会产生X+方向的运动 |
| `C007®` | X Axis JOG - | (同上) |
| `C008®` | Y Axis JOG + | (同上) |
| `C009®` | Y Axis JOG - | (同上) |
| `C010®` | Z Axis JOG+ | (同上) |
| `C011®` | Z Axis JOG - | (同上) |
| `C012®` | C(6th) Axis JOG + | (同上) |
| `C013®` | C(6th) Axis JOG - | (同上) |
| `C014~C015` | （未定义） |  |
| `C016` | X Axis MPG Selection | X 轴轴向手轮选择，此 FLAG ON 时，控制器会以 MPG 输入，驱动 X 轴走相对的位移 |
| `C017` | Y Axis MPG Selection | (同上) |
| `C018` | Z Axis MPG Selection | (同上) |
| `C019` | C(6th) Axis MPG Selection | (同上) |
| `C020` | MPG Simulation | Auto mode 下，此 bit ON，起动加工后,G00,G01,G02,G03的 FEEDRATE OVERRIDE 由 MPG 转动速度决定，转动越快，机台运动越快，MPG 停止，机台停止，非常适合机台上试加工 |
| `C021~C022` | （未定义） |  |
| `C023` | Rapid Traverse | CON JOG 下，按此键，机台的运动速度从 JOG SPEED 跳到 RAPID SPEED(G00)，同时接受面板 RAPID OVERRIDE |
| `C024` | （未定义） |  |
| `C025` | Set X Axis Machine Position | 设定轴向机械坐标，所填写的内容由R38决定。 |
| `C026` | Set Y Axis Machine Position | (同上) |
| `C027` | Set Z Axis Machine Position | (同上) |
| `C028` | Set C(6th) Axis Machine Position | (同上) |
| `C029~C030` | （未定义） |  |
| `C031` | X Axis MANUAL CONTROL | 轴向跳脱控制模式，进入回授监看模式，此时控制器无法再对轴向发送命令，若轴向因外力而移动，画面坐标也将随之更新。 串行轴向，如果需要把某些特定轴SERVO_OFF，可以通过此Cbit让串行轴向SERVO OFF 注意事项： 当轴向由回授监看模式切回控制模式时，若机台仍处于移动状态，导致零速检查失败(Pr901~)，系统将发出MOT-020/MOT-021警报，此时轴向需重新进行寻原点。 |
| `C032` | Y Axis MANUAL CONTROL | (同上) |
| `C033` | Z Axis MANUAL CONTROL | (同上) |
| `C034` | C(6th) Axis MANUAL CONTROL | (同上) |
| `C035` | Absolute Position Sync. | 若希望加工中暂停时，以任何手动方式(寸动、手轮、PLC轴等)带开机台的各轴移动量被保留，仅需在程序启动前，上缘触发此BIT。此时所有被移动轴向之移动量会同步到手轮偏置中，程序坐标回复到暂停时状态，程序启动后的加工路径会一直保留此移动量。 使用限制: 加工中、刀具回退功能执行中或O888801执行中触发此BIT，此功能无效。 兼容性异动： 10.114.50G~10.116.12间，上缘触发此BIT，主系统轴群将进行一次坐标同步。再之前版本，此BIT无作用。 |
| `C036` | Emergency Stop | 被压下，LADDER 应该触发这个 FLAG，控制器会暂停所有的机台运动，进入未就绪状态(NOT READY)，直到这个 FALG 解除，控制器内部会产生一个 RESET 动作 ，恢复就绪(READY)状态 |
| `C037` | External Reset | 外界对 CNC 发出 RESET 指令 |
| `C038` | M.S.T Finish | LADEER 在执行 M,S,T CODE 时，控制器会等到这个 FLAG ON 时，才会开始下一个 BLOCK 的执行，因此，LADDER 执行完 M,S,T CODE，需将此 FLAG ON 起来 |
| `C039` | Part count M-code stop request | 当此BIT ON时主程序的工件计数M-code就会暂停(B-STOP) 相关资料: 参数3804, S35 |
| `C040` | Single Block | 此 FLAG ON 时， G CODE 执行时，会走一个 BLOCK 即产生暂停，需再按 CYCLE START 才会再走下一个 BLOCK |
| `C041` | Optional Skip | 此 FLAG ON 时， 工件程序执行时，程序中若有写跳跃符号’/’，会跳过这一行，直接走下一个单节 |
| `C042` | Dry Run | 此 FLAG ON 时，执行 G CODE 会以空跑速度执行 |
| `C043` | Machine Lock | 此 FLAG ON 时，程序执行，程序会跑，但是机台不会动，通常用于程序检查 注：版本10.114.45, 10.115.46B, 10.115.48后取消C43功能 此功能先启动(C43 ON)下，对轴发命令，例：G91G00X100.，则轴不移动，且剩余距离与程序坐标正常显示，但机械坐标不改变。一直到此功能关闭时，系统会将机械坐标同步到程序坐标。 若是轴向移动中，此功能起启用(C43 ON)，则该轴不移动，且剩余距离与程序坐标正常显示，但机械坐标则在功能启用瞬间即停止。一直到此功能关闭时，系统会将机械坐标同步到程序坐标。 |
| `C044` | Optional Stop | 此 FLAG ON 时，执行到 M01 时，控制器会进入暂停状态，此 FLAG 不 ON 时，执行到 M01，控制器会忽略 M01，继续执行下一个 BLOCK |
| `C045` | Z Axis Lock | 此 FLAG ON 时，程序执行，程序会跑，但是Z轴不会动，通常用于程序检查 此功能先启动(C45 ON)下，对Z轴发命令，例：G91G00Z100.，则Z轴不移动，且剩余距离与程序坐标正常显示，但机械坐标不改变。一直到此功能关闭时，系统会将机械坐标同步到程序坐标。 若是轴向移动中，此功能起启用(C45 ON)，则Z轴不移动，且剩余距离与程序坐标正常显示，但机械坐标则在功能启用瞬间即停止。一直到此功能关闭时，系统会将机械坐标同步到程序坐标。 |
| `C046` | Axis Coupling Request | 第一组轴耦合状态开关，当Pr3825设定为非机构耦合时，实际耦合状态由此位决定，此 FLAG ON 时，耦合轴向就进入耦合状态，当此FLAG OFF 时，耦合轴向就离开耦合状态。耦合状态下，主动轴移动时，从动轴就会依设定比例运动。 |
| `C047` | Inhibit Persist State Flush | 此 FLAG ON 时，禁止系统对永久性数据做储存。但此 FLAG 由OFF变ON 时系统会强迫同步一次。 |
| `C048` | Wait Function Skip Signal | 所有主系统轴群跳过WAIT()指令，继续预解后续的加工程序 |
| `C049` | （未定义） |  |
| `C050` | Over Travel X+ | X轴机台正向硬件极限，此FLAG ON控制器会自动产生Feedhold，同时，开始不接受该方向的Jog指令或手轮指令，只能以反方向带出 |
| `C051` | Over Travel X- | (同上) |
| `C052` | Over Travel Y+ | (同上) |
| `C053` | Over Travel Y- | (同上) |
| `C054` | Over Travel Z+ | (同上) |
| `C055` | Over Travel Z- | (同上) |
| `C056` | Over Travel C(6th)+ | (同上) |
| `C057` | Over Travel C(6th)- | (同上) |
| `C058~C059` | （未定义） |  |
| `C060` | Spindle JOG Mode | C60 ON 时，会强迫主轴运转速度，以参数 1721 所设定的主轴定位漂移速度运转，此功能通常用于铣床主轴换刀、校模或是车床自动进料上 |
| `C061` | Spindle Orientation Stop | 10.114版本 C61 ON时，执行主轴定位功能，此功能必须在主轴侧装有位置编码器才有效，且必须等定位完成才可关掉C61。参数1741设定主轴定位的速度，主轴到达定位速度后，才开始侦测索引讯号；参数1751设定主轴定位偏移角度，此角度为相对于索引讯号的偏移角度，当更换马达、编码器、或皮带后，此参数必须重新校正；参数1761设定主轴定位时间；S61为主轴定位完成讯号。 10.116版本 C61 ON时，执行主轴定位功能，此功能必须在主轴侧装有位置编码器才有效，且必须等定位完成才可关掉C61。(1)当Pr1791=0时，主轴定位动作与114版本完全相同。 (2)当Pr1791=1~3时，初次定位动作跟寻原点相同，需设定对应轴向之寻原点方法为索引讯号(Pr96x = 1)，也可调整寻原点速度(Pr821~、Pr841~)。 (3)当Pr1791=1~3时，第二次以后的主轴定位动作跟主轴类型有关： a. 泛用主轴以及Pr1791=1~2的串行主轴，会使用Pr1801 / Pr1831的加速度进行转动，可在一圈内到达定位，定位角度则为Pr881~以及Pr1751~的和，建议Pr881~设为0。C61 on时，主轴会先停止，再由静止开始进行定位。 b. 串行主轴且Pr1791=3，使用Pr1801 / Pr1831的加速度进行转动，可在一圈内到达定位，定位角度则为Pr881~以及Pr1751~的和，建议Pr881~设为0。因全程为位置控制，因此控制器可直接将主轴定位至设定值，即使主轴正在高速运转。 (4)定位完成后，S61 on。 P.S.定位前，需开启变频器的位置控制模式。 使用限制： 攻牙模式下，此C Bit无作用。 |
| `C062®` | Skip Signal State | C62 ON时，量测逃脱指令G31会记录目前机械位置并中断G31动作，直接跳到下一个单节继续执行。 若程序中有多个G31要触发时，建议将C62使用上缘触发，避免多个G31在同一次的C62_ON内被跳脱。 |
| `C063` | Spindle OFF | 非变频主轴型态时(Pr1791~≠0)，此C BIT ON，表示主轴切换为位置控制模式，此时控制器将进行机械坐标同步(马达回授同步回机械坐标)；反之，C BIT OFF时，表示切回主轴速度控制模式，其正反转控制由C64/C65决定。 兼容性异动： 1. 10.116版之前，使用M码切换主轴C/S轴转换时，建议PLC中的C38需配合等待S63，以确保位置控制模式的正确性。 2. 9.x版之前，不使用C63即可进行位置控制模式切换，但须配合#1820先开启后关闭的行为，以进行坐标同步，确保机械坐标之正确性。 使用限制： 攻牙模式下，此C Bit无作用。 |
| `C064` | Rotating the spindle clockwise | 非变频主轴型态时(Pr1791~≠0)，此讯号为主轴正转命令 使用限制： 攻牙模式下，此C Bit无作用。 |
| `C065` | Rotating the spindle counterclockwise | 非变频主轴型态时(Pr1791~≠0)，此讯号为主轴反转命令 使用限制： 攻牙模式下，此C Bit无作用。 |
| `C066®` | X axis controlled by PLC | 1. 当此讯号为ON时，去执行PLC轴移动，NC程序的移动指令会考虑PLC轴的移动，也就是NC轴与PLC轴两者间会进行坐标同步，但此时PLC轴的移动速度不会被加成显示于人机。 2. 当此讯号为OFF时，去执行PLC轴移动，NC程序的移动指令不会考虑PLC轴的移动，但此时PLC轴的移动速度会被加成显示于人机。 3. 承2，由于此讯号为OFF，该轴向未被宣告成PLC控制，因此当模式切换时，该轴向PLC轴的移动行为会被中断。 4. 当NC程序与PLC轴同时对同一轴下命令时，该轴向的命令会有加成效应，使用者需特别注意。 |
| `C067®` | Y axis controlled by PLC | (同上) |
| `C068®` | Z axis controlled by PLC | (同上) |
| `C069®` | C axis(6th) controlled by PLC | (同上) |
| `C070` | （未定义） |  |
| `C071` | Enable MPG No1 | 当此讯号为ON时，第1号MPG的输入会被当作轴向位置命令，移动对应的轴向。 |
| `C072` | Enable MPG No2 | (同上) |
| `C073` | Enable MPG No3 | (同上) |
| `C074~C075` | （未定义） |  |
| `C076` | Clear MPG1 position | 当此讯号为ON时，第1号MPG的目前位置R6会被清除为零。 |
| `C077` | Clear MPG2 position | 当此讯号为ON时，第2号MPG的目前位置R7会被清除为零。 |
| `C078` | Clear MPG3 position | 当此讯号为ON时，第3号MPG的目前位置R8会被清除为零。 |
| `C079` | X HOME DOG | 从IO板读到HOME DOG讯号时，这个C BIT需要ON，所以LADDER里面需要加入此C BIT |
| `C080` | Y HOME DOG | (同上) |
| `C081` | Z HOME DOG | (同上) |
| `C082` | C(6th) HOME DOG | (同上) |
| `C083` | Stroke Limit Two Switch | 第三软件行程极限开关。Off：不保护；On：保护。请参考参数2441~2480进一步说明。(10.116.x之后的版本更名为第三软件行程极限) |
| `C084~C085` | （未定义） |  |
| `C086` | CHPST | On：Chopping启动；Off：Chopping停止。请参考参数3951~3955进一步说明。 |
| `C087` | CHLD | off：chopping暂停。请参考参数3951~3955进一步说明。 |
| `C088` | Disable Screen Saver | 解除屏幕保护(仅提供于CE系统) 有效版本：10.114.53, 10.115.55, 10.114.50C |
| `C089` | Edit inhibition | 禁止编辑程序模式，0:允许编辑程序，1:禁止编辑程序。 |
| `C090` | Program Edit Screen | 切换至程序编辑画面 |
| `C091` | Graph Dialog Screen | 切换至图形对话式画面 |
| `C092` | Monitor Screen | 切换至执行加工监控画面 |
| `C093` | Position Screen | 切换至位置监控画面 |
| `C094` | Tool Offset Screen | 切换至刀具设定画面 |
| `C095` | Tool Measure Screen | 切换至自动对刀画面 |
| `C096~C100` | （未定义） |  |
| `C101~C132` | Macro mapping variable | 对应到宏系统变量(#6001~#6032) |
| `C133` | Axis Exchange Request 1 | 第一组轴交换功能开关 Pr3721、Pr3722对应之两轴将进入轴交换状态 |
| `C134` | Axis Exchange Request 2 | 第二组轴交换功能开关 Pr3726、Pr3727对应之两轴将进入轴交换状态 |
| `C135` | Axis Exchange Request 3 | 第三组轴交换功能开关 Pr3731、Pr3732对应之两轴将进入轴交换状态 |
| `C136` | Axis Exchange Request 4 | 第四组轴交换功能开关 Pr3736、Pr3737对应之两轴将进入轴交换状态 |
| `C137~C139` | （未定义） |  |
| `C140` | 4th Axis OT + | 第四轴机台正向硬件极限，此FLAG ON控制器会自动产生Feedhold，同时，开始不接受该方向的Jog指令或手轮指令，只能以反方向带出。 |
| `C141` | 4th Axis OT - | (同上) |
| `C142` | 5th Axis OT + | (同上) |
| `C143` | 5th Axis OT - | (同上) |
| `C144` | 7th Axis OT + | (同上) |
| `C145` | 7th Axis OT - | (同上) |
| `C146` | 8th Axis OT + | (同上) |
| `C147` | 8th Axis OT - | (同上) |
| `C148` | 9th Axis OT + | (同上) |
| `C149` | 9th Axis OT - | (同上) |
| `C150` | 10th Axis OT + | (同上) |
| `C151` | 10th Axis OT - | (同上) |
| `C152` | 11th Axis OT + | (同上) |
| `C153` | 11th Axis OT - | (同上) |
| `C154` | 12th Axis OT + | (同上) |
| `C155` | 12th Axis OT - | (同上) |
| `C156` | 13th Axis OT + | (同上) |
| `C157` | 13th Axis OT - | (同上) |
| `C158` | 14th Axis OT + | (同上) |
| `C159` | 14th Axis OT - | (同上) |
| `C160` | 15th Axis OT + | (同上) |
| `C161` | 15th Axis OT - | (同上) |
| `C162` | 16th Axis OT + | (同上) |
| `C163` | 16th Axis OT - | (同上) |
| `C164~C169` | （未定义） |  |
| `C170®` | 4th Axis JOG + | JOG MODE 按面板第四轴JOG+的键，LADDER内这个 FLAG ON时，控制器就会产生此方向的运动 |
| `C171®` | 4th Axis JOG - | (同上) |
| `C172®` | 5th Axis JOG + | (同上) |
| `C173®` | 5th Axis JOG - | (同上) |
| `C174®` | 7th Axis JOG + | (同上) |
| `C175®` | 7th Axis JOG - | (同上) |
| `C176®` | 8th Axis JOG + | (同上) |
| `C177®` | 8th Axis JOG - | (同上) |
| `C178®` | 9th Axis JOG + | (同上) |
| `C179®` | 9th JOG - | (同上) |
| `C180®` | 10th Axis JOG + | (同上) |
| `C181®` | 10th Axis JOG - | (同上) |
| `C182®` | 11th Axis JOG + | (同上) |
| `C183®` | 11th Axis JOG - | (同上) |
| `C184®` | 12th Axis JOG + | (同上) |
| `C185®` | 12th Axis JOG - | (同上) |
| `C186®` | 13th Axis JOG + | (同上) |
| `C187®` | 13th Axis JOG - | (同上) |
| `C188®` | 14th Axis JOG + | (同上) |
| `C189®` | 14th Axis JOG - | (同上) |
| `C190®` | 15th Axis JOG + | (同上) |
| `C191®` | 15th Axis JOG - | (同上) |
| `C192®` | 16th Axis JOG + | (同上) |
| `C193®` | 16th Axis JOG - | (同上) |
| `C194~C199` | （未定义） |  |
| `C200` | 4th Axis Home Dog | 从IO板读到HOME DOG，LADDER 需触发此C BIT |
| `C201` | 5th Axis Home Dog | (同上) |
| `C202` | 7th Axis Home Dog | (同上) |
| `C203` | 8th Axis Home Dog | (同上) |
| `C204` | 9th Axis Home Dog | (同上) |
| `C205` | 10th Axis Home Dog | (同上) |
| `C206` | 11th Axis Home Dog | (同上) |
| `C207` | 12th Axis Home Dog | (同上) |
| `C208` | 13th Axis Home Dog | (同上) |
| `C209` | 14th Axis Home Dog | (同上) |
| `C210` | 15th Axis Home Dog | (同上) |
| `C211` | 16th Axis Home Dog | (同上) |
| `C212~C214` | （未定义） |  |
| `C215` | 4th Axis MPG Selection | 第四轴轴向手轮选择，此 FLAG ON 时，控制器会以 MPG 输入，驱动 第四轴 走相对的位移 |
| `C216` | 5th Axis MPG Selection | (同上) |
| `C217` | 7th Axis MPG Selection | (同上) |
| `C218` | 8th Axis MPG Selection | (同上) |
| `C219` | 9th Axis MPG Selection | (同上) |
| `C220` | 10th Axis MPG Selection | (同上) |
| `C221` | 11th Axis MPG Selection | (同上) |
| `C222` | 12th Axis MPG Selection | (同上) |
| `C223` | 13th Axis MPG Selection | (同上) |
| `C224` | 14th Axis MPG Selection | (同上) |
| `C225` | 15th Axis MPG Selection | (同上) |
| `C226` | 16th Axis MPG Selection | (同上) |
| `C227~C229` | （未定义） |  |
| `C230` | Set 4th Axis Machine Position | 设定轴向机械坐标，所填写的内容由R38决定。 |
| `C231` | Set 5th Axis Machine Position | (同上) |
| `C232` | Set 7th Axis Machine Position | (同上) |
| `C233` | Set 8th Axis Machine Position | (同上) |
| `C234` | Set 9th Axis Machine Position | (同上) |
| `C235` | Set 10th Axis Machine Position | (同上) |
| `C236` | Set 11th Axis Machine Position | (同上) |
| `C237` | Set 12th Axis Machine Position | (同上) |
| `C238` | Set 13th Axis Machine Position | (同上) |
| `C239` | Set 14th Axis Machine Position | (同上) |
| `C240` | Set 15th Axis Machine Position | (同上) |
| `C241` | Set 16th Axis Machine Position | (同上) |
| `C242~C244` | （未定义） |  |
| `C245` | 4th Axis MANUAL CONTROL | 轴向跳脱控制模式，进入回授监看模式，此时控制器无法再对轴向发送命令，若轴向因外力而移动，画面坐标也将随之更新。 注意事项： 当轴向由回授监看模式切回控制模式时，若机台仍处于移动状态，导致零速检查失败(Pr901~)，系统将发出MOT-020/MOT-021警报，此时轴向需重新进行寻原点。 |
| `C246` | 5th Axis MANUAL CONTROL | (同上) |
| `C247` | 7th Axis MANUAL CONTROL | (同上) |
| `C248` | 8th Axis MANUAL CONTROL | (同上) |
| `C249` | 9th Axis MANUAL CONTROL | (同上) |
| `C250` | 10th Axis MANUAL CONTROL | (同上) |
| `C251` | 11th Axis MANUAL CONTROL | (同上) |
| `C252` | 12th Axis MANUAL CONTROL | (同上) |
| `C253` | 13th Axis MANUAL CONTROL | (同上) |
| `C254` | 14th Axis MANUAL CONTROL | (同上) |
| `C255` | 15th Axis MANUAL CONTROL | (同上) |
| `C256` | 16th Axis MANUAL CONTROL | (同上) |
| `C257~C259` | （未定义） |  |
| `C260®` | 4th axis controlled by PLC | 当此讯号为ON时，加工中X轴就不受CNC工件程控，直接接受PLC阶梯程控。当此讯号为OFF时，X轴就回到CNC工件程控模式，加工中不受PLC阶梯程控，如果PLC阶梯程序在此时发出移动命令，控制器就会发出命令相冲突警报。 |
| `C261®` | 5th axis controlled by PLC | (同上) |
| `C262®` | 7th axis controlled by PLC | (同上) |
| `C263®` | 8th axis controlled by PLC | (同上) |
| `C264®` | 9th axis controlled by PLC | (同上) |
| `C265®` | 10th axis controlled by PLC | (同上) |
| `C266®` | 11th axis controlled by PLC | (同上) |
| `C267®` | 12th axis controlled by PLC | (同上) |
| `C268®` | 13th axis controlled by PLC | (同上) |
| `C269®` | 14th axis controlled by PLC | (同上) |
| `C270®` | 15th axis controlled by PLC | (同上) |
| `C271®` | 16th axis controlled by PLC | (同上) |
| `C272~C273` | （未定义） |  |
| `C274` | Enable MPG No4 | 当此讯号为ON时，第4号MPG的输入会被当作轴向位置命令，移动对应的轴向。 |
| `C275` | Enable MPG No5 | 当此讯号为ON时，第5号MPG的输入会被当作轴向位置命令，移动对应的轴向。 |
| `C276` | Enable MPG No6 | 当此讯号为ON时，第6号MPG的输入会被当作轴向位置命令，移动对应的轴向。 |
| `C277` | Enable MPG No7 | 当此讯号为ON时，第7号MPG的输入会被当作轴向位置命令，移动对应的轴向。 |
| `C278~C283` | （未定义） |  |
| `C284` | Clear MPG4 position | 当此讯号为ON时，第4号MPG的目前位置R9会被清除为零。 |
| `C285` | Clear MPG5 position | 当此讯号为ON时，第5号MPG的目前位置R10会被清除为零。 |
| `C286` | Clear MPG6 position | 当此讯号为ON时，第6号MPG的目前位置R11会被清除为零。 |
| `C287` | Clear MPG7 position | 当此讯号为ON时，第7号MPG的目前位置R12会被清除为零。 |
| `C288~C300` | （未定义） |  |
| `C301` | Enable 1st ECam | 启用第1组电子凸轮。此Bit On时，开始执行设定好的第1组电子凸轮，启动之后会亮起同号码之S Bit；此Bit Off时，会加工完此组凸轮中的所有曲线后才停止。 |
| `C302` | Enable 2nd ECam | (同上) |
| `C303` | Enable 3rd ECam | (同上) |
| `C304` | Enable 4th ECam | (同上) |
| `C305` | Enable 5th ECam | (同上) |
| `C306` | Enable 6th ECam | (同上) |
| `C307` | Enable 7th ECam | (同上) |
| `C308` | Enable 8th ECam | (同上) |
| `C309~C316` | （未定义） |  |
| `C317~C400` | （未定义） |  |
| `C401~C488` | Standard keyboard Scan Code | 对应到标准键盘扫描码1~88 |
| `C489` | OEM extended key | 应用程序自行定义的扩充键89-111， 其意义由个别应用自行定义。 对应到PC键盘ALT-1键 |
| `C490~C511` | （未定义） |  |
<!-- END C -->

---

## 4. S 段全表（CNC → PLC，512 点）

这张表里没有一个点可供用户使用，全部由控制器写。写程序时只能把它们当**输入触点**读。

常用的几个：

| 位 | 含义 | 典型用法 |
|---|---|---|
| `S000` | 加工中（BUSY） | 加工中禁止手动动作 |
| `S001` | 暂停中（FEED HOLD） | 暂停时松开夹紧要谨慎 |
| `S029` | M Code Read | 读到 M 码，去 `R1` 取值 |
| `S031` | Alarm | 控制器报警 |
| `S032` | Reset | 按了 RESET（单脉冲） |
| `S033` | NC Ready | 开机完成且系统正常 |
| `S006`/`S007`/`S008` | X/Y/Z 轴 Busy | 手动命令前先看轴是否空闲 |
| `S016`/`S017`/`S018` | 各轴回原点完成 | 未回原点不允许起动加工 |

<!-- BEGIN S -->
| 地址 | 名称 | 说明 |
|---|---|---|
| `S000` | Cycle Start Light | 加工中(BUSY)，此 FLAG会 ON |
| `S001` | Feed Hold Light | 暂停中(FEEDHOLD)，此 FLAG 会 ON |
| `S002` | Block stop | 单节停止中(BLOCK STOP)，此 FLAG 会 ON |
| `S003` | Feedhold inhibit | 当此FLAG为ON，表示目前为禁止暂停状态 |
| `S004` | Rigid Tapping | 第一主轴正在刚攻模式 |
| `S005` | （未定义） |  |
| `S006` | X Axis Busy | 当此FLAG为ON时表示X轴手动功能(手轮/JOG/寻原点/PLC轴)正在执行中，无法接受新的手动命令，当此FLAG为OFF，表示X轴在Idle状态，允许接受新的手动命令 |
| `S007` | Y Axis Busy | (同上) |
| `S008` | Z Axis Busy | (同上) |
| `S009` | C(6th) Axis Busy | (同上) |
| `S010` | （未定义） |  |
| `S011` | 2nd of Multiple M code read | 当参数3810(启动同一单节M code同时执行功能)设定为1时，控制器执行到同一单节第二个M code时，此 FLAG会ON，同时告诉LADDER要执行M code，M code的内容则放在R2051，控制器发出此 FLAG 后，一直要等到 M code FIN 的 C BIT FLAG ON 后，才会开始执行下一个 BLOCK |
| `S012` | 3rd of Multiple M code read | (同上，M code 的内容放在 R2052) |
| `S013` | 4th of Multiple M code read | (同上，M code 的内容放在 R2053) |
| `S014` | 5th of Multiple M code read | (同上，M code 的内容放在 R2054) |
| `S015` | （未定义） |  |
| `S016` | X Axis Home OK | X Homing OK，X 轴寻过原点，这个 FLAG 会 ON，软件行程极限保护在寻过原点后，才会被起动，因此写 LADDER 的人，应该在这个 S BIT FLAG 没有被 ON 的情况下，不允许起动加工，同时发出未寻原点的警报讯息 |
| `S017` | Y Axis Home OK | (同上) |
| `S018` | Z Axis Home OK | (同上) |
| `S019` | C(6th) Axis Home OK | (同上) |
| `S020~S028` | （未定义） |  |
| `S029` | M Code Read | 控制器执行到M CODE 时,此 FLAG会 ON，同时告诉LADDER要执行M CODE，M CODE 的内容则放在 R1，控制器发出此 FLAG 后，一直要等到 M CODE FIN 的 C BIT FLAG ON 后，才会开始执行下一个 BLOCK |
| `S030` | Distribution End | MOTION G 执行完一个 BLOCK 会发出 DEN 的讯号，通常用于 G,M CODE 同动的场合 |
| `S031` | Alarm | 控制器内部发生警报时，致必须Feedhold时，会发出这个 S BIT，如轴卡饱和，超出软件行程极限 |
| `S032` | Reset | 面板按 RESET 时，这个 FLAG 会产生 ONE SHOT 的讯息 |
| `S033` | NC Ready | 开机完成，且系统正常,会发出 NC READY FLAG |
| `S034` | Require Part Count Reached | 当需求工件数到达时，这个S FLAG会ON，当Cycle Start或Reset时此FLAG会变为OFF |
| `S035` | The part count M-code in main program | 当主程序执行到工件计数M-code时会将此FLAG ON/OFF一个脉冲 相关资料: 参数3804, C39 |
| `S036` | In Guidance Mode | 当CNC处于Guidance Function模式下此BIT会ON |
| `S037` | Loss data | 当用户数据遗失，此Bit会ON |
| `S038~S040` | （未定义） |  |
| `S041` | PLC Alarm | PLC有警报时，此旗标会ON，当PLC警报都消失时，此旗标会OFF。这旗标只有在WinCE系统才有效。 R40~R49的前16位(R4x.0~R4x.15)为PLC警报讯息，16位后的为PLC警告讯息，不会触发S41。 |
| `S042~S052` | （未定义） |  |
| `S053` | B Code Read | 此功能由参数3806启动 控制器执行到 B CODE 时，此 FLAG 会 ON，同时告诉 LADDER 要执行 B CODE，B CODE 的内容则放在 R5，控制器发出此 FLAG 后，一直要等到 B CODE FINISH 的 C BIT FLAG ON 后(C38)，才会开始执行下一个 BLOCK |
| `S054` | S Code Read | 控制器执行到 S CODE 时，此 FLAG 会 ON，同时告诉 LADDER 要执行 S CODE，S CODE 的内容则放在 R2，控制器发出此 FLAG 后，一直要等到 S CODE FIN 的 C BIT FLAG ON 后，才会开始执行下一个 BLOCK |
| `S055~S058` | （未定义） |  |
| `S059` | Spindle Threading Speed Arrival | 车牙时主轴转速到达讯号 |
| `S060` | Spindle Super Imposition Finish | 主轴乘载完成讯号 |
| `S061` | Spindle Orientation Stop Finish | 主轴定位完成讯号 |
| `S062` | Spindle Synchronization Finish | 主轴速度/相位同步完成讯号 |
| `S063` | Spindle axis mode | 当此 S BIT ON 时，表示主轴在位置控制模式；当此 S BIT OFF 时，表示主轴在主轴速度控制模式。 |
| `S064` | Spindle Cutting Speed Arrival | 切削时主轴转速到达讯号 |
| `S065~S068` | （未定义） |  |
| `S069` | T Code Read | 控制器执行到 T CODE 时，此 FLAG 会 ON，同时告诉 LADDER 要执行 T CODE，T CODE 的内容则放在 R3,控制器发出此 FLAG 后，一直要等到 T CODE FIN 的 C BIT FLAG ON 后，才会开始执行下一个 BLOCK |
| `S070` | At start point | 当此讯号为ON时表示目前正在加工起始点。 |
| `S071` | At end point | 当此讯号为ON时表示目前正在加工起终点。 |
| `S072~S079` | （未定义） |  |
| `S080` | M00 Signal | M00读取旗标。此旗标在M码读取后，将自动启用，直到系统重置(Reset)或是M Code Finish(C38 On)。 注意： 1. 有效版本：10.114.56U, 10.116.0R, 10.116.10C, 10.116.13 2. 仅支持第一MST通道 3. 为确保系统正确启用此旗标，建议PLC应用时，C38需Off直到核心将此旗标启用。 |
| `S081` | M01 Signal | M01读取旗标。选择性暂停功能(C44)启用下，此旗标在M码读取后，将自动启用，直到系统重置(Reset)或是M Code Finish(C38 On)。 注意：同S080。 |
| `S082` | M02 Signal | M02读取旗标。此旗标在M码读取后，将自动启用，直到系统重置(Reset)或是M Code Finish(C38 On)。 注意：同S080。 |
| `S083` | M30 Signal | M30读取旗标。此旗标在M码读取后，将自动启用，直到系统重置(Reset)或是M Code Finish(C38 On)。 注意：同S080。 |
| `S084~S095` | （未定义） |  |
| `S096` | Screen Saver is Running | 屏幕保护程序是否启动。当屏幕保护程序启动时，此Bit为True；当屏幕保护程序关闭时，此Bit为False。 |
| `S097` | Exe File CRC error | 当此讯号为ON时，表示系统特定档案CRC检查错误。一般会发生此状况，可能是对系统遭受病毒干染且无法复原，相关记录将被储存于C:\CRC_Chk.log。 兼容性异动： 有效版本始于10.114.52。 |
| `S098` | OCAPI Server is Running | OCAPIServer是否启动。当OCAPIServer启动时，此Bit设为True；当OCAPIServer关闭时，此Bit设为False。 |
| `S099` | Dipole connection in use | 是否正在进行Dipole联机。当有任何远程程序联机至核心时，此Bit设为1；无远程程序联机时，此Bit设为0。 |
| `S100` | DOS USB in use | on: DOS USB in use; off: DOS USB not in use. |
| `S101~S132` | （未定义） | 对应到宏系统变量(#6001~#6032) |
| `S133` | Axis Exchange Status 1 | 第一组轴交换成功旗标 系统内部完成轴交换，此状态才改变 |
| `S134` | Axis Exchange Status 2 | 第二组轴交换成功旗标 系统内部完成轴交换，此状态才改变 |
| `S135` | Axis Exchange Status 3 | 第三组轴交换成功旗标 系统内部完成轴交换，此状态才改变 |
| `S136` | Axis Exchange Status 4 | 第四组轴交换成功旗标 系统内部完成轴交换，此状态才改变 |
| `S137~S139` | （未定义） |  |
| `S140` | 4th Axis Home OK | 第四轴 Homing OK， 第四轴寻过原点,这个 FLAG 会 ON，软件行程极限保护在寻过原点后，才会被起动，因此写 LADDER 的人，应该在这个 S BIT FLAG 没有被 ON 的情况下，不允许起动加工，同时发出未寻原点的警报讯息 |
| `S141` | 5th Axis Home OK | (同上) |
| `S142` | 7th Axis Home OK | (同上) |
| `S143` | 8th Axis Home OK | (同上) |
| `S144` | 9th Axis Home OK | (同上) |
| `S145` | 10th Axis Home OK | (同上) |
| `S146` | 11th Axis Home OK | (同上) |
| `S147` | 12th Axis Home OK | (同上) |
| `S148` | 13th Axis Home OK | (同上) |
| `S149` | 14th Axis Home OK | (同上) |
| `S150` | 15th Axis Home OK | (同上) |
| `S151` | 16th Axis Home OK | (同上) |
| `S152~S154` | （未定义） |  |
| `S155` | 4th Axis Busy | 当此FLAG为ON时表示X轴正在执行中，无法接受新的命令，当此FLAG为OFF表示X轴在Idle状态，允许接受新的命令 |
| `S156` | 5th Axis Busy | (同上) |
| `S157` | 7th Axis Busy | (同上) |
| `S158` | 8th Axis Busy | (同上) |
| `S159` | 9th Axis Busy | (同上) |
| `S160` | 10th Axis Busy | (同上) |
| `S161` | 11th Axis Busy | (同上) |
| `S162` | 12th Axis Busy | (同上) |
| `S163` | 13th Axis Busy | (同上) |
| `S164` | 14th Axis Busy | (同上) |
| `S165` | 15th Axis Busy | (同上) |
| `S166` | 16th Axis Busy | (同上) |
| `S171~S186` | Servo Alarm State | 轴卡端口警报状态。 若使用泛用驱动器，当对应的轴卡端口有警报讯号输入时，S Bit Off；若使用串行驱动器，当出现驱动器警报时，对应的S bit On。 S171：泛用对应第1端口，串行对应驱动器局号设定 S172：泛用对应第2端口，串行对应驱动器局号设定 … S186：泛用对应第16端口，串行对应驱动器局号设定 例：串行环境下，当局号设定3的驱动器出现警报时，S173会On。 注意事项： 槽式机箱Servo6轴卡不支持此功能。 |
| `S190~S320` | （未定义） | (系统保留区) |
| `S301` | 1st ECam Busy | 第1组电子凸轮作用中。此Bit On时，表示第1组电子凸轮正在作用中；此Bit Off时，主、从轴之间的凸轮关系运动取消。 |
| `S302` | 2nd ECam Busy | (同上) 此Bit On时，表示第1组电子凸轮正在作用中；此Bit Off时，主、从轴不依凸轮关系动作。 |
| `S303` | 3rd ECam Busy | (同上) |
| `S304` | 4th ECam Busy | (同上) |
| `S305` | 5th ECam Busy | (同上) |
| `S306` | 6th ECam Busy | (同上) |
| `S307` | 7th ECam Busy | (同上) |
| `S308` | 8th ECam Busy | (同上) |
| `S321~S400` | （未定义） | SBit对应键盘扫描码，目前仅开放S355~S374 |
| `S401~488` | Keyboard Scan Code | 对应到键盘扫描码1~88 |
| `S511` | Reserved for CNC | 系统保留区 |
<!-- END S -->

---

## 5. R 寄存器分配表（0~65535）

| 列 | 含义 |
|---|---|
| 宏程序 / 人机界面 | 宏程序、人机界面（HMI）能不能读 / 写这个区 |
| 阶梯程序 | **梯形图**能不能读 / 写这个区 —— 写代码只看这一列 |
| 位存取 | 能不能用 `R50.0` 这种按位写法。**「否」的区只能整字读写** |
| 掉电保持 | 断电后值是否保留 |

> 这两列权限**不是一回事**：`R8000~R8255` 宏程序可读写，阶梯程序只读；`R20000~R65535`
> 反过来，宏程序只读、阶梯程序可读写。所以判断「我的梯形图能不能写」永远看**阶梯程序**那一列，
> 不要拿宏程序那列顶替。

<!-- BEGIN R -->
| 编号 | 说明 | 宏程序/人机界面 | 阶梯程序 | 位存取 | 掉电保持 |
|---|---|---|---|---|---|
| `R0~R39` | CNC系统接口区 | 只读 | 依下表 定义之 | 是 | 否 |
| `R40~R49` | PLC警报讯息区 | 只读 | 依下表 定义之 | 是 | 否 |
| `R50~R80` | 使用者自行定义 | 读/写 | 读/写 | 是 | 否 |
| `R81~R100` | 对应到系统参数3401~3420 | 只读 | 只读 | 是 | 是 |
| `R101~R102` | 刀具状态(储存于IO卡) | 读/写 | 读/写 | 是 | 是 |
| `R103~R255` | 使用者自行定义 (R103~R192对应铣床刀号数据T1~T90；R103~R255储存于IO卡) | 读/写 | 读/写 | 是 | 是 |
| `R256~R511` | 使用者自行定义（手册与上一行合并成一格） | 读/写 | 读/写 | 是 | 否 |
| `R512~R639` | CNC系统接口区 | 只读 | 依下表 定义之 | 是 | 否 |
| `R640~R1023` | CNC系统接口区（手册与上一行合并成一格） | 只读 | 依下表 定义之 | 否 | 否 |
| `R1000` | 总工作数 | 读/写 | 只读 | 否 | 是 |
| `R1002` | 需求工作数 | 读/写 | 只读 | 否 | 是 |
| `R1013` | 累计加工时间 | 只读 | 只读 | 否 | 是 |
| `R1014` | 累计开机时间 | 只读 | 只读 | 否 | 是 |
| `R1024~R1032` | 铣床自动分中/自动对刀占用，车床为使用者自行定义区 | 读/写 | 读/写 | 否 | 否 |
| `R1033~R2049` | 使用者自行定义 | 读/写 | 读/写 | 否 | 否 |
| `R2050~R2090` | Pr3810=0为使用者自行定义 | 读/写 | 读/写 | 否 | 否 |
| `R2050~R2090` | Pr3810=1为多个M Code同时执行功能占用 | 读 | 读/写 | 否 | 否 |
| `R2091~R2099` | 使用者自行定义 | 读/写 | 读/写 | 否 | 否 |
| `R2100~R3100` | Pr3228=0为使用者自行定义 | 读/写 | 读/写 | 否 | 否 |
| `R2100~R3100` | Pr3228=1为刀具管理功能占用 | 读/写 | 读/写 | 否 | 是 |
| `R3101~R4095` | 使用者自行定义 | 读/写 | 读/写 | 否 | 否 |
| `R4096~R5999` | CNC系统接口区 | 只读 | 依下表 定义之 | 否 | 否 |
| `R6000~R7999` | 使用者自行定义(储存于IO卡) | 读/写 | 读/写 | 否 | 是 |
| `R8000~R8255` | CNC系统接口区 | 读/写 | 只读 | 否 | 是 |
| `R8256~R9999` | CNC系统接口区 | 只读 | 只读 | 否 | 否 |
| `R10000~R10999` | CNC系统加值应用记忆区 | 读/写 | 读/写 | 否 | 是 |
| `R11000~R14999` | CNC系统接口区 | 只读 | 只读 | 否 | 否 |
| `R15000~R19999` | CNC系统加值应用非记忆区 | 读/写 | 读/写 | 否 | 否 |
| `R20000~R65535` | 使用者自行定义 | 只读 | 读/写 | 否 | 否 |

> 注：手册原文在 `R1014` 处多列了一行「安装累计加工时间」，编号与上一行相同。现场核对确认这是排版错误，已略去。
<!-- END R -->

> 注 1：`R40`~`R49` 是 PLC 警报讯息区，前 16 位（`R4x.0`~`R4x.15`）是警报、之后是警告；
> 有警报时 `S041` 会 ON（仅 WinCE 系统）。**报警就写这一段，别自己找地方**。
> 这一行在原表里与 `R0~R39` 是同一格（`rowspan`），权限继承下来是「阶梯依下表定义之、可位存取」，
> 与 `S041` 的 ON/OFF 完全由这一段决定的说法也对得上。
>
> 注 2：`R256~R511` 同样是从 `R103~R255` 那一格 `rowspan` 下来的 —— **阶梯可读可写、可位存取**，
> 只是掉电**不保持**。所以 `R300` 这种「模拟量转存」的写法是合法的；要跨断电记住就往下放 `R1033` 以后的区。
> 别被残缺行误导成保留区（这份表早期版本就误判过）。

> 注 3：`R640~R1023` 也是合并格，位存取明写「否」—— **整片不能取位**（`R700.0` 越界）。
> 权限同样逐条看 1-1.4.4，见注 4。这一片大多是回读的系统量（`R1000` 总工作数、
> `R1013`/`R1014` 累计时间），但也有 `R831~R840` MLC 参数、`R1020~R1023` PLC 文件系统
> 这类要写的。

> 注 4：`R512~R1023` 那一列写「依下表定义之」，意思是权限在 1-1.4.4「接口说明」里逐条定义，
> **不是整片只读**。整片判只读会漏掉 `R590~R599`（PLC 提示讯息）、`R603`（禁止轴移动）
> 这些天天要写的接口位。已按手册逐条展开成 `src/syntec_r_iface.py`，`check_write` 直接查它：
>
> | 结论 | 例子 |
> |---|---|
> | 阶梯可写 | `R590~R599` 提示讯息、`R603` 禁止轴移动、`R520/R522~R525` 轴群命令、`R641~R656` 手轮倍率、`R831~R840` MLC 参数 |
> | 阶梯只读 | `R512~R517` 网络与警报、`R521` 轴群状态、`R526` 单节剩余距离、`R700` 合成进给实际值、`R1004` 总工件数 |
> | 保留（提示不阻断） | `R519`、`R560~R579`、`R631~R639`、`R845~R850`、`R926` |
> | 手册未列明（不判定） | `R640`、`R938~R940` 等 86 个 |
>
> **未列明 ≠ 保留**：自己写程序别用，但审别人的程序时用了不算错 —— `R938~R940` 就是
> 现场用起来的例子，手册版本可能比 CNC 版本旧。`R640` 以上还多一条：位存取=否，
> `R700.0` 这种写法本身就越界。

---

## 6. 常见误用

| 写法 | 后果 | 正确做法 |
|---|---|---|
| `COIL("S0","LATCH")` 当打油请求 | 与「加工中」信号短接，逻辑全错；写的值被控制器覆盖 | `A0` |
| `COIL("C100")` 当中间位 | 给 CNC 发了一条未知命令，可能触发动作 | `A0` |
| `COIL("R50.0","LATCH")` 当中间位 | 能跑，但语义是「数据寄存器里的一位」，不是中间继电器 | `A0` |
| `NO("R1200.0")` | 该区不支持位存取，编辑器不认 | `A0` |
| 写 `R30`（CNC 接口区） | 只读，写入无效 | 读可以，写数值用 `R` 用户区 |
| 写 `A512` 以上 | 编号只编 9 位，会截断成另一个地址 | `A0`~`A511` 之内 |
| `COIL("R81")` 存参数 | 那是「参数 → 阶梯图」的单向传入区，写了不生效 | 读它；改参数去参数画面 `3401`~`3420` |
| 参数写死在程序里（`preset:300`） | 换台机床就得改程序、重新验证 | 放 `R81`~`R100`，用 `source:"R"` 读 |
| 参数存 `R50`~`R80` | 掉电不保持，断电后参数回零 | `R81`~`R100` |
| 同一地址既当输入又当输出 | `.lad` 里合法，现场表现为「信号自己抖动」 | 输入只读、状态另存 `A0` |

判定入口是 `syntec_address_db.check_write`，它返回 `('error' | 'warn', 说明)`。
对照上面这张表，实际判定是这样（逐条跑过）：

| 写法（上表行号） | `check_write` 判定 |
|---|---|
| 1 写 `S` 当请求位 | `error` |
| 2 `C100` 当中间位 | `warn`（地址库里没有这个编号，但「没有记录」不等于「一定是空位」） |
| 3 `R50.0` 当中间位 | `warn`（能跑，只是不规范） |
| 4 `R1200.0` | `error`（该区不支持位存取） |
| 5 写 `R30` | `error`（CNC 系统接口区只读） |
| 6 写 `A512` | `error`（编号越界，会被截断成别的地址） |
| 7 写 `R81` | `error`（参数传入区只读） |
| 8 参数写死在程序里 | **不查**，纯设计建议，工具不会提醒 |
| 9 参数存 `R50`~`R80` | **不查**（`R50` 确实可写，掉电不保持是靠人记住） |
| 10 同址既当输入又当输出 | **不查**，得靠人看 |

> ⚠️ 表里的 `error` / `warn` 是 `check_write` 自己的分级。**`validate` 会把它抹平成统一的一句话提示**，
> 既不区分级别、也不阻止 `save`。所以「validate 没报错」≠「编辑器也会放过」——
> 真正的拦截在编辑器那边，工具这侧只能提示。

> 注 5：轴向表的 16 个轴，地址是 **三位数**（`R701`~`R716` 各轴单轴速度、
> `R721`~`R736` 程序坐标、`R741`~`R756` 机械坐标、`R901`~`R916` 温度补偿量）。
> 轴号要补零，不是 `R71`~`R79`。`R50`~`R80` 是使用者自订区，
> 别把 `R73`/`R76` 查成「轴 3 / 轴 6 速度」——地址库早期就是这么拼错的。
