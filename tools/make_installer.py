#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打一个「解压后双击就能装」的安装包。

    python tools/make_installer.py              # 输出到 dist/
    python tools/make_installer.py --out ~/x    # 指定目录

产物只有一个 zip，里面是平铺的：

    syntec-plc-安装包-v<技能版本>.zip
    ├── 双击安装.bat
    ├── setup.py
    ├── 安装说明.md
    ├── syntec-ladder-mcp-standalone.py
    └── skill/syntec-plc/...

为什么要单独打这个包：tools/package.py 打的是「仓库包」和「技能包」，前者给开发者，
后者要手动拷目录；这个包是给**完全不想碰命令行**的人用的，双击即装。

两个细节：
  - .bat 按原字节写入，不做换行转换（cmd 需要 CRLF）。
  - 文件名含中文，zip 里写 UTF-8 标记位，Win7 以上解压不乱码。
"""
import argparse
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
INST = os.path.join(REPO, "installer")
SKILL = os.path.join(REPO, "skill", "syntec-plc")
MCP = os.path.join(REPO, "syntec-ladder-mcp-standalone.py")


def skill_version():
    p = os.path.join(SKILL, "SKILL.md")
    with open(p, encoding="utf-8") as f:
        m = re.search(r"^version:\s*(\S+)\s*$", f.read(), re.M)
    if not m:
        sys.exit("读不到 SKILL.md 的 version")
    return m.group(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(REPO, "dist"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)

    for p in (MCP, SKILL, INST):
        if not os.path.exists(p):
            sys.exit(f"缺东西：{p}")

    ver = skill_version()
    out = os.path.join(args.out, f"syntec-plc-安装包-v{ver}.zip")

    n = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        # 1) 三个入口文件，平铺在 zip 根
        for name in ("双击安装.bat", "setup.py", "安装说明.md"):
            src = os.path.join(INST, name)
            info = zipfile.ZipInfo(name)
            info.compress_type = zipfile.ZIP_DEFLATED
            # 0o755 便于 mac/linux 解压后仍有执行位
            info.external_attr = 0o755 << 16
            with open(src, "rb") as f:
                z.writestr(info, f.read())     # 原字节写入，保住 bat 的 CRLF
            n += 1

        # 2) MCP 单文件
        info = zipfile.ZipInfo("syntec-ladder-mcp-standalone.py")
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o755 << 16
        with open(MCP, "rb") as f:
            z.writestr(info, f.read())
        n += 1

        # 3) 技能包整个目录
        for root, dirs, files in os.walk(SKILL):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            for fn in files:
                if fn.endswith(".pyc"):
                    continue
                src = os.path.join(root, fn)
                # 相对仓库根，保留 skill/syntec-plc/... 这一层：
                # setup.py 是按「安装包根目录下有个 skill/syntec-plc」去找的
                rel = os.path.relpath(src, REPO)
                z.write(src, rel)
                n += 1

    size = os.path.getsize(out)
    print(f"[OK] {out}")
    print(f"     {n} 个文件, {size/1024:.0f} KB")
    print()
    print("发给人之前建议自己解压一遍，跑一次：")
    print("    双击安装.bat     （看四个 [OK] 齐不齐）")
    print("     或 python setup.py --check   （安全检查，不改文件）")


if __name__ == "__main__":
    main()
