#!/usr/bin/env python3
"""Normalized program of an AArch64 litmus file (src/ or typed/ form), for matching tests across batches.

key(path, mask) -> canonical string. Two tests have the same key iff, up to
  - register renaming (per thread, by first occurrence; a register that holds an init constant or location and is
    never written in its thread is replaced by that value: STR X12,[X10] with X12=1, X10=x is 'STR #1,[@x]'),
  - location renaming (by first occurrence over the threads in order, condition last),
  - label renaming, C types (typed/ files), whitespace, order of conjuncts in exists/filter,
  - optionally (perm=True) a permutation of the threads, with the mode mask and the condition permuted alike,
they have the same instructions per thread, the same initial values, the same filter and condition and the same mode
mask. Width (X/W) of a register is kept. Usage as a script: norm.py <file> <mask> prints the key.
"""
import itertools, re, sys

WRITES_FIRST = re.compile(r'(LD\w*|EOR|ADD|SUB|AND|ORR|MOV\w*|LSL|LSR|CSEL|CSET)$')   # Rd/Rt first, written
AMO = re.compile(r'(SWP\w*|LD(ADD|CLR|SET|EOR|SMAX|SMIN|UMAX|UMIN)\w*)$')            # Rs, Rt(written), [Rn]
CAS = re.compile(r'CAS\w*$')                                                          # Rs (written), Rt, [Rn]
STX = re.compile(r'ST(L)?X(R|P)\w*$')                                                 # Ws (written), Rt, [Rn]


def parse(path):
    txt = open(path).read()
    lines = txt.split('\n')
    i0 = next(i for i, l in enumerate(lines) if l.lstrip().startswith('{'))
    j = i0
    while '}' not in lines[j]: j += 1
    init_txt = ' '.join(lines[i0:j + 1]).strip()[1:].rsplit('}', 1)[0]
    init = {}
    for it in init_txt.split(';'):
        it = it.strip()
        if not it or '=' not in it: continue                       # 'int64_t x' declarations
        k, v = [s.strip() for s in it.split('=', 1)]
        k = k.split()[-1]                                          # drop C type
        init[k] = v
    h = next(i for i in range(j + 1, len(lines)) if re.match(r'\s*P0\s*(\||;)', lines[i]))
    e = next(i for i in range(h + 1, len(lines)) if re.match(r'\s*(exists|~exists|forall|filter|locations)', lines[i]))
    k = len(lines[h].rstrip().rstrip(';').split('|'))
    cols = [[] for _ in range(k)]
    for l in lines[h + 1:e]:
        if not l.strip(): continue
        cells = l.rstrip().rstrip(';').split('|')
        assert len(cells) == k, (path, l)
        for t, c in enumerate(cells):
            if c.strip(): cols[t].append(re.sub(r'\s+', ' ', c.strip()))
    tail = ' '.join(l.strip() for l in lines[e:] if l.strip())
    return cols, init, tail


def _written(ins):
    op, _, args = ins.partition(' ')
    regs = re.findall(r'\b[XW](\d+)\b', args.split('[')[0])
    if not regs: return set()
    if AMO.match(op): return {regs[1]} if len(regs) > 1 else set()
    if CAS.match(op) or STX.match(op): return {regs[0]}
    if WRITES_FIRST.match(op): return {regs[0]}
    return set()


def _canon(cols, init, tail, mask, order):
    n = len(cols)
    locmap = {}
    def L(v):
        if re.fullmatch(r'-?\d+|0x[0-9a-fA-F]+', v): return '#%d' % int(v, 0)
        locmap.setdefault(v, 'L%d' % len(locmap)); return '@' + locmap[v]
    out, regmaps = [], []
    for newt, t in enumerate(order):
        code = cols[t]
        written = set().union(*[_written(x) for x in code]) if code else set()
        rmap, lmap = {}, {}
        def R(m):
            w, num = m.group(1), m.group(2)
            v = init.get('%d:X%s' % (t, num), init.get('%d:W%s' % (t, num)))
            if v is not None and num not in written: return L(v)
            rmap.setdefault(num, 'r%d' % len(rmap)); return w + rmap[num][1:]
        def lab(m):
            lmap.setdefault(m.group(0), 'LAB%d' % len(lmap)); return lmap[m.group(0)]
        cc = []
        for x in code:
            x = re.sub(r'\b(LC\w+|L\d+\w*)\b', lab, x)
            x = re.sub(r'\b([XW])(\d+)\b', R, x)
            cc.append(x)
        # registers with an init value that are written in the thread: keep the initial value
        for num in sorted(written, key=lambda s: int(s)):
            v = init.get('%d:X%s' % (t, num))
            if v is not None and num in rmap: cc.append('init r%s=%s' % (rmap[num][1:], L(v)))
        regmaps.append(rmap)
        out.append(' ; '.join(cc))
    inv = {t: i for i, t in enumerate(order)}
    def condmap(s):
        def thr(m):
            t, w, num = int(m.group(1)), m.group(2), m.group(3)
            rm = regmaps[inv[t]]
            return '%d:%s%s' % (inv[t], w, rm[num][1:] if num in rm else '?' + num)
        s = re.sub(r'\b(\d+):([XW])(\d+)\b', thr, s)
        s = re.sub(r'\[?\b([a-z]\w*)\b\]?(?=\s*=)', lambda m: L(m.group(1)) if m.group(1) in locmap or m.group(1) in 'xyzw' else m.group(0), s)
        return s
    parts = []
    for clause in re.findall(r'(~?exists|forall|filter|locations)\s*(\(.*?\)|\[.*?\])(?=\s*(?:~?exists|forall|filter|locations|$))', tail):
        kw, body = clause
        b = body.strip()[1:-1]
        if '\\/' in b: parts.append(kw + ' ' + condmap(b).replace(' ', ''))
        else: parts.append(kw + ' ' + ' /\\ '.join(sorted(condmap(c).replace(' ', '') for c in b.split('/\\'))))
    pmask = ''.join('T' if mask >> t & 1 else 'A' for t in order)
    return pmask + ' || ' + ' || '.join(out) + ' || ' + ' ; '.join(sorted(parts))


def key(path, mask, perm=False):
    cols, init, tail = parse(path)
    n = len(cols)
    if not perm: return _canon(cols, init, tail, mask, list(range(n)))
    return min(_canon(cols, init, tail, mask, list(p)) for p in itertools.permutations(range(n)))


if __name__ == '__main__':
    print(key(sys.argv[1], int(sys.argv[2]), '--perm' in sys.argv))
