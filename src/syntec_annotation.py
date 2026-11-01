"""解析新代 PLC 编辑器导出的注解档 CUSCMT_*.dat

格式(纯文本, 每行一条):
    地址<TAB>短批注<TAB>长批注<CRLF>
例如:
    O10	test1	test2
    I132	test1	test2

说明:
- 这是编辑器「汇入/汇出注解档」导出的明文格式, 与 .lad 内部批注块的
  二进制打包(2字符+00 00)不同, 但内容等价。
- 「导出注解档」只导出当前 .lad 内实际用到的元件批注。
- 要拿到完整的标准 C/S/R 地址含义, 须先在编辑器执行「汇入标准注解」,
  再导出, 该文件才会包含几百条标准地址。
"""
def parse_dat(path):
    d = open(path, 'rb').read()
    text = d.decode('utf-8', 'replace')
    out = {}
    for line in text.split('\n'):
        line = line.rstrip('\r')
        if not line.strip():
            continue
        parts = line.split('\t')
        addr = parts[0].strip()
        short = parts[1].strip() if len(parts) > 1 else ''
        long = parts[2].strip() if len(parts) > 2 else ''
        out[addr] = (short, long)
    return out


if __name__ == '__main__':
    import sys
    p = sys.argv[1] if len(sys.argv) > 1 else r"C:/Users/panming/Desktop/CUSCMT_CHS.dat"
    res = parse_dat(p)
    print(f"解析到 {len(res)} 条注解:")
    for a, (s, l) in res.items():
        print(f"  {a:8s} 短={s!r} 长={l!r}")
