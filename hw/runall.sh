#!/bin/sh
# batch5 v3 runner (one script for M1 and M2), run from a git checkout; all paths are relative to this directory.
#   sh runall.sh <m1|m2> <runlist> [results.tsv]         full run, mult 10 (1e8 per cell)
#   sh runall.sh <m1|m2> --smoke <test> [mult]           one test, all six cells, mult (default 1 = 1e7 per cell),
#                                                        into results_smoke_<machine>.tsv (separate from the real results)
#     runlist: lines "name nthreads" (runlist_all.txt = everything; runlist_m1.txt / runlist_m2.txt = still to run)
#     results: default results_<machine>.tsv in this directory; rows appended in run3.sh's format:
#              harness  name  cell  mult  hits  iterations  MEMMODEL  seconds  seconds
# Every listed test, both harnesses (std_user, std_timebase) x cells E, M, P, at mult 10 = 1e8 iterations per cell:
#   2 threads: E 0-3 / M 0,1,4,5 / P 4-7, -a 4 (2 instances), -r 500;  3 threads: E 0-3 / M 0,4,5 / P 4,5,6, -a 3, -r 1000;
#   4 threads: E 0-3 / M 0,1,4,5 / P 4,5,6,7, -a 4, -r 1000;  -s 100000.  (= batch4 run3sb.sh)
# m1 (a shared Compile Farm machine): every build and every cell under `flock ~/cfarm.lock nice -n 10`, unpinned (as batch4).
# m2: M cells pinned with hw/pinshim.so (LD_PRELOAD, PIN_SKIP = a/nthreads - 1), E and P unpinned (as m2-asahi/suite/run_m2.sh).
# Resumable: a cell already in the results file (harness, name, cell, mult) is skipped. `touch STOP` stops cleanly.
# After every cell the new row is hook-checked against hooklist.txt (mask, nthreads -> expected arm_sets/tso_sets);
# a mismatch or a missing Observation aborts (exit 2). DRYRUN=1 prints the commands and runs nothing.
set -u
cd "$(dirname "$0")" || exit 1
B=$(pwd); MACH=${1:?m1|m2}; LIST=${2:?runlist}; MULT=10
if [ "$LIST" = --smoke ]; then
  T=${3:?test name}; MULT=${4:-1}
  awk -v n="$T" '$1==n{print $1" "$4; f=1} END{exit !f}' hooklist.txt > .smoke_list_$MACH || { echo "no test $T in hooklist.txt"; exit 1; }
  LIST=$B/.smoke_list_$MACH; OUT=$B/results_smoke_$MACH.tsv
else
  OUT=${3:-$B/results_$MACH.tsv}
fi
case $LIST in /*) ;; *) LIST=$B/$LIST;; esac
case $OUT in /*) ;; *) OUT=$B/$OUT;; esac
case $MACH in
  m1) LOCK="flock $HOME/cfarm.lock nice -n 10"; TMO=${CELL_TIMEOUT:-3600};;
  m2) LOCK=""; TMO=${CELL_TIMEOUT:-43200};;
  *) echo "machine must be m1 or m2"; exit 1;;
esac
X=""; [ -n "${DRYRUN:-}" ] && X="echo DRYRUN:"
ST=$B/status_$MACH.log
log() { echo "$*" >> $ST; echo "$*"; }
# ---- checks ----
[ -f "$LIST" ] || { echo "no list $LIST"; exit 1; }
bad=$(awk 'NR==FNR{ if($0!~/^#/) h[$1]=$4; next } !($1 in h) || h[$1]!=$2 {print $1}' hooklist.txt "$LIST")
[ -z "$bad" ] || { echo "not in hooklist.txt or wrong nthreads: $bad"; exit 1; }
for d in std_user std_timebase; do
  miss=$(awk -v d=harness/$d '{ f=d"/"$1".c"; if ((getline l < f) < 0) print $1; close(f) }' "$LIST")
  [ -z "$miss" ] || { echo "harness/$d lacks: $miss (run mkharness.sh)"; exit 1; }
done
touch "$OUT"; mkdir -p logs/std_user logs/std_timebase
log "# start $(date) $MACH list=$LIST ($(wc -l < "$LIST") tests) out=$OUT load=$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
# ---- build (only the listed tests) ----
if [ $MACH = m2 ] && [ ! -f hw/pinshim.so ]; then
  $X sh -c "cd hw && cc -O2 -shared -fPIC -o pinshim.so pinshim.c -ldl" || { log "pinshim build fail"; exit 1; }
fi
EXES=$(awk '{printf "%s.exe ", $1}' "$LIST")
for d in std_user std_timebase; do
  $X $LOCK sh -c "cd harness/$d && make -j4 $EXES > make.log 2>&1" || { log "build fail $d"; exit 1; }
  [ -n "$X" ] || log "harness/$d: $(ls harness/$d/*.exe 2>/dev/null | wc -l) exe"
done
# ---- run ----
hook() {   # hook <row file>: exit 1 on NA or MEMMODEL != expected for (mask, nthreads)
  awk -F'\t' 'NR==FNR{ if($0 ~ /^#/) next; m[$1]=$3; n[$1]=$4; next }
  { t=$2; k=0; x=m[t]; while(x>0){k+=x%2; x=int(x/2)}; nt=n[t]; r=(nt==2?50:100)*$4; ne=(nt==2?2:1);
    e="arm_sets=" (nt-k)*ne*r "/tso_sets=" k*ne*r;
    if(!(t in m) || $5=="NA" || $7!=e){ print "MISMATCH", $0, "expected", e; bad=1 } }
  END{ exit bad }' hooklist.txt "$1"
}
k=0
for d in std_user std_timebase; do for p in E M P; do
  while read n t; do
    [ -f STOP ] && { log "# STOP seen $(date)"; exit 3; }
    awk -F'\t' -v d=batch5/$d -v n=$n -v p=$p -v m=$MULT '$1==d&&$2==n&&$3==p&&$4==m{f=1} END{exit !f}' "$OUT" && continue
    case $t$p in
      2E) c=0-3; a=4; r=$((50*MULT));;    2M) c=0,1,4,5; a=4; r=$((50*MULT));;  2P) c=4-7; a=4; r=$((50*MULT));;
      3E) c=0-3; a=3; r=$((100*MULT));;   3M) c=0,4,5; a=3; r=$((100*MULT));;   3P) c=4,5,6; a=3; r=$((100*MULT));;
      4E) c=0-3; a=4; r=$((100*MULT));;   4M) c=0,1,4,5; a=4; r=$((100*MULT));; 4P) c=4,5,6,7; a=4; r=$((100*MULT));;
      *) log "ABORT no placement for $n t=$t p=$p"; exit 2;;
    esac
    pe=""; [ $MACH = m2 ] && [ $p = M ] && pe="LD_PRELOAD=$B/hw/pinshim.so PIN_SKIP=$((a/t-1))"
    lg=$B/logs/$d/$n.$p.x$MULT.log
    cmd="cd $B/harness/$d && t0=\$(date +%s) && env $pe timeout $TMO taskset -c $c ./$n.exe -a $a -s 100000 -r $r > $lg 2>&1 < /dev/null; echo \$t0 \$(date +%s) > $lg.t"
    if [ -n "$X" ]; then echo "DRYRUN: $LOCK sh -c \"$cmd\""; continue; fi
    $LOCK sh -c "$cmd"
    set -- $(cat $lg.t); secs=$(($2 - $1))
    pos=$(awk '/^Observation/{print $4}' $lg); neg=$(awk '/^Observation/{print $5}' $lg)
    mm=$(awk '/^MEMMODEL/{print $3"/"$4}' $lg)
    printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" batch5/$d $n $p $MULT "${pos:-NA}" "$(( ${pos:-0} + ${neg:-0} ))" "$mm" $secs $secs > $B/.last_$MACH.tsv
    cat $B/.last_$MACH.tsv >> "$OUT"
    hook $B/.last_$MACH.tsv >> $ST 2>&1 || { log "ABORT hook mismatch batch5/$d $n $p $(date)"; exit 2; }
    k=$((k+1))
  done < "$LIST"
done; done
[ -n "$X" ] && exit 0
hook "$OUT" > /dev/null 2>&1 || { log "ABORT final hookcheck of $OUT failed"; exit 2; }
log "# done $(date): $k cells run this session, $(wc -l < "$OUT") rows in $OUT"
