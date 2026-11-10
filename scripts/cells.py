#!/usr/bin/env python3
"""batch5 v3: per-test, per-cell hits on each machine (new cells from results_<m>.tsv; reused tests from the batch4
   rows named in reuse_<m>.tsv 'from', mult 10, first row per cell as select_reuse.py takes it).
   python3 cells.py  -> cells.tsv: name, machine, cell (harness/core-set), hits, iterations"""
import csv, glob, os, collections
HERE = os.path.dirname(os.path.abspath(__file__)); B4 = os.path.join(HERE, '..', 'results', 'batch4')
FILES = {'m1': sorted(glob.glob(os.path.join(B4, 'raw', 'results_*.tsv'))) +
                [os.path.join(B4, p) for p in ('mixcov/results_mixcov.tsv', 'dsbldww/results_dsbldww.tsv',
                                               'failsc/results_failsc.tsv', 'mixmp/results_mixmp.tsv')],
         'm2': [p for p in sorted(glob.glob(os.path.join(B4, 'm2', 'results_m2_*.tsv'))) if not p.endswith('results_m2_x1.tsv')]}
out = csv.writer(open(os.path.join(HERE, '..', 'results', 'cells.tsv'), 'w'), delimiter='\t', lineterminator='\n')
out.writerow(['name', 'machine', 'cell', 'hits', 'iterations'])
for m in ('m1', 'm2'):
    old = {}
    for fn in FILES[m]:
        for l in open(fn):
            f = l.rstrip('\n').split('\t')
            if len(f) < 6 or l.startswith('#') or f[3] != '10' or f[4] == 'NA': continue
            d = f[0]
            old.setdefault((d, f[1], f[2]), (int(f[4]), int(f[5])))   # reuse_m2 'from' names M2 dirs unprefixed
            if m == 'm2' and os.path.basename(fn) == 'results_m2_dsbld_arm.tsv':
                old.setdefault(('dsbld_arm/' + d, f[1], f[2]), (int(f[4]), int(f[5])))
    rows = collections.OrderedDict()
    for f in csv.reader(open(os.path.join(HERE, '..', 'results', 'results_%s.tsv' % m)), delimiter='\t'):
        if f[3] == '10' and f[4] != 'NA': rows[(f[1], f[0].split('/')[1] + '/' + f[2])] = (int(f[4]), int(f[5]))
    for r in csv.DictReader(open(os.path.join(HERE, '..', 'results', 'reuse_%s.tsv' % m)), delimiter='\t'):
        if r['status'] != 'reusable': continue
        for src in r['from'].split(','):
            d, name = src.rsplit('/', 1)
            for cell in 'EMP':
                if (d, name, cell) in old: rows[(r['name'], d.split('/')[-1] + '/' + cell)] = old[(d, name, cell)]
    for (n, c), (h, it) in rows.items(): out.writerow([n, m, c, h, it])
