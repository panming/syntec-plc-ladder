#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端验证 MCP 服务：真的把进程起起来，走 JSON-RPC，不看源码猜。

    python tools/e2e_mcp.py                          # 测发布产物(单文件版)
    python tools/e2e_mcp.py --script src/mcp_server.py

查五件事：
  1. initialize 返回 serverInfo（名字 + 版本）
  2. tools/list 返回 13 个工具，且工具描述里没有开发者本机路径
  3. 完整写一份程序：new → add_rung → validate → save → load_lad 读回
  4. 写 S 段会被 validate 拦下（语义检查真的生效，不是写着好看）
  5. 同一地址两处置位/复位会被报「重复元件」

退出码 0 表示全通过。适合发版前跑一遍、或放进 CI。
"""
import argparse
import json
import os
import subprocess
import sys
import tempfile
import re
import shutil

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPECT_TOOLS = {
    "new_ladder", "load_lad", "read_ladder", "dump_rungs", "lookup_address",
    "add_rung", "set_comment", "add_comment_line", "validate", "preview",
    "save", "explain_rung", "explain_format",
}

NO = lambda a: {"kind": "contact", "norm": "NO", "addr": a}          # noqa: E731
COIL = lambda a, n="NO": {"kind": "coil", "norm": n, "addr": a}      # noqa: E731
END = {"kind": "end"}

R = []          # 请求队列
def call(method, params=None):
    R.append({"jsonrpc": "2.0", "id": len(R) + 1, "method": method,
              "params": params or {}})
    return len(R)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default=os.path.join(ROOT, "syntec-ladder-mcp-standalone.py"))
    ap.add_argument("--timeout", type=int, default=90)
    a = ap.parse_args()
    if not os.path.isfile(a.script):
        sys.exit(f"找不到服务脚本：{a.script}")

    work = tempfile.mkdtemp(prefix="syntec_e2e_")
    out_lad = os.path.join(work, "e2e_program.lad")

    id_init = call("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "e2e", "version": "1"}})
    id_tools = call("tools/list")
    # --- 正常流程 ---
    call("tools/call", {"name": "new_ladder", "arguments": {"path": out_lad}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [NO("I0"), COIL("A0", "LATCH")]}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [NO("A0"), COIL("O3")]}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [END]}})
    id_ok = call("tools/call", {"name": "validate", "arguments": {}})
    id_save = call("tools/call", {"name": "save", "arguments": {}})
    id_load = call("tools/call", {"name": "load_lad", "arguments": {"path": out_lad}})
    # --- 写 S 段应被拦 ---
    call("tools/call", {"name": "new_ladder", "arguments": {}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [NO("I0"), COIL("S0", "LATCH")]}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [END]}})
    id_s = call("tools/call", {"name": "validate", "arguments": {}})
    # --- 重复元件应被报 ---
    call("tools/call", {"name": "new_ladder", "arguments": {}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [NO("I0"), COIL("A1", "UNLATCH")]}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [NO("I1"), COIL("A1", "UNLATCH")]}})
    call("tools/call", {"name": "add_rung", "arguments": {"elements": [END]}})
    id_dup = call("tools/call", {"name": "validate", "arguments": {}})

    payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in R) + "\n"
    try:
        p = subprocess.run([sys.executable, a.script], input=payload,
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=a.timeout, cwd=work)
    finally:
        pass

    resp = {}
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if "id" in msg:
            resp[msg["id"]] = msg
    # 有的实现把业务结果放在 result.content[].text，统一取文本
    def text(i):
        m = resp.get(i) or {}
        r = m.get("result") or {}
        if isinstance(r.get("content"), list):
            return "".join(c.get("text", "") for c in r["content"]
                           if isinstance(c, dict))
        return json.dumps(r, ensure_ascii=False)

    ok_all = True
    def chk(name, ok, detail=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  {detail}" if detail else ""))

    print("=" * 66)
    print(f" 服务: {os.path.relpath(a.script, ROOT)}")
    print("=" * 66)

    info = resp.get(id_init, {}).get("result", {}).get("serverInfo", {})
    chk("initialize 返回 serverInfo",
        info.get("name") == "syntec-ladder" and bool(info.get("version")),
        f"{info.get('name')} v{info.get('version')}")

    tools = resp.get(id_tools, {}).get("result", {}).get("tools", [])
    names = {t.get("name") for t in tools}
    chk("tools/list 返回 13 个工具", names == EXPECT_TOOLS,
        f"{len(names)} 个" + ("" if names == EXPECT_TOOLS else f"；差异 {names ^ EXPECT_TOOLS}"))
    blob = json.dumps(tools, ensure_ascii=False)
    # 只查「是不是把开发者本机路径固化进工具描述了」，不需要知道那是谁
    leak = re.search(r"[A-Za-z]:[\\/]Users[\\/]", blob) or "Desktop" in blob
    chk("工具描述不含本机绝对路径", not leak,
        "工具描述里出现了开发者本机路径" if leak else "")

    # 正常工程：4 条 rung（含 END）+ 一置一复，不该有警告
    t_ok = text(id_ok)
    chk("正常程序 validate 通过", "校验通过" in t_ok, t_ok.replace("\n", " ")[:70])

    t_save = text(id_save)
    size = os.path.getsize(out_lad) if os.path.isfile(out_lad) else 0
    chk("save 真的写出文件", size > 0 and str(size) in t_save, f"{size} 字节")

    t_load = text(id_load)
    chk("load_lad 能读回自己写的文件",
        "rung" in t_load.lower() or "行" in t_load, t_load.replace("\n", " ")[:60])

    t_s = text(id_s)
    chk("写 S 段被拦下", "S 段" in t_s and ("只读" in t_s or "CNC" in t_s),
        t_s.replace("\n", " ")[:80])

    t_dup = text(id_dup)
    chk("同址两处复位报「重复元件」", "重复元件" in t_dup, t_dup.replace("\n", " ")[:80])

    if p.returncode not in (0, None) and not ok_all:
        print(f"  服务退出码 {p.returncode}")
        err = (p.stderr or "").strip().splitlines()[-3:]
        for e in err:
            print("  stderr:", e)

    print("=" * 66)
    print("全部通过 [PASS]" if ok_all else "有失败项 [FAIL]")
    shutil.rmtree(work, ignore_errors=True)
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
