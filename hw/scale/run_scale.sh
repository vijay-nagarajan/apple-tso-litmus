#!/bin/sh
# Level 3, Sec 8: reruns the cells of tab:scale on one setup, as in the report: threads unpinned (no taskset, no
# affinity), stride 7, 2.5e10 iterations per two-thread test (-a 4 -r 125000; 2 instances x 1e5 x r), 5e9 per
# three-thread test (-a 3 -r 50000), each test preceded by its control at 2.5e7 (-r 125 / -r 250) in the same session.
# The tests of a setup are the cells of tests/scale_cells.tsv whose log is not '-'. On m2, the acquire-AMO test
# (Dw_AA_swpa-swpa) runs at strides 1, 3, 5 and 7 (1e11, footnote a of tab:scale); set SWPA_STRIDES=7 for stride 7 only.
# SWPA_STRIDES="1 3 5 7" with macos reruns the 1e11 macOS run of Sec 5.3 (34 hits on an M2 MacBook Air; same harness flags).
#   sh scale/run_scale.sh m1|m2|macos            (from hw/, after sh scale/mkharness_scale.sh linux|macos)
# m1 (a shared Compile Farm machine): every build and job under `flock ~/cfarm.lock nice -n 10`.
# Output: scale/out_<setup>/<test>.U.st<S>.r<R>.log (litmus7 output with a header line) and scale/out_<setup>/results.tsv,
# one row per job: harness name placement(U) r hits iterations MEMMODEL seconds seconds stride role cpus(all).
# Linux rows are checked against hooklist.txt (mode count of every thread). Resumable; `touch STOP` stops before the
# next job. DRYRUN=1 prints the jobs (any OS; reproduce.sh compares them with the commands logged in results/).
# SMOKE=1: every test at -r 1 (2e5 iterations; controls unchanged), output in out_<setup>_smoke/: checks the build, the
# mode hook and the log format in minutes, not the counts. Time: about 13 h (m1, m2), 6 h (macos), longer under load.
# Compare with the report: SCALE_<setup>=<abs path of out_<setup>> python3 ../scripts/scale_table.py <dir>
#   (setup linux_m1, linux_m2 or macos_m2max), which then reads that setup's cells from the rerun.
set -u
cd "$(dirname "$0")" || exit 1
B=$(pwd); M=${1:?m1|m2|macos}; T=$B/../../tests
case $M in m1) SET=linux_m1; H=$B/harness_linux; WRAP="flock $HOME/cfarm.lock nice -n 10";;
           m2) SET=linux_m2; H=$B/harness_linux; WRAP="";;
           macos) SET=macos_m2max; H=$B/harness_macos; WRAP=""; [ -n "${DRYRUN:-}" ] || [ "$(uname -s)" = Darwin ] || { echo "macos: run on macOS"; exit 1; };;
           *) echo "usage: sh run_scale.sh m1|m2|macos"; exit 1;; esac
O=$B/out_$SET; [ -n "${SMOKE:-}" ] && O=${O}_smoke; OUT=$O/results.tsv; PR=$O/progress.txt; S=7
X=""; [ -n "${DRYRUN:-}" ] && X=echo
[ -z "$X" ] && { mkdir -p $O; touch $OUT; }
hook() {   # the mode count of the row against hooklist.txt (mask, threads -> arm_sets/tso_sets); Linux only
  [ $M = macos ] && return 0
  awk -F'\t' 'NR==FNR{ if($0 ~ /^#/) next; m[$1]=$3; n[$1]=$4; next }
  { t=$2; k=0; x=m[t]; while(x>0){k+=x%2; x=int(x/2)}; nt=n[t]; ne=(nt==2?2:1); r=$4;
    e="arm_sets=" (nt-k)*ne*r "/tso_sets=" k*ne*r;
    if(!(t in m) || $5=="NA" || $7!=e || $6!=ne*100000*r){ print "MISMATCH", $0, "expected", e; bad=1 } }
  END{ exit bad }' $B/../hooklist.txt "$1"
}
[ -z "$X" ] && { (cd $H && $WRAP make > make.log 2>&1) || { echo "build failed: $H/make.log"; exit 1; }; }
job() {   # job <name> <nthreads> <role> <stride>
  n=$1; t=$2; role=$3; s=$4
  if [ $role = test ]; then r=125000; a=4; [ $t = 3 ] && { r=50000; a=3; }; else r=125; a=4; [ $t = 3 ] && { r=250; a=3; }; fi
  [ $role = test ] && [ -n "${SMOKE:-}" ] && r=1
  [ -z "$X" ] && [ -f $OUT ] && awk -F'\t' -v n=$n -v r=$r -v s=$s '$2==n&&$4==r&&$10==s{f=1} END{exit !f}' $OUT && return 0
  [ -f $B/STOP ] && { echo "$(date) STOP" >> $PR; exit 3; }
  lg=$O/$n.U.st$s.r$r.log; args="-a $a -s 100000 -r $r -st $s"
  if [ -n "$X" ]; then echo "$SET: $WRAP ./$n.exe $args > $lg"; return 0; fi
  echo "$(date) START $SET $n [$role U st$s] r=$r" >> $PR
  { echo "# host=$(hostname) setup=$SET placement=U cpus=all role=$role cmd: ./$n.exe $args"; date; } > $lg
  t0=$(date +%s); (cd $H && $WRAP ./$n.exe $args >> $lg 2>&1 < /dev/null; echo "# rc=$?" >> $lg)
  secs=$(( $(date +%s) - t0 )); date >> $lg
  pos=$(awk '/^Observation/{print $4}' $lg); neg=$(awk '/^Observation/{print $5}' $lg); mm=$(awk '/^MEMMODEL/{print $3"/"$4}' $lg)
  printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n" scale/std_user $n U $r "${pos:-NA}" "$(( ${pos:-0} + ${neg:-0} ))" "${mm:--}" $secs $secs $s $role all > $O/.last.tsv
  cat $O/.last.tsv >> $OUT
  echo "$(date) END $SET $n [$role U st$s] $(grep ^Observation $lg) ${secs}s" >> $PR
  hook $O/.last.tsv >> $PR 2>&1 || { echo "ABORT hook mismatch $n" >> $PR; exit 2; }
}
awk -F'\t' -v s=$SET 'NR==FNR{ if(FNR>1) nt[$5]=$7; next } FNR>1 && $2==s && $5!="-" {print $3, $4, nt[$3]}' $T/scale_rows.tsv $T/scale_cells.tsv |
while read tn tc nt; do
  ST=$S; if [ $tn = Dw_AA_swpa-swpa ]; then [ $M = m2 ] && ST=${SWPA_STRIDES:-1 3 5 7} || ST=${SWPA_STRIDES:-7}; fi
  for s in $ST; do job $tc $nt control $s; job $tn $nt test $s; done
done
[ -z "$X" ] && echo "$(date) ALLDONE $SET" >> $PR
