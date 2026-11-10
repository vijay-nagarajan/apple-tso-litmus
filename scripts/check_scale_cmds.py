#!/usr/bin/env python3
"""Level 3 link: the jobs that hw/scale/run_scale.sh issues (DRYRUN=1) are exactly the commands logged in the header
line of every Sec 8 log the report uses (tests/scale_cells.tsv: test and control of each cell; for linux_m2's acquire-AMO
cell, footnote a's four strides in linux_m2/swpabig/). Compared: program name and litmus7 run flags (-a -s -r -st)."""
import os, re, subprocess, sys
A = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); R = os.path.join(A, 'results', 'addon_scale')
MACH = {'linux_m1': 'm1', 'linux_m2': 'm2', 'macos_m2max': 'macos'}
def norm(cmd):   # 'gen_screen/X.exe -a 4 -s 100000 -r 125000 -st 7' -> ('X', '-a 4 -s 100000 -r 125000 -st 7')
    f = cmd.split(); return os.path.basename(f[0])[:-4], ' '.join(f[1:])
def logged(path):
    l = open(os.path.join(R, path)).readline()
    m = re.search(r'cmd: (.*)$', l); return norm(m.group(1)) if m else None
cells = [l.rstrip('\n').split('\t') for l in open(os.path.join(A, 'tests', 'scale_cells.tsv'))][1:]
bad = 0
for setup, m in MACH.items():
    want = set(); miss = []
    for c in cells:
        if c[1] != setup or c[4] == '-': continue
        logs = [c[4], c[5]]
        if setup == 'linux_m2' and c[2] == 'Dw_AA_swpa-swpa':
            d = 'linux_m2/swpabig'; logs = [os.path.join(d, f) for f in sorted(os.listdir(os.path.join(R, d))) if re.match(r'.*\.U\.st[0-9]+\.r[0-9]+\.log$', f)]
        for g in logs:
            x = logged(g); (want.add(x) if x else miss.append(g))
    out = subprocess.run(['sh', os.path.join(A, 'hw', 'scale', 'run_scale.sh'), m], env=dict(os.environ, DRYRUN='1'),
                         capture_output=True, text=True).stdout
    got = set(norm(l.split('./', 1)[1].split(' >')[0]) for l in out.splitlines() if './' in l)
    ok = want == got and not miss
    bad += not ok
    print('%s scale commands %s: %d jobs of run_scale.sh %s == %d commands logged in results/%s' % (
        'PASS' if ok else 'FAIL', setup, len(got), m, len(want), (' (no cmd header: %s)' % miss) if miss else ''))
    if not ok:
        for x in sorted(want - got): print('    logged, not issued:', *x)
        for x in sorted(got - want): print('    issued, not logged:', *x)
sys.exit(1 if bad else 0)
