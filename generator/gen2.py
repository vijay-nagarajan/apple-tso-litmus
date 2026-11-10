#!/usr/bin/env python3
"""batch5 Design v2, groups 1 and 2 (generated). Writes under v2/.

Table rows: every (mode, kind, mechanism) of gen.py's universe, plus, on TSO WR only, the extension:
  store side {str, stlr, llsc (LDXR;STXR), llscl (LDXR;STLXR), swp, swpa, swpl, swpal}
  x load side {ldr, ldapr, ldar, ldxr (LDXR;STXR of 0), ldaxr (LDAXR;STXR of 0), swp, swpa, swpl, swpal (swap in 0),
               cas, casa, casl, casal (a CAS whose comparison always fails: expected 5, memory only 0 or 1)}
  every combination ('str.ldr' is 'plain'); store-exclusive success is required by a filter on the status registers.
Base (non-pivot edges): Arm DMB ISH on every edge kind; TSO plain (WW, RR, RW), DMB ISH (WR).

Group 1: every row is the pivot of one test in its canonical 2-thread shape (WW: MP P0, RR: MP P1, RW: LB P0,
  WR: SB P0), the other thread in both modes; plus the all-base test of MP, LB, SB under every mode assignment.
Group 2 job 1: WRC, ISA2, RWC, IRIW under every mode assignment of all threads (lone writers included), all edges at
  base; IRIW also with LDAR;LDAR readers. Controls: one edge at a time plain (Arm edges and TSO WR edges only).
Group 2 job 2: every row as the pivot in its propagation position (RW: WRC P1, RR: WRC P2, WW: ISA2 P0, WR: RWC P2),
  all other threads in the pivot's mode, or all in the other mode.
Controls of a forbidden pivot: the pivot edge plain, same shape and context; for a TSO row on WW/RR/RW: the same
  mechanism on an Arm thread (same shape, same other threads), or the plain Arm edge if Arm orders that mechanism.
herd decides: the table = arm.cat (Arm rows) / tso.cat (TSO rows) on the group-1 test whose other thread has the
  pivot's mode. Forbidden tests are probed with compound minus the atomicity axiom and compound minus the order axiom.
Outputs: v2/gsrc/, v2/gherd/, v2/gen_tests.tsv, v2/roles.tsv, v2/ppo_table.tsv.   Usage: python3 gen2.py [-j N]
"""
import itertools, os, re, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gen

HERE = os.path.dirname(os.path.abspath(__file__))
V2 = os.path.join(HERE, 'v2')
MODELS = gen.MODELS
FAM = gen.FAM
BASE = {('A','WW'): 'dmb', ('A','RR'): 'dmb', ('A','RW'): 'dmb', ('A','WR'): 'dmb',
        ('T','WW'): 'plain', ('T','RR'): 'plain', ('T','RW'): 'plain', ('T','WR'): 'dmb'}
ST_EXT = ['str', 'stlr', 'llsc', 'llscl', 'swp', 'swpa', 'swpl', 'swpal']
LD_EXT = ['ldr', 'ldapr', 'ldar', 'ldxr', 'ldaxr', 'swp', 'swpa', 'swpl', 'swpal', 'cas', 'casa', 'casl', 'casal']
CANON = {'WW': ('MP', 0), 'RR': ('MP', 1), 'RW': ('LB', 0), 'WR': ('SB', 0)}
PROP = {'RW': ('WRC', 1), 'RR': ('WRC', 2), 'WW': ('ISA2', 0), 'WR': ('RWC', 2)}
KIND = lambda t: gen.kind(t)


def rows(mode, k):
    U = list(gen.universe(mode, k))
    if mode == 'T' and k == 'WR':
        for s in ST_EXT:
            for l in LD_EXT:
                m = 'plain' if (s, l) == ('str', 'ldr') else s + '.' + l
                if m not in U: U.append(m)
    return U


def is_ext(m):
    if '.' not in m: return False
    s, l = m.split('.')
    return s in ST_EXT and l in LD_EXT and not (s in ('str', 'stlr') and l in ('ldr', 'ldapr', 'ldar')) \
        and m not in ('swp.ldr', 'str.swp')


def code(tid, t, m):
    """-> (instructions, extra init {reg: val}, filter clauses)"""
    if len(t) == 2 and KIND(t) == 'WR' and is_ext(m):
        s, l = m.split('.')
        a, b = t
        X, Y = gen.LOC[a[1]], gen.LOC[b[1]]
        v = gen.VAL[a[2]]
        out, init, flt = [], {}, []
        if s in ('str', 'stlr'): out.append('%s %s,[%s]' % (s.upper(), v, X))
        elif s in ('llsc', 'llscl'):
            out += ['LDXR X7,[%s]' % X, '%s W8,%s,[%s]' % ('STXR' if s == 'llsc' else 'STLXR', v, X)]; flt.append('%d:X8=0' % tid)
        else: out.append('%s %s,X7,[%s]' % (s.upper(), v, X))
        if l in ('ldr', 'ldapr', 'ldar'): out.append('%s X0,[%s]' % (l.upper(), Y))
        elif l in ('ldxr', 'ldaxr'):
            out += ['%s X0,[%s]' % (l.upper(), Y), 'STXR W9,X16,[%s]' % Y]; init['X16'] = '0'; flt.append('%d:X9=0' % tid)
        elif l.startswith('swp'): out.append('%s X16,X0,[%s]' % (l.upper(), Y)); init['X16'] = '0'
        else: out.append('%s X0,X19,[%s]' % (l.upper(), Y)); init['X0'] = '5'; init['X19'] = '7'
        return out, init, flt
    c, z = gen.code(tid, t, m)
    return c, ({'X16': '0'} if z else {}), []


def litmus(name, threads, mechs, cond, mask=0, marker=False):
    n = len(threads)
    cols, inits, flt = [], [], []
    for i, (t, m) in enumerate(zip(threads, mechs)):
        c, ini, f = code(i, t, m)
        if marker and mask >> i & 1: c = ['ISB'] + c
        cols.append(c); inits.append(ini); flt += f
    init = ' '.join('%d:X10=x; %d:X11=y; %d:X12=1; %d:X13=2; %d:X14=z; %d:X15=w;' % ((i,) * 6)
                    + ''.join(' %d:%s=%s;' % (i, r, v) for r, v in sorted(inits[i].items())) for i in range(n))
    d = max(map(len, cols)); cols = [c + [''] * (d - len(c)) for c in cols]
    head = ['P%d' % i for i in range(n)]
    w = [max(len(x) for x in [head[j]] + cols[j]) + 2 for j in range(n)]
    fmt = lambda r: ' ' + '| '.join(x.ljust(w[j]) for j, x in enumerate(r)).rstrip() + ' ;'
    tail = (['filter (%s)' % ' /\\ '.join(flt)] if flt else []) + ['exists (%s)' % cond, '']
    return '\n'.join(['AArch64 ' + name, '{ ' + init + ' }', fmt(head)] +
                     [fmt([cols[j][i] for j in range(n)]) for i in range(d)] + tail)


T = {}      # name -> test
ROLES = []  # dicts


def name_of(fam, modes, mechs):
    return '%s_%s_%s' % (fam, ''.join(modes), '-'.join(x or 'o' for x in mechs))


def add(fam, modes, mechs, **role):
    nm = name_of(fam, modes, mechs)
    if nm not in T:
        T[nm] = dict(name=nm, fam=fam, modes=''.join(modes), mask=sum(1 << i for i, x in enumerate(modes) if x == 'T'),
                     mechs=list(mechs), n=len(modes))
    if role: role['name'] = nm; ROLES.append(role)
    return nm


def base_mechs(fam, modes):
    return [BASE[(modes[i], KIND(t))] if KIND(t) else None for i, t in enumerate(FAM[fam][0])]


def build():
    # group 1
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            fam, pos = CANON[k]
            for m in rows(mode, k):
                for ctx in 'AT':
                    modes = [ctx, ctx]; modes[pos] = mode
                    mech = base_mechs(fam, modes); mech[pos] = m
                    add(fam, modes, mech, group='1', role='pivot', entry='%s:%s:%s' % (mode, k, m), pos=pos,
                        context='P%d=%s' % (1 - pos, ctx))
    for fam in ('MP', 'LB', 'SB'):
        for modes in itertools.product('AT', repeat=2):
            add(fam, list(modes), base_mechs(fam, modes), group='1', role='base', entry='-', pos=-1, context=''.join(modes))
    # group 2 job 1
    for fam in ('WRC', 'ISA2', 'RWC', 'IRIW'):
        n = len(FAM[fam][0])
        for modes in itertools.product('AT', repeat=n):
            variants = [base_mechs(fam, modes)]
            if fam == 'IRIW': variants.append([None, None, 'ldar.ldar', 'ldar.ldar'])
            for vi, mech in enumerate(variants):
                add(fam, list(modes), mech, group='2-job1', role='base' if vi == 0 else 'base-acq', entry='-', pos=-1,
                    context=''.join(modes))
    # group 2 job 2
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            fam, pos = PROP[k]
            n = len(FAM[fam][0])
            for m in rows(mode, k):
                for ctx in (mode, 'A' if mode == 'T' else 'T'):
                    modes = [ctx] * n; modes[pos] = mode
                    mech = base_mechs(fam, modes); mech[pos] = m
                    add(fam, modes, mech, group='2-job2', role='pivot', entry='%s:%s:%s' % (mode, k, m), pos=pos,
                        context='others=%s' % ctx)


def herd(model, path):
    args = ['herd7', '-I', MODELS, '-model', model, path] if model != 'aarch64' else ['herd7', '-model', 'aarch64.cat', path]
    o = subprocess.run(args, capture_output=True, text=True).stdout
    m = re.search(r'^Observation \S+ (\w+)', o, re.M)
    return m.group(1) if m else 'ERR'


def probes():
    os.makedirs(os.path.join(V2, 'probe'), exist_ok=True)
    head = 'catdep\ninclude "prelude.cat"\ninclude "arm-ppo.cat"\ninclude "tso-ppo.cat"\n' \
           'let MARK = ISB & ~range(po)\nlet TSO  = MARK | range([MARK]; po)\nlet ARM  = ~TSO\n' \
           'let ppo = [ARM]; arm-ppo-all; [ARM] | [TSO]; tso-ppo-all; [TSO]\nlet obs = rfe | coe | fre\n' \
           'acyclic po-loc | rf | co | fr  as sc-per-location\n'
    p = {'noatom': head + 'acyclic ppo | obs as order\n', 'noorder': head + 'empty rmw & (fre; coe) as atomicity\n'}
    out = {}
    for k, body in p.items():
        f = os.path.join(V2, 'probe', 'compound-%s.cat' % k)
        open(f, 'w').write('AArch64 "probe: compound.cat without the %s axiom"\n\n' % ('atomicity' if k == 'noatom' else 'order') + body)
        out[k] = f
    return out


def write_tests(names):
    for nm in names:
        t = T[nm]; th, cond = FAM[t['fam']]
        open(os.path.join(V2, 'gsrc', nm + '.litmus'), 'w').write(litmus(nm, th, t['mechs'], cond))
        open(os.path.join(V2, 'gherd', nm + '.litmus'), 'w').write(litmus(nm, th, t['mechs'], cond, t['mask'], True))


def run_herd(names, jobs, P):
    work = []
    for nm in names:
        t = T[nm]; s = os.path.join(V2, 'gsrc', nm + '.litmus'); h = os.path.join(V2, 'gherd', nm + '.litmus')
        work += [(nm, 'compound', h, os.path.join(MODELS, 'compound.cat')), (nm, 'compound-apple', h, os.path.join(MODELS, 'compound-apple.cat')),
                 (nm, 'aarch64', s, 'aarch64'), (nm, 'noatom', h, P['noatom']), (nm, 'noorder', h, P['noorder'])]
        if set(t['modes']) == {'A'}: work.append((nm, 'arm', s, os.path.join(MODELS, 'arm.cat')))
        if set(t['modes']) == {'T'}: work.append((nm, 'tso', h, os.path.join(MODELS, 'tso.cat')))
    with ThreadPoolExecutor(jobs) as ex:
        res = list(ex.map(lambda w: herd(w[3], w[2]), work))
    for (nm, m, _, _), r in zip(work, res): T[nm].setdefault('v', {})[m] = r


def axiom(v):
    if v['compound'] != 'Never': return '-'
    na, no = v['noatom'] == 'Never', v['noorder'] == 'Never'
    return 'order' if na and not no else 'atomicity' if no and not na else 'order+atomicity' if not na and not no else 'order|atomicity (either)'


def main():
    jobs = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else os.cpu_count()
    for d in ('gsrc', 'gherd'):
        os.makedirs(os.path.join(V2, d), exist_ok=True)
        for f in os.listdir(os.path.join(V2, d)): os.remove(os.path.join(V2, d, f))
    P = probes()
    build()
    write_tests(list(T)); run_herd(list(T), jobs, P)
    # table from group 1, the other thread in the pivot's mode, single-mode model
    table = {}
    for r in ROLES:
        if r['group'] != '1' or r['role'] != 'pivot': continue
        mode, k, m = r['entry'].split(':')
        if r['context'] != 'P%d=%s' % (1 - r['pos'], mode): continue
        v = T[r['name']]['v']['arm' if mode == 'A' else 'tso']
        table[r['entry']] = ({'Never': 'ordered', 'Sometimes': 'not-ordered'}.get(v, 'ERR:' + v), r['name'], axiom(T[r['name']]['v']))
    # controls
    new = []
    for r in list(ROLES):
        t = T[r['name']]; fam = t['fam']; modes = list(t['modes']); mech = list(t['mechs'])
        th = FAM[fam][0]
        if r['role'] == 'pivot':
            mode, k, m = r['entry'].split(':'); i = r['pos']
            if table[r['entry']][0] != 'ordered': r['control'] = '-'; continue
            if mode == 'A' or k == 'WR':
                mm = list(mech); mm[i] = 'plain'
                c = name_of(fam, modes, mm)
            else:
                md = list(modes); md[i] = 'A'; mm = list(mech)
                if table['A:%s:%s' % (k, m)][0] == 'ordered': mm[i] = 'plain'
                c = name_of(fam, md, mm)
            if c not in T: c = 'MISSING:' + c
            r['control'] = c
        elif r['role'] in ('base', 'base-acq'):
            cs = []
            for j, tt in enumerate(th):
                kk = KIND(tt)
                if not kk: continue
                if modes[j] == 'A' or kk == 'WR':
                    mm = list(mech); mm[j] = 'plain'
                    nm = name_of(fam, modes, mm)
                    if nm not in T: add(fam, modes, mm); new.append(nm)
                    ROLES.append(dict(name=nm, group=r['group'] + '-control', role='control-of', entry='-', pos=j,
                                      context=''.join(modes), control='-', of=r['name']))
                    cs.append(nm)
                else:
                    cs.append('none(P%d TSO %s)' % (j, kk))
            r['control'] = ';'.join(cs)
    write_tests(new); run_herd(new, jobs, P)
    os.makedirs(V2, exist_ok=True)
    with open(os.path.join(V2, 'ppo_table.tsv'), 'w') as f:
        f.write('# herd7: arm.cat (A) / tso.cat (T) on the group-1 witness (other thread in the pivot mode); axiom = which axiom forbids under compound\n')
        f.write('mode\tkind\tmechanism\tentry\textension\twitness\taxiom\n')
        for e, (o, w, ax) in table.items():
            mode, k, m = e.split(':')
            f.write('\t'.join([mode, k, m, o, 'ext' if (mode == 'T' and k == 'WR' and is_ext(m)) else '-', w, ax]) + '\n')
    with open(os.path.join(V2, 'roles.tsv'), 'w') as f:
        f.write('name\tgroup\trole\tentry\tpivot\tcontext\tcontrol\tof\n')
        for r in ROLES:
            f.write('\t'.join([r['name'], r['group'], r['role'], r['entry'], 'P%d' % r['pos'] if r['pos'] >= 0 else '-',
                               r['context'], r.get('control', '-'), r.get('of', '-')]) + '\n')
    cols = ['compound', 'compound-apple', 'arm', 'tso', 'aarch64', 'noatom', 'noorder']
    with open(os.path.join(V2, 'gen_tests.tsv'), 'w') as f:
        f.write('name\tfamily\tnthreads\tmask\tmodes\tmechanisms\t' + '\t'.join(cols) + '\taxiom\n')
        for nm, t in T.items():
            f.write('\t'.join([nm, t['fam'], str(t['n']), str(t['mask']), t['modes'], '-'.join(x or 'o' for x in t['mechs'])] +
                              [t['v'].get(c, '-') for c in cols] + [axiom(t['v'])]) + '\n')
    err = [nm for nm, t in T.items() if 'ERR' in t['v'].values()]
    print(len(T), 'generated tests;', len(ROLES), 'roles;', len(table), 'table rows;', len(new), 'extra control tests; herd errors', len(err), err[:5])


if __name__ == '__main__':
    main()
