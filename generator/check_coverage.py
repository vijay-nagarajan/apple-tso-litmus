#!/usr/bin/env python3
"""Mechanically check the batch5 invariant. Independent of gen.py: it re-reads src/ and herd/, classifies every
thread's po-edge from its instructions, and does not import gen.py.

Invariant: for every ppo-table entry (mode, kind, mechanism), every position (shape, thread) whose edge has that
kind, and every mode assignment of the edge-carrying threads in which that thread has that mode, exactly one test
(lone-op threads Arm) has that entry as its pivot: the entry on that thread and the base of its mode on every other
edge. For a base entry, that test is the base test of the assignment. herd's compound.cat verdict on it must be
Never iff the entry is ordered (ppo_table.tsv). Also: every base test is forbidden; every lone-thread assignment
has its base test; herd/ = src/ + a leading ISB on exactly the TSO threads; on single-mode tests compound agrees
with arm.cat / tso.cat, and arm.cat with aarch64.cat. Exit 1 on any failure.
"""
import itertools, os, re, sys
from collections import defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
# shape: op kinds per thread (W/R), as in the litmus shapes of the report
SHAPE = {'MP': ['WW', 'RR'], 'S': ['WW', 'RW'], 'LB': ['RW', 'RW'], 'R': ['WW', 'WR'], '2+2W': ['WW', 'WW'],
         'SB': ['WR', 'WR'], 'WRC': ['W', 'RW', 'RR'], 'ISA2': ['WW', 'RW', 'RR'], 'RWC': ['W', 'RR', 'WR'],
         'IRIW': ['W', 'W', 'RR', 'RR']}
BASE = {('A','WW'): 'str.stlr', ('A','RR'): 'ldar.ldr', ('A','RW'): 'data', ('A','WR'): 'dmb',
        ('T','WW'): 'plain', ('T','RR'): 'plain', ('T','RW'): 'plain', ('T','WR'): 'dmb'}

def spec_universe(mode, k):
    """The mechanism universe as the task states it (independent restatement)."""
    L, S = ['ldr', 'ldapr', 'ldar'], ['str', 'stlr']
    forms = ['%s.%s' % (a, b) for a in (L if k[0] == 'R' else S) for b in (L if k[1] == 'R' else S)]
    forms = ['plain' if f in ('ldr.ldr', 'ldr.str', 'str.ldr', 'str.str') else f for f in forms]
    U = set(forms) | {'dmb', 'dmbld', 'dmbst', 'dsb', 'dsbld', 'dsbst'}
    if k in ('RR', 'RW'): U |= {'addr', 'ctrl', 'ctrlisb'}
    if k == 'RW': U |= {'data'}
    if mode == 'T' and k == 'WR': U |= {'swp.ldr', 'str.ldadd', 'str.swp', 'swpmid'}
    return U

def parse(path):
    S = open(path).read().split('\n')
    h = next(i for i, l in enumerate(S) if re.match(r'\s*P0\s*\|', l))
    e = next(i for i in range(h + 1, len(S)) if S[i].startswith('exists'))
    k = len(S[h].split('|'))
    cols = [[r.rstrip().rstrip(';').split('|')[j].strip() for r in S[h + 1:e]] for j in range(k)]
    init = dict(re.findall(r'(\d+:X\d+)=(\w+)', S[1]))
    return [[x for x in c if x] for c in cols], init, S[e]

BAR = {'DMB ISH': 'dmb', 'DMB ISHLD': 'dmbld', 'DMB ISHST': 'dmbst', 'DSB ISH': 'dsb', 'DSB ISHLD': 'dsbld', 'DSB ISHST': 'dsbst'}
FORM = {'LDR': 'ldr', 'LDAPR': 'ldapr', 'LDAR': 'ldar', 'STR': 'str', 'STLR': 'stlr'}

def classify(tid, ins, init, k):
    """(mechanism) of a thread's code for edge kind k; raises on anything unexpected."""
    mem = [i for i, x in enumerate(ins) if re.match(r'(LDR|LDAPR|LDAR|STR|STLR|SWP|LDADD)\b', x)]
    loc = lambda x: init.get('%d:%s' % (tid, re.search(r'\[(X\d+)', x).group(1)))
    if len(k) == 1:
        assert len(ins) == 1 and len(mem) == 1, ins
        return 'o'
    mid = [i for i in mem[1:-1]]
    acc = [mem[0], mem[-1]]
    between = ins[acc[0] + 1:acc[1]]
    def form(x, want):
        op = x.split()[0]
        if op in FORM:
            assert (op.startswith('LD')) == (want == 'R'), (x, want)
            return FORM[op]
        regs = re.findall(r'X\d+', x)
        val = init.get('%d:%s' % (tid, regs[0]))
        if op == 'SWP' and want == 'W': assert val in ('1', '2'), x; return 'swp'
        if op == 'SWP' and want == 'R': assert val == '0', x; return 'swp'
        if op == 'LDADD' and want == 'R': assert val == '0', x; return 'ldadd'
        raise AssertionError(x)
    f1, f2 = form(ins[acc[0]], k[0]), form(ins[acc[1]], k[1])
    assert loc(ins[acc[0]]) != loc(ins[acc[1]]), ins
    plain = f1 in ('ldr', 'str') and f2 in ('ldr', 'str')
    if not between:
        return 'plain' if plain else '%s.%s' % (f1, f2)
    assert plain, ins           # one thing between only with plain accesses
    if len(between) == 1 and between[0] in BAR: return BAR[between[0]]
    if len(between) == 1 and between[0].startswith('SWP'):
        assert loc(between[0]) not in (loc(ins[acc[0]]), loc(ins[acc[1]])), ins
        return 'swpmid'
    r0 = re.match(r'LD\w* (X\d+)', ins[acc[0]]).group(1)
    if between == ['EOR X5,%s,%s' % (r0, r0)] and ',X5]' in ins[acc[1]]: return 'addr'
    if (len(between) == 2 and between[0] == 'EOR X6,%s,%s' % (r0, r0) and between[1].startswith('ADD X6,X6,#')
            and ins[acc[1]].startswith('STR X6,')):
        return 'data'
    m = re.match(r'CBNZ %s,(\w+)$' % r0, between[0])
    if m and between[1:] == [m.group(1) + ':']: return 'ctrl'
    if m and between[1:] == [m.group(1) + ':', 'ISB']: return 'ctrlisb'
    raise AssertionError(('unclassified', ins))

def main():
    fail = []
    def bad(*a): fail.append(' '.join(map(str, a)))
    tab = {}
    for l in open(os.path.join(HERE, 'ppo_table.tsv')):
        if l.startswith(('#', 'mode\t')): continue
        f = l.rstrip('\n').split('\t'); tab[(f[0], f[1], f[2])] = f[3]
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            got = {m for (a, b, m) in tab if (a, b) == (mode, k)}
            if got != spec_universe(mode, k):
                bad('UNIVERSE', mode, k, 'table-only', sorted(got - spec_universe(mode, k)),
                    'spec-only', sorted(spec_universe(mode, k) - got))
            if tab.get((mode, k, BASE[(mode, k)])) != 'ordered': bad('BASE-NOT-ORDERED', mode, k)
    rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(HERE, 'list.tsv'))]
    H = rows[0]; rows = [dict(zip(H, r)) for r in rows[1:]]
    names = {r['name'] for r in rows}
    if names != {f[:-7] for f in os.listdir(os.path.join(HERE, 'src')) if f.endswith('.litmus')}:
        bad('LIST != src/')
    pivots = defaultdict(list)     # (fam, pos, emask, mode, kind, mech) -> tests
    lw = defaultdict(list)         # (fam, mask) -> base tests
    single = defaultdict(int)
    for r in rows:
        fam, n, mask = r['family'], int(r['nthreads']), int(r['mask'])
        kinds = SHAPE[fam]
        cols, init, cond = parse(os.path.join(HERE, 'src', r['name'] + '.litmus'))
        hcols, hinit, hcond = parse(os.path.join(HERE, 'herd', r['name'] + '.litmus'))
        if len(cols) != n or len(kinds) != n: bad('NTHREADS', r['name']); continue
        for i in range(n):
            exp = (['ISB'] if mask >> i & 1 else []) + cols[i]
            if hcols[i] != exp: bad('HERD-MARKER', r['name'], 'P%d' % i)
            if any(x == 'ISB' for x in cols[i][:1]): bad('SRC-STARTS-WITH-ISB', r['name'], 'P%d' % i)
        if (hinit, hcond) != (init, cond): bad('HERD-INIT/COND', r['name'])
        modes = ['T' if mask >> i & 1 else 'A' for i in range(n)]
        if ''.join(modes) != r['modes']: bad('MODES', r['name'])
        try:
            mech = [classify(i, cols[i], init, kinds[i]) for i in range(n)]
        except AssertionError as e:
            bad('CLASSIFY', r['name'], e); continue
        if '-'.join(mech) != r['mechanisms']: bad('MECH-NAME', r['name'], mech)
        E = [i for i in range(n) if len(kinds[i]) == 2]
        L = [i for i in range(n) if len(kinds[i]) == 1]
        emask = sum(1 << i for i in E if mask >> i & 1)
        nonbase = [i for i in E if mech[i] != BASE[(modes[i], kinds[i])]]
        for i in E:
            if (modes[i], kinds[i], mech[i]) not in tab: bad('NOT-IN-TABLE', r['name'], 'P%d' % i, mech[i])
        cv = r['compound']
        if not nonbase:
            if r['kind'] not in ('base', 'base-lw'): bad('KIND', r['name'])
            if cv != 'Never': bad('BASE-ALLOWED', r['name'], cv)
            lw[(fam, emask, mask)].append(r['name'])
            if mask == emask:
                for i in E: pivots[(fam, i, emask, modes[i], kinds[i], mech[i])].append(r['name'])
        elif len(nonbase) == 1:
            i = nonbase[0]
            if r['kind'] != 'pivot' or r['pivot_thread'] != 'P%d' % i: bad('PIVOT-META', r['name'])
            if mask != emask: bad('PIVOT-LONE-TSO', r['name'])
            ent = (modes[i], kinds[i], mech[i])
            pivots[(fam, i, emask) + ent].append(r['name'])
            want = 'Never' if tab.get(ent) == 'ordered' else 'Sometimes'
            if cv != want: bad('VERDICT', r['name'], 'entry', ent, tab.get(ent), 'compound', cv)
        else:
            bad('MULTI-PIVOT', r['name'], nonbase)
        sm = ('A' if all(modes[i] == 'A' for i in E) else 'T' if all(modes[i] == 'T' for i in E) else '')
        if sm:
            single[sm] += 1
            other = r['arm' if sm == 'A' else 'tso']
            if other != cv: bad('SANITY', r['name'], 'compound', cv, 'arm' if sm == 'A' else 'tso', other)
            if sm == 'A' and r['aarch64'] != r['arm']: bad('SANITY-aarch64', r['name'], r['arm'], r['aarch64'])
    # coverage: every entry x position x assignment exactly once
    matrix = defaultdict(lambda: [0, 0])     # (mode, kind, mech, fam) -> [covered, required]
    for fam, kinds in SHAPE.items():
        n = len(kinds); E = [i for i in range(n) if len(kinds[i]) == 2]; L = [i for i in range(n) if len(kinds[i]) == 1]
        for bits in itertools.product([0, 1], repeat=len(E)):
            emask = sum(1 << i for i, b in zip(E, bits) if b)
            for lb in itertools.product([0, 1], repeat=len(L)):
                mask = emask | sum(1 << i for i, b in zip(L, lb) if b)
                if len(lw[(fam, emask, mask)]) != 1: bad('BASE-LW', fam, emask, mask, lw[(fam, emask, mask)])
            for i in E:
                md = 'T' if emask >> i & 1 else 'A'
                for (mo, k, m) in tab:
                    if (mo, k) != (md, kinds[i]): continue
                    got = pivots.get((fam, i, emask, mo, k, m), [])
                    c = matrix[(mo, k, m, fam)]; c[1] += 1
                    if len(got) == 1: c[0] += 1
                    else: bad('COVERAGE', fam, 'P%d' % i, 'mask', emask, (mo, k, m), got)
    fams = list(SHAPE)
    print('coverage matrix: covered/required (position x mode-assignment) per entry and shape; o = ordered, - = not')
    print('%-4s %-4s %-11s %s' % ('mode', 'kind', 'mechanism', ' '.join('%7s' % f for f in fams)))
    for (mo, k, m) in sorted(tab, key=lambda e: ('AT'.index(e[0]), ['WW','RR','RW','WR'].index(e[1]))):
        cells = []
        for f in fams:
            c = matrix.get((mo, k, m, f))
            cells.append('%7s' % ('.' if not c else '%d/%d' % tuple(c)))
        print('%-4s %-4s %-11s %s  %s' % (mo, k, m, ' '.join(cells), 'o' if tab[(mo, k, m)] == 'ordered' else '-'))
    tot = [sum(c[0] for c in matrix.values()), sum(c[1] for c in matrix.values())]
    print('total (entry, position, assignment) cells: %d/%d covered; tests %d; single-mode tests A %d, T %d'
          % (tot[0], tot[1], len(rows), single['A'], single['T']))
    if fail:
        print('FAIL: %d problems' % len(fail)); [print('  ' + x) for x in fail[:200]]; sys.exit(1)
    print('PASS: invariant holds; herd verdicts match the table; single-mode sanity holds')

# ---------------------------------------------------------------- Design v2 (--v2)
BASE2 = {('A','WW'): 'dmb', ('A','RR'): 'dmb', ('A','RW'): 'dmb', ('A','WR'): 'dmb',
         ('T','WW'): 'plain', ('T','RR'): 'plain', ('T','RW'): 'plain', ('T','WR'): 'dmb'}
CANON2 = {'WW': ('MP', 0), 'RR': ('MP', 1), 'RW': ('LB', 0), 'WR': ('SB', 0)}
PROP2 = {'RW': ('WRC', 1), 'RR': ('WRC', 2), 'WW': ('ISA2', 0), 'WR': ('RWC', 2)}
ST_EXT = ['str', 'stlr', 'llsc', 'llscl', 'swp', 'swpa', 'swpl', 'swpal']
LD_EXT = ['ldr', 'ldapr', 'ldar', 'ldxr', 'ldaxr', 'swp', 'swpa', 'swpl', 'swpal', 'cas', 'casa', 'casl', 'casal']

def spec_universe2(mode, k):
    U = spec_universe(mode, k)
    if mode == 'T' and k == 'WR':
        U |= {'plain' if (a, b) == ('str', 'ldr') else a + '.' + b for a in ST_EXT for b in LD_EXT}
    return U

def classify2(tid, ins, init, k):
    """Mechanism of a thread, from its instructions; accesses grouped into units (an LL/SC pair is one unit)."""
    if len(k) == 1:
        assert len(ins) == 1 and re.match(r'(LDR|STR) ', ins[0]), ins
        return 'o'
    reg = lambda r: init.get('%d:%s' % (tid, r))
    loc = lambda x: reg(re.search(r'\[(X\d+)', x).group(1))
    units, between, i = [], [], 0
    while i < len(ins):
        x = ins[i]; op = x.split()[0]
        if op in ('LDXR', 'LDAXR') and i + 1 < len(ins) and re.match(r'STL?XR ', ins[i + 1]) and loc(ins[i + 1]) == loc(x):
            units.append((len(between), [x, ins[i + 1]])); i += 2; continue
        if re.match(r'(LDR|LDAPR|LDAR|STR|STLR|SWP\w*|LDADD\w*|CAS\w*)$', op) and not (len(units) == 1 and op == 'SWP' and loc(x) not in ('x', 'y', 'z') and i + 1 < len(ins)):
            units.append((len(between), [x])); i += 1; continue
        between.append(x); i += 1
    assert len(units) == 2, (ins, units)
    (p0, u0), (p1, u1) = units
    btw = between[p0:p1] if p1 > p0 else []
    assert loc(u0[0]) != loc(u1[0]), ins
    def form(u, want):
        ops = [y.split()[0] for y in u]
        regs = re.findall(r'X\d+', u[0])
        if len(u) == 2:   # LL/SC pair
            if want == 'W': assert ops[0] == 'LDXR'; return {'STXR': 'llsc', 'STLXR': 'llscl'}[ops[1]]
            assert reg(re.findall(r'X\d+', u[1])[0]) == '0', u
            return {'LDXR': 'ldxr', 'LDAXR': 'ldaxr'}[ops[0]]
        op = ops[0]
        if op in FORM: assert op.startswith('LD') == (want == 'R'), (u, want); return FORM[op]
        if op.startswith('SWP'):
            assert reg(regs[0]) == ('0' if want == 'R' else reg(regs[0])) and (want == 'R' or reg(regs[0]) in ('1', '2')), u
            return op.lower()
        if op.startswith('LDADD'): assert want == 'R' and reg(regs[0]) == '0'; return op.lower()
        if op.startswith('CAS'): assert want == 'R' and reg(regs[0]) == '5', u; return op.lower()
        raise AssertionError(u)
    f1, f2 = form(u0, k[0]), form(u1, k[1])
    plain = f1 in ('ldr', 'str') and f2 in ('ldr', 'str')
    if not btw: return 'plain' if plain else '%s.%s' % (f1, f2)
    assert plain, ins
    m = classify(tid, [u0[0]] + btw + [u1[0]], init, k)
    return m

def main2():
    sys.path.insert(0, HERE); import norm
    V = os.path.join(HERE, 'v2'); fail, warn = [], []
    bad = lambda *a: fail.append(' '.join(map(str, a)))
    tab = {}
    for l in open(os.path.join(V, 'ppo_table.tsv')):
        if l.startswith(('#', 'mode\t')): continue
        f = l.rstrip('\n').split('\t'); tab[(f[0], f[1], f[2])] = f[3]
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            got = {m for (a, b, m) in tab if (a, b) == (mode, k)}
            if got != spec_universe2(mode, k): bad('UNIVERSE', mode, k, sorted(got ^ spec_universe2(mode, k)))
    L = [l.rstrip('\n').split('\t') for l in open(os.path.join(V, 'list.tsv'))]
    rows = {r[0]: dict(zip(L[0], r)) for r in L[1:]}
    roles = [dict(zip(['name', 'group', 'role', 'entry', 'pivot', 'context', 'control', 'of'], l.rstrip('\n').split('\t')))
             for l in list(open(os.path.join(V, 'roles.tsv')))[1:]]
    if {f[:-7] for f in os.listdir(os.path.join(V, 'src'))} != set(rows): bad('LIST != v2/src')
    idx, mech_of = {}, {}
    for n, r in rows.items():
        cols, init, cond = norm.parse(os.path.join(V, 'src', n + '.litmus'))
        hcols, hinit, hcond = norm.parse(os.path.join(V, 'herd', n + '.litmus'))
        if (hinit, hcond) != (init, cond): bad('HERD-INIT/COND', n)
        mask = int(r['mask'])
        for i in range(len(cols)):
            if hcols[i] != (['ISB'] if mask >> i & 1 else []) + cols[i]: bad('HERD-MARKER', n, 'P%d' % i)
            if cols[i][:1] == ['ISB']: bad('SRC-STARTS-WITH-ISB', n)
        modes = ''.join('T' if mask >> i & 1 else 'A' for i in range(len(cols)))
        if modes != r['modes']: bad('MODES', n)
        sm = set(modes)
        if sm == {'A'} and not (r['compound'] == r['arm'] == r['aarch64']): bad('SANITY-A', n, r['compound'], r['arm'], r['aarch64'])
        if sm == {'T'} and r['compound'] != r['tso']: bad('SANITY-T', n, r['compound'], r['tso'])
        if r['origin'] != 'generated': continue
        fam = r['family']
        try: mech = tuple(classify2(i, cols[i], init, SHAPE[fam][i]) for i in range(len(cols)))
        except AssertionError as e: bad('CLASSIFY', n, e); continue
        if '-'.join(mech) != n.split('_', 2)[2]: bad('NAME', n, mech)
        idx[(fam, modes, mech)] = n; mech_of[n] = (fam, modes, mech)
    def find(fam, modes, mech):
        return idx.get((fam, ''.join(modes), tuple(m or 'o' for m in mech)))
    def base(fam, modes):
        return [BASE2[(modes[i], k)] if len(k) == 2 else 'o' for i, k in enumerate(SHAPE[fam])]
    piv = defaultdict(set)
    for r in roles:
        if r['role'] == 'pivot': piv[(r['name'], r['group'])].add(r['entry'])
    # (i), (ii)
    for (mo, k, m), o in tab.items():
        for grp, P in (('1', CANON2), ('2-job2', PROP2)):
            fam, pos = P[k]
            for ctx in ('AT' if grp == '1' else (mo, 'A' if mo == 'T' else 'T')):
                modes = [ctx] * len(SHAPE[fam]); modes[pos] = mo
                mech = base(fam, modes); mech[pos] = m
                n = find(fam, modes, mech)
                if not n: bad('MISSING-PIVOT', grp, (mo, k, m), ''.join(modes)); continue
                if '%s:%s:%s' % (mo, k, m) not in piv[(n, grp)]: bad('PIVOT-ROLE', grp, n, (mo, k, m))
                want = 'Never' if o == 'ordered' else 'Sometimes'
                if rows[n]['compound'] != want: bad('VERDICT', grp, n, (mo, k, m), o, rows[n]['compound'])   # (v)
    # (iii)
    nbase = 0
    for fam in ('MP', 'LB', 'SB', 'WRC', 'ISA2', 'RWC', 'IRIW'):
        for modes in itertools.product('AT', repeat=len(SHAPE[fam])):
            vs = [base(fam, modes)] + ([['o', 'o', 'ldar.ldar', 'ldar.ldar']] if fam == 'IRIW' else [])
            for mech in vs:
                n = find(fam, modes, mech); nbase += 1
                if not n: bad('MISSING-BASE', fam, ''.join(modes), mech)
                elif rows[n]['compound'] != 'Never': bad('BASE-ALLOWED', n)
    # (iv) controls of every forbidden generated test
    noctl, nctl = [], 0
    byname = defaultdict(list)
    for r in roles: byname[r['name']].append(r)
    for n, r in rows.items():
        if r['compound'] != 'Never': continue
        if r['origin'] != 'generated':
            continue
        rs = [x for x in byname[n] if x['role'] in ('pivot', 'base', 'base-acq')]
        if not rs: bad('FORBIDDEN-WITHOUT-ROLE', n); continue
        if n not in mech_of: continue
        fam, modes, mech = mech_of[n]
        any_ctl = False
        for x in rs:
            ctls = [c for c in x['control'].split(';') if c and c != '-']
            if x['role'] == 'pivot' and not ctls: bad('NO-CONTROL', n, x['entry']); continue
            for c in ctls:
                if c.startswith('none('):
                    j = int(re.search(r'P(\d)', c).group(1))
                    if not (modes[j] == 'T' and SHAPE[fam][j] != 'WR'): bad('BAD-NONE', n, c)
                    continue
                if c not in mech_of: bad('CONTROL-MISSING', n, c); continue
                cf, cm, cmech = mech_of[c]
                dm = [i for i in range(len(modes)) if cm[i] != modes[i]]
                dk = [i for i in range(len(modes)) if cmech[i] != mech[i]]
                ok = cf == fam and ((not dm and len(dk) == 1 and cmech[dk[0]] == 'plain') or
                                    (len(dm) == 1 and modes[dm[0]] == 'T' and cm[dm[0]] == 'A' and SHAPE[fam][dm[0]] != 'WR'
                                     and set(dk) <= set(dm) and (not dk or cmech[dm[0]] == 'plain')))
                if not ok: bad('CONTROL-NOT-ONE-EDGE', n, c, dm, dk)
                if rows[c]['compound'] != 'Sometimes': bad('CONTROL-NOT-ALLOWED', n, c, rows[c]['compound'])
                any_ctl = True; nctl += 1
        if not any_ctl: noctl.append(n)
    # group 3: look for a one-thread-different allowed test in the universe (reported, not required)
    keys = {n: norm.key(os.path.join(V, 'src', n + '.litmus'), int(r['mask'])).split(' || ') for n, r in rows.items()}
    g3f, g3c = [], {}
    for n, r in rows.items():
        if r['origin'] == 'generated' or r['compound'] != 'Never': continue
        g3f.append(n); kn = keys[n]
        for m, km in keys.items():
            if m == n or rows[m]['compound'] != 'Sometimes' or len(km) != len(kn) or km[-1] != kn[-1]: continue
            if km[0] == kn[0] and sum(a != b for a, b in zip(km[1:-1], kn[1:-1])) == 1: g3c[n] = m; break
    print('v2 table rows %d; group-1 and job-2 pivots checked in both contexts; base tests %d; controls checked %d'
          % (len(tab), nbase, nctl))
    print('forbidden generated tests with no control at all (every edge TSO non-WR): %d %s' % (len(noctl), noctl))
    print('group-3 forbidden tests: %d; with a one-thread-different allowed test in the universe: %d; without: %s'
          % (len(g3f), len(g3c), sorted(set(g3f) - set(g3c))))
    if fail:
        print('FAIL: %d problems' % len(fail)); [print('  ' + x) for x in fail[:200]]; sys.exit(1)
    print('PASS (v2): (i)-(vi) hold')

# ---------------------------------------------------------------- Design v3 (--v3)
MENU3 = {('A','RW'): ['addr', 'data'], ('A','RR'): ['addr', 'ldapr.ldr'], ('A','WW'): ['str.stlr', 'dmbst'], ('A','WR'): ['stlr.ldar'],
         ('T','RW'): ['plain', 'ldapr.str'], ('T','RR'): ['plain', 'ldr.ldapr'], ('T','WW'): ['plain', 'stlr.str'], ('T','WR'): ['dmb', 'stlr.ldar']}

def main3():
    sys.path.insert(0, HERE); import norm
    V = os.path.join(HERE, 'v3'); fail = []
    bad = lambda *a: fail.append(' '.join(map(str, a)))
    tab = {}
    for l in open(os.path.join(V, 'ppo_table.tsv')):
        if l.startswith(('#', 'mode\t')): continue
        f = l.rstrip('\n').split('\t'); tab[(f[0], f[1], f[2])] = f[3]
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            got = {m for (a, b, m) in tab if (a, b) == (mode, k)}
            if got != spec_universe2(mode, k): bad('UNIVERSE', mode, k, sorted(got ^ spec_universe2(mode, k)))
    L = [l.rstrip('\n').split('\t') for l in open(os.path.join(V, 'list.tsv'))]
    rows = {r[0]: dict(zip(L[0], r)) for r in L[1:]}
    roles = [dict(zip(['name', 'group', 'role', 'entry', 'pivot', 'context', 'control', 'of'], l.rstrip('\n').split('\t')))
             for l in list(open(os.path.join(V, 'roles.tsv')))[1:]]
    if {f[:-7] for f in os.listdir(os.path.join(V, 'src'))} != set(rows): bad('LIST != v3/src')
    idx, mech_of = {}, {}
    for n, r in rows.items():
        cols, init, cond = norm.parse(os.path.join(V, 'src', n + '.litmus'))
        hcols, hinit, hcond = norm.parse(os.path.join(V, 'herd', n + '.litmus'))
        if (hinit, hcond) != (init, cond): bad('HERD-INIT/COND', n)
        mask = int(r['mask'])
        for i in range(len(cols)):
            if hcols[i] != (['ISB'] if mask >> i & 1 else []) + cols[i]: bad('HERD-MARKER', n, 'P%d' % i)
            if cols[i][:1] == ['ISB']: bad('SRC-STARTS-WITH-ISB', n)
        modes = ''.join('T' if mask >> i & 1 else 'A' for i in range(len(cols)))
        if modes != r['modes']: bad('MODES', n)
        want_sec = '5' if set(modes) == {'A'} else '6' if set(modes) == {'T'} else '7'
        if r['section'] != want_sec: bad('SECTION', n, r['section'])
        # (iv) verdicts present and single-mode sanity
        for c in ('compound', 'compound-apple', 'aarch64') + (('arm',) if set(modes) == {'A'} else ()) + (('tso',) if set(modes) == {'T'} else ()):
            if r[c] not in ('Never', 'Sometimes', 'Always'): bad('NO-VERDICT', n, c, r[c])
        if set(modes) == {'A'} and not (r['compound'] == r['arm'] == r['aarch64']): bad('SANITY-A', n, r['compound'], r['arm'], r['aarch64'])
        if set(modes) == {'T'} and r['compound'] != r['tso']: bad('SANITY-T', n, r['compound'], r['tso'])
        if r['origin'] != 'generated': continue
        fam = r['family']
        try: mech = tuple(classify2(i, cols[i], init, SHAPE[fam][i]) for i in range(len(cols)))
        except AssertionError as e: bad('CLASSIFY', n, e); continue
        if '-'.join(mech) != n.split('_', 2)[2]: bad('NAME', n, mech)
        idx[(fam, modes, mech)] = n; mech_of[n] = (fam, modes, mech)
    find = lambda fam, modes, mech: idx.get((fam, ''.join(modes), tuple(m or 'o' for m in mech)))
    base = lambda fam, modes: [BASE2[(modes[i], k)] if len(k) == 2 else 'o' for i, k in enumerate(SHAPE[fam])]
    piv = defaultdict(set)
    for r in roles:
        if r['role'] == 'pivot': piv[r['name']].add(r['entry'])
    # (i) group 1
    for (mo, k, m), o in tab.items():
        fam, pos = CANON2[k]
        for ctx in 'AT':
            modes = [ctx, ctx]; modes[pos] = mo
            mech = base(fam, modes); mech[pos] = m
            n = find(fam, modes, mech)
            if not n: bad('MISSING-PIVOT', (mo, k, m), ''.join(modes)); continue
            if '%s:%s:%s' % (mo, k, m) not in piv[n]: bad('PIVOT-ROLE', n, (mo, k, m))
            if rows[n]['compound'] != ('Never' if o == 'ordered' else 'Sometimes'): bad('VERDICT', n, (mo, k, m), o, rows[n]['compound'])
    for fam in ('MP', 'LB', 'SB'):
        for modes in itertools.product('AT', repeat=2):
            n = find(fam, modes, base(fam, modes))
            if not n or rows[n]['compound'] != 'Never': bad('BASE', fam, modes, n)
    # (ii) group 2 cross product
    ncomb = 0; first = {}
    for fam in ('WRC', 'ISA2', 'RWC', 'IRIW'):
        for modes in itertools.product('AT', repeat=len(SHAPE[fam])):
            menus = [MENU3[(modes[i], k)] if len(k) == 2 else ['o'] for i, k in enumerate(SHAPE[fam])]
            first[(fam, ''.join(modes))] = [m[0] for m in menus]
            for combo in itertools.product(*menus):
                n = find(fam, modes, combo); ncomb += 1
                if not n: bad('MISSING-COMBINATION', fam, ''.join(modes), combo)
                elif not any(r['group'] == '2' for r in roles if r['name'] == n): bad('COMBINATION-ROLE', n)
    # (iii) controls of every forbidden generated test
    byname = defaultdict(list)
    for r in roles: byname[r['name']].append(r)
    nctl, noctl = 0, []
    def one_edge(fam, modes, mech, c, j=None):
        """c differs from (modes, mech) in one edge j: that edge plain, or (TSO WW/RR/RW) that thread Arm with the edge plain
        or with the same mechanism if Arm does not order it."""
        cf, cm, cmech = mech_of[c]
        if cf != fam: return False
        dm = [i for i in range(len(modes)) if cm[i] != modes[i]]
        dk = [i for i in range(len(modes)) if cmech[i] != mech[i]]
        if not dm and len(dk) == 1 and cmech[dk[0]] == 'plain': return j is None or dk == [j]
        if len(dm) == 1 and modes[dm[0]] == 'T' and cm[dm[0]] == 'A' and SHAPE[fam][dm[0]] != 'WR' and set(dk) <= set(dm) \
                and (not dk or cmech[dm[0]] == 'plain'): return j is None or dm == [j]
        return False
    for n, r in rows.items():
        if r['origin'] != 'generated' or r['compound'] != 'Never' or n not in mech_of: continue
        fam, modes, mech = mech_of[n]
        rs = [x for x in byname[n] if x['role'] in ('pivot', 'base', 'combination')]
        if not rs: bad('FORBIDDEN-WITHOUT-ROLE', n); continue
        ok_any = False
        for x in rs:
            ctls = [c for c in x['control'].split(';') if c and c != '-']
            if x['role'] in ('pivot', 'combination') and not ctls: bad('NO-CONTROL', n, x['role']); continue
            if x['role'] == 'combination':
                ref = first[(fam, modes)]; E = [i for i, k in enumerate(SHAPE[fam]) if len(k) == 2]
                if len(ctls) != len(E): bad('G2-CONTROLS-PER-EDGE', n, len(ctls), len(E))
                for j, c in zip(E, ctls):
                    if c not in mech_of: bad('CONTROL-MISSING', n, c); continue
                    if not one_edge(fam, modes, tuple(ref), c, j): bad('G2-CONTROL-NOT-ONE-EDGE-OF-FIRST', n, c, 'P%d' % j)
                    if rows[c]['compound'] != 'Sometimes': bad('CONTROL-NOT-ALLOWED', n, c)
                    nctl += 1; ok_any = True
                continue
            for c in ctls:
                if c.startswith('none('):
                    jj = int(re.search(r'P(\d)', c).group(1))
                    if not (modes[jj] == 'T' and SHAPE[fam][jj] != 'WR'): bad('BAD-NONE', n, c)
                    continue
                if c not in mech_of: bad('CONTROL-MISSING', n, c); continue
                if not one_edge(fam, modes, mech, c): bad('CONTROL-NOT-ONE-EDGE', n, c)
                if rows[c]['compound'] != 'Sometimes': bad('CONTROL-NOT-ALLOWED', n, c)
                nctl += 1; ok_any = True
        if not ok_any: noctl.append(n)
    if noctl: bad('FORBIDDEN-WITH-NO-VALID-CONTROL', noctl)
    # group 2: how many combinations differ from their control in more than one pair (by design: controls are of the first combination)
    multi = sum(1 for n in rows if n in mech_of and any(x['role'] == 'combination' for x in byname[n])
                and list(mech_of[n][2]) != first[(mech_of[n][0], mech_of[n][1])])
    # group 3 forbidden: one-thread-different allowed test in the universe (reported)
    keys = {n: norm.key(os.path.join(V, 'src', n + '.litmus'), int(r['mask'])).split(' || ') for n, r in rows.items()}
    g3f, g3c = [], {}
    for n, r in rows.items():
        if r['origin'] == 'generated' or r['compound'] != 'Never': continue
        g3f.append(n); kn = keys[n]
        for m, km in keys.items():
            if m != n and rows[m]['compound'] == 'Sometimes' and len(km) == len(kn) and km[-1] == kn[-1] and km[0] == kn[0] \
                    and sum(a != b for a, b in zip(km[1:-1], kn[1:-1])) == 1: g3c[n] = m; break
    print('v3: %d table rows (group 1, both contexts); %d group-2 combinations; %d named controls checked' % (len(tab), ncomb, nctl))
    print('group-2 combinations that are not the first combination of their assignment (their controls differ from them in the '
          'controlled pair and in the other pairs\' menu choices): %d of %d' % (multi, ncomb))
    print('group-3 forbidden tests: %d; with a one-thread-different allowed test in the universe: %d; without: %s'
          % (len(g3f), len(g3c), sorted(set(g3f) - set(g3c))))
    if fail:
        print('FAIL: %d problems' % len(fail)); [print('  ' + x) for x in fail[:200]]; sys.exit(1)
    print('PASS (v3): (i)-(iv) hold for groups 1 and 2; single-mode sanity holds for all %d tests' % len(rows))

if __name__ == '__main__':
    main3() if '--v3' in sys.argv else main2() if '--v2' in sys.argv else main()
