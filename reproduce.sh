#!/bin/sh
# One entry point for the checks that need no Apple hardware.
#   sh reproduce.sh L1     every results table (Sections 5 to 8) recomputed from the raw results and compared with
#                          expected/ (the report's tables), and the counts quoted in the text      (Python 3, seconds)
#   sh reproduce.sh L2     every herd verdict (scripts/check_verdicts.py)                        (herdtools7 7.58, minutes)
#   sh reproduce.sh all    both (the default)
# Prints PASS or FAIL per table and per quoted number, a diff for a table that differs, and a summary; exit 1 on a FAIL.
# Level 3 (the hardware runs) is described in README.md; nothing here runs a litmus test on hardware.
cd "$(dirname "$0")" || exit 1
LV=${1:-all}; FAIL=0; NP=0; NF=0
pass() { echo "PASS $*"; NP=$((NP + 1)); }
fail() { echo "FAIL $*"; NF=$((NF + 1)); FAIL=1; }
# review markup of the report (\color{violet}% ... for review) is not part of a table's content
norm() { sed -e 's/\\color{violet}//g' -e 's/% *new [a-z]*, for review//' -e 's/[[:space:]]*$//' "$1"; }
l1() {
  echo "== Level 1: tables from raw results"
  W=tables; rm -rf $W; mkdir -p $W
  (cd scripts && python3 cells.py) || { fail "cells.py"; return; }
  (cd scripts && python3 make_tables.py ../$W > ../$W/make_tables.out) || { fail "make_tables.py"; cat $W/make_tables.out; return; }
  (cd scripts && python3 scale_table.py ../$W > ../$W/scale_table.out); rs=$?
  for e in expected/res-*.tex; do
    b=$(basename $e)
    if [ ! -f $W/$b ]; then fail "table $b: not generated"; continue; fi
    norm $e > $W/.e; norm $W/$b > $W/.g
    if cmp -s $W/.e $W/.g; then pass "table $b"; else fail "table $b"; diff $W/.e $W/.g | sed 's/^/    /'; fi
  done
  rm -f $W/.e $W/.g
  for t in $W/res-*.tex; do [ -f expected/$(basename $t) ] || fail "table $(basename $t): no expected/ copy"; done
  # make_tables.py's own checks (Sec 5.3 failing CAS, violations, missing data)
  grep -q "^violations (compound-apple Never, seen): \[\]$" $W/make_tables.out && pass "no outcome forbidden by compound-apple.cat seen (add-ons included)" || fail "violations: $(grep ^violations $W/make_tables.out)"
  grep -q "^missing machine data: \[\]$" $W/make_tables.out && pass "every add-on test has its six cells on both machines" || fail "$(grep ^missing $W/make_tables.out)"
  grep -q "failing CASAL M1 0, M2 0; failing CAS/CASA/CASL M1 10^{4}--10^{5}, M2 10^{4}; succeeding CASAL M1 0, M2 0" $W/make_tables.out \
    && pass "Sec 5.3 failing CAS magnitudes" || fail "Sec 5.3: $(grep 'casfail summary' $W/make_tables.out)"
  echo "-- Sec 8 runs and quoted numbers (scripts/scale_table.py)"
  cat $W/scale_table.out
  NP=$((NP + $(grep -c '^PASS' $W/scale_table.out))); NF=$((NF + $(grep -c '^FAIL' $W/scale_table.out))); [ $rs -eq 0 ] || FAIL=1
  echo "-- Sec 8 run script against the logged commands (scripts/check_scale_cmds.py)"
  (cd scripts && python3 check_scale_cmds.py) > $W/check_scale_cmds.out; rc=$?
  cat $W/check_scale_cmds.out
  NP=$((NP + $(grep -c '^PASS' $W/check_scale_cmds.out))); NF=$((NF + $(grep -c '^FAIL' $W/check_scale_cmds.out))); [ $rc -eq 0 ] || FAIL=1
  echo "-- quoted counts, Sections 1 to 7 (scripts/check_prose.py)"
  (cd scripts && python3 check_prose.py) > $W/check_prose.out; rp=$?
  cat $W/check_prose.out
  NP=$((NP + $(grep -c '^PASS' $W/check_prose.out))); NF=$((NF + $(grep -c '^FAIL' $W/check_prose.out))); [ $rp -eq 0 ] || FAIL=1
}
l2() {
  echo "== Level 2: herd verdicts"
  H7=$(command -v herd7 || echo $HOME/.opam/default/bin/herd7)
  if [ ! -x "$H7" ]; then fail "herd7 not found (install herdtools7 7.58)"; return; fi
  echo "herd7: $H7 ($($H7 -version 2>/dev/null))"
  PATH=$(dirname $H7):$PATH python3 scripts/check_verdicts.py > tables/check_verdicts.out 2>&1; r=$?
  tail -5 tables/check_verdicts.out
  if [ $r -eq 0 ] && grep -q 'ALL CHECKS PASS' tables/check_verdicts.out; then pass "herd verdicts (check_verdicts.py)"; else fail "herd verdicts: see tables/check_verdicts.out"; fi
}
mkdir -p tables
case $LV in L1) l1;; L2) l2;; all) l1; l2;; *) echo "usage: sh reproduce.sh [L1|L2|all]"; exit 1;; esac
NOTE=$(cat tables/scale_table.out 2>/dev/null | grep -c '^NOTE')
echo "== summary: $NP PASS, $NF FAIL, $NOTE NOTE (approximate wording; values printed above)"
exit $FAIL
