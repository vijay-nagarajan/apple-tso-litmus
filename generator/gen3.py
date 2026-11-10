#!/usr/bin/env python3
"""batch5 Design v3 (= paper method.tex Sec. "Choosing the Tests"), groups 1 and 2. Writes under v3/.

Group 1 (as v2): every table row (212) as the pivot of its canonical 2-thread shape (WW: MP P0, RR: MP P1, RW: LB P0,
  WR: SB P0), the other thread in each mode; base on other edges: Arm DMB ISH, TSO plain (WW/RR/RW) / DMB ISH (WR);
  all-base MP, LB, SB under every assignment. Controls: pivot edge plain, or for a TSO row on WW/RR/RW the same
  mechanism on an Arm thread (plain if Arm orders it); a not-ordered row needs none; base tests: one edge at a time plain.
Group 2: WRC, ISA2, RWC, IRIW; every assignment of modes to all threads; on every po-edge every combination of
  Arm: RW {addr, data}; RR {addr, ldapr.ldr}; WW {str.stlr, dmbst}; WR {stlr.ldar}
  TSO: RW {plain, ldapr.str}; RR {plain, ldr.ldapr}; WW {plain, stlr.str}; WR {dmb, stlr.ldar}
  Controls: one per (shape, assignment, edge): that edge plain and the other edges at their first menu entry; where the
  edge is TSO WW/RR/RW, the same with that thread in Arm mode (edge plain). Every group-2 test names the controls of
  its (shape, assignment), one per edge.
Outputs: v3/gsrc, v3/gherd, v3/gen_tests.tsv, v3/roles.tsv, v3/ppo_table.tsv, v3/probe/.  Usage: python3 gen3.py [-j N]
"""
import itertools, os, sys
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
import gen2
V3 = os.path.join(HERE, 'v3')
gen2.V2 = V3                     # gen2's writers/probes write under v3/
FAM, KIND, BASE = gen2.FAM, gen2.KIND, gen2.BASE
MENU = {('A','RW'): ['addr', 'data'], ('A','RR'): ['addr', 'ldapr.ldr'], ('A','WW'): ['str.stlr', 'dmbst'], ('A','WR'): ['stlr.ldar'],
        ('T','RW'): ['plain', 'ldapr.str'], ('T','RR'): ['plain', 'ldr.ldapr'], ('T','WW'): ['plain', 'stlr.str'], ('T','WR'): ['dmb', 'stlr.ldar']}
G2 = ('WRC', 'ISA2', 'RWC', 'IRIW')

def main():
    jobs = int(sys.argv[sys.argv.index('-j') + 1]) if '-j' in sys.argv else os.cpu_count()
    for d in ('gsrc', 'gherd'):
        os.makedirs(os.path.join(V3, d), exist_ok=True)
        for f in os.listdir(os.path.join(V3, d)): os.remove(os.path.join(V3, d, f))
    P = gen2.probes()
    T, R, add = gen2.T, gen2.ROLES, gen2.add
    # ---- group 1 (v2 code path, group 1 only) ----
    for mode in 'AT':
        for k in ('WW', 'RR', 'RW', 'WR'):
            fam, pos = gen2.CANON[k]
            for m in gen2.rows(mode, k):
                for ctx in 'AT':
                    modes = [ctx, ctx]; modes[pos] = mode
                    mech = gen2.base_mechs(fam, modes); mech[pos] = m
                    add(fam, modes, mech, group='1', role='pivot', entry='%s:%s:%s' % (mode, k, m), pos=pos, context='P%d=%s' % (1 - pos, ctx))
    for fam in ('MP', 'LB', 'SB'):
        for modes in itertools.product('AT', repeat=2):
            add(fam, list(modes), gen2.base_mechs(fam, modes), group='1', role='base', entry='-', pos=-1, context=''.join(modes))
    # ---- group 2 ----
    g2ctl = {}
    for fam in G2:
        th = FAM[fam][0]; n = len(th)
        E = [i for i, t in enumerate(th) if KIND(t)]
        for modes in itertools.product('AT', repeat=n):
            modes = list(modes)
            menus = [MENU[(modes[i], KIND(t))] if KIND(t) else [None] for i, t in enumerate(th)]
            first = [m[0] for m in menus]
            ctls = []
            for j in E:
                k = KIND(th[j])
                if modes[j] == 'T' and k != 'WR':
                    md = list(modes); md[j] = 'A'
                    mech = [MENU[(md[i], KIND(t))][0] if KIND(t) else None for i, t in enumerate(th)]; mech[j] = 'plain'
                else:
                    md = list(modes); mech = list(first); mech[j] = 'plain'
                ctls.append((j, md, mech))
            names = []
            for j, md, mech in ctls:
                nm = add(fam, md, mech, group='2-control', role='control-of', entry='-', pos=j, context=''.join(modes),
                         control='-', of='%s_%s' % (fam, ''.join(modes)))
                names.append(nm)
            for combo in itertools.product(*menus):
                add(fam, modes, list(combo), group='2', role='combination', entry='-', pos=-1, context=''.join(modes),
                    control=';'.join(names))
            g2ctl[(fam, ''.join(modes))] = names
    gen2.write_tests(list(T)); gen2.run_herd(list(T), jobs, P)
    table = {}
    for r in R:
        if r['group'] == '1' and r['role'] == 'pivot':
            mode, k, m = r['entry'].split(':')
            if r['context'] == 'P%d=%s' % (1 - r['pos'], mode):
                v = T[r['name']]['v']['arm' if mode == 'A' else 'tso']
                table[r['entry']] = ({'Never': 'ordered', 'Sometimes': 'not-ordered'}.get(v, 'ERR:' + v), r['name'], gen2.axiom(T[r['name']]['v']))
    # group-1 controls (v2 rule)
    new = []
    for r in list(R):
        if r['group'] != '1': continue
        t = T[r['name']]; fam = t['fam']; modes = list(t['modes']); mech = list(t['mechs']); th = FAM[fam][0]
        if r['role'] == 'pivot':
            mode, k, m = r['entry'].split(':'); i = r['pos']
            if table[r['entry']][0] != 'ordered': r['control'] = '-'; continue
            if mode == 'A' or k == 'WR':
                mm = list(mech); mm[i] = 'plain'; c = gen2.name_of(fam, modes, mm)
            else:
                md = list(modes); md[i] = 'A'; mm = list(mech)
                if table['A:%s:%s' % (k, m)][0] == 'ordered': mm[i] = 'plain'
                c = gen2.name_of(fam, md, mm)
            r['control'] = c if c in T else 'MISSING:' + c
        else:
            cs = []
            for j, tt in enumerate(th):
                kk = KIND(tt)
                if modes[j] == 'A' or kk == 'WR':
                    mm = list(mech); mm[j] = 'plain'; nm = gen2.name_of(fam, modes, mm)
                    if nm not in T: add(fam, modes, mm); new.append(nm)
                    R.append(dict(name=nm, group='1-control', role='control-of', entry='-', pos=j, context=''.join(modes),
                                  control='-', of=r['name']))
                    cs.append(nm)
                else: cs.append('none(P%d TSO %s)' % (j, kk))
            r['control'] = ';'.join(cs)
    if new: gen2.write_tests(new); gen2.run_herd(new, jobs, P)
    with open(os.path.join(V3, 'ppo_table.tsv'), 'w') as f:
        f.write('# herd7: arm.cat (A) / tso.cat (T) on the group-1 witness (other thread in the pivot mode); axiom = which axiom forbids under compound\n')
        f.write('mode\tkind\tmechanism\tentry\textension\twitness\taxiom\n')
        for e, (o, w, ax) in table.items():
            mode, k, m = e.split(':')
            f.write('\t'.join([mode, k, m, o, 'ext' if (mode == 'T' and k == 'WR' and gen2.is_ext(m)) else '-', w, ax]) + '\n')
    with open(os.path.join(V3, 'roles.tsv'), 'w') as f:
        f.write('name\tgroup\trole\tentry\tpivot\tcontext\tcontrol\tof\n')
        for r in R:
            f.write('\t'.join([r['name'], r['group'], r['role'], r['entry'], 'P%d' % r['pos'] if r['pos'] >= 0 else '-',
                               r['context'], r.get('control', '-'), r.get('of', '-')]) + '\n')
    cols = ['compound', 'compound-apple', 'arm', 'tso', 'aarch64', 'noatom', 'noorder']
    with open(os.path.join(V3, 'gen_tests.tsv'), 'w') as f:
        f.write('name\tfamily\tnthreads\tmask\tmodes\tmechanisms\t' + '\t'.join(cols) + '\taxiom\n')
        for nm, t in T.items():
            f.write('\t'.join([nm, t['fam'], str(t['n']), str(t['mask']), t['modes'], '-'.join(x or 'o' for x in t['mechs'])] +
                              [t['v'].get(c, '-') for c in cols] + [gen2.axiom(t['v'])]) + '\n')
    ncomb = sum(1 for r in R if r['role'] == 'combination')
    print(len(T), 'generated tests;', len(table), 'rows;', ncomb, 'group-2 combinations;',
          len({r['name'] for r in R if r['group'] == '2-control'}), 'group-2 control tests;',
          'herd errors', [n for n, t in T.items() if 'ERR' in t['v'].values()][:5])

if __name__ == '__main__':
    main()
