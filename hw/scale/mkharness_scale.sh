#!/bin/sh
# Level 3, Sec 8: builds the harness of the long runs (tab:scale) from tests/typed/, for the tests and controls of
# tests/scale_rows.tsv, with the flags of the runs in the report:
#   Linux (m1, m2):  litmus7 -os linux -a 4 -mode std -barrier user -st 1, -march=armv8.4-a, patch_mode.py mode hook
#                    -> scale/harness_linux/
#   macOS (M2 Max):  litmus7 -os mac   -a 4 -s 100000 -mode std -barrier user -st 1, Arm-mode (AA, AAA) tests only
#                    (macOS has no per-thread TSO bit) -> scale/harness_macos/
# Usage: sh scale/mkharness_scale.sh linux|macos   (from hw/; set L7 if litmus7 is not at ~/.opam/default/bin/litmus7)
set -e
cd "$(dirname "$0")"; OS=${1:?linux|macos}
L7=${L7:-$HOME/.opam/default/bin/litmus7}; T=../../tests
names=$(awk -F'\t' 'NR>1{print $5; print $6}' $T/scale_rows.tsv | sort -u)
[ $OS = macos ] && names=$(echo "$names" | grep -v -e '_T' -e '^n6_AT_')   # Arm-mode tests only
d=harness_$OS; rm -rf $d src_$OS; mkdir -p $d src_$OS
for n in $names; do cp $T/typed/$n.litmus src_$OS/; done
case $OS in
  linux) $L7 -os linux -a 4 -mode std -barrier user -st 1 -o $d src_$OS/*.litmus 2> $d/litmus7.err
         sed 's/^GCCOPTS=.*/GCCOPTS=-D_GNU_SOURCE -Wall -std=gnu99 -O2 -pthread -march=armv8.4-a/' $d/Makefile > $d/Makefile.tmp && mv $d/Makefile.tmp $d/Makefile
         python3 ../patch_mode.py $d ../modes_all.tsv > $d/patch.log
         echo "$d: $(ls $d/*.c | wc -l) .c files, $(grep -c '^patched' $d/patch.log) patched";;
  macos) $L7 -os mac -a 4 -s 100000 -mode std -barrier user -st 1 -o $d src_$OS/*.litmus 2> $d/litmus7.err
         echo "$d: $(ls $d/*.c | wc -l) .c files";;
  *) echo "usage: sh mkharness_scale.sh linux|macos"; exit 1;;
esac
