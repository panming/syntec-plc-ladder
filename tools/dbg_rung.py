# -*- coding: utf-8 -*-
"""调试单条 rung: 打印原始网格 / 竖线 / 重建树 / 重新生成的网格与差异"""
import sys
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
for _d in (_HERE, os.path.join(_HERE, "src"), os.path.join(os.path.dirname(_HERE), "src")):
    if os.path.isdir(_d) and _d not in sys.path:
        sys.path.insert(0, _d)

import syntec_re as R
import syntec_parse as P
import syntec_layout as Y


def show(rows, a, b, tag):
    print(f'--- {tag}  R{a+1}..R{b+1} ---')
    for r in range(a, b + 1):
        cells = []
        for i, c in enumerate(rows[r]):
            if c is None:
                continue
            conn, el, raw = c
            name = el[0] if el[0] != 'FB' else f"FB:{el[1]}:{hex(el[2])}"
            if el[0] == 'CONTACT':
                name = f"C{'NO' if el[1] == 'NO' else 'NC'}{el[2]}"
            cells.append(f'{i}:{conn:02x}:{name}')
        print(f'  r{r}: ' + '  '.join(cells))


def main(path, r0, r1):
    data = open(path, 'rb').read()
    recs = [p for k, p in R.parse_records(data) if k == 'logic']
    rows = [P.decode_row(r) for r in recs]
    gd = P.guides(rows)
    print('全部竖线:', gd)
    print('rung 分组:', P.rung_groups(rows))
    show(rows, r0, r1, '原文')
    node, why = P.build_tree(rows, gd, r0, r1)
    print('树 =', why if node is None else Y._w(node), why or '')
    if node is None:
        return
    print('树 =', _fmt(node))
    for la in (False, True):
        try:
            grid = Y.to_grid(node, left_anchor=la)
        except Exception as e:
            print(f'  left_anchor={la}: layout 失败 {e}')
            continue
        out = [Y.emit_grid(g) for g in grid]
        print(f'  left_anchor={la}: 生成 {len(out)} 行')
        rows2 = [P.decode_row(x) for x in out]
        show(rows2, 0, len(out) - 1, f'生成(la={la})')
        print('  竖线生成:', P.guides(rows2))
        nd2, why2 = P.build_tree(rows2, P.guides(rows2), 0, len(out) - 1)
        print('  回读:', 'OK' if nd2 == node else ('FAIL ' + str(why2)), _fmt(nd2) if nd2 else '')
        print('  自检:', Y.check_grid(grid) or 'OK')


def _fmt(n):
    if n is None:
        return '(None)'
    if n[0] == 'LEAF':
        return str(n[1])
    return '(' + (',' if n[0] == 'SERIES' else '|').join(_fmt(c) for c in n[1]) + ')'


if __name__ == '__main__':
    main(sys.argv[1], int(sys.argv[2]) - 1, int(sys.argv[3]) - 1)
