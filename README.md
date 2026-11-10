# Artifact: Do Apple M-series processors enforce the compound memory model?

This directory has everything behind the results of the report: the 936 litmus tests, the herd models, the raw litmus7 results from an Apple M1 and an Apple M2 and the scripts that turn them into the tables. It can be checked at three levels.

The 936 tests are 658 generated and 278 written by hand: the 246 hand-written tests of `list.tsv` (origin `batch4`) and the 32 add-ons of `addon.tsv`.

| Level | What it checks | Needs | Time |
|---|---|---|---|
| 1 | Every table in Sections 5 to 8, recomputed from the raw results, and the counts quoted in the text | Python 3 | seconds |
| 2 | Every herd verdict, and the model files against herd's own Arm and x86-TSO models | Python 3, herdtools7 7.58 | minutes |
| 3 | The hardware results themselves | An Apple M1 or M2 running Asahi Linux (Sec 8 also: an M2 Max under macOS), litmus7 7.58, gcc | days |

`sh reproduce.sh [L1|L2|all]` runs levels 1 and 2 and prints `PASS` or `FAIL` for every table, every Sec 8 run and every
quoted number, with a diff for a table that differs from `expected/`; `NOTE` marks a sentence whose wording is approximate,
with the computed values. It exits 1 on any `FAIL`.

## Contents

```
models/      herd models (cat files)
tests/
  scale_rows.tsv, scale_cells.tsv   tab:scale: each row's test, control and overlap state; each cell's log, control log
               and rows file under results/addon_scale/ (the map from the table to the raw data)
  list.tsv     the 904 tests of the suite: shape, modes, why each test is there, its control, its herd verdicts
  addon.tsv    32 more tests, run separately with the same harness: Dekker with SWPAL between store and load, the
               26 same-address fwd*_TTT tests (the fwd*_T tests with every thread in TSO mode; Table 6's same-address rows),
               and 5 all-Arm Dekker tests with a failing CAS, CASA, CASL or CASAL (or a succeeding CASAL, the reference)
               between store and load (Sec 5.3, "A failing CAS")
  ppo_table.tsv  the preserved-program-order table the generator expands: per mode, pair and mechanism (and the RMW
                 pairs of TSO threads), the verdict and the test that queries it
  src/         every test in AArch64 syntax, as herd's aarch64.cat reads it
  herd/        the same tests with a leading ISB on each TSO thread, the mode marker of our models
  typed/       the same tests with C types, for litmus7
  x86/         the 18 x86 programs (all-TSO tests with only LDR, STR and DMB) translated to x86 syntax, with herd's x86tso verdicts
results/
  results_m1.tsv, results_m2.tsv   raw litmus7 rows of the runs of this suite
  reuse_m1.tsv, reuse_m2.tsv       tests whose six cells were already run, identically, in an earlier batch, and where
  batch4/                          the raw rows of that earlier batch that reuse_*.tsv points to
  addon_swpal/                     raw rows of the SWPAL add-on test
  addon_fwdtso/                    raw rows, herd.tsv verdicts and logs/{m1,m2} of the 26 fwd*_TTT tests
  addon_casfail/                   raw rows, herd.tsv verdicts and logs/{m1,m2} of the 5 failing-CAS tests
  addon_mpreader/                  raw rows and logs of a rerun of MP_AA_plain-dmb (as MPr_AA_plain-dmb, the same program),
                                   quoted in Sec 4.3 and 7.1: 49 on the M1 and 26 on the M2
  addon_scale/                     Sec 8 (tab:scale), the long unpinned runs at stride 7, one directory per setup and campaign:
    linux_m1/, linux_m2/             unpinned_screen/ (the claim tests and SWPAL; SWPA on the M1), fill/ (SWPL load, SB DMB;
                                     n6 on the M2), n6/ (n6 on the M1), on the M2 also swpabig/ (SWPA at 4 strides, 1e11:
                                     the M2 Linux SWPA cell and footnote a) and swpa_st7_chunks/ (SWPA 25 x 1e9, Nov 9: 5 hits
                                     in 9.1e6 overlaps, a replication not used in the table); each with its rows (.tsv) and logs
    macos_m2max/                     M2 Max (Mac14,13) under macOS: the AA tests and their controls, logs only
    macos_m2/                        M2 MacBook Air under macOS: SWPA at 4 strides, 34 in 1e11 (Sec 5.3), logs only
  logs/                            litmus7 output of every run
  cells.tsv                        per test, machine and cell: hits and iterations (written by scripts/cells.py)
scripts/     cells.py, make_tables.py, scale_table.py, check_prose.py (level 1), check_verdicts.py and translate_x86.py (level 2)
hw/          generation and run scripts (level 3); hw/scale/ for the long runs of Sec 8
generator/   the scripts that generated and selected the tests (for inspection)
expected/    the tables as they appear in the report (res-*.tex); add the report's section sources as expected/sections/
             to have the quoted counts checked against its text
reproduce.sh levels 1 and 2 in one command
```

### Models

The models are split so that each preserved program order is written once.

| File | Contents |
|---|---|
| `prelude.cat` | herd library includes and barrier names |
| `axioms.cat` | the three shared axioms: sc-per-location, atomicity, order (with `rfe`, `coe`, `fre`) |
| `arm-ppo.cat` | Arm preserved program order |
| `tso-ppo.cat` | the sequential composition: TSO's order over every load and store, AMOs locked, together with Arm's order |
| `apple-ppo.cat` | `apple-all`: the three orders both machines preserve beyond the models (A1 to A3), and the rule that a CAS always writes |
| `arm.cat`, `tso.cat`, `compound.cat` | Arm on every thread; the sequential composition on every thread; the compound model, Arm on Arm threads and the sequential composition on TSO threads |
| `arm-apple.cat`, `tso-apple.cat`, `compound-apple.cat` | the same three with `apple-all` added to every thread |

A thread whose first instruction is `ISB` runs in TSO mode.

### Tests

`list.tsv` columns: `name`; `family` (MP, SB, LB, WRC, ISA2, RWC, IRIW, n6, n7, Dekker forms, ...); `nthreads`; `mask` (bit i set when thread i runs in TSO mode); `modes` (A or T per thread); `group` (1: a row of preserved program order or its control; 2: propagation, three and four threads; 3: written by hand); `entry_or_reason` (the row a generated test queries, or why a hand-written test was written); `pivot`, `context`; `section` of the report; `control` (the allowed test that differs at one pair); the verdicts of `compound.cat`, `compound-apple.cat`, `arm.cat` (all-Arm tests), `tso.cat` (all-TSO tests) and herd's `aarch64.cat`; `axiom` (which axiom forbids the outcome under the compound model); `origin` (`generated`, or `batch4` for tests written by hand).

### Result rows

Each row of `results/results_*.tsv`, `results/batch4/`, `results/addon_swpal/`, `results/addon_fwdtso/` and `results/addon_casfail/` is one litmus7 run:

| Column | Meaning |
|---|---|
| 1 | harness: batch directory and litmus7 synchronization mode (`std_user`, `std_timebase`) |
| 2 | test name |
| 3 | placement: `P` all threads on performance cores, `E` all on efficiency cores, `M` across both clusters |
| 4 | size multiplier: 10 is 10^8 iterations (only multiplier 10 is counted) |
| 5 | runs that showed the outcome |
| 6 | runs counted (for LL/SC pairs, runs in which every store-exclusive succeeded) |
| 7 | how many times threads set the Arm and the TSO mode, checked against the test's mask |
| 8, 9 | run time in seconds |

A test's total on a machine is the sum over its six cells (two harnesses times three placements), 6x10^8 iterations. On the M2, `M` runs pin each thread with `hw/hw/pinshim.c` (LD_PRELOAD). The logs are named `<test>.<placement>.x<multiplier>.log`; the smoke runs (multiplier 1) are not part of the artifact, and the scripts ignore any row whose multiplier is not 10.

## Level 1: recompute the tables

`sh reproduce.sh L1` does all of this. By hand:

```
cd scripts
python3 cells.py
mkdir -p ../tables
python3 make_tables.py ../tables
python3 scale_table.py ../tables
python3 check_prose.py
```

and compare `tables/res-*.tex` with `expected/`.

`cells.py` collects every counted row into `results/cells.tsv`, taking a reused test's rows from `results/batch4/`. `make_tables.py` writes the tables of Sections 5 to 7. Each cell of a table names the tests behind it, and the script stops if a test's herd verdict disagrees with its row; it also prints the comparisons quoted in the text (each row with a partner of each mode, and the summaries of the three- and four-thread tables). The `diff` should print nothing. `make_tables.py` also prints, for the five failing-CAS tests of `results/addon_casfail/`, each test's total and magnitude on each machine (Sec 5.3: a failing CASAL 0 on both, a failing CAS, CASA or CASL 10^4 to 10^5 on the M1 and 10^4 on the M2), and the violations (a test forbidden by `compound-apple.cat` and seen) and missing machine data over the add-ons, both of which should be `[]`. Table cells are written as status macros (`\rfz` forbidden and never seen, `\rsn{..}` allowed and seen, `\rst{A1}` allowed, never seen and forbidden by A1-A3, `\rux` allowed and never seen, unexplained, `\rvi{..}` forbidden and seen); the report's `macros.tex` defines how they are drawn.

`scale_table.py` writes `res-scale.tex` (Sec 8) from the litmus7 logs named in `tests/scale_cells.tsv`. A cell is the
hits of its run (the `Observation` line) and, for Dekker, SB and LB, the overlapping iterations in millions: the histogram
count of the state of `tests/scale_rows.tsv` in which both loads read 1 (LB: both read 0). Each run is checked against its
rows file, its mode count, its iteration count (2.5e10; 5e9 for the three-thread n7) and its control, which must have
appeared in the same session; the same program must have the same litmus7 hash on every setup. It then checks footnote a
(the M2 Linux SWPA cell, 4 hits in 1e11 at four strides, all at stride 7, overlap count of the stride-7 run) and every
number of the text of Sec 8. `check_prose.py` checks the counts quoted in Sections 1 to 7 (test counts, the partner
comparisons, 67/26/231/49/78, the mixed-mode counts, the failing-CAS and acquire-AMO numbers): each phrase is rebuilt
from the data and, if `expected/sections/` holds the report's text, must occur in it; otherwise it is printed (`PHRASE`)
for comparison with the report. Order-of-magnitude summaries of table cells in the text ("10^5 to
10^7 times") are not checked one by one; the cells themselves are.

## Level 2: recompute the herd verdicts

Install herdtools7 7.58 (for example `opam install herdtools7.7.58`), then

```
python3 scripts/check_verdicts.py
```

It recomputes every verdict column of `tests/list.tsv` and `tests/addon.tsv`, and checks that `arm.cat` agrees with herd's `aarch64.cat` on every all-Arm test, that `tso.cat` agrees with herd's `x86tso.cat` on every all-TSO test that is an x86 program (translated to x86 syntax), and that `compound.cat` and `compound-apple.cat` reduce to the single-mode models on single-mode tests. It should end with `ALL CHECKS PASS`. Set `HERDLIB` if herd's library directory is not next to the `herd7` executable.

To look at one test: `herd7 -I models -model models/compound.cat tests/herd/SB_TT_dmb-dmb.litmus`.

## Level 3: rerun on an M1 or M2

The M1 is an Apple Mac mini (M1, 2020) in the GCC Compile Farm, running Debian with an Asahi Linux 6.5 kernel; the M2 is a MacBook Air (M2) running Fedora Asahi Linux with a 7.2 kernel; both use litmus7 7.58 and gcc. The kernel exposes the per-thread TSO bit through `prctl(PR_SET_MEM_MODEL, 1)` (TSO) and `prctl(PR_SET_MEM_MODEL, 0)` (Arm), with `PR_GET_MEM_MODEL` to read it back.

`hw/runlist_all.txt`, `hw/modes_all.tsv` and `hw/hooklist.txt` list all 936 tests (the 904 of `list.tsv`, then the 32 add-ons), so the harnesses cover every test and `runall.sh` can run any of them (a shorter runlist runs a subset).

1. Generate the harnesses (on any machine with litmus7; set `L7` if litmus7 is not at `~/.opam/default/bin/litmus7`): `sh hw/mkharness.sh`. It runs litmus7 on `tests/typed/` for each synchronization mode and then `hw/patch_mode.py`, which inserts one call per test thread that sets its mode according to `hw/modes_all.tsv` and reads it back; a mismatch aborts the run, and every run prints how many times each mode was set.
2. Copy `hw/`, with `harness/` and `typed/`, to the machine.
3. Run `sh runall.sh <m1|m2> runlist_all.txt` in `hw/`. It builds the harnesses, runs every test in its six cells at 10^8 iterations each, appends one row per cell to `results_<machine>.tsv`, and checks every row's mode count against `hooklist.txt`. It is resumable, and `touch STOP` stops it cleanly. On a shared machine, run it under a lock (`flock`) and at low priority (`nice`), as we did on the M1.

The full suite takes several days of machine time on each machine.

### The long runs of Sec 8

`sh hw/scale/mkharness_scale.sh linux` (or `macos`) builds the harness of the tests and controls of `tests/scale_rows.tsv`
with the flags of the report's runs (`-a 4 -mode std -barrier user -st 1`; on Linux the mode hook, on macOS the Arm-mode
tests only). `sh hw/scale/run_scale.sh m1|m2|macos` (from `hw/`) then runs every cell of that setup unpinned at stride 7,
each test after its control: about 13 hours on each Linux machine. On the M2 the SWPA test runs at strides 1, 3, 5 and 7
(`SWPA_STRIDES` overrides; `SWPA_STRIDES="1 3 5 7"` on macOS reruns Sec 5.3's 1e11 run). `DRYRUN=1` lists the jobs, and `SMOKE=1` runs every test at `-r 1` (2e5 iterations; controls unchanged) to check the build, the mode hook and the log format in minutes. The long-run results in `results/addon_scale/` were produced by the scripts in our tree that this one replaces. Level 1 checks that `run_scale.sh` issues exactly the commands logged in those results (`scripts/check_scale_cmds.py`: program and litmus7 flags, every Sec 8 log; 24 jobs on m1, 30 on m2, 16 on macos). `SMOKE=1` was run end to end on 2026-11-10 on the M1 (Linux) and on the M2 under macOS: every job finished, every mode count matched, every control appeared (`results/addon_scale/smoke/`). Not yet smoke-run: the M2 under Linux and the M2 Max.
To compare a rerun with the report: `SCALE_linux_m2=$PWD/hw/scale/out_linux_m2 python3 scripts/scale_table.py <dir>`
(likewise `SCALE_linux_m1`, `SCALE_macos_m2max`). Rates of rare outcomes vary between runs and machines, so a rerun is
expected to reproduce the zeros and the controls, not the exact counts.


## License

Scripts: MIT (`LICENSE`). Tests, models, results and expected tables: CC BY 4.0 (`LICENSE-DATA`).
