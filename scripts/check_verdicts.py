#!/usr/bin/env python3
"""Recompute every herd verdict and check the model files against herd's own models.

Usage: check_models.py [-j JOBS]
Needs herd7 (herdtools7 7.58) on PATH. Checks:
  1. verdicts of tests/list.tsv and tests/addon.tsv: compound.cat, compound-apple.cat (on ISB-marked tests), arm.cat (all-Arm
     tests), tso.cat (all-TSO tests) and herd's aarch64.cat (on unmarked tests) are recomputed and must match the list.
  2. arm.cat gives the same verdict as herd's aarch64.cat on every test.
  3. tso.cat gives the same verdict as herd's x86tso.cat on every test that is an x86 program
     (plain LDR/STR and DMB SY/ISH only), translated to x86 syntax.
  4. compound.cat equals arm.cat on all-Arm tests and tso.cat on all-TSO tests; likewise for the -apple files.
Exits non-zero if any check fails.
"""
import csv, os, re, subprocess, sys, shutil, tempfile
from multiprocessing import Pool

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
MODELS = os.path.join(ROOT, 'models')
JOBS = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else os.cpu_count()

def herdlib():
    """herd's library directory: $HERDLIB, else <prefix>/share/herdtools7/herd next to herd7."""
    exe = shutil.which('herd7') or sys.exit('herd7 not on PATH')
    d = os.path.join(os.path.dirname(os.path.dirname(os.path.realpath(exe))), 'share', 'herdtools7', 'herd')
    if os.path.exists(os.path.join(d, 'aarch64.cat')): return d
    sys.exit('cannot find herd library directory with aarch64.cat; set HERDLIB')
HLIB = os.environ.get('HERDLIB') or herdlib()

T = {}
for lst in ('list.tsv', 'addon.tsv'):
    for f in csv.DictReader(open(os.path.join(ROOT, 'tests', lst)), delimiter='\t'):
        T[f['name']] = dict(mask=int(f['mask']), nt=int(f['nthreads']), spec=f['compound'], enf=f['compound-apple'],
                            armv=f['arm'], tsov=f['tso'], arm=f['aarch64'],
                            u=os.path.join(ROOT, 'tests', 'src', f['name'] + '.litmus'),
                            m=os.path.join(ROOT, 'tests', 'herd', f['name'] + '.litmus'))

def herd(a):
    model, inc, path = a
    r = subprocess.run(['herd7', '-I', inc, '-model', model, path], capture_output=True, text=True)
    m = [l.split()[2] for l in r.stdout.splitlines() if l.startswith('Observation')]
    return m[0] if m else 'ERR'

def run(model, inc, key, names):
    with Pool(JOBS) as p:
        return dict(zip(names, p.map(herd, [(model, inc, T[n][key]) for n in names])))

REG = ['EAX', 'EBX', 'ECX', 'EDX', 'ESI', 'EDI']
def to_x86(path):
    s = open(path).read()
    env = {}
    for a in re.search(r'\{(.*?)\}', s, re.S).group(1).split(';'):
        m = re.match(r'(\d+):(X\d+)\s*=\s*(\w+)', a.replace('int64_t', '').strip())
        if m: env[(int(m.group(1)), m.group(2))] = m.group(3)
    body = s[s.index('}') + 1:]
    cond = [l for l in body.splitlines() if l.strip().startswith(('exists', 'forall', '~exists', 'filter'))]
    if any(c.strip().startswith('filter') for c in cond): return None
    rows = [l.rstrip().rstrip(';').split('|') for l in body.splitlines() if l.strip().endswith(';')]
    nt = len(rows[0]); out = [[] for _ in range(nt)]; regmap = {}
    for row in rows[1:]:
        for t, ins in enumerate(row):
            ins = ins.strip()
            if not ins or (ins == 'ISB' and not out[t]): continue
            m = re.match(r'STR (X\d+),\[(X\d+)\]$', ins)
            if m:
                v, loc = env.get((t, m.group(1))), env.get((t, m.group(2)))
                if v is None or loc is None or not v.isdigit(): return None
                out[t].append('MOV [%s],$%s' % (loc, v)); continue
            m = re.match(r'LDR (X\d+),\[(X\d+)\]$', ins)
            if m:
                loc = env.get((t, m.group(2)))
                if loc is None: return None
                r = regmap.setdefault((t, m.group(1)), REG[len([k for k in regmap if k[0] == t])])
                out[t].append('MOV %s,[%s]' % (r, loc)); continue
            if ins in ('DMB SY', 'DMB ISH'): out[t].append('MFENCE'); continue
            return None
    try: c = re.sub(r'(\d+):(X\d+)', lambda m: '%s:%s' % (m.group(1), regmap[(int(m.group(1)), m.group(2))]), '\n'.join(cond))
    except KeyError: return None
    txt = ['X86 %s' % os.path.basename(path)[:-7], '{ }', ' ' + ' | '.join('P%d' % i for i in range(nt)) + ' ;']
    for i in range(max(len(o) for o in out)):
        txt.append(' ' + ' | '.join((o[i] if i < len(o) else '') for o in out) + ' ;')
    return '\n'.join(txt + [c]) + '\n'

def main():
    N = sorted(T); bad = 0
    def check(title, pairs):
        nonlocal bad
        d = [p for p in pairs if p[1] != p[2]]
        print('%-58s %4d compared, %d differ' % (title, len(pairs), len(d)))
        for p in d: print('     ', *p)
        bad += len(d)
    V = {}
    for m, k in [('compound', 'm'), ('arm', 'u'), ('tso', 'u'), ('arm', 'm'), ('tso', 'm'), ('compound-apple', 'm'), ('arm-apple', 'm'), ('tso-apple', 'm')]:
        V[(m, k)] = run(os.path.join(MODELS, m + '.cat'), MODELS, k, N)
    V['aarch64'] = run(os.path.join(HLIB, 'aarch64.cat'), HLIB, 'u', N)
    print('1. verdict list')
    check('   compound.cat == list', [(n, V[('compound', 'm')][n], T[n]['spec']) for n in N])
    check('   compound-apple.cat == list', [(n, V[('compound-apple', 'm')][n], T[n]['enf']) for n in N])
    check('   herd aarch64.cat == list', [(n, V['aarch64'][n], T[n]['arm']) for n in N])
    check('   arm.cat == list (all-Arm tests)', [(n, V[('arm', 'u')][n], T[n]['armv']) for n in N if T[n]['armv'] != '-'])
    check('   tso.cat == list (all-TSO tests)', [(n, V[('tso', 'm')][n], T[n]['tsov']) for n in N if T[n]['tsov'] != '-'])
    print('2. Arm')
    check('   arm.cat == herd aarch64.cat, all-Arm tests', [(n, V[('arm', 'u')][n], V['aarch64'][n]) for n in N if T[n]['mask'] == 0])
    print('3. TSO')
    tmp = tempfile.mkdtemp(); pairs = []
    for n in N:
        if T[n]['mask'] != (1 << T[n]['nt']) - 1: continue      # all-TSO tests only
        x = to_x86(T[n]['u'])
        if x is None: continue
        p = os.path.join(tmp, n + '.litmus'); open(p, 'w').write(x)
        pairs.append((n, V[('tso', 'u')][n], herd((os.path.join(HLIB, 'x86tso.cat'), HLIB, p))))
    check('   tso.cat == herd x86tso.cat (x86 programs)', pairs)
    shutil.rmtree(tmp)
    print('4. compound restricted to one mode')
    A = [n for n in N if T[n]['mask'] == 0]; TT = [n for n in N if T[n]['mask'] == (1 << T[n]['nt']) - 1]
    check('   compound == arm, all-Arm tests', [(n, V[('compound', 'm')][n], V[('arm', 'm')][n]) for n in A])
    check('   compound == tso, all-TSO tests', [(n, V[('compound', 'm')][n], V[('tso', 'm')][n]) for n in TT])
    check('   compound-apple == arm-apple, all-Arm tests', [(n, V[('compound-apple', 'm')][n], V[('arm-apple', 'm')][n]) for n in A])
    check('   compound-apple == tso-apple, all-TSO tests', [(n, V[('compound-apple', 'm')][n], V[('tso-apple', 'm')][n]) for n in TT])
    print('ALL CHECKS PASS' if not bad else '%d MISMATCHES' % bad)
    sys.exit(1 if bad else 0)

if __name__ == '__main__':
    main()
