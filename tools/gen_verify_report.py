#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跑完全部回归并把原始输出汇总成仓库根的 `验证结果.txt`。

输出里的本机绝对路径会替换成 `<仓库根>` / `<临时目录>`，方便别人复跑对照。
用法: python tools/gen_verify_report.py
"""
import datetime
import os
import re
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8")
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
OUT = os.path.join(ROOT, "验证结果.txt")
VER = "0.13.2"

SECTIONS = [
    ("端到端自检", ["tools/selftest.py"], "写 -> 存 -> 读 -> 再存, 逐项核对"),
    ("全量往返验证", ["tools/roundtrip_full.py"], "仓库自带样本逐字节往返"),
    ("元件逐字节", ["tools/verify_samples.py"], ""),
    ("并联结构", ["tools/verify_parallel.py"], ""),
    ("注释编码", ["tools/verify_comments.py"], "自带样例 + 真机语料"),
    ("地址权限与同址驱动", ["tools/verify_address.py", "--samples", "samples"], ""),
    ("比较块槽位", ["tools/verify_compare.py"], "A=常数、B=寄存器"),
    ("地址三方核对", ["tools/verify_addr_conflicts.py"], "手册/文档/代码"),
    ("R512~R1023 逐条权限", ["tools/verify_r_iface.py"], ""),
    ("路径枚举 vs 串并联树", ["tools/verify_paths.py"], ""),
    ("一条 rung 多个线圈", ["tools/verify_multi_coil.py"], ""),
    ("审查工具自身回归", ["tools/verify_review_fixes.py"], "标签截断/轴向地址/悬空误报/warn 措辞/警报位"),
    ("报警定义 XML 对账", ["tools/verify_alarm_xml.py", "--selftest"], "合成用例"),
    ("串联功能块是条件", ["tools/verify_series_blocks.py"], "定时器/运算块导通才有下游，含真值表"),
    ("MCP 端到端", ["tools/e2e_mcp.py"], "起进程走 JSON-RPC"),
    ("单文件版自检", ["syntec-ladder-mcp-standalone.py", "--selftest"], "打包产物独立可用"),
]


def sanitize(text):
    for p in (ROOT, ROOT.replace("\\", "/"),
              os.path.abspath(tempfile.gettempdir()),
              os.path.abspath(tempfile.gettempdir()).replace("\\", "/")):
        if p:
            text = text.replace(p, "<临时目录>" if "Temp" in p or "tmp" in p else "<仓库根>")
    # 兜底：Windows 用户目录
    text = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", "<临时目录>", text)
    return text


def main():
    lines = ["=" * 62,
             " syntec-plc-ladder  v%s   验证结果" % VER,
             " 生成时间: " + datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
             " 说明: 为便于他人复跑，本机绝对路径已替换为 <仓库根> / <临时目录>，其余为原始输出",
             " Python: " + sys.version.split()[0],
             "=" * 62, "",
             "说明: 真机程序(cnc.lad / cnc_1.lad)不随仓库分发, 相关用例记 SKIP。",
             "      要验证自己的程序: python tools/roundtrip_full.py --samples D:/your_lad", ""]
    failed = []
    for n, (title, cmd, note) in enumerate(SECTIONS, 1):
        lines.append("【%d】%s  %s" % (n, title, " ".join(cmd)))
        if note:
            lines.append("     " + note)
        lines.append("-" * 62)
        try:
            p = subprocess.run([sys.executable] + cmd, cwd=ROOT,
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               timeout=300)
            out = p.stdout.decode("utf-8", "replace")
            rc = p.returncode
        except Exception as e:                       # noqa: BLE001
            out, rc = "执行失败: %s\n" % e, 1
        lines.extend(sanitize(out).rstrip("\n").splitlines())
        lines.append("")
        if rc != 0:
            failed.append((n, title, rc))
            lines.append("[本项退出码 %d]" % rc)
            lines.append("")
        print("【%d】%s -> %s" % (n, title, "OK" if rc == 0 else "FAIL(%d)" % rc))
    lines.append("=" * 62)
    if failed:
        lines.append("未通过: " + "、".join("%d %s(rc=%d)" % x for x in failed))
    else:
        lines.append("全部通过")
    lines.append("=" * 62)
    open(OUT, "w", encoding="utf-8", newline="\n").write("\n".join(lines) + "\n")
    print("已写出:", OUT)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
