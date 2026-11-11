#!/usr/bin/env python3
"""Level 1: every counted row recomputed from its litmus7 log (artifact tree; run from scripts/).
   Main suite: results/results_<m>.tsv against results/logs/<m>/<harness>/<test>.<cell>.x10.log.
   Reused batch4 cells (the rows cells.py takes through reuse_<m>.tsv): results/batch4/<rows> against
   results/batch4/logs/<m>/<from>/<test>.<cell>.x10.log, as listed in results/batch4/reuse_logs.tsv.
   Add-ons: results/addon_*/results_<m>.tsv against their logs.
   A log matches its row when its Observation line gives the row's hits and iterations (positive + negative).
   Prints PASS or FAIL per group, NOTE for a reused cell with no log, and exits 1 on a FAIL."""
import csv, glob, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); R = os.path.join(HERE, '..', 'results'); B4 = os.path.join(R, 'batch4')
fails = 0

def obs(f):
    o = re.search(r'^Observation \S+ \S+ (\d+) (\d+)', open(f, errors='replace').read(), re.M)
    return (int(o.group(1)), int(o.group(2))) if o else None

def matches(row, f):
    if not os.path.isfile(f): return 'no log'
    o = obs(f)
    if o is None: return 'no Observation line'
    h, n = row
    return None if o in ((h, n - h), (h, n)) else 'log %d/%d' % (o[0], o[0] + o[1])

def check_rows(label, rows_f, logdir):
    global fails
    bad = []; n = 0
    for f in csv.reader(open(rows_f), delimiter='\t'):
        if len(f) < 6 or f[3] != '10' or f[4] == 'NA': continue
        n += 1
        e = matches((int(f[4]), int(f[5])), os.path.join(logdir, f[0].split('/')[-1], '%s.%s.x10.log' % (f[1], f[2])))
        if e: bad.append('%s %s %s: row %s/%s, %s' % (f[0], f[1], f[2], f[4], f[5], e))
    if bad:
        fails += 1; print('FAIL %s: %d of %d rows differ from their logs' % (label, len(bad), n))
        for b in bad[:10]: print('    ' + b)
    else: print('PASS %s: %d rows, each equal to its log' % (label, n))

for m in ('m1', 'm2'):
    check_rows('main suite, %s' % m, os.path.join(R, 'results_%s.tsv' % m), os.path.join(R, 'logs', m))

# reused batch4 cells: the rows as cells.py reads them, and the manifest of their logs
FILES = {'m1': sorted(glob.glob(os.path.join(B4, 'raw', 'results_*.tsv'))) +
                [os.path.join(B4, p) for p in ('mixcov/results_mixcov.tsv', 'dsbldww/results_dsbldww.tsv',
                                               'failsc/results_failsc.tsv', 'mixmp/results_mixmp.tsv')],
         'm2': [p for p in sorted(glob.glob(os.path.join(B4, 'm2', 'results_m2_*.tsv'))) if not p.endswith('results_m2_x1.tsv')]}
man = {(r['machine'], r['from'], r['name'], r['cell']) for r in csv.DictReader(open(os.path.join(B4, 'reuse_logs.tsv')), delimiter='\t')}
for m in ('m1', 'm2'):
    old = {}
    for fn in FILES[m]:
        for l in open(fn):
            f = l.rstrip('\n').split('\t')
            if len(f) < 6 or l.startswith('#') or f[3] != '10' or f[4] == 'NA': continue
            old.setdefault((f[0], f[1], f[2]), (int(f[4]), int(f[5])))
            if m == 'm2' and os.path.basename(fn) == 'results_m2_dsbld_arm.tsv':
                old.setdefault(('dsbld_arm/' + f[0], f[1], f[2]), (int(f[4]), int(f[5])))
    bad = []; nolog = []; n = 0
    for r in csv.DictReader(open(os.path.join(R, 'reuse_%s.tsv' % m)), delimiter='\t'):
        if r['status'] != 'reusable': continue
        for src in r['from'].split(','):
            d, name = src.rsplit('/', 1)
            for cell in 'EMP':
                if (d, name, cell) not in old: continue
                n += 1
                if (m, d, name, cell) not in man: nolog.append('%s/%s %s (test %s)' % (d, name, cell, r['name'])); continue
                e = matches(old[(d, name, cell)], os.path.join(B4, 'logs', m, d, '%s.%s.x10.log' % (name, cell)))
                if e: bad.append('%s/%s %s: row %d/%d, %s' % (d, name, cell, old[(d, name, cell)][0], old[(d, name, cell)][1], e))
    if bad:
        fails += 1; print('FAIL reused batch4 cells, %s: %d of %d differ from their logs' % (m, len(bad), n))
        for b in bad[:10]: print('    ' + b)
    else: print('PASS reused batch4 cells, %s: %d of %d cells have a log, each equal to its row' % (m, n - len(nolog), n))
    for b in nolog: print('NOTE reused batch4 cell without a log, %s: %s' % (m, b))

for a, dirs in (('addon_swpal', {'m1': 'logs', 'm2': 'logs_m2'}), ('addon_mpreader', {'m1': 'logs', 'm2': 'logs_m2'}),
                ('addon_fwdtso', {'m1': 'logs/m1', 'm2': 'logs/m2'}), ('addon_casfail', {'m1': 'logs/m1', 'm2': 'logs/m2'})):
    for m in ('m1', 'm2'):
        check_rows('%s, %s' % (a, m), os.path.join(R, a, 'results_%s.tsv' % m), os.path.join(R, a, dirs[m]))
sys.exit(1 if fails else 0)
