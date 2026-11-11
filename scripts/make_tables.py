#!/usr/bin/env python3
"""batch5 v3: the results tables of the report (sections 5-7), from list.tsv (herd verdicts), cells.tsv (per-cell hits,
   python3 cells.py) and the add-on directories. Every cell is named by the tests behind it (ROWS below).
   python3 make_tables.py <overleaf/tables dir>   -> res-*.tex, plus a check summary on stdout
An entry is the order of magnitude of the total over 6e8 runs: 10^k means 10^k .. 10^(k+1)-1; a range spans a row's tests."""
import csv, collections, math, os, sys
HERE = os.path.dirname(os.path.abspath(__file__))
L = {r['name']: r for r in csv.DictReader(open(os.path.join(HERE, '..', 'tests', 'list.tsv')), delimiter='\t')}
H = collections.defaultdict(int); SEEN = set()
for r in csv.DictReader(open(os.path.join(HERE, '..', 'results', 'cells.tsv')), delimiter='\t'):
    H[(r['name'], r['machine'])] += int(r['hits']); SEEN.add((r['name'], r['machine']))
ADDON = {'Dw_AA_swpal-swpal': ('addon_swpal', 'Never')}          # tests outside list.tsv: (dir, aarch64 verdict)
for n, (d, v) in ADDON.items():
    for m in ('m1', 'm2'):
        p = os.path.join(HERE, '..', 'results', d, 'results_%s.tsv' % m)
        if os.path.exists(p):
            rows = [l.split('\t') for l in open(p) if l.strip()]
            if len(rows) == 6: H[(n, m)] = sum(int(x[4]) for x in rows); SEEN.add((n, m))
# add-ons with their own herd.tsv: addon_fwdtso, the fwd*_T tests with every thread in TSO mode (Sec 6 same-address rows),
# and addon_casfail, all-Arm Dekker with a failing CAS between store and load (Sec 5.3). A test counts on a machine when
# it has its six full-run cells (mult 10, 1e8 iterations each); rows of other multipliers (smoke runs) are ignored.
def load_addon(d):
    xv = {r['name']: r for r in csv.DictReader(open(os.path.join(HERE, '..', 'results', d, 'herd.tsv')), delimiter='\t')}
    for n in xv:
        for m in ('m1', 'm2'):
            p = os.path.join(HERE, '..', 'results', d, 'results_%s.tsv' % m)
            if os.path.exists(p):
                rows = [l.rstrip('\n').split('\t') for l in open(p) if l.strip()]
                rows = [x for x in rows if x[1] == n and x[3] == '10']
                if len(rows) == 6 and len({(x[0], x[2]) for x in rows}) == 6:
                    H[(n, m)] = sum(int(x[4]) for x in rows); SEEN.add((n, m))
    return xv
XV = load_addon('addon_fwdtso')
XC = load_addon('addon_casfail')
def V(t, col): return ADDON[t][1] if t in ADDON else XV[t][col] if t in XV else XC[t][col] if t in XC else L[t][col]
CHECK = []
def mag1(x):
    if x == 0: return '0'
    return '$10^{%d}$' % int(math.log10(x))          # every nonzero entry as 10^k, 10^0 and 10^1 included
# A cell's status (macros in the paper's macros.tex): \fz forbidden and 0; \sn{..} allowed and seen;
# \st{A1} allowed by the rule, 0, forbidden by A1-A3 (machine stronger); \ux allowed and 0, unexplained; \vi{..} forbidden and seen.
def mag(tests, m, note='', forb=False, plain=False):
    for t in tests:
        if (t, m) not in SEEN: return '\\tbd{to run}'
    v = sorted({(0 if H[(t, m)] == 0 else int(math.log10(H[(t, m)])) + 1) for t in tests})
    lab = lambda k: '0' if k == 0 else mag1(10 ** (k - 1))
    s = lab(v[0]) if len(v) == 1 else '%s--%s' % (lab(v[0]), lab(v[-1]))
    if plain: return s + (' (%s)' % note if note and v == [0] else '')
    if forb: return '\\rfz' if v == [0] else '\\rvi{%s}' % s
    if v == [0]: return '\\rst{%s}' % note if note else '\\rux'
    return '\\rsn{%s}' % s
def verdict(tests, col):
    vs = {V(t, col) for t in tests}
    assert len(vs) == 1, (tests, col, vs)
    return {'Never': 'ordered', 'Sometimes': 'not ordered'}[vs.pop()]
def expect(tests, col, want):   # assert herd verdicts, record
    for t in tests:
        v = V(t, col)
        assert v == want, (t, col, v, want)
    CHECK.append((tests, col, want))

def modewords(t):   # mode names in control labels take their mode's color
    return t.replace('Arm-mode', '\\armw{Arm}-mode').replace('TSO partner', '\\tsow{TSO} partner')
def ppo_table(fn, col, rows, caption, label):
    out = ['\\begin{table}[!htbp]', '\\centering', '\\footnotesize', '\\setlength{\\tabcolsep}{3pt}',
           '\\begin{tabularx}{\\linewidth}{@{}>{\\raggedright\\arraybackslash}p{0.11\\linewidth}>{\\raggedright\\arraybackslash}Xllll>{\\raggedright\\arraybackslash}p{0.24\\linewidth}@{}}', '\\toprule',
           'Pair & Mechanism & Shape & %s & M1 & M2 & Control: M1 / M2\\\\' % ('\\armw{Arm}' if col == 'arm' else '\\tsow{TSO}'), '\\midrule']
    prev = None
    for pair, mech, shape, tests, note, ctl in rows:
        if prev is not None and pair != prev: out.append('\\addlinespace')
        v = verdict(tests, col)
        c = ''
        if ctl:
            c = '; '.join('%s: %s / %s' % (modewords(lab), mag(ts, 'm1', nt), mag(ts, 'm2', nt)) for lab, ts, nt in ctl)
        f = v == 'ordered'
        out.append('%s & %s & %s & %s & %s & %s & %s\\\\' % (pair if pair != prev else '', mech, shape, v,
                   mag(tests, 'm1', note, f), mag(tests, 'm2', note, f), c))
        prev = pair
    out += ['\\bottomrule', '\\end{tabularx}', '\\caption{%s}' % caption, '\\label{%s}' % label, '\\end{table}']
    open(fn, 'w').write('\n'.join(out) + '\n')

def multi_table(fn, scope, caption, label):
    out = ['\\begin{table}[!htbp]', '\\centering', '\\small', '\\begin{tabular}{@{}lrrrll@{}}', '\\toprule',
           '& \\multicolumn{2}{c}{Forbidden} & \\multicolumn{3}{c}{Allowed controls}\\\\',
           '\\cmidrule(lr){2-3}\\cmidrule(lr){4-6}', 'Shape & tests & seen & tests & M1 & M2\\\\', '\\midrule']
    summ = {}
    for fam in ('RWC', 'IRIW', 'WRC', 'ISA2'):
        ts = [n for n, r in L.items() if r['family'] == fam and r['group'].startswith('2') and scope(r['modes'])]
        fb = [n for n in ts if L[n]['compound-apple'] == 'Never']
        seen = sum(1 for n in fb if H[(n, 'm1')] + H[(n, 'm2')] > 0)
        ctl = list(dict.fromkeys(c for n in fb for c in L[n]['control'].split(';')
                                 if c and c != '-' and c in L and L[c]['compound-apple'] == 'Sometimes'))
        sc = '\\rfz' if seen == 0 else '\\rvi{%d}' % seen
        out.append('%s & %d & %s & %d & %s & %s\\\\' % (fam, len(fb), sc, len(ctl), mag(ctl, 'm1'), mag(ctl, 'm2')))
        summ[fam] = (len(fb), seen, ctl)
    out += ['\\bottomrule', '\\end{tabular}', '\\caption{%s}' % caption, '\\label{%s}' % label, '\\end{table}']
    open(fn, 'w').write('\n'.join(out) + '\n')
    return summ

A = lambda *s: ['MP_AA_' + x if x[0] != '!' else x[1:] for x in s]
def run(D):
    I = lambda s: '\\ins{%s}' % s
    # ---------------- Table: Arm ppo ----------------
    WWo = ['MP_AA_%s-dmb' % m for m in ('str.stlr', 'stlr.stlr', 'dmb', 'dmbst', 'dsb', 'dsbst')]
    RRo = ['MP_AA_dmb-%s' % m for m in ('ldapr.ldr', 'ldapr.ldapr', 'ldapr.ldar', 'ldar.ldr', 'ldar.ldapr', 'ldar.ldar',
                                        'dmb', 'dmbld', 'dsb', 'dsbld', 'addr', 'ctrlisb')]
    RWo = ['LB_AA_%s-dmb' % m for m in ('ldr.stlr', 'ldapr.str', 'ldapr.stlr', 'ldar.str', 'ldar.stlr', 'dmb', 'dmbld',
                                        'dsb', 'dsbld', 'addr', 'data', 'ctrl', 'ctrlisb')]
    WRo = ['SB_AA_%s-dmb' % m for m in ('stlr.ldar', 'dmb', 'dsb', 'dsbst')]
    ctlWW = [('plain', ['MP_AA_plain-dmb'], ''), ('TSO partner', ['MP_AT_plain-plain'], '')]
    rows = [
      ('store $\\to$ store', 'STR;STLR, STLR;STLR, DMB, DMB ST, DSB, DSB ST (6)'.replace('STLR', I('STLR')) and
       '%s;%s, %s;%s, %s, %s, %s, %s (6)' % (I('STR'), I('STLR'), I('STLR'), I('STLR'), I('DMB'), I('DMB ST'), I('DSB'), I('DSB ST')),
       'MP', WWo, '', ctlWW),
      ('store $\\to$ store', 'plain', 'MP', ['MP_AA_plain-dmb'], '', None),
      ('store $\\to$ store', '%s;%s' % (I('STLR'), I('STR')), 'MP', ['MP_AA_stlr.str-dmb'], '', None),
      ('store $\\to$ store', '%s, %s' % (I('DMB LD'), I('DSB LD')), 'MP', ['MP_AA_dmbld-dmb', 'MP_AA_dsbld-dmb'], 'A2', None),
      ('load $\\to$ load', 'acquire first, %s, %s, %s, %s, address, control and %s (12)' % (I('DMB'), I('DMB LD'), I('DSB'), I('DSB LD'), I('ISB')),
       'MP', RRo, '', [('plain', ['MP_AA_dmb-plain'], '')]),
      ('load $\\to$ load', 'plain; %s;%s; %s;%s; %s' % (I('LDR'), I('LDAPR'), I('LDR'), I('LDAR'), I('DMB ST')), 'MP',
       ['MP_AA_dmb-plain', 'MP_AA_dmb-ldr.ldapr', 'MP_AA_dmb-ldr.ldar', 'MP_AA_dmb-dmbst'], '', None),
      ('load $\\to$ load', 'control', 'MP', ['MP_AA_dmb-ctrl'], '', None),
      ('load $\\to$ load', I('DSB ST'), 'MP', ['MP_AA_dmb-dsbst'], '', None),
      ('load $\\to$ store', 'release or acquire, %s, %s, %s, %s, dependencies (13)' % (I('DMB'), I('DMB LD'), I('DSB'), I('DSB LD')),
       'LB', RWo, '', [('plain', ['LB_AA_plain-dmb'], 'A3')]),
      ('load $\\to$ store', 'plain, %s, %s' % (I('DMB ST'), I('DSB ST')), 'LB', ['LB_AA_plain-dmb', 'LB_AA_dmbst-dmb', 'LB_AA_dsbst-dmb'], 'A3', None),
      ('store $\\to$ load', '%s;%s, %s, %s, %s (4)' % (I('STLR'), I('LDAR'), I('DMB'), I('DSB'), I('DSB ST')), 'SB', WRo, '',
       [('plain', ['SB_AA_plain-dmb'], '')]),
      ('store $\\to$ load', 'plain; %s;%s; %s;%s; %s' % (I('STR'), I('LDAPR'), I('STR'), I('LDAR'), I('DMB ST')), 'SB',
       ['SB_AA_plain-dmb', 'SB_AA_str.ldapr-dmb', 'SB_AA_str.ldar-dmb', 'SB_AA_dmbst-dmb'], '', None),
      ('store $\\to$ load', '%s;%s; %s;%s' % (I('STLR'), I('LDR'), I('STLR'), I('LDAPR')), 'SB', ['SB_AA_stlr.ldr-dmb', 'SB_AA_stlr.ldapr-dmb'], '', None),
      ('store $\\to$ load', '%s, %s' % (I('DMB LD'), I('DSB LD')), 'SB', ['SB_AA_dmbld-dmb', 'SB_AA_dsbld-dmb'], 'A2', None),
      ('same address', '%s;%s' % (I('STLR'), I('LDAR')), 'n7', ['fwd5_stlr-ldar'], '', [('%s;%s' % (I('STLR'), I('LDR')), ['fwd8_stlr-ldr-addr'], '')]),
      ('same address', '%s;%s' % (I('STR'), I('LDR')), 'n7', ['fwd7_str-ldr-addr'], '', None),
      ('same address', '%s;%s' % (I('STLR'), I('LDR')), 'n7', ['fwd8_stlr-ldr-addr'], '', None),
      ('same address', '%s;%s' % (I('STXR'), I('LDR')), 'n7', ['fwd10_stxr-ldr-addr', 'fwd11_stxr-ldr'], '', None),
      ('same address', '%s, %s or %s, then %s or %s' % (I('STR'), I('STLR'), I('STXR'), I('LDAPR'), I('LDAR')), 'n7',
       ['fwd3_str-ldapr', 'fwd6_str-ldar', 'fwd4_stlr-ldapr', 'fwd9_stxr-ldar'], 'A1', None),
    ]
    rows[0] = ('store $\\to$ store', '%s;%s, %s;%s, %s, %s, %s, %s (6)' % (I('STR'), I('STLR'), I('STLR'), I('STLR'), I('DMB'), I('DMB ST'), I('DSB'), I('DSB ST')),
               'MP', WWo, '', ctlWW)
    for p, me, sh, ts, nt, c in rows:
        for t in ts: assert L[t]['modes'] in ('AA', 'AAA'), t
    ppo_table(os.path.join(D, 'res-arm-ppo.tex'), 'arm', rows,
        'The Arm rows of preserved program order on the two machines, every thread in Arm mode, $6\\times10^8$ iterations '
        'of each test on each machine. An entry is the order of magnitude of the number of times the outcome appeared '
        '($10^k$: from $10^k$ to $10^{k+1}-1$; a range spans the row\'s tests). An ordered row\'s control is the same test with '
        'the pair left plain; on the M2, the store $\\to$ store control is the same test with a TSO-mode partner, since in these runs it appeared only with that partner (\\cref{sec:compound-partner}). '
        'Shading: \\rfz\\ and \\rsn{$10^{4}$}, the machines agree with the model (forbidden and never seen, allowed and seen); '
        '\\rst{A2}, allowed by the model but never seen, and forbidden by A2 (\\cref{sec:models-apple}): the machines are stronger; '
        '\\rux, allowed but never seen, and no order of the machines forbids it. No forbidden outcome was seen. '
        'The n7 tests~\\cite{x86tso-tphols} order Thread~0\'s last two loads by an acquire or an address dependency, so that on Arm '
        'only a read-back of the store before it is visible can produce the outcome.', 'tab:arm-results')
    # ---------------- Table: TSO ppo ----------------
    TWW = ['MP_TT_%s-plain' % m for m in ('plain', 'str.stlr', 'stlr.str', 'stlr.stlr', 'dmb', 'dmbld', 'dmbst', 'dsb', 'dsbld', 'dsbst')]
    TRR = ['MP_TT_plain-%s' % m for m in ('ldr.ldapr', 'ldr.ldar', 'ldapr.ldr', 'ldapr.ldapr', 'ldapr.ldar', 'ldar.ldr', 'ldar.ldapr',
                                          'ldar.ldar', 'dmb', 'dmbld', 'dmbst', 'dsb', 'dsbld', 'dsbst', 'addr', 'ctrl', 'ctrlisb')]
    TRW = ['LB_TT_%s-plain' % m for m in ('plain', 'ldr.stlr', 'ldapr.str', 'ldapr.stlr', 'ldar.str', 'ldar.stlr', 'dmb', 'dmbld',
                                          'dmbst', 'dsb', 'dsbld', 'dsbst', 'addr', 'data', 'ctrl', 'ctrlisb')]
    TWRo = ['SB_TT_%s-dmb' % m for m in ('stlr.ldar', 'dmb', 'dsb', 'dsbst')]
    tso_rows = [
      ('store $\\to$ store', 'every mechanism (10)', 'MP', TWW, '',
       [('Arm-mode writer, plain', ['MP_AT_plain-plain'], ''), ('%s;%s' % (I('STLR'), I('STR')), ['MP_AT_stlr.str-plain'], ''),
        ('%s, %s' % (I('DMB LD'), I('DSB LD')), ['MP_AT_dmbld-plain', 'MP_AT_dsbld-plain'], 'A2')]),
      ('load $\\to$ load', 'every mechanism (18)', 'MP', TRR + ['MP_TT_plain-plain'], '',
       [('Arm-mode reader', ['MP_TA_plain-plain', 'MP_TA_plain-ldr.ldapr', 'MP_TA_plain-ldr.ldar', 'MP_TA_plain-dmbst', 'MP_TA_plain-ctrl'], ''),
        (I('DSB ST'), ['MP_TA_plain-dsbst'], '')]),
      ('load $\\to$ store', 'every mechanism (16)', 'LB', TRW, '', [('Arm-mode thread', ['LB_AT_plain-plain', 'LB_AT_dmbst-plain', 'LB_AT_dsbst-plain'], 'A3')]),
      ('store $\\to$ load', '%s;%s, %s, %s, %s (4)' % (I('STLR'), I('LDAR'), I('DMB'), I('DSB'), I('DSB ST')), 'SB', TWRo, '',
       [('plain', ['SB_TT_plain-dmb'], '')]),
      ('store $\\to$ load', 'plain; %s;%s; %s;%s; %s;%s; %s;%s; %s' % (I('STR'), I('LDAPR'), I('STR'), I('LDAR'), I('STLR'), I('LDR'), I('STLR'), I('LDAPR'), I('DMB ST')),
       'SB', ['SB_TT_plain-dmb', 'SB_TT_str.ldapr-dmb', 'SB_TT_str.ldar-dmb', 'SB_TT_stlr.ldr-dmb', 'SB_TT_stlr.ldapr-dmb', 'SB_TT_dmbst-dmb'], '', None),
      ('store $\\to$ load', '%s, %s' % (I('DMB LD'), I('DSB LD')), 'SB', ['SB_TT_dmbld-dmb', 'SB_TT_dsbld-dmb'], 'A2', None),
    ]
    ppo_table(os.path.join(D, 'res-tso-ppo.tex'), 'tso', tso_rows,
        'The rows of the sequential composition on the two machines, every thread in TSO mode, $6\\times10^8$ iterations '
        'of each test on each machine. Entries as in \\cref{tab:arm-results}. TSO orders every store $\\to$ store, '
        'load $\\to$ load and load $\\to$ store row whatever the mechanism; their control is the same test with that thread '
        'in Arm mode, where the pair is not ordered. A number in parentheses counts the mechanisms of a row; with the 12 '
        'store $\\to$ load mechanisms, the 44 of the first three rows make up the 56 of \\cref{sec:method-tests}. '
        'The same-address rows are n7 with every thread in TSO mode and each store and load form on Thread~0.', 'tab:tsoarm-results')
    # TSO same-address rows: n7 with every thread TSO (n7_TTT and addon_fwdtso), each store and load form on Thread 0
    fwd_rows = [
      ('same address', '%s;%s' % (I('STR'), I('LDR')), 'n7', ['n7_TTT_plain-plain-plain', 'fwd12_str-ldr_TTT', 'fwd7_str-ldr-addr_TTT'], '', None),
      ('same address', '%s;%s' % (I('STLR'), I('LDR')), 'n7', ['fwd8_stlr-ldr-addr_TTT'], '', None),
      ('same address', '%s;%s' % (I('STXR'), I('LDR')), 'n7', ['fwd10_stxr-ldr-addr_TTT', 'fwd11_stxr-ldr_TTT'], '', None),
      ('same address', '%s;%s' % (I('STLXR'), I('LDR')), 'n7', ['fwd12_stlxr-ldr_TTT'], '', None),
      ('same address', '%s or %s, then %s' % (I('STR'), I('STLR'), I('LDXR')), 'n7', ['fwd12_str-ldxr_TTT', 'fwd12_stlr-ldxr_TTT'], '', None),
      ('same address', '%s;%s' % (I('STLXR'), I('LDXR')), 'n7', ['fwd12_stlxr-ldxr_TTT'], '', None),
      ('same address', '%s, %s, %s or %s, then an acquire load' % (I('STR'), I('STLR'), I('STXR'), I('STLXR')), 'n7',
       ['fwd3_str-ldapr_TTT', 'fwd6_str-ldar_TTT', 'fwd4_stlr-ldapr_TTT', 'fwd9_stxr-ldar_TTT', 'fwd12_str-ldaxr_TTT', 'fwd12_stlxr-ldapr_TTT'], 'A1', None),
      ('same address', 'a release, then %s or %s' % (I('LDAR'), I('LDAXR')), 'n7',
       ['fwd5_stlr-ldar_TTT', 'fwd12_stlr-ldaxr_TTT', 'fwd12_stlxr-ldar_TTT', 'fwd12_stlxr-ldaxr_TTT'], '', None),
      ('same address', 'an AMO, then any load', 'n7', ['fwd12_swp-ldr_TTT', 'fwd12_swp-ldapr_TTT', 'fwd12_swp-ldar_TTT', 'fwd12_swp-ldxr_TTT', 'fwd12_swp-ldaxr_TTT'], '', None),
      ('same address', '%s after the read-back' % I('DMB LD'), 'n7', ['fwd1_str-ldr-dmbld_TTT', 'fwd2_stlr-ldr-dmbld_TTT'], 'A2', None),
    ]
    assert sorted(t for r in fwd_rows for t in r[3] if t in XV) == sorted(XV), 'every addon_fwdtso test in exactly one row'
    # verdicts of mixed tests: use compound column
    def fwdtab():
        out = open(os.path.join(D, 'res-tso-ppo.tex')).read().split('\n')
        i = max(k for k, l in enumerate(out) if l.startswith('\\bottomrule'))
        new = ['\\addlinespace']; prev = None
        for pair, mech, shape, tests, note, ctl in fwd_rows:
            assert all(t in XV or L[t]['modes'] == 'TTT' for t in tests), tests
            col = 'tso'
            v = verdict(tests, col); f = v == 'ordered'
            new.append('%s & %s & %s & %s & %s & %s & \\\\' % (pair if pair != prev else '', mech, shape, v,
                       mag(tests, 'm1', note, f), mag(tests, 'm2', note, f)))
            prev = pair
        out[i:i] = new
        open(os.path.join(D, 'res-tso-ppo.tex'), 'w').write('\n'.join(out))
    fwdtab()
    # ---------------- multi-thread tables ----------------
    sa = multi_table(os.path.join(D, 'res-arm-multi.tex'), lambda md: set(md) == {'A'},
        'WRC, ISA2, RWC and IRIW with every thread in Arm mode, under every combination of the doubtful mechanisms '
        '(\\cref{sec:method-tests}), $6\\times10^8$ iterations of each test on each machine. Forbidden by the Arm model with '
        'A1--A3. A control is a forbidden test with one edge left unordered; controls that A3 forbids are omitted, and the '
        'range spans the shape\'s controls. Entries as in \\cref{tab:arm-results}.', 'tab:arm-multi')
    st = multi_table(os.path.join(D, 'res-tso-multi.tex'), lambda md: set(md) == {'T'},
        'WRC, ISA2, RWC and IRIW with every thread in TSO mode, under every combination of TSO\'s own order and the '
        'annotations \\ins{LDAPR} and \\ins{STLR}, $6\\times10^8$ iterations of each test on each machine. Where TSO orders '
        'every edge, a control is the same test with one thread in Arm mode. Format as in \\cref{tab:arm-multi}.', 'tab:tso-multi')
    sm = multi_table(os.path.join(D, 'res-mixed-multi.tex'), lambda md: len(set(md)) > 1,
        'WRC, ISA2, RWC and IRIW under every assignment of modes that mixes Arm and TSO, $6\\times10^8$ iterations of each '
        'test on each machine. Format as in \\cref{tab:arm-multi}. A control may run every thread in Arm mode.', 'tab:mixcov-results')
    # ---------------- Arm RMW table ----------------
    def amo_cell(ts, col='arm', note=''):
        v = verdict(ts, col).replace('not ordered', 'allowed').replace('ordered', 'forbidden')
        f = v == 'forbidden'
        return '%s & %s & %s' % (v, mag(ts, 'm1', note, f), mag(ts, 'm2', note, f))
    arm_rmw = [
      ('replaces the load', 'release', ['Dr_AA_swpl-swpl'], ['Dr_AA_llscl-llscl']),
      ('', 'acquire', ['Dr_AA_swpa-swpa'], ['Dr_AA_llsca-llsca']),
      ('replaces the store', 'release', ['Dw_AA_swpl-swpl', 'Dw_AA_ldaddl-ldaddl', 'Dw_AA_casl-casl'], ['Dw_AA_llscl-llscl']),
      ('', 'acquire', ['Dw_AA_swpa-swpa', 'Dw_AA_ldadda-ldadda', 'Dw_AA_casa-casa'], ['Dw_AA_llsca-llsca']),
      ('', 'both', ['Dw_AA_swpal-swpal'], ['Dw_AA_llscal-llscal']),
      ('as a fence', 'release', ['Df_AA_swpl-swpl'], ['Df_AA_llscl-llscl']),
      ('', 'acquire', ['Df_AA_swpa-swpa'], ['Df_AA_llsca-llsca']),
      ('', 'both', ['Df_AA_swpal-swpal'], ['Df_AA_llscal-llscal']),
    ]
    out = ['\\begin{table}[!htbp]', '\\centering', '\\footnotesize', '\\setlength{\\tabcolsep}{4pt}', '\\begin{tabular}{@{}llllllll@{}}', '\\toprule',
           '& & \\multicolumn{3}{c}{AMO} & \\multicolumn{3}{c}{LL/SC pair}\\\\', '\\cmidrule(lr){3-5}\\cmidrule(lr){6-8}',
           'Dekker: the RMW & Ordering & \\armw{Arm} & M1 & M2 & \\armw{Arm} & M1 & M2\\\\', '\\midrule']
    for i, (a, o, am, ll) in enumerate(arm_rmw):
        if a and i: out.append('\\addlinespace')
        c = amo_cell(am)
        out.append('%s & %s & %s & %s\\\\' % (a, o, c, amo_cell(ll)))
    out += ['\\bottomrule', '\\end{tabular}',
            '\\caption{Dekker with RMWs, both threads in Arm mode: the RMW replaces each thread\'s load (\\ins{STR x}; RMW \\ins{y}), '
            'its store (RMW \\ins{x}; \\ins{LDR y}), or neither, between the two (\\ins{STR x}; RMW \\ins{z}; \\ins{LDR y}). '
            'The AMO is \\ins{SWP}; where the RMW replaces the store, also \\ins{LDADD} and \\ins{CAS}, whose rows agree. The LL/SC pair is '
            '\\ins{LDXR}/\\ins{STXR}, with \\ins{LDAXR} for acquire and \\ins{STLXR} for release. For LL/SC pairs only runs in which both '
            'store-exclusives succeed are counted, $4.4\\times10^8$ to $6\\times10^8$. Entries as in \\cref{tab:arm-results}.}',
            '\\label{tab:arm-atomics}', '\\end{table}']
    open(os.path.join(D, 'res-arm-rmw.tex'), 'w').write('\n'.join(out) + '\n')
    # ---------------- TSO RMW table ----------------
    WR = {}
    for n, r in L.items():
        if r['modes'] == 'TT' and r['group'].startswith('1'):
            for e in r['entry_or_reason'].split(';'):
                if e.startswith('T:WR:'): WR[e[5:]] = n
    rmw = {k: v for k, v in WR.items() if any(x in k for x in ('swp', 'cas', 'ldadd', 'ldxr', 'ldaxr', 'llsc'))}
    amo = {k: v for k, v in rmw.items() if any(x in k for x in ('swp', 'cas', 'ldadd'))}
    atom = {k: rmw[k] for k in ('str.ldxr', 'str.ldaxr', 'stlr.ldxr', 'llsc.ldxr', 'llsc.ldaxr', 'llscl.ldxr')}
    rel = {k: rmw[k] for k in ('stlr.ldaxr', 'llscl.ldar', 'llscl.ldaxr')}
    unord = {k: v for k, v in rmw.items() if k not in amo and k not in atom and k not in rel}
    assert len(rmw) == 100 and len(amo) + len(atom) + len(rel) + len(unord) == 100, (len(rmw), len(amo), len(atom), len(rel), len(unord))
    expect(list(amo.values()) + list(atom.values()) + list(rel.values()), 'tso', 'Never'); expect(list(unord.values()), 'tso', 'Sometimes')
    DfA = ['Df_TT_%s-%s' % (x, x) for x in ('swp', 'swpa', 'swpl', 'swpal', 'ldadd', 'ldadda', 'ldaddl', 'ldaddal', 'cas', 'casa', 'casl', 'casal', 'casfail')]
    DfL = ['Df_TT_llsca-llsca', 'Df_TT_llscl-llscl', 'Df_TT_llscal-llscal']
    expect(DfA, 'tso', 'Never'); expect(DfL, 'tso', 'Sometimes')
    rows = [
      ('an AMO as the store, as the load, or between (%d)' % len(amo), 'locked', sorted(amo.values())),
      ('a store, then the load-exclusive of an LL/SC pair (%d)' % len(atom), 'atomicity', sorted(atom.values())),
      ('a release (%s, or an LL/SC pair with %s), then %s or %s (%d)' % (I('STLR'), I('STLXR'), I('LDAR'), I('LDAXR'), len(rel)), 'release, acquire', sorted(rel.values())),
      ('an LL/SC pair, then %s, %s or %s (%d)' % (I('LDR'), I('LDAPR'), I('LDAR'), len(unord)), 'not ordered', sorted(unord.values())),
      ('Dekker, an AMO between store and load, every form and ordering, and a failing %s (13)' % I('CAS'), 'locked', DfA),
      ('Dekker, an LL/SC pair between store and load, each annotation (3)', 'not ordered', DfL),
    ]
    out = ['\\begin{table}[!htbp]', '\\centering', '\\footnotesize', '\\begin{tabularx}{\\linewidth}{@{}>{\\raggedright\\arraybackslash}Xlll@{}}', '\\toprule',
           'Store $\\to$ load pairs with an RMW, both threads in TSO mode & Sequential composition & M1 & M2\\\\', '\\midrule']
    for d, v, ts in rows:
        f = v != 'not ordered'
        out.append('%s & %s & %s & %s\\\\' % (d, v, mag(ts, 'm1', '', f), mag(ts, 'm2', '', f)))
    out += ['\\bottomrule', '\\end{tabularx}',
            '\\caption{RMWs on TSO threads, $6\\times10^8$ iterations of each test on each machine. The first four rows are every '
            'store $\\to$ load pair with an exclusive or an AMO access, each in SB with \\ins{DMB} on the other thread; the controls are '
            'SB without the RMW (%s on the M1, %s on the M2) and Dekker without the RMW (%s, %s). For LL/SC pairs only runs in which the '
            'store-exclusives succeed are counted. Entries as in \\cref{tab:arm-results}.}' % (mag(['SB_TT_plain-dmb'], 'm1', plain=True), mag(['SB_TT_plain-dmb'], 'm2', plain=True),
                                                                                   mag(['Df_TT_ldr-ldr'], 'm1', plain=True), mag(['Df_TT_ldr-ldr'], 'm2', plain=True)),
            '\\label{tab:tso-atomics}', '\\end{table}']
    open(os.path.join(D, 'res-tso-rmw.tex'), 'w').write('\n'.join(out) + '\n')
    # ---------------- checks / numbers for the text ----------------
    rowtests = collections.defaultdict(dict)
    for n, r in L.items():
        if r['group'].startswith('1'):
            for e in r['entry_or_reason'].split(';'):
                if e[:2] in ('A:', 'T:'): rowtests[e][r['modes']] = n
    same = diff = 0; dl = []
    for e, d in rowtests.items():
        own = 'AA' if e[0] == 'A' else 'TT'
        if own not in d: continue
        for md, n in d.items():
            if md == own: continue
            for m in ('m1', 'm2'):
                if (H[(d[own], m)] > 0) == (H[(n, m)] > 0): same += 1
                else: diff += 1; dl.append((e, d[own], n, m, H[(d[own], m)], H[(n, m)]))
    print('partner comparisons: same %d, differ %d %s' % (same, diff, dl))
    for k, s in (('arm', sa), ('tso', st), ('mixed', sm)):
        print(k, {f: (v[0], v[1], len(v[2])) for f, v in s.items()})
    print('TSO RMW classes: amo %d atom %d rel %d unord %d' % (len(amo), len(atom), len(rel), len(unord)))
    # Sec 5.3, a failing CAS (addon_casfail, all-Arm Dekker): totals over 6e8 iterations and their magnitudes
    m10 = lambda t, m: mag([t], m, plain=True).replace('$', '')
    for t in sorted(XC):
        print('casfail %-26s %-9s %-9s compound-apple %-9s M1 %7d (%s)  M2 %7d (%s)' % (t, XC[t]['aarch64'], XC[t]['compound'],
              XC[t]['compound-apple'], H[(t, 'm1')], m10(t, 'm1'), H[(t, 'm2')], m10(t, 'm2')))
    seen3 = ['Df_AA_casfail-casfail', 'Df_AA_casafail-casafail', 'Df_AA_caslfail-caslfail']
    print('casfail summary: failing CASAL M1 %s, M2 %s; failing CAS/CASA/CASL M1 %s, M2 %s; succeeding CASAL M1 %s, M2 %s' % (
          m10('Df_AA_casalfail-casalfail', 'm1'), m10('Df_AA_casalfail-casalfail', 'm2'), mag(seen3, 'm1', plain=True).replace('$', ''),
          mag(seen3, 'm2', plain=True).replace('$', ''), m10('Df_AA_casal-casal', 'm1'), m10('Df_AA_casal-casal', 'm2')))
    viol = [n for n in list(L) + list(XV) + list(XC) for m in ('m1', 'm2') if V(n, 'compound-apple') == 'Never' and H[(n, m)] > 0]
    print('violations (compound-apple Never, seen):', viol)
    print('missing machine data:', [(t, m) for t in list(ADDON) + list(XV) + list(XC) for m in ('m1', 'm2') if (t, m) not in SEEN])

if __name__ == '__main__':
    run(sys.argv[1])
