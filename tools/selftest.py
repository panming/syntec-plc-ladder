#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端自检: 以 MCP 客户端身份启动 mcp_server.py, 跑一遍「写 -> 存 -> 读 -> 再存」。

覆盖: new_ladder / add_rung(含并联) / validate / save / read_ladder / load_lad / dump_rungs
关键判据: 读入刚生成的文件后再原样保存, 字节必须完全相同(读能力无损)。

用法:  python selftest.py
"""
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def _find_server():
    """兼容两种布局: 平铺(解压即用) / src+tools(源码仓库)"""
    cands = [HERE, os.path.join(HERE, "src"),
             os.path.join(os.path.dirname(HERE), "src")]
    for d in cands:
        f = os.path.join(d, "mcp_server.py")
        if os.path.isfile(f):
            return f
    return os.path.join(HERE, "mcp_server.py")


SERVER = _find_server()
OUT1 = os.path.join(tempfile.gettempdir(), "syntec_selftest.lad")
OUT2 = os.path.join(tempfile.gettempdir(), "syntec_selftest_reread.lad")


def call(rid, name, args=None):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": args or {}}}


REQS = [
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "selftest", "version": "1"}}},
    {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
    call(3, "new_ladder", {"path": OUT1}),
    # 1) 单行: 急停常闭 -> 线圈 O10
    call(4, "add_rung", {"condition": [{"kind": "contact", "norm": "NC", "addr": "C36"}],
                         "action": [{"kind": "coil", "norm": "NO", "addr": "O10"}]}),
    # 2) 并联: I100 串 (I101 | I102) 驱动 O200
    call(5, "add_rung", {"elements": [
        {"kind": "contact", "norm": "NO", "addr": "I100"},
        {"kind": "parallel", "branches": [[{"kind": "contact", "norm": "NO", "addr": "I101"}],
                                          [{"kind": "contact", "norm": "NO", "addr": "I102"}]]},
        {"kind": "coil", "norm": "NO", "addr": "O200"}]}),
    # 3) 定时器
    call(6, "add_rung", {"condition": [{"kind": "contact", "norm": "NO", "addr": "I132"}],
                         "action": [{"kind": "timer", "name": "TM100", "preset": 60}]}),
    call(7, "add_rung", {"elements": [{"kind": "end"}]}),
    call(8, "validate"),
    call(9, "save", {}),
    # 只读解析
    call(10, "read_ladder", {"path": OUT1, "format": "json", "limit": 10}),
    # 读入 -> 原样另存
    call(11, "load_lad", {"path": OUT1}),
    call(12, "dump_rungs", {"start": 2, "limit": 1}),
    call(13, "save", {"path": OUT2}),
]


def main():
    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in REQS) + "\n"
    p = subprocess.run([sys.executable, SERVER], input=payload.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if p.returncode != 0:
        print("[FAIL] 进程退出码", p.returncode, p.stderr.decode("utf-8", "replace")[:500])
        return 1
    got = {}
    for line in p.stdout.decode("utf-8", "replace").splitlines():
        if not line.strip():
            continue
        o = json.loads(line)
        got[o.get("id")] = o.get("result", {})

    def text(i):
        return got.get(i, {}).get("content", [{}])[0].get("text", "")

    checks = []

    def chk(name, cond, detail=""):
        checks.append((name, bool(cond), detail))

    chk("initialize 服务名", got.get(1, {}).get("serverInfo", {}).get("name") == "syntec-ladder")
    tools = [t["name"] for t in got.get(2, {}).get("tools", [])]
    chk("工具齐全", len(tools) >= 12 and {"set_comment", "add_comment_line"} <= set(tools),
        str(len(tools)))
    chk("新增读工具齐全", all(n in tools for n in ("load_lad", "read_ladder", "dump_rungs")))
    chk("并联展开为 2 行", "展开为 2 行" in text(5), text(5))
    chk("校验无告警", "校验通过" in text(8), text(8))
    chk("保存成功", "已保存" in text(9), text(9))
    chk("read_ladder 返回元件", '"kind": "coil"' in text(10) or '"kind":"coil"' in text(10))
    chk("load_lad 载入 4 条 rung", "rung 4" in text(11), text(11))
    chk("dump_rungs 有 parallel", '"parallel"' in text(12), text(12)[:200])

    a = open(OUT1, "rb").read() if os.path.isfile(OUT1) else b""
    b = open(OUT2, "rb").read() if os.path.isfile(OUT2) else b""
    chk("文件以 00 fe 结尾", a.endswith(b"\x00\xfe"))
    chk("读入再存回逐字节相同", a and a == b, f"{len(a)} vs {len(b)}")

    bad = [c for c in checks if not c[1]]
    for name, ok, detail in checks:
        print(f"  [{'OK ' if ok else 'FAIL'}] {name}" + (f"  <- {detail}" if not ok else ""))
    print()
    if bad:
        print(f"[FAIL] {len(bad)}/{len(checks)} 项未通过")
        return 1
    print(f"[PASS] {len(checks)}/{len(checks)} 项通过  产物: {OUT1}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
