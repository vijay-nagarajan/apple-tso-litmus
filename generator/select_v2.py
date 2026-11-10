#!/usr/bin/env python3
"""batch5 Design v2: group 3 (hand-written, with reasons), additional.tsv, the merged list, reuse, run lists, estimate.
Run after gen2.py. Reads batch4/ and artifact/tests/ read-only; writes under v2/:
  src/ herd/ typed/      every test of the run universe (generated: from gsrc/gherd; group 3: batch4's files)
  list.tsv               one row per test: groups, entries/reasons, contexts, paper section, controls, verdicts
  group3.tsv             every group-3 test: reason, and the generated test it equals (if any)
  additional.tsv         batch4 tests outside the run universe: category; six cells on M1 / M2
  reuse_m1.tsv reuse_m2.tsv runlist_all.txt runlist_m1.txt runlist_m2.txt hooklist.txt modes_all.tsv estimate.tsv
"""
import glob, itertools, os, re, shutil, statistics, subprocess, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import norm, gen2

V2 = os.path.join(HERE, 'v2')
B4 = os.path.normpath(os.path.join(HERE, '..', 'batch4'))
ART = os.path.normpath(os.path.join(HERE, '..', '..', 'artifact', 'tests'))
MODELS = gen2.MODELS
CELLS = [(h, c) for h in ('std_user', 'std_timebase') for c in 'EMP']
SHAPES = ['MP', 'S', 'LB', 'R', '2+2W', 'SB', 'WRC', 'ISA2', 'RWC', 'IRIW']
PLAIN_REF = ['MP_AA_plain-plain', 'SB_AA_plain-plain', 'LB_AA_plain-plain', 'S_AA_plain-plain', 'R_AA_plain-plain',
             '2+2W_AA_plain-plain', 'WRC_AAA_plain-plain-plain', 'ISA2_AAA_plain-plain-plain', 'RWC_AAA_plain-plain-plain',
             'IRIW_AAAA_plain-plain-plain-plain']

def tsv(p):
    L = [l.rstrip('\n').split('\t') for l in open(p) if l.strip() and not l.startswith('#')]
    return [dict(zip(L[0], r)) for r in L[1:]]

def masks_of(p): return {r['name']: int(r['mask']) for r in tsv(p)} if os.path.exists(p) else {}

def section(modes, reason=''):
    if reason.startswith('x86'): return '6a'
    if reason.startswith('same-address'): return '6c'
    if reason.startswith('RMW'): return '6d'
    s = set(modes)
    return '5' if s == {'A'} else '6b' if s == {'T'} else '7'

def load_results(man):
    """machine -> key -> (harness, cell) -> [row]; and durations machine -> (family, nthreads, cell, harness) -> [s]"""
    def src_of(prefix, name, mach, fn):
        if mach == 'm2' and os.path.basename(fn) == 'results_m2_dsbld_arm.tsv': prefix = 'dsbld_arm'
        c = []
        if prefix and os.path.exists(os.path.join(B4, prefix, 'typed', name + '.litmus')): c.append(os.path.join(B4, prefix, 'typed', name + '.litmus'))
        for d in (os.path.join(ART, 'typed'), os.path.join(B4, 'typed'), os.path.join(B4, 'src')):
            if os.path.exists(os.path.join(d, name + '.litmus')): c.append(os.path.join(d, name + '.litmus'))
        mk = masks_of(os.path.join(B4, prefix, 'modes.tsv')) if prefix else {}
        return (c[0] if c else None), mk.get(name, int(man[name]['mask']) if name in man else None)
    files = {'m1': sorted(glob.glob(os.path.join(B4, 'raw', 'results_*.tsv'))) +
                   [os.path.join(B4, p) for p in ('mixcov/results_mixcov.tsv', 'dsbldww/results_dsbldww.tsv',
                                                  'failsc/results_failsc.tsv', 'mixmp/results_mixmp.tsv')],
             'm2': [p for p in sorted(glob.glob(os.path.join(B4, 'm2', 'results_m2_*.tsv'))) if not p.endswith('results_m2_x1.tsv')]}
    found = {m: defaultdict(lambda: defaultdict(list)) for m in files}
    dur = {m: defaultdict(list) for m in files}
    seen, bad = set(), []
    for mach, fl in files.items():
        for fn in fl:
            for l in open(fn):
                f = l.rstrip('\n').split('\t')
                if len(f) < 9: continue
                d, name, cell, mult, hits, iters, mm, t = f[:8]
                if (mach, d, name, cell, mult) in seen: continue
                seen.add((mach, d, name, cell, mult))
                prefix, harness = d.rsplit('/', 1) if '/' in d else ('', d)
                if harness not in ('std_user', 'std_timebase') or mult != '10' or hits == 'NA': continue
                src, mask = src_of(prefix, name, mach, fn)
                if src is None or mask is None: bad.append((mach, d, name)); continue
                nthr = len(norm.parse(src)[0])
                m = re.match(r'arm_sets=(\d+)/tso_sets=(\d+)', mm)
                if not m or int(m.group(2)) * nthr != bin(mask).count('1') * (int(m.group(1)) + int(m.group(2))):
                    bad.append((mach, d, name, mm)); continue
                found[mach][norm.key(src, mask)][(harness, cell)].append(dict(dir=d, name=name, hits=int(hits), n=int(iters)))
                fam = man[name]['family'] if name in man else name.split('_')[0]
                dur[mach][(fam, nthr, cell, harness)].append(int(t)); dur[mach][('*', nthr, cell, harness)].append(int(t))
    return found, dur, bad

def herd(model, path):
    a = ['herd7', '-I', MODELS, '-model', model, path] if model != 'aarch64' else ['herd7', '-model', 'aarch64.cat', path]
    o = subprocess.run(a, capture_output=True, text=True).stdout
    m = re.search(r'^Observation \S+ (\w+)', o, re.M)
    return m.group(1) if m else 'ERR'

def main():
    man = {r['name']: r for r in tsv(os.path.join(ART, 'MANIFEST.tsv'))}
    G = {r['name']: r for r in tsv(os.path.join(V2, 'gen_tests.tsv'))}
    R = tsv(os.path.join(V2, 'roles.tsv'))
    gkey = {n: norm.key(os.path.join(V2, 'gsrc', n + '.litmus'), int(r['mask'])) for n, r in G.items()}
    K = {k: n for n, k in gkey.items()}
    rep1 = {r['name']: r for r in tsv(os.path.join(HERE, 'reproduction.tsv'))}
    # ---- group 3 ----
    g3 = {}   # name -> dict
    def put(name, reason, src, typed, mask, n, origin):
        if name in g3: g3[name]['reason'] += '; ' + reason; return
        g3[name] = dict(name=name, reason=reason, src=src, typed=typed, mask=mask, n=n, origin=origin)
    art = lambda d, n: os.path.join(ART, d, n + '.litmus')
    def llsc_threads(name):
        cols = norm.parse(art('src', name))[0]
        return sum(1 for c in cols if any(re.match(r'(LDA?XR|STL?XR|SWP|LDADD|CAS)', x) for x in c))
    sbx_subsumed = []
    for name, r in sorted(man.items()):
        fam, mask, n = r['family'], int(r['mask']), int(r['nthreads'])
        k = norm.key(art('typed', name), mask)
        a = (art('src', name), art('typed', name), mask, n, 'batch4')
        if r['class'] == 'tso': put(name, 'x86 program (x86-TSO vs IBM 370)', *a)
        if fam in ('n6', 'n7', 'n7fwd', 'fwd'): put(name, 'same-address', *a)
        if fam in ('Df', 'Dr', 'Dw'): put(name, 'RMW atomicity', *a)
        if r['compound'] != r['compound-apple'] and k not in K: put(name, 'A1-A4 evidence', *a)
        if name in PLAIN_REF: put(name, 'plain Arm reference', *a)
        if fam == 'SBx':
            if k in K: sbx_subsumed.append((name, K[k]))
            else: put(name, 'SBx (not subsumed by group 1)', *a)
        if fam in SHAPES and name in rep1 and ('LL/SC' in rep1[name]['category'] or 'AMO' in rep1[name]['category']) \
                and k not in K and llsc_threads(name) == 1:
            put(name, 'RMW (LL/SC or AMO on one thread of a TSO shape, outside the generator)', *a)
    for name, m in sorted(masks_of(os.path.join(B4, 'failsc', 'modes.tsv')).items()):
        put(name, 'RMW atomicity (failsc)', os.path.join(B4, 'failsc', 'src', name + '.litmus'),
            os.path.join(B4, 'failsc', 'typed', name + '.litmus'), m, 2, 'batch4/failsc')
    # plain references the batch4 suite lacks: generate in the generator's layout
    os.makedirs(os.path.join(V2, 'g3gen'), exist_ok=True)
    for name in PLAIN_REF:
        if name in man: continue
        fam = name.split('_')[0]; th, cond = gen2.FAM[fam]
        mech = ['plain' if gen2.KIND(t) else None for t in th]
        nm = gen2.name_of(fam, ['A'] * len(th), mech)
        p = os.path.join(V2, 'g3gen', nm + '.litmus'); open(p, 'w').write(gen2.litmus(nm, th, mech, cond))
        put(nm, 'plain Arm reference (generated; not in batch4)', p, None, 0, len(th), 'group3-generated')
    for t in g3.values():
        t['key'] = norm.key(t['src'], t['mask'])
        t['same_as'] = K.get(t['key'], '-')
        t['run_name'] = t['same_as'] if t['same_as'] != '-' else (t['name'] + '_b4' if t['name'] in G else t['name'])
    # ---- additional: batch4 tests outside the run universe ----
    ukeys = set(K) | {t['key'] for t in g3.values()}
    found, dur, bad = load_results(man)
    six = lambda m, k: sum(1 for c in CELLS if c in found[m].get(k, {}))
    add = []
    allb4 = [(n, r['set'], r['family'], int(r['mask']), art('typed', n)) for n, r in man.items()]
    for n, st, fam, mask, p in sorted(allb4):
        k = norm.key(p, mask)
        if k in ukeys: continue
        cat = rep1[n]['category'] if n in rep1 and rep1[n]['category'] != '-' else \
              ('v1 base (rel/acq/data on the other edges): not a v2 test' if n in rep1 else 'not a shape test, not in group 3')
        if 'LL/SC' in cat or 'AMO' in cat: cat += ' (two or more RMW threads)'
        add.append((n, st, fam, cat, six('m1', k), six('m2', k)))
    with open(os.path.join(V2, 'additional.tsv'), 'w') as f:
        f.write('name\tset\tfamily\tcategory\tm1_cells_of_6\tm2_cells_of_6\tall_six_on\n')
        for a in add:
            f.write('\t'.join(map(str, a)) + '\t%s\n' % ('+'.join(m for m, c in (('M1', a[4]), ('M2', a[5])) if c == 6) or 'neither'))
    # ---- merged universe ----
    for d in ('src', 'herd'):
        os.makedirs(os.path.join(V2, d), exist_ok=True)
        for f in glob.glob(os.path.join(V2, d, '*.litmus')): os.remove(f)
    U = {}
    for n, r in G.items():
        U[n] = dict(name=n, family=r['family'], n=int(r['nthreads']), mask=int(r['mask']), modes=r['modes'], key=gkey[n],
                    origin='generated', v=r)
        shutil.copyfile(os.path.join(V2, 'gsrc', n + '.litmus'), os.path.join(V2, 'src', n + '.litmus'))
        shutil.copyfile(os.path.join(V2, 'gherd', n + '.litmus'), os.path.join(V2, 'herd', n + '.litmus'))
    sys.path.insert(0, HERE); import select_reuse as s1
    for t in g3.values():
        if t['same_as'] != '-': continue
        n = t['run_name']; L = open(t['src']).read().split('\n'); L[0] = re.sub(r'^(AArch64\s+)\S+', lambda m: m.group(1) + n, L[0])
        open(os.path.join(V2, 'src', n + '.litmus'), 'w').write('\n'.join(L))
        s1.add_isb(os.path.join(V2, 'src', n + '.litmus'), os.path.join(V2, 'herd', n + '.litmus'), t['mask'])
        modes = ''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n']))
        U[n] = dict(name=n, family=n.split('_')[0], n=t['n'], mask=t['mask'], modes=modes, key=t['key'], origin=t['origin'], v={})
    work = [(n, m) for n, u in U.items() if u['origin'] != 'generated' for m in ('compound', 'compound-apple', 'aarch64')]
    work += [(n, 'arm') for n, u in U.items() if u['origin'] != 'generated' and set(u['modes']) == {'A'}]
    work += [(n, 'tso') for n, u in U.items() if u['origin'] != 'generated' and set(u['modes']) == {'T'}]
    path = lambda n, m: os.path.join(V2, 'src' if m in ('aarch64', 'arm') else 'herd', n + '.litmus')
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(lambda w: herd(w[1] if w[1] == 'aarch64' else os.path.join(MODELS, w[1] + '.cat'), path(*w)), work))
    for (n, m), v in zip(work, res): U[n]['v'][m] = v
    # roles per test
    roles = defaultdict(list)
    for r in R: roles[r['name']].append(r)
    for t in g3.values(): roles[t['run_name']].append(dict(group='3', role='hand-written', entry=t['reason'], context=''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n'])),
                                                        control='-', name=t['run_name'], b4=t['name']))
    with open(os.path.join(V2, 'group3.tsv'), 'w') as f:
        f.write('name\trun_name\treason\torigin\tmask\tsame_program_as_generated\tsection\n')
        for t in g3.values():
            modes = ''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n']))
            f.write('\t'.join([t['name'], t['run_name'], t['reason'], t['origin'], str(t['mask']), t['same_as'], section(modes, t['reason'])]) + '\n')
    cols = ['compound', 'compound-apple', 'arm', 'tso', 'aarch64']
    with open(os.path.join(V2, 'list.tsv'), 'w') as f:
        f.write('name\tfamily\tnthreads\tmask\tmodes\tgroup\tentry_or_reason\tpivot\tcontext\tsection\tcontrol\t' + '\t'.join(cols) + '\taxiom\torigin\n')
        for n, u in U.items():
            rs = roles[n]
            grp = ';'.join(sorted({r['group'] for r in rs}))
            ent = ';'.join(r['entry'] if r['entry'] != '-' else r['role'] for r in rs)
            piv = ';'.join(r.get('pivot', '-') for r in rs)
            ctx = ';'.join(r['context'] for r in rs)
            ctl = ';'.join(r['control'] for r in rs if r['control'] != '-') or '-'
            reason = ';'.join(r['entry'] for r in rs if r['group'] == '3')
            sec = section(u['modes'], reason)
            f.write('\t'.join([n, u['family'], str(u['n']), str(u['mask']), u['modes'], grp, ent, piv, ctx, sec, ctl] +
                              [u['v'].get(c, '-') for c in cols] + [u['v'].get('axiom', '-'), u['origin']]) + '\n')
    # typed/, modes, hooklist, runlists
    shutil.rmtree(os.path.join(V2, 'typed'), ignore_errors=True); os.makedirs(os.path.join(V2, 'typed'))
    for n, u in U.items():
        t = next((x for x in g3.values() if x['run_name'] == n and x['same_as'] == '-'), None)
        if t and t['typed']:
            L = open(t['typed']).read().split('\n'); L[0] = re.sub(r'^(AArch64\s+)\S+', lambda m: m.group(1) + n, L[0])
            open(os.path.join(V2, 'typed', n + '.litmus'), 'w').write('\n'.join(L))
        else:
            subprocess.run(['python3', '-I', os.path.join(B4, 'typer.py'), os.path.join(V2, 'src', n + '.litmus'),
                            os.path.join(V2, 'typed', n + '.litmus')], check=True)
        assert norm.key(os.path.join(V2, 'typed', n + '.litmus'), u['mask']) == u['key'], n
    with open(os.path.join(V2, 'modes_all.tsv'), 'w') as f:
        f.write('name\tmask\tmodes\texpected\n'); [f.write('%s\t%d\t%s\t-\n' % (n, u['mask'], u['modes'])) for n, u in U.items()]
    with open(os.path.join(V2, 'hooklist.txt'), 'w') as f:
        f.write('# name\trole\tmask\tnthreads\n'); [f.write('%s\ttest\t%d\t%d\n' % (n, u['mask'], u['n'])) for n, u in U.items()]
    with open(os.path.join(V2, 'runlist_all.txt'), 'w') as f: [f.write('%s %d\n' % (n, u['n'])) for n, u in U.items()]
    summ = {}
    for mach in ('m1', 'm2'):
        rows, torun = [], []
        for n, u in U.items():
            c = found[mach].get(u['key'], {}); have = [x for x in CELLS if x in c]; ok = len(have) == 6
            rows.append((n, u['origin'], 'reusable' if ok else 'to-run', len(have),
                         ','.join(sorted({'%s/%s' % (r['dir'], r['name']) for x in have for r in c[x]})) or '-',
                         min(c[x][0]['n'] for x in have) if ok else '-', sum(c[x][0]['hits'] for x in have) if ok else '-',
                         sum(c[x][0]['n'] for x in have) if ok else '-'))
            if not ok: torun.append(n)
        with open(os.path.join(V2, 'reuse_%s.tsv' % mach), 'w') as f:
            f.write('name\torigin\tstatus\tcells_found_of_6\tfrom\tmin_cell_iterations\thits_6cells\tcounted_iterations_6cells\n')
            for r in rows: f.write('\t'.join(map(str, r)) + '\n')
        with open(os.path.join(V2, 'runlist_%s.txt' % mach), 'w') as f: [f.write('%s %d\n' % (n, U[n]['n'])) for n in torun]
        tot = defaultdict(float)
        for n in torun:
            u = U[n]
            for h, c in CELLS:
                xs = dur[mach].get((u['family'], u['n'], c, h)) or dur[mach][('*', u['n'], c, h)]
                s = statistics.median(xs); tot['all'] += s; tot['%dT' % u['n']] += s
                tot['generated' if u['origin'] == 'generated' else 'group3'] += s
        summ[mach] = dict(reusable=sum(r[2] == 'reusable' for r in rows), torun=len(torun),
                          torun_gen=sum(1 for n in torun if U[n]['origin'] == 'generated'),
                          reuse_gen=sum(1 for r in rows if r[2] == 'reusable' and r[1] == 'generated'),
                          hours={k: round(v / 3600, 1) for k, v in tot.items()})
    with open(os.path.join(V2, 'estimate.tsv'), 'w') as f:
        for m, s in summ.items(): f.write('%s\t%s\n' % (m, s))
    print('universe', len(U), 'generated', len(G), 'group3', len(g3), 'group3 same as generated', sum(t['same_as'] != '-' for t in g3.values()))
    print('group3 reasons', dict(sorted(defaultdict(int, {k: sum(1 for t in g3.values() if t['reason'].split(';')[0] == k) for k in {t['reason'].split(';')[0] for t in g3.values()}}).items())))
    print('SBx subsumed', sbx_subsumed)
    print('additional', len(add), 'result problems', len(bad))
    print(summ)

if __name__ == '__main__':
    main()
