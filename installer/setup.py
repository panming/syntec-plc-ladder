#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一键安装：把 MCP 工具和技能包装进 WorkBuddy。

给不想碰命令行的人用。双击同目录的「双击安装.bat」即可，不要单独运行这个文件。

做四件事，每件都先说清楚要干什么、做完告诉你结果：
    1. 检查 Python（版本够不够）
    2. 跑一遍工具自检（确认这个 Python 能跑起来）
    3. 装技能包到 ~/.workbuddy/skills/syntec-plc/
    4. 把 MCP 配置写进 ~/.workbuddy/mcp.json（已有的其它服务原样保留）

所有改动都先备份，改坏了可以还原。重复运行是安全的。
"""
import argparse
import datetime
import json
import os
import shutil
import subprocess
import sys

# ---------------------------------------------------------------- 输出
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OK, BAD, WARN, INFO = "[OK]", "[!!]", "[??]", "   "


def say(tag, msg=""):
    print(f"{tag} {msg}")


def title(n, total, text):
    print()
    print(f"--- 第 {n}/{total} 步：{text} " + "-" * max(0, 40 - len(text)))


def home():
    # normpath 是为了环境变量末尾带反斜杠时不出现 C:////Users////////x 这种双斜杠
    return os.path.normpath(os.path.expanduser("~"))


def wb_dir():
    return os.path.join(home(), ".workbuddy")


# ---------------------------------------------------------------- 找料
def find_inputs(base):
    """在安装包目录（或仓库根目录）里找到 MCP 单文件和技能包。"""
    mcp_cands = [
        os.path.join(base, "syntec-ladder-mcp-standalone.py"),
        os.path.join(base, "..", "syntec-ladder-mcp-standalone.py"),
        os.path.join(base, "..", "src", "mcp_server.py"),
    ]
    skill_cands = [
        os.path.join(base, "skill", "syntec-plc"),
        os.path.join(base, "..", "skill", "syntec-plc"),
    ]
    mcp = next((os.path.abspath(p) for p in mcp_cands if os.path.isfile(p)), None)
    skill = next((os.path.abspath(p) for p in skill_cands
                  if os.path.isfile(os.path.join(p, "SKILL.md"))), None)
    return mcp, skill


def stamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# ---------------------------------------------------------------- 1 Python
def check_python():
    v = sys.version_info
    say(INFO, f"用的是 {sys.executable}")
    if v < (3, 8):
        say(BAD, f"Python 版本 {v.major}.{v.minor} 太旧，需要 3.8 以上")
        say(INFO, "去 https://www.python.org/downloads/ 装最新版，安装时勾上 Add python.exe to PATH")
        return False
    say(OK, f"Python {v.major}.{v.minor}.{v.micro}")
    return True


# ---------------------------------------------------------------- 2 自检
def run_selftest(mcp_path):
    say(INFO, "正在试跑工具（约 10 秒）…")
    try:
        r = subprocess.run([sys.executable, mcp_path, "--selftest"],
                           capture_output=True, text=True, timeout=180,
                           encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired:
        say(BAD, "自检超时。可能被杀毒软件拦住了")
        return False
    out = (r.stdout or "") + (r.stderr or "")
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-1:] or ["(无输出)"]
    if r.returncode == 0 and "PASS" in out.upper():
        say(OK, "工具自检通过：" + tail[0].strip())
        return True
    say(BAD, "自检没通过，最后一行是：" + tail[0].strip())
    for ln in out.strip().splitlines()[-8:]:
        print("      " + ln)
    return False


# ---------------------------------------------------------------- 3 技能包
def install_skill(skill_src):
    dst = os.path.join(wb_dir(), "skills", "syntec-plc")
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    if os.path.isdir(dst):
        bak = f"{dst}.bak-{stamp()}"
        shutil.move(dst, bak)
        say(INFO, f"已装过旧版，先备份到 {os.path.basename(bak)}")

    shutil.copytree(skill_src, dst,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    n = sum(len(fs) for _, _, fs in os.walk(dst))
    say(OK, f"技能包已装到 {dst}（{n} 个文件）")
    return True


# ---------------------------------------------------------------- 4 MCP 配置
def install_mcp_config(mcp_path):
    cfg = os.path.join(wb_dir(), "mcp.json")
    os.makedirs(wb_dir(), exist_ok=True)

    data = {}
    if os.path.isfile(cfg):
        with open(cfg, encoding="utf-8") as f:
            raw = f.read().strip()
        if raw:
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                say(BAD, f"{cfg} 不是合法的 JSON，不敢动它（{e}）")
                say(INFO, "请把这一行告诉帮你装的人：" + cfg)
                return False
        bak = f"{cfg}.bak-{stamp()}"
        shutil.copy2(cfg, bak)
        say(INFO, f"原配置已备份到 {os.path.basename(bak)}")

    servers = data.setdefault("mcpServers", {})
    before = json.dumps(servers.get("syntec-ladder"), sort_keys=True)
    servers["syntec-ladder"] = {
        "command": os.path.normpath(sys.executable),
        "args": [os.path.normpath(mcp_path)],
    }
    after = json.dumps(servers["syntec-ladder"], sort_keys=True)

    tmp = cfg + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, cfg)

    if before == after:
        say(OK, f"配置里已经有这一项，内容一致（{cfg}）")
    else:
        say(OK, f"已写入 {cfg}")
    others = [k for k in servers if k != "syntec-ladder"]
    if others:
        say(INFO, "保留下来的其它服务：" + "、".join(others))
    return True


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description="一键装好 syntec-plc 的 MCP 工具与技能包")
    ap.add_argument("--base", default=os.path.dirname(os.path.abspath(__file__)),
                    help="安装包所在目录（默认本文件所在目录）")
    ap.add_argument("--check", action="store_true", help="只检查环境，不改任何东西")
    ap.add_argument("--no-config", action="store_true", help="只装技能包，不写 MCP 配置")
    args = ap.parse_args()

    print("=" * 60)
    print(" 新代（SYNTEC）梯形图工具 · 一键安装")
    print("=" * 60)
    if args.check:
        print("  （检查模式：不会改动任何文件）")
    print()
    print(" 这个程序会做四件事：")
    print("   1. 看你的 Python 够不够新")
    print("   2. 试跑一次工具，确认它能用")
    print("   3. 把技能包装进 WorkBuddy")
    print("   4. 把工具登记到 WorkBuddy 的 MCP 配置里")

    total = 4
    ok = True

    title(1, total, "检查 Python")
    ok &= check_python()
    if not ok:
        return 1

    title(2, total, "找到安装文件并试跑")
    mcp, skill = find_inputs(os.path.abspath(args.base))
    if not mcp:
        say(BAD, "没找到 syntec-ladder-mcp-standalone.py")
        say(INFO, "确认这个安装包是完整解压的，不是只解压了一半")
        return 1
    say(OK, "工具：" + mcp)
    if not skill:
        say(BAD, "没找到 skill/syntec-plc/ 目录")
        say(INFO, "确认安装包里的 skill 文件夹还在，没有被杀毒软件删掉")
        return 1
    say(OK, "技能包：" + skill)
    if not run_selftest(mcp):
        say(INFO, "这一项不过，装上去也用不了。请把上面的报错发给帮你装的人")
        return 1

    if args.check:
        print()
        say(OK, "检查完成，一切正常。去掉 --check 再运行一次就会真装")
        return 0

    title(3, total, "安装技能包")
    install_skill(skill)

    title(4, total, "登记 MCP 工具")
    if args.no_config:
        say(WARN, "按参数要求跳过；需要时手动把下面这段加进 mcp.json：")
        print(json.dumps({"mcpServers": {"syntec-ladder": {
            "command": sys.executable, "args": [mcp]}}}, ensure_ascii=False, indent=2))
    elif not install_mcp_config(mcp):
        return 1

    print()
    print("=" * 60)
    print(" 装好了。接下来三件事：")
    print("=" * 60)
    print(" 1. 完全退出 WorkBuddy（右上角关掉不算，要到托盘图标右键退出）")
    print(" 2. 重新打开 WorkBuddy")
    print(" 3. 新建一个对话，把这句话发给它：")
    print()
    print("    用 syntec 技能帮我写一个液压站启停的梯形图，")
    print("    要求：开机默认停泵，按面板按钮启动后自锁，过载和急停都要停泵。")
    print()
    print(" 它应该会开始查资料、调用工具（你能看到它在读 add_rung / validate 这类工具）。")
    print(" 如果它说“我没有这些工具”，看《安装说明》最后一节。")
    print()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已取消，什么都没改。")
        sys.exit(130)
