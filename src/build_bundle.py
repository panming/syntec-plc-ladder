#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
把 mcp_server.py + 依赖模块打包成 **单文件** 可执行脚本。

产物: dist/syntec-ladder-mcp-standalone.py
用途: 发给别人时只需传一个 .py 文件, 对方配置里指向它即可, 不用管目录结构。

重新生成: python build_bundle.py
"""
import base64
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
# 两种布局:
#   A) 开发目录: build_bundle.py 与各模块平铺, 产物进 ./dist/
#   B) 仓库目录: 本脚本在 src/, 产物直接落在仓库根 (README 旁边), 方便 git 提交
_IN_SRC = os.path.basename(HERE) == "src"
ROOT = os.path.dirname(HERE) if _IN_SRC else HERE
SRC_DIR = os.path.join(ROOT, "dist", "syntec-ladder-mcp")
OUT = (os.path.join(ROOT, "syntec-ladder-mcp-standalone.py") if _IN_SRC
       else os.path.join(HERE, "dist", "syntec-ladder-mcp-standalone.py"))

MODULES = ["syntec_re", "syntec_lad", "syntec_layout", "syntec_r_iface",
           "syntec_address_db", "syntec_model", "syntec_parse", "syntec_paths",
           "syntec_read"]

VERSION = "0.13.2"

HEADER = '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新代(SYNTEC) PLC 梯形图 MCP Server —— 单文件版 (v{ver})

本文件是 mcp_server.py + syntec_lad / syntec_layout / syntec_address_db / syntec_model 的打包产物,
纯 Python 标准库实现, 无需 pip 安装任何依赖。

用法(客户端 mcp 配置):
  {{
    "mcpServers": {{
      "syntec-ladder": {{
        "command": "python",
        "args": ["<本文件的绝对路径>"]
      }}
    }}
  }}

自检(不接客户端也能跑):
  python syntec-ladder-mcp-standalone.py --selftest

重新打包: 在源项目目录里执行 python build_bundle.py
"""
import base64
import sys
import types

VERSION = "{ver}"

# ---- 内嵌模块源码(base64 以免引号/缩进被破坏) ----
_EMBEDDED = {{
'''

FOOTER = '''
def _install_modules():
    # 两遍: 先把所有模块对象挂进 sys.modules, 再逐个 exec ——
    # 否则先 exec 的模块一旦 import 后面的兄弟模块就会 ModuleNotFoundError。
    for name in _EMBEDDED:
        if name in sys.modules:
            continue
        mod = types.ModuleType(name)
        mod.__file__ = "<embedded:" + name + ">"
        sys.modules[name] = mod
    for name, b64 in _EMBEDDED.items():
        exec(compile(base64.b64decode(b64).decode("utf-8"), name + ".py", "exec"),
             sys.modules[name].__dict__)


_install_modules()

# ---- 服务本体 ----
_SERVER_SRC = base64.b64decode(_SERVER_B64).decode("utf-8")


def _run_server():
    """把服务源码装进本模块的全局命名空间。
    exec 前把 __name__ 临时改掉, 否则服务端源码里的 `if __name__ == "__main__"`
    会在 exec 时就启动 main() 并阻塞在 stdin 上(--selftest 就再也跑不到了)。"""
    g = globals()
    old = g.get("__name__")
    g["__name__"] = "syntec_ladder_server"
    try:
        exec(compile(_SERVER_SRC, "mcp_server.py", "exec"), g)
    finally:
        g["__name__"] = old
    g["main"]()



def _selftest():
    import json, os, subprocess, tempfile
    out = os.path.join(tempfile.gettempdir(), "syntec_selftest.lad")
    reqs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                    "clientInfo": {"name": "selftest", "version": "1"}}},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "new_ladder", "arguments": {"path": out}}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "add_rung", "arguments": {
             "condition": [{"kind": "contact", "norm": "NC", "addr": "C36"}],
             "action": [{"kind": "coil", "norm": "NO", "addr": "O10"}]}}},
        {"jsonrpc": "2.0", "id": 5, "method": "tools/call",
         "params": {"name": "add_rung", "arguments": {"elements": [{"kind": "end"}]}}},
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call",
         "params": {"name": "save", "arguments": {}}},
    ]
    payload = "\\n".join(json.dumps(r) for r in reqs) + "\\n"
    p = subprocess.run([sys.executable, os.path.abspath(__file__)], input=payload.encode(),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    if p.returncode != 0:
        print("[FAIL] 进程退出码", p.returncode, p.stderr.decode("utf-8", "replace"))
        return 1
    got = [json.loads(l) for l in p.stdout.decode("utf-8").splitlines() if l.strip()]
    ok = len(got) == len(reqs)
    ok = ok and got[0].get("result", {}).get("serverInfo", {}).get("name") == "syntec-ladder"
    ok = ok and len(got[1].get("result", {}).get("tools", [])) >= 8
    ok = ok and os.path.isfile(out) and open(out, "rb").read().endswith(b"\\x00\\xfe")
    print("[PASS] 单文件版可用, 共 %d 个工具, 已生成 %s" % (
        len(got[1].get("result", {}).get("tools", [])), out) if ok else "[FAIL] 自检未通过")
    return 0 if ok else 1


def _lock_utf8():
    # 英文版 Windows 控制台是 cp1252, 打印中文会 UnicodeEncodeError
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


if __name__ == "__main__":
    _lock_utf8()
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    _run_server()
'''


def read(name):
    with open(os.path.join(SRC_DIR, name + ".py"), "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def sync_sources():
    """把源目录里的模块复制到 dist/syntec-ladder-mcp/ (单文件打包与 zip 都以它为源)"""
    os.makedirs(SRC_DIR, exist_ok=True)
    n = 0
    for name in MODULES + ["mcp_server", "selftest"]:
        src = os.path.join(HERE, name + ".py")
        if not os.path.exists(src):
            continue
        dst = os.path.join(SRC_DIR, name + ".py")
        if os.path.exists(dst) and open(src, "rb").read() == open(dst, "rb").read():
            continue
        with open(src, "rb") as f, open(dst, "wb") as g:
            g.write(f.read())
        n += 1
    return n


def main():
    ver = VERSION
    print("同步源码:", sync_sources(), "个文件更新")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    out = [HEADER.format(ver=ver)]
    for m in MODULES:
        out.append('    "%s": "%s",\n' % (m, read(m)))
    out.append("}\n")
    out.append('_SERVER_B64 = "%s"\n' % read("mcp_server"))
    out.append(FOOTER)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(out))
    print("已生成:", OUT, os.path.getsize(OUT), "字节")


if __name__ == "__main__":
    main()
