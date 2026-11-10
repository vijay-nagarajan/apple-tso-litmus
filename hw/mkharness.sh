#!/bin/sh
# Generation step: builds harness/std_user and harness/std_timebase from tests/typed/ (litmus7 -mode std -a 4,
# -march=armv8.4-a) and inserts the mode hook with patch_mode.py.
set -e
cd "$(dirname "$0")"; ln -sfn ../tests/typed typed
L7=${L7:-$HOME/.opam/default/bin/litmus7}
PATCH=./patch_mode.py
[ "$(ls typed | wc -l)" -eq "$(wc -l < runlist_all.txt)" ] || { echo "typed/ and runlist_all.txt disagree"; exit 1; }
mkdir -p harness
for b in ${BARRIERS:-user timebase}; do
  d=harness/std_$b; rm -rf $d; mkdir $d
  $L7 -os linux -a 4 -mode std -barrier $b -o $d typed/*.litmus 2> $d/litmus7.err
  sed 's/^GCCOPTS=.*/GCCOPTS=-Wall -std=gnu99 -O2 -pthread -march=armv8.4-a/' $d/Makefile > $d/Makefile.tmp && mv $d/Makefile.tmp $d/Makefile
  python3 $PATCH $d modes_all.tsv > $d/patch.log
  echo "$d: $(ls $d/*.c | wc -l) .c files, $(grep -c '^patched' $d/patch.log) patched, litmus7.err $(wc -l < $d/litmus7.err) lines"
done
