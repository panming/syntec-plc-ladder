#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""打发布包：仓库包 + 技能包，并当场自检。

    python tools/package.py                 # 输出到 dist/
    python tools/package.py --out ~/Desktop # 输出到指定目录
    python tools/package.py --no-verify     # 跳过解压自检

产出两个 zip：

    syntec-plc-ladder-v<VER>.zip      整个仓库（不含 .git / dist / __pycache__）
                                     里面内嵌 skill/syntec-plc.zip，拿到就能离线用
    syntec-plc-skill-v<SKILL_VER>.zip 技能包，解压到 ~/.workbuddy/skills/ 即可

版本号自动从源码读，不手填：
    src/build_bundle.py 的 VERSION
    skill/syntec-plc/SKILL.md frontmatter 的 version
两个包内容有重叠（技能包既是独立包，也内嵌在仓库包里），所以一次打完能保证一致。
"""
import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_DIR = os.path.join(ROOT, "skill", "syntec-plc")
BUNDLE = os.path.join(ROOT, "src", "build_bundle.py")
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")

EXCLUDE_DIRS = {".git", "__pycache__", "dist", "build", ".venv", "venv",
                ".idea", ".vscode", ".pytest_cache"}
EXCLUDE_EXT = {".pyc", ".pyo", ".zip"}
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", "desktop.ini"}


def read_version():
    s = open(BUNDLE, encoding="utf-8").read()
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"', s, re.M)
    if not m:
        sys.exit(f"读不到版本号：{BUNDLE}")
    return m.group(1)


def read_skill_version():
    s = open(SKILL_MD, encoding="utf-8").read()
    head = s.split("---")[1] if s.startswith("---") else ""
    m = re.search(r"^version:\s*(\S+)", head, re.M)
    return m.group(1) if m else "0.0.0"


def walk_files(src, skip_names=()):
    """返回 [(绝对路径, 相对路径)]，跳过缓存 / 打包产物。"""
    out = []
    for dirpath, dirnames, files in os.walk(src):
        dirnames[:] = sorted(d for d in dirnames if d not in EXCLUDE_DIRS)
        for f in sorted(files):
            if os.path.splitext(f)[1].lower() in EXCLUDE_EXT:
                continue
            if f in EXCLUDE_NAMES or f in skip_names:
                continue
            full = os.path.join(dirpath, f)
            rel = os.path.relpath(full, src).replace("\\", "/")
            out.append((full, rel))
    return out


def build_zip(src, prefix, out_path, extra=(), skip_names=()):
    items = walk_files(src, skip_names)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for full, rel in items:
            z.write(full, f"{prefix}/{rel}")
        for full, arc in extra:
            z.write(full, arc)
    return len(items) + len(extra)


def read_readme_version():
    """README 顶部写着「MCP `vX.Y.Z`」，改了代码忘改这里，朋友看到的版本就是错的。"""
    s = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    m = re.search(r"MCP `v([^`]+)`", s)
    return m.group(1) if m else None


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def inspect(zip_path):
    """返回 (文件数, 重名列表, 可疑条目列表, 中文名未标 UTF-8 的条目)。"""
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()
        info = z.infolist()
    dup = sorted({n for n in names if names.count(n) > 1})
    bad = [n for n in names
           if n.endswith((".pyc", ".pyo")) or "/.git/" in n or n.startswith(".git/")
           or "__pycache__" in n or n.endswith("/.DS_Store")]
    nonutf8 = [i.filename for i in info
               if not i.filename.isascii() and not (i.flag_bits & 0x800)]
    return len(names), dup, bad, nonutf8


def verify_repo_zip(zip_path):
    """解压到临时目录，跑单文件版自检 + 端到端 MCP 测试。
    证明「朋友拿到这个包，解压就能跑通」，而不是只看 zip 打得开。"""
    tmp = tempfile.mkdtemp(prefix="syntec_pkg_")
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(tmp)
        root = os.path.join(tmp, "syntec-plc-ladder")
        exe = os.path.join(root, "syntec-ladder-mcp-standalone.py")
        if not os.path.isfile(exe):
            return False, "包内缺 syntec-ladder-mcp-standalone.py"

        r1 = subprocess.run([sys.executable, exe, "--selftest"],
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=root)
        t1 = [l for l in (r1.stdout or "").strip().splitlines() if l.strip()][-1:]
        ok1 = r1.returncode == 0 and "PASS" in (r1.stdout or "")

        e2e = os.path.join(root, "tools", "e2e_mcp.py")
        ok2, t2 = True, "跳过（包内无 tools/e2e_mcp.py）"
        if os.path.isfile(e2e):
            r2 = subprocess.run([sys.executable, e2e, "--script", exe],
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", cwd=root)
            ok2 = r2.returncode == 0 and "PASS" in (r2.stdout or "")
            t2 = ([l for l in (r2.stdout or "").strip().splitlines() if l.strip()][-1:]
                  or ["无输出"])[0].strip()

        return ok1 and ok2, f"selftest: {t1[0].strip() if t1 else '无输出'}  |  e2e: {t2}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def kb(n):
    return f"{n / 1024:.1f} KB"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"),
                    help="输出目录（默认 dist/）")
    ap.add_argument("--no-verify", action="store_true", help="跳过解压自检")
    a = ap.parse_args()

    ver = read_version()
    sver = read_skill_version()
    out_dir = os.path.abspath(os.path.expanduser(a.out))
    os.makedirs(out_dir, exist_ok=True)

    repo_zip = os.path.join(out_dir, f"syntec-plc-ladder-v{ver}.zip")
    skill_zip = os.path.join(out_dir, f"syntec-plc-skill-v{sver}.zip")
    nested = os.path.join(SKILL_DIR, "syntec-plc.zip")

    print(f"syntec-plc-ladder  v{ver}   技能包 v{sver}")
    print("-" * 66)

    rv = read_readme_version()
    if rv != ver:
        print(f"[FAIL] README 顶部写的是 v{rv}，源码里是 v{ver} —— 先改 README")
        return 1

    # 1) 技能包先打，供仓库包内嵌
    n_skill = build_zip(SKILL_DIR, "syntec-plc", nested)
    shutil.copyfile(nested, skill_zip)
    os.remove(nested)

    # 2) 仓库包（内嵌上面那一份，保证两处内容一致）
    n_repo = build_zip(ROOT, "syntec-plc-ladder", repo_zip,
                       extra=[(skill_zip, "syntec-plc-ladder/skill/syntec-plc.zip")],
                       skip_names={"syntec-plc.zip"})

    ok_all = True
    for label, path, n in (("仓库包", repo_zip, n_repo), ("技能包", skill_zip, n_skill)):
        cnt, dup, bad, nonutf8 = inspect(path)
        size = os.path.getsize(path)
        print(f"{label}  {os.path.basename(path)}")
        print(f"         {cnt} 文件  {kb(size)}  sha256 {sha256(path)[:16]}")
        problems = []
        if dup:
            problems.append(f"重名 {dup}")
        if bad:
            problems.append(f"不该打包的条目 {bad[:5]}")
        if nonutf8:
            problems.append(f"中文文件名未标 UTF-8: {nonutf8[:3]}")
        if cnt != n:
            problems.append(f"计数不符 {cnt} != {n}")
        if problems:
            ok_all = False
            print("         [FAIL] " + "；".join(problems))
        else:
            print("         [PASS] 无重名 / 无缓存文件 / 文件名编码正常")

    if not a.no_verify:
        ok, msg = verify_repo_zip(repo_zip)
        ok_all &= ok
        print("自检  解压到临时目录后实跑")
        print(f"         [{'PASS' if ok else 'FAIL'}] {msg}")

    print("-" * 66)
    print("全部通过 [PASS]" if ok_all else "有问题 [FAIL]")
    return 0 if ok_all else 1


if __name__ == "__main__":
    sys.exit(main())
