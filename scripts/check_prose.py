#!/usr/bin/env python3
"""The counts quoted in the text of Sections 1 to 7 (the quoted numbers of Sec 8 are checked by scale_table.py).
   python3 check_prose.py   -> one PASS/FAIL line per claim; exit 1 on a FAIL.
Each claim is a phrase of the report with its numbers computed from the data (tests/*.tsv, results/cells.tsv, the add-on
rows); a claim passes when the phrase so computed occurs in expected/sections/<file> (whitespace normalised).
Order-of-magnitude summaries of table cells ("10^5 to 10^7 times") are not checked here: the cells themselves are
checked by the table diff, the summary wording is not."""
import csv, collections, math, os, re, sys
HERE = os.path.dirname(os.path.abspath(__file__)); A = os.path.join(HERE, '..')
SEC = os.path.join(A, 'expected', 'sections')
L = {r['name']: r for r in csv.DictReader(open(os.path.join(A, 'tests', 'list.tsv')), delimiter='\t')}
AD = {r['name']: r for r in csv.DictReader(open(os.path.join(A, 'tests', 'addon.tsv')), delimiter='\t')}
H = collections.defaultdict(int); NC = collections.Counter(); IT = collections.defaultdict(int)
for r in csv.DictReader(open(os.path.join(A, 'results', 'cells.tsv')), delimiter='\t'):
    H[(r['name'], r['machine'])] += int(r['hits']); NC[(r['name'], r['machine'])] += 1; IT[(r['name'], r['machine'])] += int(r['iterations'])
def addon(d, keep=lambda f: True):   # add-on rows: a test's six multiplier-10 cells on a machine
    for m in ('m1', 'm2'):
        rows = [l.rstrip('\n').split('\t') for l in open(os.path.join(A, 'results', d, 'results_%s.tsv' % m)) if l.strip()]
        for f in rows:
            if f[3] == '10' and keep(f): H[(f[1], m)] += int(f[4]); NC[(f[1], m)] += 1; IT[(f[1], m)] += int(f[5])
for d in ('addon_swpal', 'addon_fwdtso', 'addon_casfail', 'addon_mpreader'): addon(d)
ALL = dict(L); ALL.update(AD)
seen = lambda n: H[(n, 'm1')] + H[(n, 'm2')] > 0
both = lambda n: H[(n, 'm1')] > 0 and H[(n, 'm2')] > 0
mag = lambda x: 0 if x == 0 else int(math.log10(x))
mixed = lambda r: len(set(r['modes'])) > 1
def _plain(t):   # drop the review markup \newtext{..} / \rev{..} (keep the text), so claims match the words
    while True:
        m = re.search(r'\\(?:newtext|rev)\{', t)
        if not m: return t
        i, d = m.end(), 1
        while d:
            d += {'{': 1, '}': -1}.get(t[i], 0); i += 1
        t = t[:m.start()] + t[m.end():i - 1] + t[i:]
# The report's text is optional: with expected/sections/ present each phrase must occur in it (PASS/FAIL); without it
# each phrase rebuilt from the data is printed (PHRASE) for comparison with the published report, and only the
# data-side condition of the claim is checked.
TEXT = {f: re.sub(r'\s+', ' ', _plain(open(os.path.join(SEC, f)).read())) for f in os.listdir(SEC) if f.endswith('.tex')} if os.path.isdir(SEC) else None
NF = [0]; OUT = []
def claim(f, phrase, ok=True, note=''):
    hit = True if TEXT is None else re.sub(r'\s+', ' ', phrase) in TEXT[f]
    st = ('PASS' if hit and ok else 'FAIL') if TEXT is not None else ('PHRASE' if ok else 'FAIL')
    if st == 'FAIL': NF[0] += 1
    OUT.append('%s %s: "%s"%s%s' % (st, f, phrase, '' if hit else '  [phrase not in text]', '' if ok else '  [data check failed: %s]' % note))

# the suite
gen = [n for n, r in L.items() if r['origin'] == 'generated']; hand = [n for n, r in L.items() if r['origin'] == 'batch4'] + list(AD)
claim('abstract.tex', 'with %d litmus tests' % len(ALL))
claim('method.tex', 'In all there are %d tests, %d generated and %d written by hand' % (len(ALL), len(gen), len(hand)))
claim('intro.tex', 'run %d litmus tests' % len(ALL))
claim('artifacts.tex', 'The artifact contains the %d litmus tests' % len(ALL))
six = all(NC[(n, m)] == 6 for n in ALL for m in ('m1', 'm2'))
claim('method.tex', 'so every test runs $6\\times10^8$ times on each machine', six, 'a test without six cells')
nA = [n for n, r in ALL.items() if set(r['modes']) == {'A'}]; nT = [n for n, r in ALL.items() if set(r['modes']) == {'T'}]
nx86 = len([l for l in open(os.path.join(A, 'tests', 'x86', 'list.txt')) if l.strip()])
claim('compose.tex', 'On all %d tests whose threads all run in Arm mode' % len(nA))
claim('compose.tex', 'The %d tests whose threads all run in TSO mode' % nx86)
claim('artifacts.tex', 'the %d x86 programs' % nx86)
claim('results-arm.tex', 'in any of the %d tests whose threads all run in Arm mode' % len(nA),
      not any(seen(n) for n in nA if ALL[n]['arm'] == 'Never'), 'an Arm-forbidden all-Arm outcome seen')
claim('results-tso.tex', 'in any of the %d tests whose threads all run in TSO mode' % len(nT),
      not any(seen(n) for n in nT if ALL[n]['tso'] == 'Never'), 'a TSO-forbidden all-TSO outcome seen')
# preserved program order rows
P = [l.rstrip('\n').split('\t') for l in open(os.path.join(A, 'tests', 'ppo_table.tsv')) if l.strip() and not l.startswith('#')][1:]
pA = [p for p in P if p[0] == 'A']; pT = [p for p in P if p[0] == 'T']
rmwtok = ('swp', 'cas', 'ldadd', 'ldxr', 'ldaxr', 'llsc')
pTr = [p for p in pT if any(t in p[2] for t in rmwtok)]
claim('method.tex', 'The same %d mechanisms appear in each mode, %d rows in all' % (len(pA), len(pA) + len(pT) - len(pTr)), len(pA) == len(pT) - len(pTr))
claim('method.tex', 'with an exclusive or AMO access is tested, %d pairs' % len(pTr))
claim('results-tso.tex', 'None of these %d rows was observed' % len([p for p in pT if p[1] in ('WW', 'RR', 'RW')]),
      not any(seen(p[5]) for p in pT if p[1] in ('WW', 'RR', 'RW')), 'a TSO ww/rr/rw row seen')
# mixed programs (Sec 7)
M = {n: r for n, r in ALL.items() if mixed(r)}
cN = [n for n, r in M.items() if r['compound'] == 'Never']; aN = [n for n, r in M.items() if r['compound-apple'] == 'Never']
claim('results-compound.tex', 'We ran %d tests that mix Arm and TSO threads. The compound model forbids the outcome of %d of them, and the model of the machines, which adds A1--A3, forbids %d. Neither machine showed any of these %d.'
      % (len(M), len(cN), len(aN), len(aN)), not any(seen(n) for n in aN))
# partner comparisons (as make_tables.py)
rowtests = collections.defaultdict(dict)
for n, r in L.items():
    if r['group'].startswith('1'):
        for e in r['entry_or_reason'].split(';'):
            if e[:2] in ('A:', 'T:'): rowtests[e][r['modes']] = n
same = diff = 0; per = collections.Counter(); dl = []
for e, d in rowtests.items():
    own = 'AA' if e[0] == 'A' else 'TT'
    if own not in d: continue
    for md, n in d.items():
        if md == own: continue
        for m in ('m1', 'm2'):
            per[m] += 1
            if (H[(d[own], m)] > 0) == (H[(n, m)] > 0): same += 1
            else: diff += 1; dl.append((d[own], n, m))
claim('results-compound.tex', 'They agree in %d of the %d pairs of runs, %d on each machine' % (same, same + diff, per['m1']), per['m1'] == per['m2'])
claim('results-compound.tex', 'never reordered with an Arm-mode reader, and reordered %d times in $6\\times10^8$ with a TSO-mode reader' % H[('MP_AT_plain-plain', 'm2')],
      dl == [('MP_AA_plain-dmb', 'MP_AT_plain-plain', 'm2')] and H[('MP_AA_plain-dmb', 'm2')] == 0)
claim('results-compound.tex', 'A second run of the Arm-mode test showed the outcome %d times' % H[('MPr_AA_plain-dmb', 'm2')], NC[('MPr_AA_plain-dmb', 'm2')] == 6)
claim('method.tex', 'appeared %d times in one run on the M1 and %d in another' % (H[('MP_AA_plain-dmb', 'm1')], H[('MPr_AA_plain-dmb', 'm1')]), NC[('MPr_AA_plain-dmb', 'm1')] == 6)
# one address, mixed modes
SA = [n for n, r in M.items() if r['family'] in ('n6', 'n7') or r['family'].startswith('fwd')]
fS = [n for n in SA if M[n]['compound-apple'] == 'Never']; aS = [n for n in SA if M[n]['compound-apple'] == 'Sometimes']
claim('results-compound.tex', 'We also ran the same tests with Arm observers: %d tests' % len(SA))
claim('results-compound.tex', 'The model of the machines forbids %d of them, and neither machine showed any. Of the %d it allows, %d appeared on both machines.'
      % (len(fS), len(aS), len([n for n in aS if both(n)])), not any(seen(n) for n in fS))
# RMWs, mixed modes
WR = [n for n, r in M.items() if r['group'].startswith('1') and any(e.startswith('T:WR:') and any(t in e for t in rmwtok) for e in r['entry_or_reason'].split(';'))]
wN = [n for n in WR if M[n]['compound'] == 'Never']; wS = [n for n in WR if M[n]['compound'] == 'Sometimes']
ms = sorted({mag(H[(n, m)]) for n in wS for m in ('m1', 'm2')})
claim('results-compound.tex', 'with the RMW on a TSO thread and an Arm partner, %d tests. The compound model forbids %d of the outcomes, and neither machine showed any; the five it allows, an LL/SC pair followed by a load, appeared on both machines, $10^%d$ to $10^%d$ times'
      % (len(WR), len(wN), ms[0], ms[-1]), not any(seen(n) for n in wN) and len(wS) == 5 and all(both(n) for n in wS))
DK = [n for n, r in M.items() if r['family'] in ('Df', 'Dw', 'Dr')]
dN = [n for n in DK if M[n]['compound'] == 'Never']
claim('results-compound.tex', 'In the %d hand-written Dekker tests, an RMW on an Arm thread meets an RMW on a TSO thread. The compound model forbids one of their outcomes, and it was not observed' % len(DK), len(dN) == 1 and not any(seen(n) for n in dN))
A13 = [n for n, r in M.items() if r['compound'] == 'Sometimes' and r['compound-apple'] == 'Never']
claim('results-compound.tex', 'In %d mixed tests, an order added on one thread closes a cycle' % len(A13))
claim('results-compound.tex', 'None of the %d was observed' % len(A13), not any(seen(n) for n in A13))
# the release store-exclusive (Sec 6)
stx = ['fwd10_stxr-ldr-addr_TTT', 'fwd11_stxr-ldr_TTT']
claim('results-tso.tex', 'The M2 shows the outcome, %d times in $6\\times10^8$ iterations, more often than after \\ins{STXR}' % H[('fwd12_stlxr-ldr_TTT', 'm2')],
      H[('fwd12_stlxr-ldr_TTT', 'm1')] == 0 and all(H[(n, 'm2')] < H[('fwd12_stlxr-ldr_TTT', 'm2')] for n in stx) and all(mag(H[(n, 'm1')]) == 1 for n in stx),
      'M1 STLXR %d, M1 STXR %s, M2 STXR %s' % (H[('fwd12_stlxr-ldr_TTT', 'm1')], [H[(n, 'm1')] for n in stx], [H[(n, 'm2')] for n in stx]))
# a failing CAS (Sec 5.3)
c3 = ['Df_AA_casfail-casfail', 'Df_AA_casafail-casafail', 'Df_AA_caslfail-caslfail']
m1 = sorted({mag(H[(n, 'm1')]) for n in c3}); m2 = sorted({mag(H[(n, 'm2')]) for n in c3})
claim('results-arm.tex', 'shows it $10^%d$ to $10^%d$ times on the M1 and $10^{%d}$ times on the M2' % (m1[0], m1[-1], m2[0]),
      len(m2) == 1 and H[('Df_AA_casalfail-casalfail', 'm1')] == H[('Df_AA_casalfail-casalfail', 'm2')] == 0)
# the acquire AMO at 1e11 (Sec 5.3): macOS (M2 MacBook Air) and Linux (M2, unpinned)
def obs(p):
    for l in open(p):
        if l.startswith('Observation'): f = l.split(); return int(f[3]), int(f[3]) + int(f[4])
mac = [obs(os.path.join(A, 'results', 'addon_scale', 'macos_m2', 'swpa_st%d.log' % s)) for s in (1, 3, 5, 7)]
big = [l.split('\t') for l in open(os.path.join(A, 'results', 'addon_scale', 'linux_m2', 'swpabig', 'results_swpabig_m2.tsv')) if l.strip()]
big = [(int(f[4]), int(f[5])) for f in big if f[10] == 'test']
claim('results-arm.tex', 'In $10^{11}$ iterations on the M2 with unpinned threads, it appeared %d times under macOS and %d times under Linux'
      % (sum(h for h, _ in mac), sum(h for h, _ in big)), sum(i for _, i in mac) == sum(i for _, i in big) == 10 ** 11)
# intro, Fig 1(e): SB with STR;LDAR on TSO threads (the other thread DMB)
e = 'SB_TT_str.ldar-dmb'
claim('intro.tex', 'both show (e), $10^%d$ times on the M1 and $10^%d$ on the M2' % (mag(H[(e, 'm1')]), mag(H[(e, 'm2')])), L[e]['compound'] == 'Sometimes')
print('\n'.join(OUT))
print('prose: %d claims, %d FAIL' % (len(OUT), NF[0]))
sys.exit(1 if NF[0] else 0)
