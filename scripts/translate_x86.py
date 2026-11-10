#!/usr/bin/env python3
"""batch5 v3: the x86 programs among the tests. A test qualifies when every thread is TSO and uses only LDR, STR and
   full DMB (DMB ISH/SY = MFENCE); ISB (the TSO marker) is dropped. Writes x86/<name>.litmus in herd's X86 syntax.
   python3 x86/translate.py  -> list of translated tests on stdout"""
import csv, os, re, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
L = {r['name']: r for r in csv.DictReader(open(os.path.join(HERE, 'list.tsv')), delimiter='\t')}
REG = ['EAX', 'EBX', 'ECX', 'EDX', 'ESI', 'EDI']
out = []
for n, r in L.items():
    if set(r['modes']) != {'T'}: continue
    src = open(os.path.join(HERE, 'typed', n + '.litmus')).read()
    init = src[src.index('{') + 1:src.index('}')]
    env = {}                                           # (thread, reg) -> location or value
    for a in init.split(';'):
        m = re.match(r'\s*(?:int64_t\s+)?(\d+):(X\d+)\s*=\s*(\w+)\s*$', a)
        if m: env[(int(m.group(1)), m.group(2))] = m.group(3)
    lines = src[src.index('}') + 1:].split('\n')
    hdr = next(i for i, l in enumerate(lines) if l.strip().startswith('P0'))
    nth = lines[hdr].count('|') + 1
    prog = [[] for _ in range(nth)]; ok = True; regmap = [{} for _ in range(nth)]
    i = hdr + 1
    while i < len(lines) and '|' in lines[i]:
        for t, c in enumerate(lines[i].rstrip(' ;').split('|')):
            c = c.strip()
            if not c or c == 'ISB': continue
            m = re.match(r'STR (X\d+),\[(X\d+)\]$', c)
            if m and (t, m.group(1)) in env and (t, m.group(2)) in env and env[(t, m.group(1))].isdigit():
                prog[t].append('MOV [%s],$%s' % (env[(t, m.group(2))], env[(t, m.group(1))])); continue
            if m: ok = False; continue
            m = re.match(r'LDR (X\d+),\[(X\d+)\]$', c)
            if m and (t, m.group(2)) not in env: ok = False; continue
            if m:
                rg = regmap[t].setdefault(m.group(1), REG[len(regmap[t])])
                prog[t].append('MOV %s,[%s]' % (rg, env[(t, m.group(2))])); continue
            if c in ('DMB ISH', 'DMB SY'): prog[t].append('MFENCE'); continue
            ok = False
        i += 1
    if not ok: continue
    rest = '\n'.join(lines[i:])
    cond = rest[rest.index('exists'):].strip() if 'exists' in rest else None
    if cond is None or 'filter' in rest: continue
    cond = re.sub(r'(\d+):(X\d+)', lambda m: '%s:%s' % (m.group(1), regmap[int(m.group(1))][m.group(2)]), cond)
    cond = re.sub(r'(?<![:\w\[])([a-z]\w*)=(\d+)', r'[\1]=\2', cond)
    locs = sorted({v for (t, k), v in env.items() if not v.isdigit()})
    w = max(len(x) for p in prog for x in p) + 2 if any(prog) else 8
    rows = ['X86 %s' % n, '{ %s }' % ' '.join('%s=0;' % l for l in locs),
            ' | '.join(('P%d' % t).ljust(w) for t in range(nth)) + ' ;']
    for k in range(max(len(p) for p in prog)):
        rows.append(' | '.join((prog[t][k] if k < len(prog[t]) else '').ljust(w) for t in range(nth)) + ' ;')
    rows.append(cond)
    open(os.path.join(HERE, 'x86', n + '.litmus'), 'w').write('\n'.join(rows) + '\n')
    out.append(n)
print('\n'.join(out))
