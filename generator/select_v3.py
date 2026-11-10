#!/usr/bin/env python3
"""batch5 Design v3: group 3 (same-address; RMW), additional.tsv, merged list, reuse, run lists, estimate. After gen3.py.
Group 3: MANIFEST families n6, n7, n7fwd, fwd (same-address); Df, Dr, Dw, batch4/failsc, and the SB/LB batch4 tests
with an RMW on both threads (RMW). Everything else of batch4 that groups 1-3 do not contain goes to additional.tsv.
Section = mode class: 5 all Arm, 6 all TSO, 7 mixed.
"""
import glob, os, re, shutil, statistics, subprocess, sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import norm, select_v2 as s2, select_reuse as s1

V3 = os.path.join(HERE, 'v3')
B4, ART, MODELS, CELLS = s2.B4, s2.ART, s2.MODELS, s2.CELLS
section = lambda modes: '5' if set(modes) == {'A'} else '6' if set(modes) == {'T'} else '7'

def main():
    man = {r['name']: r for r in s2.tsv(os.path.join(ART, 'MANIFEST.tsv'))}
    G = {r['name']: r for r in s2.tsv(os.path.join(V3, 'gen_tests.tsv'))}
    R = s2.tsv(os.path.join(V3, 'roles.tsv'))
    gkey = {n: norm.key(os.path.join(V3, 'gsrc', n + '.litmus'), int(r['mask'])) for n, r in G.items()}
    K = {k: n for n, k in gkey.items()}
    v2add = {r['name']: r for r in s2.tsv(os.path.join(HERE, 'v2', 'additional.tsv'))}
    v2g3 = {r['name']: r for r in s2.tsv(os.path.join(HERE, 'v2', 'group3.tsv'))}
    art = lambda d, n: os.path.join(ART, d, n + '.litmus')
    g3 = {}
    def put(name, reason, src, typed, mask, n):
        if name in g3: return
        k = norm.key(typed, mask)
        g3[name] = dict(name=name, reason=reason, src=src, typed=typed, mask=mask, n=n, key=k, same_as=K.get(k, '-'))
    for name, r in sorted(man.items()):
        a = (art('src', name), art('typed', name), int(r['mask']), int(r['nthreads']))
        if r['family'] in ('n6', 'n7', 'n7fwd', 'fwd'): put(name, 'same-address', *a)
        elif r['family'] in ('Df', 'Dr', 'Dw'): put(name, 'RMW', *a)
        elif name in v2add and '(two or more RMW threads)' in v2add[name]['category']: put(name, 'RMW (RMW on both threads of SB/LB)', *a)
    for name, m in sorted(s2.masks_of(os.path.join(B4, 'failsc', 'modes.tsv')).items()):
        put(name, 'RMW (failsc)', os.path.join(B4, 'failsc', 'src', name + '.litmus'), os.path.join(B4, 'failsc', 'typed', name + '.litmus'), m, 2)
    for t in g3.values():
        t['run_name'] = t['same_as'] if t['same_as'] != '-' else (t['name'] + '_b4' if t['name'] in G else t['name'])
    ukeys = set(K) | {t['key'] for t in g3.values()}
    found, dur, bad = s2.load_results(man)
    six = lambda m, k: sum(1 for c in CELLS if c in found[m].get(k, {}))
    add = []
    b4 = [(n, r['set'], r['family'], int(r['mask']), art('typed', n)) for n, r in man.items()]
    b4 += [(n, 'failsc', 'SB', m, os.path.join(B4, 'failsc', 'typed', n + '.litmus')) for n, m in s2.masks_of(os.path.join(B4, 'failsc', 'modes.tsv')).items()]
    for n, st, fam, mask, p in sorted(b4):
        k = norm.key(p, mask)
        if k in ukeys: continue
        if n in v2add: cat = v2add[n]['category']
        elif n in v2g3: cat = 'v2 group 3: ' + v2g3[n]['reason']
        else: cat = 'v2 generated (groups 1-2), not a v3 test'
        add.append((n, st, fam, cat, six('m1', k), six('m2', k)))
    with open(os.path.join(V3, 'additional.tsv'), 'w') as f:
        f.write('name\tset\tfamily\tcategory\tm1_cells_of_6\tm2_cells_of_6\tall_six_on\n')
        for a in add:
            f.write('\t'.join(map(str, a)) + '\t%s\n' % ('+'.join(m for m, c in (('M1', a[4]), ('M2', a[5])) if c == 6) or 'neither'))
    # ---- merged universe ----
    for d in ('src', 'herd'):
        os.makedirs(os.path.join(V3, d), exist_ok=True)
        for f in glob.glob(os.path.join(V3, d, '*.litmus')): os.remove(f)
    U = {}
    for n, r in G.items():
        U[n] = dict(n=int(r['nthreads']), mask=int(r['mask']), modes=r['modes'], family=r['family'], key=gkey[n], origin='generated', v=r)
        shutil.copyfile(os.path.join(V3, 'gsrc', n + '.litmus'), os.path.join(V3, 'src', n + '.litmus'))
        shutil.copyfile(os.path.join(V3, 'gherd', n + '.litmus'), os.path.join(V3, 'herd', n + '.litmus'))
    for t in g3.values():
        if t['same_as'] != '-': continue
        n = t['run_name']; L = open(t['src']).read().split('\n'); L[0] = re.sub(r'^(AArch64\s+)\S+', lambda m: m.group(1) + n, L[0])
        open(os.path.join(V3, 'src', n + '.litmus'), 'w').write('\n'.join(L))
        s1.add_isb(os.path.join(V3, 'src', n + '.litmus'), os.path.join(V3, 'herd', n + '.litmus'), t['mask'])
        U[n] = dict(n=t['n'], mask=t['mask'], modes=''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n'])),
                    family=t['name'].split('_')[0], key=t['key'], origin='batch4', v={}, g3=t)
    work = [(n, m) for n, u in U.items() if u['origin'] != 'generated' for m in ('compound', 'compound-apple', 'aarch64')]
    work += [(n, 'arm') for n, u in U.items() if u['origin'] != 'generated' and set(u['modes']) == {'A'}]
    work += [(n, 'tso') for n, u in U.items() if u['origin'] != 'generated' and set(u['modes']) == {'T'}]
    path = lambda n, m: os.path.join(V3, 'src' if m in ('aarch64', 'arm') else 'herd', n + '.litmus')
    with ThreadPoolExecutor(os.cpu_count()) as ex:
        res = list(ex.map(lambda w: s2.herd(w[1] if w[1] == 'aarch64' else os.path.join(MODELS, w[1] + '.cat'), path(*w)), work))
    for (n, m), v in zip(work, res): U[n]['v'][m] = v
    roles = defaultdict(list)
    for r in R: roles[r['name']].append(r)
    for t in g3.values():
        roles[t['run_name']].append(dict(group='3', role='hand-written', entry=t['reason'], pivot='-',
                                         context=''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n'])), control='-'))
    with open(os.path.join(V3, 'group3.tsv'), 'w') as f:
        f.write('name\trun_name\treason\tmask\tsame_program_as_generated\tsection\n')
        for t in g3.values():
            f.write('\t'.join([t['name'], t['run_name'], t['reason'], str(t['mask']), t['same_as'],
                               section(''.join('T' if t['mask'] >> i & 1 else 'A' for i in range(t['n'])))]) + '\n')
    cols = ['compound', 'compound-apple', 'arm', 'tso', 'aarch64']
    with open(os.path.join(V3, 'list.tsv'), 'w') as f:
        f.write('name\tfamily\tnthreads\tmask\tmodes\tgroup\tentry_or_reason\tpivot\tcontext\tsection\tcontrol\t' + '\t'.join(cols) + '\taxiom\torigin\n')
        for n, u in U.items():
            rs = roles[n]
            f.write('\t'.join([n, u['family'], str(u['n']), str(u['mask']), u['modes'],
                               ';'.join(sorted({r['group'] for r in rs})),
                               ';'.join(r['entry'] if r['entry'] != '-' else r['role'] for r in rs),
                               ';'.join(r['pivot'] for r in rs), ';'.join(r['context'] for r in rs), section(u['modes']),
                               ';'.join(r['control'] for r in rs if r['control'] not in ('-', '')) or '-'] +
                              [u['v'].get(c, '-') for c in cols] + [u['v'].get('axiom', '-'), u['origin']]) + '\n')
    shutil.rmtree(os.path.join(V3, 'typed'), ignore_errors=True); os.makedirs(os.path.join(V3, 'typed'))
    for n, u in U.items():
        if u['origin'] == 'batch4':
            L = open(u['g3']['typed']).read().split('\n'); L[0] = re.sub(r'^(AArch64\s+)\S+', lambda m: m.group(1) + n, L[0])
            open(os.path.join(V3, 'typed', n + '.litmus'), 'w').write('\n'.join(L))
        else:
            subprocess.run(['python3', '-I', os.path.join(B4, 'typer.py'), os.path.join(V3, 'src', n + '.litmus'),
                            os.path.join(V3, 'typed', n + '.litmus')], check=True)
        assert norm.key(os.path.join(V3, 'typed', n + '.litmus'), u['mask']) == u['key'], n
    with open(os.path.join(V3, 'modes_all.tsv'), 'w') as f:
        f.write('name\tmask\tmodes\texpected\n'); [f.write('%s\t%d\t%s\t-\n' % (n, u['mask'], u['modes'])) for n, u in U.items()]
    with open(os.path.join(V3, 'hooklist.txt'), 'w') as f:
        f.write('# name\trole\tmask\tnthreads\n'); [f.write('%s\ttest\t%d\t%d\n' % (n, u['mask'], u['n'])) for n, u in U.items()]
    with open(os.path.join(V3, 'runlist_all.txt'), 'w') as f: [f.write('%s %d\n' % (n, u['n'])) for n, u in U.items()]
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
        with open(os.path.join(V3, 'reuse_%s.tsv' % mach), 'w') as f:
            f.write('name\torigin\tstatus\tcells_found_of_6\tfrom\tmin_cell_iterations\thits_6cells\tcounted_iterations_6cells\n')
            for r in rows: f.write('\t'.join(map(str, r)) + '\n')
        with open(os.path.join(V3, 'runlist_%s.txt' % mach), 'w') as f: [f.write('%s %d\n' % (n, U[n]['n'])) for n in torun]
        tot = defaultdict(float)
        for n in torun:
            u = U[n]
            for h, c in CELLS:
                xs = dur[mach].get((u['family'], u['n'], c, h)) or dur[mach][('*', u['n'], c, h)]
                s = statistics.median(xs); tot['all'] += s; tot['%dT' % u['n']] += s
                tot['group ' + ('3' if u['origin'] == 'batch4' else ('2' if any(r['group'].startswith('2') for r in roles[n]) else '1'))] += s
        summ[mach] = dict(reusable=sum(r[2] == 'reusable' for r in rows), torun=len(torun),
                          torun_by_origin={o: sum(1 for n in torun if U[n]['origin'] == o) for o in ('generated', 'batch4')},
                          hours={k: round(v / 3600, 1) for k, v in sorted(tot.items())})
    with open(os.path.join(V3, 'estimate.tsv'), 'w') as f:
        f.write('# basis: median duration of existing mult-10 cells of the same family, nthreads, harness, cell on that machine (else nthreads)\n')
        f.write('machine\treusable\tto_run\tto_run_generated\tto_run_group3\thours_total\thours_by_part\n')
        for m, s in summ.items():
            f.write('%s\t%d\t%d\t%d\t%d\t%s\t%s\n' % (m, s['reusable'], s['torun'], s['torun_by_origin']['generated'],
                                                    s['torun_by_origin']['batch4'], s['hours']['all'], s['hours']))
    print('universe', len(U), '| generated', len(G), '| group3', len(g3), 'same as generated', sum(t['same_as'] != '-' for t in g3.values()))
    print('group3 reasons', {k: sum(1 for t in g3.values() if t['reason'] == k) for k in sorted({t['reason'] for t in g3.values()})})
    print('additional', len(add), 'result problems', len(bad)); print(summ)

if __name__ == '__main__':
    main()
