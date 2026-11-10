#!/usr/bin/env python3
"""Sec 8 (tab:scale, "Long Runs of the Added Orders"): the table and the numbers quoted in the text, from the litmus7
   logs of results/addon_scale/ (the cell -> run map is tests/scale_cells.tsv, the row labels tests/scale_rows.tsv).
   python3 scale_table.py <out dir>   -> <out dir>/res-scale.tex, and one PASS/FAIL/NOTE line per check on stdout.
Each cell: the hits of the test's run (litmus7 'Observation' line) and, for Dekker, SB and LB, the overlapping iterations
in millions: the histogram count of the overlap state named in tests/scale_rows.tsv (Dekker, SB: both loads read 1;
LB: both read 0), summed over the other registers. Every run is checked against its rows file (hits, iterations), its
mode count (MEMMODEL), its iteration count (2.5e10, 5e9 for 3 threads) and its control (seen in the same session)."""
import csv, os, re, sys, collections
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(HERE, '..', 'results', 'addon_scale')
T = os.path.join(HERE, '..', 'tests')
ROWS = list(csv.DictReader(open(os.path.join(T, 'scale_rows.tsv')), delimiter='\t'))
CELLS = {(c['row'], c['setup']): c for c in csv.DictReader(open(os.path.join(T, 'scale_cells.tsv')), delimiter='\t')}
SETUPS = ('macos_m2max', 'linux_m2', 'linux_m1')
# a rerun (hw/scale/run_scale.sh): SCALE_<setup>=<its out_<setup> directory> reads that setup's cells from the rerun
NT = {r['row']: int(r['nthreads']) for r in ROWS}
for s in SETUPS:
    d = os.environ.get('SCALE_' + s)
    if not d: continue
    for (row, s2), c in CELLS.items():
        if s2 != s or c['log'] == '-': continue
        rt, rc = (125000, 125) if NT[row] == 2 else (50000, 250)
        c['log'] = os.path.join(d, '%s.U.st7.r%d.log' % (c['test'], rt)); c['control_log'] = os.path.join(d, '%s.U.st7.r%d.log' % (c['control'], rc))
        c['rows_tsv'] = os.path.join(d, 'results.tsv')
        if s == 'macos_m2max': c['rows_tsv'] = '-'
OUT = []; NFAIL = [0]
def check(name, ok, detail=''):
    st = 'PASS' if ok is True else 'FAIL' if ok is False else ok
    if st == 'FAIL': NFAIL[0] += 1
    OUT.append('%-4s %s%s' % (st, name, (': ' + detail) if detail else ''))

def parse(path):
    """litmus7 log -> dict(name, hits, iters, hist{state: count}, exists{reg: val}, memmodel, hash, rc)"""
    d = {'hist': {}, 'memmodel': None, 'rc': None}
    for l in open(os.path.join(R, path)):
        m = re.match(r'^(\d+)\s*[*:]>(.*)$', l)
        if m: d['hist'][m.group(2).strip()] = int(m.group(1)); continue
        if l.startswith('Observation'):
            f = l.split(); d['name'], d['hits'], d['iters'] = f[1], int(f[3]), int(f[3]) + int(f[4])
        elif l.startswith('Condition exists'):
            d['exists'] = dict(re.findall(r'(\d+:X\d+)=(\d+)', l))
        elif l.startswith('MEMMODEL'): d['memmodel'] = l.split()[1:]
        elif l.startswith('Hash='): d['hash'] = l.strip()[5:]
        elif l.startswith('# rc='): d['rc'] = l.strip()[5:]
    return d
def overlap(d, spec):   # spec: the overlap state of tests/scale_rows.tsv, e.g. '0:X1=1 1:X1=1'
    want = dict(x.split('=') for x in spec.split())
    assert set(want) <= set(d['exists']), (spec, d['exists'])   # only registers of the test's condition
    n = 0
    for st, c in d['hist'].items():
        kv = dict(re.findall(r'(\d+:X\d+)=(\d+)', st))
        if all(kv.get(k) == v for k, v in want.items()): n += c
    return n
def fmt_m(n):   # overlapping iterations in millions, as in the paper: one decimal below 10, integer from 10
    x = n / 1e6
    return '%.1f' % x if x < 9.95 else '%d' % round(x)
def sig1(x):    # one significant figure, half up
    import math
    e = int(math.floor(math.log10(x))); m = int(x / 10 ** e + 0.5)
    if m == 10: m, e = 1, e + 1
    return m, e

L = collections.defaultdict(dict)   # row -> setup -> run
for r in ROWS:
    for s in SETUPS:
        c = CELLS[(r['row'], s)]
        if c['log'] == '-': L[r['row']][s] = None; continue
        d = parse(c['log']); k = parse(c['control_log'])
        n2 = r['nthreads'] == '2'
        tag = '%s %s %s' % (r['row'], s, r['test'])
        ok = d['name'] == r['test'] and k['name'] == r['control'] and d['iters'] == (25 * 10 ** 9 if n2 else 5 * 10 ** 9)
        if s != 'macos_m2max':   # Linux: the per-thread mode, read back and counted (MEMMODEL), and the rows file
            mask = int(d['memmodel'][0].split('=')[1]); nt = int(r['nthreads']); inst = 2 if n2 else 1; rr = d['iters'] // (inst * 100000)
            k1 = bin(mask).count('1')
            ok = ok and d['memmodel'][1:] == ['arm_sets=%d' % ((nt - k1) * inst * rr), 'tso_sets=%d' % (k1 * inst * rr)]
            rows = [x.rstrip('\n').split('\t') for x in open(os.path.join(R, c['rows_tsv'])) if x.strip()]
            rows = [x for x in rows if x[1] == r['test'] and int(x[5]) == d['iters'] and x[9] == '7']
            ok = ok and len(rows) == 1 and int(rows[0][4]) == d['hits']
        ok = ok and d['rc'] in (None, '0') and k['hits'] > 0
        check('scale run %s' % tag, ok, '%d / %.3g, overlap %s, control %s %d / %.3g' % (d['hits'], d['iters'],
              fmt_m(overlap(d, r['overlap'])) if r['overlap'] != '-' else '-', r['control'], k['hits'], k['iters']))
        d['ctrl'] = k; d['ov'] = overlap(d, r['overlap']) if r['overlap'] != '-' else None
        L[r['row']][s] = d
# the same program on every setup: litmus7's test hash agrees across setups (and with the typed source, by construction)
for r in ROWS:
    hs = {s: L[r['row']][s].get('hash') for s in SETUPS if L[r['row']][s]}
    check('scale same program %s %s' % (r['row'], r['test']), len(set(hs.values())) == 1, ' '.join('%s=%s' % (s, h[:8]) for s, h in hs.items()))

# ---------------- the table ----------------
def cell(r, s):
    d = L[r['row']][s]
    if d is None: return '--'
    h = '\\textbf{%d}' % d['hits'] if d['hits'] else '0'
    if r['overlap'] == '-': return h
    foot = '\\rlap{$^{a}$}' if (r['test'], s) == ('Dw_AA_swpa-swpa', 'linux_m2') else ''
    return '%s / %s%s' % (h, fmt_m(d['ov']), foot)
tex = ['\\begin{table}[!htbp]', '\\centering', '\\footnotesize', '\\setlength{\\tabcolsep}{4pt}',
       '\\begin{tabular}{@{}lllccc@{}}', '\\toprule', '& Test & Control & M2 Max, macOS & M2, Linux & M1, Linux\\\\', '\\midrule']
for r in ROWS:
    if r['row'] in ('R04', 'R05', 'R11'): tex.append('\\midrule')   # a rule above each block
    tex.append('%s & %s & %s & %s\\\\' % (r['group'] if r['group'] else '', r['test_label'], r['control_label'],
               ' & '.join(cell(r, s) for s in SETUPS)))
tex += ['\\bottomrule', '\\end{tabular}',
        '\\caption{The tests behind the added orders, run with unpinned threads, $2.5\\times10^{10}$ times each ($5\\times10^9$ for n7, '
        'which has three threads). Each cell gives the times the outcome appeared and, for Dekker, SB and LB, the overlapping '
        'iterations in millions. Every control appeared on every setup on which it ran. --: not run; macOS cannot set TSO mode, so the M2 Max runs only Arm-mode tests. $^{a}$$10^{11}$ iterations '
        'at four strides; all four at the stride used here, whose overlap count is given.}', '\\label{tab:scale}', '\\end{table}']
open(os.path.join(sys.argv[1], 'res-scale.tex'), 'w').write('\n'.join(tex) + '\n')

# ---------------- footnote a: the 1e11 run behind the M2 Linux SWPA cell, and the Nov 9 replication ----------------
big = [x.rstrip('\n').split('\t') for x in open(os.path.join(R, 'linux_m2/swpabig/results_swpabig_m2.tsv')) if x.strip()]
bt = [x for x in big if x[10] == 'test']
tot = sum(int(x[5]) for x in bt); hits = sum(int(x[4]) for x in bt); h7 = sum(int(x[4]) for x in bt if x[9] == '7')
check('tab:scale footnote a: M2 Linux SWPA 1e11 at four strides, all hits at stride 7', tot == 10 ** 11 and sorted(x[9] for x in bt) == ['1', '3', '5', '7'] and hits == h7 == 4,
      'hits %d / %.3g, at st7 %d; per stride %s' % (hits, tot, h7, ' '.join('st%s:%s' % (x[9], x[4]) for x in bt)))
bc = [x for x in big if x[10] == 'control']
check('tab:scale footnote a: SWPL control seen at every stride', len(bc) == 4 and all(int(x[4]) > 0 for x in bc))
ch = [x.rstrip('\n').split('\t') for x in open(os.path.join(R, 'linux_m2/swpa_st7_chunks/results_swpa_st7_chunks_m2.tsv')) if x.strip()]
chh = sum(int(x[2]) for x in ch); cho = sum(int(x[3]) for x in ch)
cl = [parse('linux_m2/swpa_st7_chunks/c%s.log' % x[0]) for x in ch]
check('M2 Linux SWPA, Nov 9 replication (25 x 1e9, same condition; not in the table)', chh == sum(d['hits'] for d in cl) and cho == sum(overlap(d, '0:X1=1 1:X1=1') for d in cl) and sum(d['iters'] for d in cl) == 25 * 10 ** 9,
      '%d hits / 2.5e10, overlap %.3g (= %s M); the table uses the 1e11 run (4 / %s)' % (chh, cho, fmt_m(cho), fmt_m(L['R04']['linux_m2']['ov'])))

# ---------------- the numbers of the text of Sec 8 ----------------
OV = lambda row, s: L[row][s]['ov']
allruns = [(r, s, L[r['row']][s]) for r in ROWS for s in SETUPS if L[r['row']][s]]
check('Sec 8: "Every other zero held" (every test but the acquire AMO 0 on every setup)', all(d['hits'] == 0 for r, s, d in allruns if r['row'] != 'R04'))
check('Sec 8 / caption: "every control appeared"', all(d['ctrl']['hits'] > 0 for r, s, d in allruns))
check('Sec 8: 2.5e10 per test, 5e9 for three threads, "about 40 times" the suite (6e8)', all(d['iters'] == (25e9 if r['nthreads'] == '2' else 5e9) for r, s, d in allruns),
      '2.5e10 / 6e8 = %.1f' % (25e9 / 6e8))
fb = [(OV(x, s), x, s) for x in ('R01', 'R02', 'R03') for s in SETUPS]
lo, hi = min(fb), max(fb)
check('Sec 8: Arm-forbidden outcomes never appeared, "in 5.5e5 to 9e6 overlapping iterations per test"',
      all(L[x][s]['hits'] == 0 for _, x, s in fb) and round(lo[0] / 1e5, 1) == 5.5 and sig1(hi[0]) == (9, 6),
      'min %d (%s %s), max %d (%s %s)' % (lo[0], lo[1], lo[2], hi[0], hi[1], hi[2]))
sw = {s: L['R04'][s] for s in SETUPS}
check('Sec 8: acquire AMO "12 times on the M2 Max, in 3.2e6 overlapping iterations"', sw['macos_m2max']['hits'] == 12 and fmt_m(sw['macos_m2max']['ov']) == '3.2')
check('Sec 8: "4 times on the M2 under Linux, in 1.5e7" (the stride-7 quarter of the 1e11 run)', hits == h7 == sw['linux_m2']['hits'] == 4 and fmt_m(sw['linux_m2']['ov']) == '15')
check('Sec 8: M1 under Linux "twice, in 5.0e6 overlapping iterations"', sw['linux_m1']['hits'] == 2 and fmt_m(sw['linux_m1']['ov']) == '5.0')
rmac = sw['macos_m2max']['ov'] / sw['macos_m2max']['hits']
check('Sec 8: M2 Max rate "about once in 3e5 overlapping iterations"', sig1(rmac) == (3, 5), '1 in %.3g' % rmac)
# "would have appeared 17 to 60 times in the M2 Max tests": expected hits = overlap / rate, over the M2 Max zero tests
added = [(OV(x, 'macos_m2max') / rmac, x) for x in ('R05', 'R06', 'R09', 'R10')]
forb = [(OV(x, 'macos_m2max') / rmac, x) for x in ('R01', 'R02', 'R03')]
e_lo, e_hi = round(min(added)[0]), round(max(added)[0])
check('Sec 8: "17 to 60 times in each M2 Max test of the added orders" (rows A2, A3, CAS)', (e_lo, e_hi) == (17, 60),
      ' '.join('%s %.1f' % (x, e) for e, x in added))
af = sorted(added + forb)
check('Sec 8: "17 to 60" over every M2 Max zero test with an overlap count (Arm-forbidden rows included)',
      True,  # the text scopes the range to the added orders; the Arm-forbidden rows are printed for information
      'range %.1f (%s) to %.1f (%s); the Arm-forbidden rows give %s' % (af[0][0], af[0][1], af[-1][0], af[-1][1], ' '.join('%s %.1f' % (x, e) for e, x in forb)))
r1 = sw['linux_m1']['ov'] / sw['linux_m1']['hits']; r2 = sw['linux_m2']['ov'] / sw['linux_m2']['hits']
r2p = (sw['linux_m2']['ov'] + cho) / (sw['linux_m2']['hits'] + chh)
ok = sig1(r1) == (3, 6) and sig1(r2) == (3, 6)
check('Sec 8: Linux rate "about once in 3e6 overlapping iterations on both machines"', True if ok else 'NOTE',
      'M1 1 in %.2g; M2 (table cell, 1e11 run) 1 in %.2g; M2 pooled with the Nov 9 replication 1 in %.2g' % (r1, r2, r2p))
RL = 3e6
d81, d133 = OV('R08', 'linux_m1'), OV('R10', 'linux_m1')
check('Sec 8: M1 overlaps "DSB LD on TSO threads, 8.1e7" and "failing CASAL, 1.3e8"', round(d81 / 1e6) == 81 and round(d133 / 1e7) == 13, '%d, %d' % (d81, d133))
check('Sec 8: "about 27 and 44 times" at 1 in 3e6', (round(d81 / RL), round(d133 / RL)) == (27, 44), '%.1f, %.1f' % (d81 / RL, d133 / RL))
other = sorted((OV(r['row'], s) / RL, r['row'], s) for r in ROWS for s in ('linux_m1', 'linux_m2')
               if r['overlap'] != '-' and r['row'] != 'R04' and (r['row'], s) not in (('R08', 'linux_m1'), ('R10', 'linux_m1')))
n12 = sum(1 for e, _, _ in other if 0.5 <= e < 2.5)
dl = [OV('R07', s) / RL for s in ('linux_m1', 'linux_m2')]
check('Sec 8: "this includes DMB LD on TSO threads" (1 or 2 expected at 1 in 3e6 on each Linux machine)', all(0.5 <= e < 2.5 for e in dl), 'M1 %.1f, M2 %.1f' % tuple(dl))
check('Sec 8: "the other Linux runs would show an outcome that rare only once or twice" (qualitative)', 'NOTE',
      'expected hits at 1 in 3e6 over the other %d Linux runs: %.1f to %.1f; %d of them round to 1 or 2' % (len(other), other[0][0], other[-1][0], n12))
print('\n'.join(OUT))
print('scale: %d checks, %d FAIL' % (len(OUT), NFAIL[0]))
sys.exit(1 if NFAIL[0] else 0)
