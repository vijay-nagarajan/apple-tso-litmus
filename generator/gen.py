#!/usr/bin/env python3
"""batch5 generator: one ppo-table entry per test, in every position of every shape, under every mode assignment.

The ppo table of a model is indexed by (thread mode in {A, T}) x (edge kind in {WW, RR, RW, WR}, two accesses to
different addresses) x (mechanism); each entry is ordered or not ordered. A test queries one entry: a critical-cycle
shape, the queried mechanism on one po-edge (the pivot), and the base mechanism of its thread's mode on every other
po-edge. Then that edge alone decides the verdict: forbidden iff the entry is ordered.

Shapes (as batch4/mixcov/gen_mixcov.py): MP S LB R 2+2W SB WRC ISA2 RWC IRIW, same conditions.

Mechanism universe for an edge of kind K on a thread of mode M (universe(M, K)):
  access forms, nothing between: load form in {ldr, ldapr, ldar}, store form in {str, stlr}, every combination
      (named '<first>.<second>', e.g. ldar.ldr; ldr.ldr / str.str / ... is named 'plain')
  plain accesses with one thing between: dmb dmbld dmbst dsb dsbld dsbst (DMB/DSB ISH, ISHLD, ISHST)
      and, if the edge starts with a load: addr (RR, RW), data (RW), ctrl (RR, RW), ctrlisb (RR, RW)
  TSO-thread WR edges only (AMOs): swp.ldr (the store is a SWP), str.ldadd (the load is LDADD of 0),
      str.swp (the load is SWP of 0), swpmid (STR; SWP to a third location w; LDR)
Base mechanism: TSO: plain for WW, RR, RW; dmb for WR. Arm (gen_mixcov SUFF[0]): str.stlr, ldar.ldr, data, dmb.

Tests:
  base   every edge its base; lone-op threads (WRC/RWC/IRIW writers) in every mode (kind base; 'base-lw' if a lone
         thread is TSO). The base test with lone threads Arm is the pivot test of every base entry of its mask.
  pivot  one edge thread i at a time takes every mechanism of universe(mode_i, kind_i) except the base; lone threads Arm.
Masks: every assignment over the threads that carry a po-edge, all-Arm and all-TSO included (bit i set = Pi TSO).

Ordered / not ordered is decided by herd: arm.cat (Arm entries) or tso.cat (TSO entries) on the single-mode 2-thread
test that has the entry as pivot: WW -> MP P0, RR -> MP P1, RW -> LB P0, WR -> SB P0 (ppo_table.tsv).
Every generated test is then run through compound.cat, compound-apple.cat, arm.cat (all edge threads Arm),
tso.cat (all edge threads TSO), and herd's own aarch64.cat on the unmarked source.

Writes: src/ (AArch64, no mode marker), herd/ (leading ISB on each TSO thread), modes.tsv (name, mask),
list.tsv, ppo_table.tsv.  Usage: python3 gen.py [-j N] [--no-herd]
"""
import itertools, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
MODELS = os.path.normpath(os.path.join(HERE, '..', '..', 'compound-herd', 'models'))
HERD = os.environ.get('HERD7', 'herd7')

LOC = {'x': 'X10', 'y': 'X11', 'z': 'X14', 'w': 'X15'}
VAL = {1: 'X12', 2: 'X13'}
ZERO = 'X16'          # initialised to 0: the addend / swap value of an AMO that replaces a load
SWPOUT = 'X7'         # result register of a SWP that replaces a store (not in the condition)
MIDOUT = 'X8'         # result register of the SWP between (swpmid)

FAM = {
 'MP':   ([[('W','x',1),('W','y',1)], [('R','y'),('R','x')]],                 '1:X0=1 /\\ 1:X1=0'),
 'S':    ([[('W','x',2),('W','y',1)], [('R','y'),('W','x',1)]],               '1:X0=1 /\\ x=2'),
 'LB':   ([[('R','x'),('W','y',1)], [('R','y'),('W','x',1)]],                 '0:X0=1 /\\ 1:X0=1'),
 'R':    ([[('W','x',1),('W','y',1)], [('W','y',2),('R','x')]],               'y=2 /\\ 1:X0=0'),
 '2+2W': ([[('W','x',2),('W','y',1)], [('W','y',2),('W','x',1)]],             'x=2 /\\ y=2'),
 'SB':   ([[('W','x',1),('R','y')], [('W','y',1),('R','x')]],                 '0:X0=0 /\\ 1:X0=0'),
 'WRC':  ([[('W','x',1)], [('R','x'),('W','y',1)], [('R','y'),('R','x')]],    '1:X0=1 /\\ 2:X0=1 /\\ 2:X1=0'),
 'ISA2': ([[('W','x',1),('W','y',1)], [('R','y'),('W','z',1)], [('R','z'),('R','x')]], '1:X0=1 /\\ 2:X0=1 /\\ 2:X1=0'),
 'RWC':  ([[('W','x',1)], [('R','x'),('R','y')], [('W','y',1),('R','x')]],    '1:X0=1 /\\ 1:X1=0 /\\ 2:X0=0'),
 'IRIW': ([[('W','x',1)], [('W','y',1)], [('R','x'),('R','y')], [('R','y'),('R','x')]],
          '2:X0=1 /\\ 2:X1=0 /\\ 3:X0=1 /\\ 3:X1=0'),
}
LDF = ['ldr', 'ldapr', 'ldar']
STF = ['str', 'stlr']
INS = {'ldr': 'LDR', 'ldapr': 'LDAPR', 'ldar': 'LDAR', 'str': 'STR', 'stlr': 'STLR'}
BAR = {'dmb': 'DMB ISH', 'dmbld': 'DMB ISHLD', 'dmbst': 'DMB ISHST',
       'dsb': 'DSB ISH', 'dsbld': 'DSB ISHLD', 'dsbst': 'DSB ISHST'}
AMO = ['swp.ldr', 'str.ldadd', 'str.swp', 'swpmid']
BASE = {('A','WW'): 'str.stlr', ('A','RR'): 'ldar.ldr', ('A','RW'): 'data', ('A','WR'): 'dmb',
        ('T','WW'): 'plain',    ('T','RR'): 'plain',    ('T','RW'): 'plain', ('T','WR'): 'dmb'}
PIVOT2 = {'WW': ('MP', 0), 'RR': ('MP', 1), 'RW': ('LB', 0), 'WR': ('SB', 0)}   # where ppo_table is decided


def universe(mode, kind):
    U = []
    for f1 in (LDF if kind[0] == 'R' else STF):
        for f2 in (LDF if kind[1] == 'R' else STF):
            U.append('plain' if f1 in ('ldr', 'str') and f2 in ('ldr', 'str') else f1 + '.' + f2)
    U += list(BAR)
    if kind[0] == 'R':
        U += ['addr'] + (['data'] if kind == 'RW' else []) + ['ctrl', 'ctrlisb']
    if mode == 'T' and kind == 'WR':
        U += AMO
    return U


def kind(t):
    return t[0][0] + t[1][0] if len(t) == 2 else None


def code(tid, t, m):
    """Instructions of thread tid (ops t) with mechanism m on its po-edge (None for a lone op)."""
    out, nld, used0 = [], 0, False
    def ld(op, form='ldr', idx=False):
        nonlocal nld, used0
        r = 'X%d' % nld; nld += 1
        a = '[%s,X5]' % LOC[op[1]] if idx else '[%s]' % LOC[op[1]]
        if form == 'ldadd': used0 = True; return 'LDADD %s,%s,%s' % (ZERO, r, a)
        if form == 'swp':   used0 = True; return 'SWP %s,%s,%s' % (ZERO, r, a)
        return '%s %s,%s' % (INS[form], r, a)
    def st(op, form='str', reg=None, idx=False):
        a = '[%s,X5]' % LOC[op[1]] if idx else '[%s]' % LOC[op[1]]
        if form == 'swp': return 'SWP %s,%s,%s' % (VAL[op[2]], SWPOUT, a)
        return '%s %s,%s' % (INS[form], reg or VAL[op[2]], a)
    acc = lambda op, form, **k: ld(op, form, **k) if op[0] == 'R' else st(op, form, **k)
    a = t[0]
    if len(t) == 1:
        return [acc(a, 'ldr' if a[0] == 'R' else 'str')], False
    b = t[1]
    if '.' in m:
        f1, f2 = m.split('.')
    else:
        f1, f2 = ('ldr' if a[0] == 'R' else 'str'), ('ldr' if b[0] == 'R' else 'str')
    out.append(acc(a, f1))
    lab = 'LC%d0' % tid
    if m in BAR: out.append(BAR[m])
    elif m == 'addr': out.append('EOR X5,X0,X0')
    elif m == 'data': out += ['EOR X6,X0,X0', 'ADD X6,X6,#%d' % b[2]]
    elif m == 'ctrl': out += ['CBNZ X0,%s' % lab, '%s:' % lab]
    elif m == 'ctrlisb': out += ['CBNZ X0,%s' % lab, '%s:' % lab, 'ISB']
    elif m == 'swpmid': out.append('SWP X12,%s,[%s]' % (MIDOUT, LOC['w']))
    out.append(acc(b, f2, idx=(m == 'addr'), **({'reg': 'X6'} if m == 'data' else {})))
    return out, used0


def litmus(name, threads, mechs, cond, mask=0, marker=False):
    n = len(threads)
    cols, zero = [], []
    for i, (t, m) in enumerate(zip(threads, mechs)):
        c, z = code(i, t, m)
        if marker and mask >> i & 1:
            c = ['ISB'] + c
        cols.append(c); zero.append(z)
    init = ' '.join('%d:X10=x; %d:X11=y; %d:X12=1; %d:X13=2; %d:X14=z; %d:X15=w;' % ((i,) * 6)
                    + (' %d:%s=0;' % (i, ZERO) if zero[i] else '') for i in range(n))
    d = max(map(len, cols)); cols = [c + [''] * (d - len(c)) for c in cols]
    head = ['P%d' % i for i in range(n)]
    w = [max(len(x) for x in [head[j]] + cols[j]) + 2 for j in range(n)]
    fmt = lambda r: ' ' + '| '.join(x.ljust(w[j]) for j, x in enumerate(r)).rstrip() + ' ;'
    return '\n'.join(['AArch64 ' + name, '{ ' + init + ' }', fmt(head)] +
                     [fmt([cols[j][i] for j in range(n)]) for i in range(d)] + ['exists (%s)' % cond, ''])


def gen():
    tests = []
    for fam, (threads, cond) in FAM.items():
        n = len(threads)
        E = [i for i, t in enumerate(threads) if kind(t)]
        L = [i for i, t in enumerate(threads) if not kind(t)]
        def mk(mask, mechs, k, piv):
            modes = ['T' if mask >> i & 1 else 'A' for i in range(n)]
            name = '%s_%s_%s' % (fam, ''.join(modes), '-'.join(x or 'o' for x in mechs))
            ent = None if piv is None else (modes[piv], kind(threads[piv]), mechs[piv])
            return dict(name=name, fam=fam, mask=mask, n=n, modes=''.join(modes), mechs=mechs, kind=k,
                        pivot=piv, entry=ent, threads=threads, cond=cond,
                        emask=sum(1 << i for i in E if mask >> i & 1),
                        single=('A' if all(modes[i] == 'A' for i in E) else
                                'T' if all(modes[i] == 'T' for i in E) else ''))
        for ebits in itertools.product([0, 1], repeat=len(E)):
            emask = sum(1 << i for i, b in zip(E, ebits) if b)
            md = lambda i, m: 'T' if m >> i & 1 else 'A'
            base = [BASE[(md(i, emask), kind(t))] if kind(t) else None for i, t in enumerate(threads)]
            for lbits in itertools.product([0, 1], repeat=len(L)):
                mask = emask | sum(1 << i for i, b in zip(L, lbits) if b)
                tests.append(mk(mask, list(base), 'base' if mask == emask else 'base-lw', None))
            for i in E:
                for m in universe(md(i, emask), kind(threads[i])):
                    if m == base[i]: continue
                    o = list(base); o[i] = m
                    tests.append(mk(emask, o, 'pivot', i))
    names = [t['name'] for t in tests]
    assert len(names) == len(set(names)), 'duplicate names'
    return tests


def herd(model, path):
    args = [HERD] + (['-I', MODELS] if model != 'aarch64' else []) + ['-model', model + '.cat', path]
    o = subprocess.run(args, capture_output=True, text=True).stdout
    m = re.search(r'^Observation \S+ (\w+)', o, re.M)
    return m.group(1) if m else 'ERR'


def main():
    jobs = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else os.cpu_count()
    T = gen()
    for d in ('src', 'herd'):
        os.makedirs(os.path.join(HERE, d), exist_ok=True)
        for f in os.listdir(os.path.join(HERE, d)):
            if f.endswith('.litmus'): os.remove(os.path.join(HERE, d, f))
    for t in T:
        open(os.path.join(HERE, 'src', t['name'] + '.litmus'), 'w').write(
            litmus(t['name'], t['threads'], t['mechs'], t['cond']))
        open(os.path.join(HERE, 'herd', t['name'] + '.litmus'), 'w').write(
            litmus(t['name'], t['threads'], t['mechs'], t['cond'], t['mask'], marker=True))
    with open(os.path.join(HERE, 'modes.tsv'), 'w') as f:
        f.write('name\tmask\tmodes\texpected\n')
        for t in T: f.write('%s\t%d\t%s\t-\n' % (t['name'], t['mask'], t['modes']))
    if '--no-herd' in sys.argv:
        print(len(T), 'tests (no herd)'); return
    # herd: every test x the models that apply
    work = []
    for t in T:
        s, h = (os.path.join(HERE, d, t['name'] + '.litmus') for d in ('src', 'herd'))
        work += [(t['name'], 'compound', h), (t['name'], 'compound-apple', h), (t['name'], 'aarch64', s)]
        if t['single'] == 'A': work.append((t['name'], 'arm', s))
        if t['single'] == 'T': work.append((t['name'], 'tso', h))
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(lambda w: herd(w[1], w[2]), work))
    V = {}
    for (n, m, _), r in zip(work, res): V.setdefault(n, {})[m] = r
    # ppo table from the single-mode 2-thread tests
    table = []
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            fam, pos = PIVOT2[k]
            for m in universe(mode, k):
                hit = [t for t in T if t['fam'] == fam and t['mask'] == (0 if mode == 'A' else 3) and
                       ((t['kind'] == 'base' and m == BASE[(mode, k)]) or (t['kind'] == 'pivot' and t['pivot'] == pos and t['mechs'][pos] == m))]
                assert len(hit) == 1, (mode, k, m, len(hit))
                v = V[hit[0]['name']]['arm' if mode == 'A' else 'tso']
                table.append((mode, k, m, {'Never': 'ordered', 'Sometimes': 'not-ordered'}.get(v, 'ERR:' + v),
                              'base' if m == BASE[(mode, k)] else '-', hit[0]['name']))
    with open(os.path.join(HERE, 'ppo_table.tsv'), 'w') as f:
        f.write('# decided by herd7 (arm.cat for A, tso.cat for T) on the witness test\n')
        f.write('mode\tkind\tmechanism\tentry\tbase\twitness\n')
        for r in table: f.write('\t'.join(r) + '\n')
    tab = {(r[0], r[1], r[2]): r[3] for r in table}
    cols = ['compound', 'compound-apple', 'arm', 'tso', 'aarch64']
    with open(os.path.join(HERE, 'list.tsv'), 'w') as f:
        f.write('name\tfamily\tnthreads\tmask\tmodes\tmechanisms\tkind\tpivot_thread\tpivot_entry\tentry_table\texpected\t'
                + '\t'.join(cols) + '\n')
        for t in T:
            if t['pivot'] is None:
                ent, et, exp = '-', '-', 'Never'
            else:
                ent = '%s:%s:%s' % t['entry']; et = tab[t['entry']]
                exp = 'Never' if et == 'ordered' else 'Sometimes'
            f.write('\t'.join([t['name'], t['fam'], str(t['n']), str(t['mask']), t['modes'], '-'.join(x or 'o' for x in t['mechs']),
                               t['kind'], '-' if t['pivot'] is None else 'P%d' % t['pivot'], ent, et, exp] +
                              [V[t['name']].get(c, '-') for c in cols]) + '\n')
    bad = [t['name'] for t in T if any(v == 'ERR' for v in V[t['name']].values())]
    print(len(T), 'tests;', len(table), 'table entries;', 'herd errors:', len(bad), bad[:5])


if __name__ == '__main__':
    main()
