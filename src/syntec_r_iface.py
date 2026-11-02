# -*- coding: utf-8 -*-
"""R512~R1023 逐条权限（1-1.4.4「接口说明」的 PLC 读写规则列）。

本文件由 tools/gen_r_perm_table.py 生成，不要手改。
区段表 1-1.4.3 对这一段写的是「依下表定义之」——整片判只读会误报 49 条，
整片判可写会放过写状态寄存器。所以权限必须逐条查。

四类：
  WRITE      阶梯可写（手册明写唯写/读写，或按用途推定）
  READONLY   阶梯只读（手册明写只读，或是核心回报的状态量）
  RESERVED   手册明写保留——写进去行为未定义，但只提示不阻断
  UNDEFINED  手册没定义——**不判定**。写程序时别用，审别人的程序时用了不算错，
             手册版本可能比 CNC 版本旧（R938~R940 就是实例）。
"""

# 阶梯可写
WRITE = [
    (518, 518, 'Manuel Coordinate'),
    (520, 520, 'First Axis Group Control Registers'),
    (522, 525, 'First Axis Group Control Registers'),
    (530, 530, 'Second Axis Group Control Registers'),
    (532, 535, 'Second Axis Group Control Registers'),
    (540, 540, 'Third Axis Group Control Registers'),
    (542, 545, 'Third Axis Group Control Registers'),
    (550, 550, 'Fourth Axis Group Control Registers'),
    (552, 555, 'Fourth Axis Group Control Registers'),
    (580, 580, 'Spindle PLC Control Mode'),
    (581, 581, 'Spindle OFF'),
    (583, 583, 'Rotating the spindle clockwise'),
    (584, 584, 'Rotating the spindle counterclockwise'),
    (585, 585, 'Spindle JOG Mode'),
    (586, 586, 'Spindle Orientation Stop'),
    (590, 599, 'PLC warning message'),
    (600, 600, 'Machine Lock'),
    (601, 601, 'Axis MPG simulation'),
    (602, 602, 'Spindle Y-Delta Request Mode'),
    (603, 603, 'Inhibit Axis Command'),
    (604, 604, 'Teach In command'),
    (605, 605, 'Tool Offset Write'),
    (606, 606, 'MPG Shift'),
    (608, 608, 'Modbus PLC Communication'),
    (612, 612, 'Machine Positive Direction Lock'),
    (613, 613, 'Machine Negiaive Direction Lock'),
    (614, 614, 'Axis Coupling Request'),
    (615, 618, 'Second M/S/T Execution Channel'),
    (619, 622, 'Third M/S/T Execution Channel'),
    (623, 626, 'Fourth M/S/T Execution Channel'),
    (627, 627, 'Axis Torque Mode'),
    (630, 630, 'Axis M code complete（见 R629）'),
    (641, 656, 'Axis MPG command multiplier ratio'),
    (661, 676, 'PLC axis program G00/G01 feedrate overri'),
    (782, 786, 'Spindle Gear Selection'),
    (791, 794, 'Effective Spindle Selection'),
    (831, 840, 'MLC System Parameter'),
    (851, 856, 'Spindle Override'),
    (880, 895, 'Reference Value for D/A of Asix Card or '),
    (900, 900, 'Data Acquisition Trigger'),
    (901, 916, 'Axis temperature compensation amount'),
    (920, 920, 'EDM discharge enable.'),
    (921, 921, 'EDM control mode'),
    (922, 922, 'EDM normal ON time'),
    (923, 923, 'EDM normal OFF time'),
    (924, 924, 'EDM arc ON time'),
    (925, 925, 'EDM arc OFF time'),
    (934, 937, 'MPG: 1: x1 2: x10 3: x100 4: x根据系统参数2001'),
    (941, 946, 'PLC Spindle Command'),
    (1019, 1019, 'PLC Version'),
    (1020, 1023, 'PLC File System'),
]

# 阶梯只读
READONLY = [
    (512, 512, 'Net Ready'),
    (513, 513, 'Net Timeout'),
    (514, 514, 'Pending alarm module ID'),
    (515, 515, 'Pending alarm ID'),
    (516, 516, 'Pending alarm Axis ID'),
    (517, 517, 'Pending alarm Spindle ID'),
    (521, 521, 'First Axis Group Control Registers'),
    (526, 526, 'First Axis Group Control Registers'),
    (531, 531, 'Second Axis Group Control Registers'),
    (536, 536, 'Second Axis Group Control Registers'),
    (541, 541, 'Third Axis Group Control Registers'),
    (546, 546, 'Third Axis Group Control Registers'),
    (551, 551, 'Fourth Axis Group Control Registers'),
    (556, 556, 'Fourth Axis Group Control Registers'),
    (582, 582, 'Spindle axis mode'),
    (587, 587, 'Spindle Orientation Stop Finish'),
    (588, 588, 'Rigid Tapping Mode'),
    (589, 589, 'Multiple Axis Group MST associated infor'),
    (607, 607, 'Spindle Speed Arrival'),
    (609, 609, 'Axis Coupling Status'),
    (610, 610, 'Skip Position Latched'),
    (611, 611, 'Axis Movement Flag'),
    (628, 628, 'Spindle CSS Mode'),
    (629, 629, 'Axis M code'),
    (681, 696, 'PLC axis M code value'),
    (700, 700, 'Actual compound feedrate'),
    (701, 716, 'Axis Velocity'),
    (721, 736, 'Program Coordinate'),
    (741, 756, 'Machine Coordinate'),
    (761, 766, 'Spindle Machine Position'),
    (771, 776, 'Spindle Speed'),
    (801, 830, 'MLC System Parameter'),
    (841, 844, 'Cause of Block Stop'),
    (861, 870, 'Break point machine position'),
    (871, 876, 'Spindle Effective Speed Command'),
    (896, 899, 'A/D value'),
    (927, 927, 'Total Discharge Count'),
    (928, 928, 'Normal Discharge Count'),
    (929, 929, 'Abnormal Discharge Count'),
    (951, 951, 'Active interpolation mode'),
    (961, 976, 'Home Dog Shift'),
    (981, 996, 'Axis Absolute Counter'),
    (1000, 1000, 'Part count'),
    (1002, 1002, 'Required part count'),
    (1004, 1004, 'Total part count'),
    (1009, 1009, 'Power-on time (ms，71 分钟回绕)'),
    (1010, 1010, 'Cutting time per cycle'),
    (1011, 1011, 'Accumulate cutting time'),
    (1012, 1012, 'Power-on time (s)'),
    (1013, 1013, 'Accumulate power-on time'),
    (1014, 1014, 'Installation cutting time'),
    (1015, 1015, 'Installation power-on time'),
    (1016, 1016, 'System date'),
    (1017, 1017, 'System time'),
    (1018, 1018, 'Cutting time per cycle'),
]

# 手册明写保留
RESERVED = [
    (519, 519, 'Reserved for CNC'),
    (527, 529, 'First Axis Group Control Registers'),
    (537, 539, 'Second Axis Group Control Registers'),
    (547, 549, 'Third Axis Group Control Registers'),
    (557, 559, 'Fourth Axis Group Control Registers'),
    (560, 579, 'Reserved for CNC'),
    (631, 639, 'Reserved for CNC'),
    (845, 850, 'Reserved'),
    (926, 926, 'Reserved'),
]

# 手册未列明：不判定
UNDEFINED = [
    (640, 640, ''),
    (657, 660, ''),
    (677, 680, ''),
    (697, 699, ''),
    (717, 720, ''),
    (737, 740, ''),
    (757, 760, ''),
    (767, 770, ''),
    (777, 781, ''),
    (787, 790, ''),
    (795, 800, ''),
    (857, 860, ''),
    (877, 879, ''),
    (917, 919, ''),
    (930, 933, ''),
    (938, 940, ''),
    (947, 950, ''),
    (952, 960, ''),
    (977, 980, ''),
    (997, 999, ''),
    (1001, 1001, ''),
    (1003, 1003, ''),
    (1005, 1008, ''),
]

# 位存取：手册区段表 1-1.4.3 —— R512~R639 可，R640 以上不可
BIT_MAX = 639


def _find(table, no):
    for lo, hi, nm in table:
        if lo <= no <= hi:
            return nm
    return None


def classify(no):
    """返回 (类别, 名称)。类别: write | readonly | reserved | undefined | unknown"""
    if not 512 <= no <= 1023:
        return ("unknown", None)
    for tag, table in (("write", WRITE), ("reserved", RESERVED),
                       ("undefined", UNDEFINED), ("readonly", READONLY)):
        nm = _find(table, no)
        if nm is not None:
            return (tag, nm)
    return ("undefined", None)      # 兜底: 宁可放过, 不乱判


def bit_ok(no):
    """这一段能不能按位寻址"""
    return no <= BIT_MAX
