#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报警定义 XML <-> 阶梯图 对账。

新代机床的报警文字放在 Ladder/AlarmPLC_CHS.xml（CHT/COM 是其它语系），
一条消息用 Content 里的 (R44.5) 标出对应的报警位。只有阶梯里真的有线圈
去驱动这个位，屏幕上才可能弹出那条消息。两边对不上就有两类情况：

  * 有文字、没人点  —— 该编号的警报讯息不会被触发；也可能是删掉程序逻辑后
    留下的文字残留（文字由 MLCEdit 单独维护，删逻辑不一定会删文字）
  * 点了、没文字    —— 屏幕上只有编号或空白占位

手册依据 (PLC Editor Manual-ZH-CN.chm 第 1-5 章):
  * 1-5.21    R40~R43 = 系统内定警报(编号 1~64)，文字在控制器里，不在 XML。
  * 1-5.22    R44~R49 = 自订警报；R44.0~R44.15 对应 Alarm 65~80，
              R44.16~R44.31 对应 Warning 315~330。Alarm/Warning 必须自保。
  * 1-5.22.49 WinCE 10.114.46 以后按语系读三份之一：
              CHS=AlarmPLC_CHS.xml / CHT=AlarmPLC_CHT.xml / COM=AlarmPLC_COM.xml
              所以「控制器读哪份」取决于控制器语系，不是三份同时生效。
  * 1-5       PLC 发出警报只在屏幕显示字符串，不会自动中止任何动作；
              要停加工/主轴，必须在 PLC 程序里另行处理。

另外把「两条不同位写着一模一样的文字」列出来：可能是报警位迁移后留下的
旧条目，哪条在用要现场确认，工具不替它下结论。

用法：
    python tools/verify_alarm_xml.py --lad cnc.lad [--xml AlarmPLC_CHS.xml]
    python tools/verify_alarm_xml.py --selftest        # 合成用例，不依赖机床文件
    python tools/verify_alarm_xml.py --lad cnc.lad --strict   # 有发现就退出码 1
"""
import argparse
import collections
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "..", "src")):
    if _d not in sys.path:
        sys.path.insert(0, _d)

MSG_RE = re.compile(r'<Message\s+ID="AlarmMsg::MLC::ID=(\d+)"\s+Content="(.*?)"\s*/>')
BIT_RE = re.compile(r'\(R(\d+)\.(\d+)\)')
# 未使用的模板槽位不算「有文字」——它们遍地都是，全列出来是噪音
PLACEHOLDER = re.compile(r'^\s*PLC\s*(警报|警告|Alarm|Warning|警報)\s*$', re.I)


def decode_xml(raw):
    """CHS 实测是 UTF-8 BOM；老版本可能是 Big5/GBK，逐个试。"""
    for enc in ("utf-8-sig", "big5", "cp950", "gbk"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", "replace")


def parse_alarm_xml(text):
    """-> {addr: (id, 文字)}。Content 里的 (Rxx.y) 就是位地址。"""
    bits = {}
    for mid, content in MSG_RE.findall(text):
        m = BIT_RE.search(content)
        if not m:
            continue
        addr = "R%s.%s" % (m.group(1), m.group(2))
        label = BIT_RE.sub("", content).strip()
        bits[addr] = (int(mid), label)
    return bits


def is_placeholder(label):
    return bool(PLACEHOLDER.match(label or ""))


def cross_check(bits, driven):
    """bits: parse_alarm_xml 的结果；driven: 阶梯里被线圈驱动的位地址集合。

    -> {'dead': [(addr,id,文字)], 'undefined': [(addr,文字)],
        'duplicate': [(文字, [addr...])], 'driven_ok': int}
    """
    words = {int(a.split(".")[0][1:]) for a in bits}
    dead, undefined = [], []
    for addr, (mid, label) in sorted(bits.items(),
                                    key=lambda kv: (int(kv[0].split(".")[0][1:]),
                                                    int(kv[0].split(".")[1]))):
        if addr not in driven and not is_placeholder(label):
            dead.append((addr, mid, label))
    # 只对 XML 覆盖到的那些字（如 R44~R49）判「点了没文字」；
    # R40~R43 属系统内定警报区，文字在控制器里，不在 XML 里，不能算缺失。
    for addr in sorted(driven, key=lambda s: (int(s.split(".")[0][1:]),
                                              int(s.split(".")[1])) if "." in s else (0, 0)):
        m = re.match(r"^R(\d+)\.(\d+)$", addr)
        if not m or int(m.group(1)) not in words:
            continue
        if addr not in bits:
            undefined.append((addr, ""))
    by_text = collections.defaultdict(list)
    for addr, (_mid, label) in bits.items():
        if not is_placeholder(label) and len(label) > 3:
            by_text[label].append(addr)
    duplicate = [(t, sorted(a, key=lambda s: (int(s.split(".")[0][1:]),
                                              int(s.split(".")[1]))))
                 for t, a in by_text.items() if len(a) > 1]
    return {"dead": dead, "undefined": undefined,
            "duplicate": duplicate, "n_def": len(bits),
            "driven_ok": sum(1 for a in bits if a in driven)}


def collect_driven(lad_path):
    """按字节行采集所有线圈（含桥式/多负载 rung），不依赖串并联树。"""
    import review_ladder as RV
    import syntec_read as R
    import syntec_parse as P
    d = R.read_ladder(lad_path)
    logic, _others, _tail = R.split_records(open(lad_path, "rb").read())
    rows = [P.decode_row(r) for r in logic]
    coils, _contacts, _cmps, _timers, _moves = RV.collect(d, rows)
    return set(coils)


def report(res, title):
    print("=" * 74)
    print(title)
    print("=" * 74)
    print("XML 定义的位 %d 个，其中阶梯有驱动 %d 个" %
          (res["n_def"], res["driven_ok"]))
    print()
    if res["dead"]:
        print("[·] 有报警文字、阶梯里没有驱动这个位: %d 条" % len(res["dead"]))
        for a, i, t in res["dead"]:
            print("    %-9s #%-4d %s" % (a, i, t))
        print("    注: 文字由 MLCEdit 单独维护, 删掉程序逻辑不一定会删文字;")
        print("        也可能是该警报在本机未启用。是否要处理请现场确认。")
        print()
    if res["undefined"]:
        print("[!] 阶梯驱动了、XML 却没有对应文字: %d 条" % len(res["undefined"]))
        for a, _ in res["undefined"]:
            print("    %s" % a)
        print()
    if res["duplicate"]:
        print("[·] 同一个文字挂在多个位上（可能是迁移后留下的旧位）: %d 组" %
              len(res["duplicate"]))
        for t, addrs in res["duplicate"]:
            print("    %s  <-  %s" % (t[:46], "、".join(addrs)))
        print()
    if not (res["dead"] or res["undefined"] or res["duplicate"]):
        print("[OK] 没有发现对不上的地方")
    return len(res["dead"]) + len(res["undefined"]) + len(res["duplicate"])


def selftest():
    xml = """<ResMap>
  <Message ID="AlarmMsg::MLC::ID=65" Content="(R44.0)PLC 警报" />
  <Message ID="AlarmMsg::MLC::ID=66" Content="(R44.1)刀杯上失败警报。" />
  <Message ID="AlarmMsg::MLC::ID=70" Content="(R44.5)刀库马达过载警报。" />
  <Message ID="AlarmMsg::MLC::ID=73" Content="(R44.8)刀库马达过载警报。" />
  <Message ID="AlarmMsg::MLC::ID=79" Content="(R44.14)四轴松夹信号异常" />
  <Message ID="AlarmMsg::MLC::ID=315" Content="(R44.16)PLC 警告" />
</ResMap>"""
    bits = parse_alarm_xml(xml)
    driven = {"R44.1", "R44.8", "R44.14", "R44.3"}
    res = cross_check(bits, driven)
    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    chk("解析 6 条消息", len(bits) == 6, str(len(bits)))
    chk("占位文字识别", is_placeholder("PLC 警报") and is_placeholder("PLC Warning"))
    chk("占位文字不算死报警",
        all(a not in ("R44.0", "R44.16") for a, _, _ in res["dead"]),
        str(res["dead"]))
    chk("R44.5 报为死报警", any(a == "R44.5" for a, _, _ in res["dead"]))
    chk("R44.3 报为无文字", any(a == "R44.3" for a, _ in res["undefined"]),
        str(res["undefined"]))
    chk("R40.2 不算无文字", all(a != "R40.2" for a, _ in res["undefined"]))
    chk("同名文字报重复", len(res["duplicate"]) == 1 and
        set(res["duplicate"][0][1]) == {"R44.5", "R44.8"}, str(res["duplicate"]))
    chk("驱动计数", res["driven_ok"] == 3, str(res["driven_ok"]))
    # 编码容错
    chk("Big5 能解", "刀" in decode_xml("(R44.1)刀".encode("big5")))
    chk("UTF-8 BOM 能解", "(R44.1)" in decode_xml(b"\xef\xbb\xbf(R44.1)x"))

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if not ok else ""))
    print()
    if bad:
        print(f"[FAIL] {len(bad)}/{len(checks)} 项未通过")
        return 1
    print(f"[PASS] {len(checks)}/{len(checks)} 项通过")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lad", help="cnc.lad 路径")
    ap.add_argument("--xml", help="AlarmPLC_CHS.xml 路径；不填就在 lad 同目录找")
    ap.add_argument("--selftest", action="store_true", help="跑合成用例，不读机床文件")
    ap.add_argument("--strict", action="store_true", help="有发现就返回退出码 1")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.lad:
        ap.error("要 --lad，或者 --selftest")
    xml_path = args.xml or os.path.join(os.path.dirname(os.path.abspath(args.lad)),
                                        "AlarmPLC_CHS.xml")
    if not os.path.isfile(xml_path):
        print("找不到报警定义 XML:", xml_path)
        return 2
    bits = parse_alarm_xml(decode_xml(open(xml_path, "rb").read()))
    driven = collect_driven(args.lad)
    res = cross_check(bits, driven)
    n = report(res, "%s  <->  %s" % (os.path.basename(args.lad),
                                     os.path.basename(xml_path)))
    return 1 if (args.strict and n) else 0


if __name__ == "__main__":
    sys.exit(main())
