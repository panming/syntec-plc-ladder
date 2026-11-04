#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""简体 -> 繁体（台湾用字）转换，专为 .lad 注释设计。

为什么需要这个脚本：新代 .lad 的注释块编码固定是 cp950(Big5)，
与编辑器界面是简体还是繁体无关。简体字在 cp950 里没有字形，
写进去**不会报错**，只会在编辑器里显示成问号（或整段被吞）。
所以注释必须先转繁体再写。

用法：
    python zh_tw.py "润滑油泵控制程序"          # 打印转换结果
    python zh_tw.py --check "润滑油泵控制程序"   # 只检查哪些字进不去 cp950
    python zh_tw.py --table                     # 打印 Markdown 映射表(生成文档用)
    python zh_tw.py --audit                     # 自查映射表(源字本来就能编码的可疑项)
    python zh_tw.py --file 注释.txt              # 转换整个文件
    echo "润滑油泵" | python zh_tw.py -          # 从 stdin 读

作为模块：
    from zh_tw import to_tw, unencodable
    to_tw("润滑油泵")        # -> '潤滑油泵'
    unencodable("潤滑油泵")  # -> []
"""
import argparse
import sys

ENCODING = "cp950"        # .lad 注释块固定编码

# 简体 -> 繁体。紧凑写法：每两个字符一对，"简繁"。
# 只收"简体字形进不去 cp950"的字 —— 本来就以繁体字形存在的字不需要映射，
# 硬映射反而可能改错语义（比如"松"在 cp950 里有，不必转"鬆"）。
_PAIRS = """
报報 锁鎖 复復 异異 态態 产產 断斷 开開 关關 过過 载載 压壓 温溫 电電 气氣
发發 连連 续續 间間 错錯 误誤 讯訊 号號 显顯 鸣鳴 响響 继繼 触觸 点點 线線
铁鐵 绕繞 组組 险險 丝絲 钮鈕 灯燈 极極 级級 转轉 换換 变變 频頻 额額 绝絕
缘緣 导導 体體 铜銅 铝鋁 阀閥 轴軸 马馬 达達 齿齒 轮輪 带帶 链鏈 杆桿 轨軌
库庫 却卻 润潤 动動 滤濾 网網 节節 门門 盖蓋 壳殼 盘盤 夹夾 紧緊 启啟 运運
环環 骤驟 顺順 参參 数數 设設 计計 时時 较較 输輸 单單 双雙 选選 择擇 统統
机機 备備 确確 认認 检檢 测測 试試 验驗 证證 审審 记記 录錄 说說 书書 注註
释釋 项項 条條 这這 么麼 个個 们們 为為 与與 从從 会會 后後 里裡 还還 应應
该該 对對 于於 现現 实實 际際 经經 结結 据據 类類 长長 画畫 图圖 标標 准準
签簽 键鍵 删刪 减減 调調 简簡 须須 总總 汇匯 详詳 细細 周週 钟鐘 历歷 进進
闭閉 维維 护護 养養 洁潔 无無 业業 页頁 义義 仅僅 优優 许許 语語 远遠 约約
张張 种種 装裝 状狀 别別 边邊 并並 厂廠 处處 传傳 创創 当當 档檔 顶頂 订訂
读讀 尔爾 废廢 费費 风風 钢鋼 给給 构構 购購 观觀 规規 柜櫃 积積 见見 将將
脚腳 尽盡 举舉 块塊 况況 来來 离離 两兩 灵靈 领領 满滿 没沒 灭滅 内內 拟擬
鸟鳥 喷噴 齐齊 轻輕 区區 权權 热熱 软軟 声聲 湿濕 适適 势勢 随隨 台臺 听聽
头頭 团團 卫衛 稳穩 务務 雾霧 习習 写寫 悬懸 严嚴 阳陽 样樣 议議 邮郵 预預
员員 圆圓 愿願 云雲 杂雜 暂暫 则則 赠贈 账賬 针針 诊診 织織 执執 职職 质質
钻鑽 监監 视視 绪緒 请請 讲講 让讓 桥橋 联聯 车車 镗鏜 钥鑰 码碼 忆憶
络絡 铣銑 铲鏟 静靜 负負 馈饋 弹彈 脉脈 冲衝 编編 栅柵
"""

# 源字本来就在 cp950 里、但转成繁体更符合台湾用字的（风格转换，非编码必需）。
# 其中这几项有语义歧义，转换可能改错意思，列出来备查：
SEMANTIC_TRAPS = {
    "里": "公里 / 里 作为长度单位时应保留「里」，转成「公裡」是错的",
    "复": "復 表「再、返回」（復位 ✓）；複 表「重复」（複製），不要一律转復",
    "准": "準 表「标准」（校準 ✓）；准 表「准许」，两者并存",
    "台": "臺 表台湾/台座；工作台 → 工作臺 可接受，但机台编号等场合宜保留",
    "于": "於 表「在」；姓氏「于」不能转",
    "并": "並 表「并且」；合併 用併",
    "云": "雲 表云；「云」作「说」时不能转（工控语境罕见）",
    "后": "後 表「之后」；皇后 用后（工控语境罕见）",
}


def _build(text):
    """解析紧凑字对表。同一简体出现两次且繁体不同 -> 直接报错，避免静默覆盖。"""
    toks = text.split()
    s2t = {}
    for tok in toks:
        if len(tok) != 2:
            raise ValueError(f"映射表里有一项不是两个字符: {tok!r}")
        s, t = tok[0], tok[1]
        if s in s2t and s2t[s] != t:
            raise ValueError(f"映射冲突: {s} -> {s2t[s]} / {t}")
        s2t[s] = t
    return s2t


S2T = _build(_PAIRS)


def can_encode(text):
    """能否按 cp950 编码（.lad 注释块的唯一编码）"""
    try:
        text.encode(ENCODING)
        return True
    except UnicodeEncodeError:
        return False


def unencodable(text):
    """返回 [(字符, 位置, 建议)]，建议为 None 表示映射表里也没有"""
    return [(ch, i, S2T.get(ch)) for i, ch in enumerate(text) if not can_encode(ch)]


def to_tw(text):
    """简体 -> 繁体，逐字映射"""
    return "".join(S2T.get(ch, ch) for ch in text)


def report(text):
    """人可读的检查报告"""
    bad = unencodable(text)
    if not bad:
        return f"OK  所有字符均可编码 (cp950): {text}"
    lines = [f"FAIL  {len(bad)} 个字符无法按 cp950 编码:"]
    for ch, pos, sug in bad:
        hint = f"->  {sug}" if sug else "->  (映射表无此字，换写法)"
        lines.append(f"   第 {pos + 1} 字  {ch}  {hint}")
    conv = to_tw(text)
    still = unencodable(conv)
    if still:
        lines.append("转换后仍有无法编码的字: " + " ".join(c for c, _p, _s in still))
    else:
        lines.append(f"转换后可用: {conv}")
    return "\n".join(lines)


def table_md(per_row=8):
    """Markdown 对照表（供 references/comment-encoding.md 生成，保证文档与脚本一致）"""
    pairs = sorted(S2T.items(), key=lambda kv: kv[0].encode("utf-8"))
    cells = [f"{s}→{t}" for s, t in pairs]
    rows = ["| " + " | ".join(cells[i:i + per_row]) + " |"
            for i in range(0, len(cells), per_row)]
    return "\n".join(rows)


def audit():
    """自查映射表。返回 (errors, style, traps)：
       errors —— 真正的错误（目标字进不去 cp950、非单字映射），必须修
       style  —— 源字本来就能编码，属"风格转换"，可选
       traps  —— style 里有语义歧义的，已在 SEMANTIC_TRAPS 记录
    """
    errors, style, traps = [], [], []
    for s, t in sorted(S2T.items()):
        if len(s) != 1 or len(t) != 1:
            errors.append(f"非单字映射: {s} -> {t}")
            continue
        if not can_encode(t):
            errors.append(f"目标字无法编码: {s} -> {t}（映射无效）")
        if can_encode(s):
            if s in SEMANTIC_TRAPS:
                traps.append(f"{s} -> {t}：{SEMANTIC_TRAPS[s]}")
            else:
                style.append(f"{s} -> {t}")
    return errors, style, traps


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="简体转繁体（cp950 安全），用于新代 .lad 注释")
    ap.add_argument("text", nargs="?", help="要转换的文字；给 - 表示读 stdin")
    ap.add_argument("--check", action="store_true", help="只检查可编码性，不转换")
    ap.add_argument("--file", help="处理整个文本文件")
    ap.add_argument("--table", action="store_true", help="打印 Markdown 映射表")
    ap.add_argument("--audit", action="store_true", help="自查映射表")
    ap.add_argument("--strict", action="store_true",
                    help="转换后仍有不可编码字符时以非 0 退出")
    args = ap.parse_args(argv)

    if args.table:
        print(table_md())
        return 0
    if args.audit:
        errors, style, traps = audit()
        print(f"映射表 {len(S2T)} 项：编码必需 {len(S2T) - len(style)} 项，"
              f"风格转换 {len(style)} 项（其中语义歧义 {len(traps)} 项）")
        if errors:
            print(f"\n[错误] {len(errors)} 项，必须修：")
            for e in errors:
                print("  " + e)
        if traps:
            print(f"\n[注意] 以下转换有语义歧义，批量转换后要人工扫一眼：")
            for t in traps:
                print("  " + t)
        if style:
            print(f"\n[信息] 源字本就能编码、只是字形不同（通常无害）：")
            print("  " + "、".join(style))
        print("\n自查" + ("未通过" if errors else "通过"))
        return 1 if errors else 0

    if args.file:
        with open(args.file, encoding="utf-8") as f:
            text = f.read()
        if args.check:
            print(report(text))
            return 1 if unencodable(text) else 0
        out = to_tw(text)
        with open(args.file, "w", encoding="utf-8") as f:
            f.write(out)
        bad = unencodable(out)
        print(f"已转换写回 {args.file}")
        if bad:
            print("[警告] 仍有无法编码的字: "
                  + " ".join(c for c, _p, _s in bad), file=sys.stderr)
            return 1 if args.strict else 0
        return 0

    if args.text == "-" or (args.text is None and not sys.stdin.isatty()):
        text = sys.stdin.read()
    elif args.text is None:
        ap.print_help()
        return 2
    else:
        text = args.text

    if args.check:
        print(report(text))
        return 1 if unencodable(text) else 0

    out = to_tw(text)
    print(out)
    bad = unencodable(out)
    if bad:
        print("[警告] 仍有无法编码的字: "
              + " ".join(c for c, _p, _s in bad), file=sys.stderr)
        return 1 if args.strict else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
