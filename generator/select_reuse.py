#!/usr/bin/env python3
"""batch5: targeted set, reproduction of batch4 shape tests, reuse of existing results, to-run lists, time estimate.

Run after gen.py. Reads (read-only) batch4/ and artifact/tests/; writes under batch5/:
  targeted/{src,herd,typed}/, targeted/list.tsv      hand-written tests kept (groups below), herd verdicts
  reproduction.tsv                                   every batch4 shape test: reproduced by which generated test, or why not
  undecided.tsv                                      shape tests not reproduced and not A1-A4 evidence (chosen by hand)
  runlist_all.txt, runlist_{m1,m2}.txt               'name nthreads' (run3 format): everything / still to run
  reuse_{m1,m2}.tsv                                  per test: reusable? from which batch4 harness/name, cells found
  hooklist.txt                                       '# name role mask nthreads' for hookcheck
  estimate.tsv                                       machine-time estimate per machine
Reuse rule: same normalized program (norm.key, threads NOT permuted) and same mode mask, and all six cells
{std_user, std_timebase} x {E, M, P} at mult 10 (1e8 each) on that machine. M2 results_m2_x1.tsv is never used.
"""
import csv, glob, os, re, shutil, statistics, subprocess, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import norm

HERE = os.path.dirname(os.path.abspath(__file__))
B4 = os.path.normpath(os.path.join(HERE, '..', 'batch4'))
ART = os.path.normpath(os.path.join(HERE, '..', '..', 'artifact', 'tests'))
M2A = os.path.normpath(os.path.join(HERE, '..', '..', 'm2-asahi'))
MODELS = os.path.normpath(os.path.join(HERE, '..', '..', 'compound-herd', 'models'))
SHAPES = ['MP', 'S', 'LB', 'R', '2+2W', 'SB', 'WRC', 'ISA2', 'RWC', 'IRIW']
KEEP_FAM = ['Df', 'Dr', 'Dw', 'SBx', 'fwd', 'n6', 'n7', 'n7fwd']
CELLS = [(h, c) for h in ('std_user', 'std_timebase') for c in 'EMP']

def tsv(p):
    rows = [l.rstrip('\n').split('\t') for l in open(p) if l.strip() and not l.startswith('#')]
    return [dict(zip(rows[0], r)) for r in rows[1:]]

def masks_of(path):
    return {r['name']: int(r['mask']) for r in tsv(path)} if os.path.exists(path) else {}

def herd(model, path):
    a = ['herd7'] + (['-I', MODELS] if model != 'aarch64' else []) + ['-model', model + '.cat', path]
    o = subprocess.run(a, capture_output=True, text=True).stdout
    m = re.search(r'^Observation \S+ (\w+)', o, re.M)
    return m.group(1) if m else 'ERR'

def add_isb(src, dst, mask):
    """src -> dst with a leading ISB on every TSO thread (as batch4/mk_herd_isb.py)."""
    L = open(src).read().split('\n')
    h = next(i for i, l in enumerate(L) if re.match(r'\s*P0\s*(\||;)', l))
    e = next(i for i in range(h + 1, len(L)) if re.match(r'\s*(exists|~exists|forall|filter|locations)', L[i]))
    head = [c.strip() for c in L[h].rstrip().rstrip(';').split('|')]
    rows = [[c.strip() for c in l.rstrip().rstrip(';').split('|')] for l in L[h + 1:e] if l.strip()]
    k = len(head)
    cols = [[r[j] for r in rows] for j in range(k)]
    for j in range(k):
        if mask >> j & 1: cols[j] = ['ISB'] + cols[j]
    d = max(map(len, cols)); cols = [c + [''] * (d - len(c)) for c in cols]
    w = [max(len(x) for x in [head[j]] + cols[j]) + 2 for j in range(k)]
    fmt = lambda r: ' ' + '| '.join(x.ljust(w[j]) for j, x in enumerate(r)).rstrip() + ' ;'
    open(dst, 'w').write('\n'.join(L[:h] + [fmt(head)] + [fmt([cols[j][i] for j in range(k)]) for i in range(d)] + L[e:]))

def main():
    man = {r['name']: r for r in tsv(os.path.join(ART, 'MANIFEST.tsv'))}
    gen = tsv(os.path.join(HERE, 'list.tsv'))
    G = {}                                   # key -> generated name
    gkey = {}
    for r in gen:
        k = norm.key(os.path.join(HERE, 'src', r['name'] + '.litmus'), int(r['mask']))
        assert k not in G, ('two generated tests with one key', r['name'], G[k]); G[k] = r['name']; gkey[r['name']] = k
    # per-thread code of generated tests -> mechanism, per (family, position, mode); and the family's condition
    thr = defaultdict(dict); famtail = defaultdict(set)
    for r in gen:
        k = gkey[r['name']]; parts = k.split(' || ')
        modes, code, tail = parts[0], parts[1:-1], parts[-1]
        famtail[r['family']].add(tail)
        for i, (c, m) in enumerate(zip(code, r['mechanisms'].split('-'))):
            thr[(r['family'], i, modes[i])][c] = m
    BASE = {('A','WW'): 'str.stlr', ('A','RR'): 'ldar.ldr', ('A','RW'): 'data', ('A','WR'): 'dmb',
            ('T','WW'): 'plain', ('T','RR'): 'plain', ('T','RW'): 'plain', ('T','WR'): 'dmb'}
    SK = {'MP': ['WW', 'RR'], 'S': ['WW', 'RW'], 'LB': ['RW', 'RW'], 'R': ['WW', 'WR'], '2+2W': ['WW', 'WW'],
          'SB': ['WR', 'WR'], 'WRC': ['W', 'RW', 'RR'], 'ISA2': ['WW', 'RW', 'RR'], 'RWC': ['W', 'RR', 'WR'],
          'IRIW': ['W', 'W', 'RR', 'RR']}

    def why_not(fam, path, mask):
        """Reason a shape test is not generated: classify each thread against the generator's per-position codes,
        under the thread order that explains it best (hand-written IRIW puts the writers at P0 and P2)."""
        import itertools
        cols, init, tail0 = norm.parse(path)
        best = None
        for order in itertools.permutations(range(len(cols))):
            k = norm._canon(cols, init, tail0, mask, list(order))
            r = why_one(fam, k)
            score = (r.startswith('P') or r.startswith('thread count'), r.startswith('condition'), r.count(';'), order != tuple(range(len(cols))))
            if best is None or score < best[0]: best = (score, r, order)
        r, order = best[1], best[2]
        return r if order == tuple(range(len(cols))) else r + ' [threads read in order %s]' % ','.join('P%d' % o for o in order)
    def why_one(fam, k):
        parts = k.split(' || '); modes, code, tail = parts[0], parts[1:-1], parts[-1]
        if len(code) != len(SK[fam]): return 'thread count differs from the shape'
        rs, nonbase = [], []
        for i, c in enumerate(code):
            m = thr[(fam, i, modes[i])].get(c)
            if m is None:
                tags = []
                if re.search(r'\b(LDXR|LDAXR|STXR|STLXR)\b', c): tags.append('LL/SC pair')
                if re.search(r'\b(SWP\w*|LDADD\w*|CAS\w*)\b', c): tags.append('AMO')
                if re.search(r'\bDMB SY|DMB LD|DMB ST|DSB SY|DSB LD|DSB ST\b', c): tags.append('barrier written SY/LD/ST form (generator uses ISH forms)')
                if re.search(r'\bISB\b', c) and 'CBNZ' not in c: tags.append('ISB without ctrl')
                ann = re.search(r'\b(LDAR|LDAPR|STLR)\b', c); bar = re.search(r'\b(DMB|DSB|EOR|CBNZ)\b', c)
                if ann and bar: tags.append('annotated access + barrier/dependency')
                if len(re.findall(r'\b(LDR|LDAR|LDAPR|STR|STLR|SWP\w*|LDADD\w*|LDX\w*|LDAX\w*|ST\w*XR)\b', c)) > (len(SK[fam][i])) + 1:
                    tags.append('more accesses than the shape')
                rs.append('P%d not in universe (%s): %s' % (i, ', '.join(tags) or 'other', c))
            elif m != 'o' and m != BASE[(modes[i], SK[fam][i])]:
                nonbase.append('P%d=%s' % (i, m))
        if rs: return '; '.join(rs)
        if tail not in famtail[fam]: return 'condition/filter differs from the shape: ' + tail
        lone_t = [i for i in range(len(code)) if len(SK[fam][i]) == 1 and modes[i] == 'T']
        if len(nonbase) >= 2: return 'two or more non-base edges (%s)' % ', '.join(nonbase)
        if lone_t and nonbase: return 'lone-op thread TSO in a pivot test (%s)' % ', '.join(nonbase)
        return 'same as a generated test up to thread order' if not nonbase or len(nonbase) == 1 else 'unexplained'

    # ---- batch4 shape tests: reproduced? ----
    ev = lambda r: r['compound'] != r['compound-apple']
    rep = []
    for name, r in sorted(man.items()):
        if r['family'] not in SHAPES: continue
        k = norm.key(os.path.join(ART, 'typed', name + '.litmus'), int(r['mask']))
        assert k == norm.key(os.path.join(ART, 'src', name + '.litmus'), int(r['mask'])), name
        g = G.get(k)
        rep.append(dict(name=name, set=r['set'], family=r['family'], mask=r['mask'], generated=g or '-',
                        evidence='A-evidence' if ev(r) else '-', reason='-' if g else why_not(r['family'], os.path.join(ART, 'src', name + '.litmus'), int(r['mask'])),
                        key=k))
    # thread-permutation matches (reported only; not used for reuse: M cells place threads on core types by role)
    gperm = {}
    for r in gen:
        gperm.setdefault(norm.key(os.path.join(HERE, 'src', r['name'] + '.litmus'), int(r['mask']), perm=True), r['name'])
    for x in rep:
        if x['generated'] == '-':
            pk = norm.key(os.path.join(ART, 'src', x['name'] + '.litmus'), int(x['mask']), perm=True)
            x['perm'] = gperm.get(pk, '-')
        else: x['perm'] = '-'
        x['decision'] = ('reproduced' if x['generated'] != '-' else 'kept: A1-A4 evidence' if x['evidence'] != '-'
                         else 'UNDECIDED')
    def category(r):
        if r == '-': return '-'
        c = []
        if 'LL/SC' in r: c.append('LL/SC pair')
        if 'AMO' in r: c.append('AMO outside the generator (SWPA/SWPL/AMO with annotated access/AMO on both edges)')
        if 'SY/LD/ST form' in r: c.append('barrier in SY/LD/ST form (generator: ISH forms)')
        if 'annotated access + barrier' in r: c.append('annotated access + barrier/dependency')
        if 'two or more non-base' in r: c.append('two or more non-base edges')
        if 'lone-op thread TSO' in r: c.append('lone-op writer TSO with a non-base edge')
        if 'up to thread order' in r: c.append('same as a generated test up to thread order')
        if 'condition' in r: c.append('condition differs')
        return '; '.join(c) or 'other'
    for x in rep: x['cat'] = category(x['reason'])
    with open(os.path.join(HERE, 'reproduction.tsv'), 'w') as f:
        f.write('name\tset\tfamily\tmask\tdecision\treproduced_by\tA_evidence\tcategory\treason_not_reproduced\tmatches_generated_up_to_thread_permutation\n')
        for x in rep:
            f.write('\t'.join([x['name'], x['set'], x['family'], x['mask'], x['decision'], x['generated'], x['evidence'],
                               x['cat'], x['reason'], x['perm']]) + '\n')

    # ---- targeted set ----
    T = []   # dict(name, group, mask, n, typed, src)
    def add(name, group, mask, n, typed, src):
        T.append(dict(name=name, group=group, mask=mask, n=n, typed=typed, src=src))
    for name, r in sorted(man.items()):
        art = lambda d: os.path.join(ART, d, name + '.litmus')
        if r['family'] in KEEP_FAM: add(name, 'family ' + r['family'], int(r['mask']), int(r['nthreads']), art('typed'), art('src'))
        elif r['set'] == 'dsbldww': add(name, 'dsbldww', int(r['mask']), int(r['nthreads']), art('typed'), art('src'))
        elif r['family'] in SHAPES and ev(r):
            x = next(x for x in rep if x['name'] == name)
            if x['generated'] == '-': add(name, 'A1-A4 evidence (shape, not generated)', int(r['mask']), int(r['nthreads']), art('typed'), art('src'))
    fm = masks_of(os.path.join(B4, 'failsc', 'modes.tsv'))
    for name, m in sorted(fm.items()):
        add(name, 'failsc', m, 2, os.path.join(B4, 'failsc', 'typed', name + '.litmus'), os.path.join(B4, 'failsc', 'src', name + '.litmus'))
    gnames = {r['name'] for r in gen}
    for t in T:
        t['key'] = norm.key(t['typed'], t['mask'])
        t['dup'] = G.get(t['key'], '-')
        t['orig'] = t['name']
        if t['name'] in gnames and t['dup'] != t['name']:      # same name, different program (e.g. DSB LD vs DSB ISHLD)
            t['name'] = t['name'] + '_b4'
    for d in ('src', 'herd', 'typed'): os.makedirs(os.path.join(HERE, 'targeted', d), exist_ok=True)
    for d in ('src', 'herd', 'typed'):
        for f in glob.glob(os.path.join(HERE, 'targeted', d, '*.litmus')): os.remove(f)
    def cp(a, b, nm):
        L = open(a).read().split('\n'); L[0] = re.sub(r'^(AArch64\s+)\S+', lambda m: m.group(1) + nm, L[0])
        open(b, 'w').write('\n'.join(L))
    for t in T:
        cp(t['src'], os.path.join(HERE, 'targeted', 'src', t['name'] + '.litmus'), t['name'])
        cp(t['typed'], os.path.join(HERE, 'targeted', 'typed', t['name'] + '.litmus'), t['name'])
        add_isb(os.path.join(HERE, 'targeted', 'src', t['name'] + '.litmus'), os.path.join(HERE, 'targeted', 'herd', t['name'] + '.litmus'), t['mask'])
    work = [(t['name'], m) for t in T for m in ('compound', 'compound-apple', 'aarch64')]
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(lambda w: herd(w[1], os.path.join(HERE, 'targeted', 'src' if w[1] == 'aarch64' else 'herd', w[0] + '.litmus')), work))
    V = defaultdict(dict)
    for (n, m), v in zip(work, res): V[n][m] = v
    herd_mismatch = []
    for t in T:
        r = man.get(t['orig'])
        if r:
            for m in ('compound', 'compound-apple', 'aarch64'):
                if r[m] != V[t['name']][m]: herd_mismatch.append((t['name'], m, r[m], V[t['name']][m]))
    with open(os.path.join(HERE, 'targeted', 'list.tsv'), 'w') as f:
        f.write('name\tbatch4_name\tgroup\tnthreads\tmask\tsame_program_as_generated\tcompound\tcompound-apple\taarch64\n')
        for t in T:
            f.write('\t'.join([t['name'], t['orig'], t['group'], str(t['n']), str(t['mask']), t['dup']] +
                              [V[t['name']][m] for m in ('compound', 'compound-apple', 'aarch64')]) + '\n')
    with open(os.path.join(HERE, 'targeted', 'modes.tsv'), 'w') as f:
        f.write('name\tmask\tmodes\texpected\n')
        for t in T: f.write('%s\t%d\t-\t-\n' % (t['name'], t['mask']))

    # ---- existing results ----
    def src_of(prefix, name, machine, fname):
        if machine == 'm2' and os.path.basename(fname) == 'results_m2_dsbld_arm.tsv': prefix = 'dsbld_arm'
        cands = []
        if prefix:
            p = os.path.join(B4, prefix, 'typed', name + '.litmus')
            if os.path.exists(p): cands.append(p)
        for d in (os.path.join(ART, 'typed'), os.path.join(B4, 'typed'), os.path.join(B4, 'src')):
            p = os.path.join(d, name + '.litmus')
            if os.path.exists(p): cands.append(p)
        mk = masks_of(os.path.join(B4, prefix, 'modes.tsv')) if prefix else {}
        mask = mk.get(name, int(man[name]['mask']) if name in man else None)
        return (cands[0] if cands else None), mask
    files = {'m1': sorted(glob.glob(os.path.join(B4, 'raw', 'results_*.tsv'))) +
                   [os.path.join(B4, p) for p in ('mixcov/results_mixcov.tsv', 'dsbldww/results_dsbldww.tsv',
                                                  'failsc/results_failsc.tsv', 'mixmp/results_mixmp.tsv')],
             'm2': [p for p in sorted(glob.glob(os.path.join(B4, 'm2', 'results_m2_*.tsv'))) if not p.endswith('results_m2_x1.tsv')]}
    found = {m: defaultdict(lambda: defaultdict(list)) for m in files}   # machine -> key -> (harness, cell) -> rows
    dur = {m: defaultdict(list) for m in files}                          # machine -> (family, nthreads, cell) -> seconds
    problems, short = [], []
    seen_rows = set()
    for mach, fl in files.items():
        for fn in fl:
            for l in open(fn):
                f = l.rstrip('\n').split('\t')
                if len(f) < 9: continue
                d, name, cell, mult, hits, iters, mm, t = f[0], f[1], f[2], f[3], f[4], f[5], f[6], f[7]
                rid = (mach, d, name, cell, mult)
                if rid in seen_rows: continue          # raw/ holds copies of some sub-batch files
                seen_rows.add(rid)
                prefix, harness = (d.rsplit('/', 1) if '/' in d else ('', d))
                if harness not in ('std_user', 'std_timebase') or mult != '10' or hits == 'NA': continue
                src, mask = src_of(prefix, name, mach, fn)
                if src is None or mask is None: problems.append((mach, fn, d, name, 'no source/mask')); continue
                nthr = len(norm.parse(src)[0])
                mmm = re.match(r'arm_sets=(\d+)/tso_sets=(\d+)', mm)
                k_t = bin(mask).count('1')
                if not mmm or int(mmm.group(2)) * nthr != k_t * (int(mmm.group(1)) + int(mmm.group(2))):
                    problems.append((mach, fn, d, name, 'MEMMODEL %s vs mask %d' % (mm, mask))); continue
                if int(iters) < 100000000: short.append((mach, d, name, cell, iters))
                k = norm.key(src, mask)
                found[mach][k][(harness, cell)].append(dict(file=os.path.relpath(fn, B4), dir=d, name=name, hits=int(hits), n=int(iters)))
                fam = man[name]['family'] if name in man else name.split('_')[0]
                dur[mach][(fam, nthr, cell, harness)].append(int(t))
                dur[mach][('*', nthr, cell, harness)].append(int(t))
    # ---- run universe: generated + targeted not identical to a generated test ----
    U = [(r['name'], int(r['nthreads']), int(r['mask']), gkey[r['name']], r['family'], 'generated') for r in gen]
    U += [(t['name'], t['n'], t['mask'], t['key'], t['name'].split('_')[0], 'targeted') for t in T if t['dup'] == '-']
    with open(os.path.join(HERE, 'runlist_all.txt'), 'w') as f:
        for n, nt, *_ in U: f.write('%s %d\n' % (n, nt))
    with open(os.path.join(HERE, 'hooklist.txt'), 'w') as f:
        f.write('# name\trole\tmask\tnthreads\n')
        for n, nt, mk, *_ in U: f.write('%s\ttest\t%d\t%d\n' % (n, mk, nt))
    summary = {}
    for mach in files:
        reuse, torun = [], []
        for n, nt, mk, k, fam, src in U:
            cells = found[mach].get(k, {})
            have = [c for c in CELLS if c in cells]
            ok = len(have) == 6
            frm = sorted({'%s/%s' % (x['dir'], x['name']) for c in have for x in cells[c]})
            mn = min(cells[c][0]['n'] for c in have) if ok else '-'
            reuse.append((n, src, 'reusable' if ok else 'to-run', len(have), ','.join(frm) or '-', mn,
                          sum(cells[c][0]['hits'] for c in have) if ok else '-',
                          sum(cells[c][0]['n'] for c in have) if ok else '-'))
            if not ok: torun.append((n, nt, fam))
        with open(os.path.join(HERE, 'reuse_%s.tsv' % mach), 'w') as f:
            f.write('name\tsource\tstatus\tcells_found_of_6\tfrom\tmin_cell_iterations\thits_6cells\titerations_6cells\n')
            for r in reuse: f.write('\t'.join(map(str, r)) + '\n')
        with open(os.path.join(HERE, 'runlist_%s.txt' % mach), 'w') as f:
            for n, nt, fam in torun: f.write('%s %d\n' % (n, nt))
        # time estimate: per cell, median duration of the same family+cell+harness on this machine, else of nthreads
        tot, basis = 0, defaultdict(int)
        for n, nt, fam in torun:
            for h, c in CELLS:
                xs = dur[mach].get((fam, nt, c, h)) or dur[mach].get((fam.split('_')[0], nt, c, h))
                b = 'family'
                if not xs: xs = dur[mach][('*', nt, c, h)]; b = 'nthreads'
                tot += statistics.median(xs); basis[b] += 1
                basis['s_' + ('generated' if n in gnames else 'targeted')] += statistics.median(xs)
                basis['s_%dT' % nt] += statistics.median(xs)
        summary[mach] = dict(reusable=sum(r[2] == 'reusable' for r in reuse), torun=len(torun),
                             torun_gen=sum(1 for n, nt, fam in torun if n in gnames), seconds=tot, basis=dict(basis),
                             partial=sum(1 for r in reuse if 0 < r[3] < 6))
    # per-(nthreads, cell) median durations for the report
    with open(os.path.join(HERE, 'estimate.tsv'), 'w') as f:
        f.write('machine\tnthreads\tharness\tcell\tmedian_s\tn_cells\n')
        for mach in files:
            for nt in (2, 3, 4):
                for h, c in CELLS:
                    xs = dur[mach][('*', nt, c, h)]
                    f.write('%s\t%d\t%s\t%s\t%s\t%d\n' % (mach, nt, h, c, statistics.median(xs) if xs else '-', len(xs)))
        for mach, s in summary.items():
            f.write('# %s: reusable %d, to-run %d (generated %d), partial-cell tests %d, est. %.0f s = %.1f h; basis %s\n'
                    % (mach, s['reusable'], s['torun'], s['torun_gen'], s['partial'], s['seconds'], s['seconds'] / 3600, s['basis']))
    und = [x for x in rep if x['decision'] == 'UNDECIDED']
    with open(os.path.join(HERE, 'undecided.tsv'), 'w') as f:
        f.write('name\tset\tfamily\tmask\tcategory\treason_not_reproduced\tm1_cells_of_6\tm2_cells_of_6\n')
        for x in und:
            f.write('\t'.join([x['name'], x['set'], x['family'], x['mask'], x['cat'], x['reason']] +
                              [str(len([c for c in CELLS if c in found[m].get(x['key'], {})])) for m in ('m1', 'm2')]) + '\n')
    print('targeted', len(T), 'of which identical to a generated test', sum(t['dup'] != '-' for t in T))
    print('groups', dict(sorted(defaultdict(int, {g: sum(1 for t in T if t['group'] == g) for g in {t['group'] for t in T}}).items())))
    print('shape tests', len(rep), 'reproduced', sum(x['decision'] == 'reproduced' for x in rep),
          'kept-evidence', sum(x['decision'].startswith('kept') for x in rep), 'undecided', len(und),
          'perm-only matches', sum(x['perm'] != '-' for x in rep))
    print('run universe', len(U)); print('summary', summary)
    print('herd mismatches vs MANIFEST', herd_mismatch)
    print('result-row problems', len(problems), problems[:10]); print('short cells (<1e8)', len(short), short[:10])

if __name__ == '__main__':
    main()
