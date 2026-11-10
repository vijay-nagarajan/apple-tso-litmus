#!/usr/bin/env python3
"""Insert a per-role memory-model hook into litmus7 (-mode presi) generated tests.

litmus7 re-assigns roles (P0, P1, ...) to OS threads in set_role(); we set the calling
thread's memory model right after its role is final, so the TSO bit follows the role.
Asahi per-thread TSO: prctl(PR_SET_MEM_MODEL, 1=TSO / 0=default), verified with
PR_GET_MEM_MODEL on every call; any mismatch aborts the run.
Usage: patch_mode.py <litmus7 dir> <modes.tsv>
"""
import sys, os

HOOK_DEFS = r'''
/* ---- per-role memory-model hook (patch_mode.py) ---- */
#include <sys/prctl.h>
#define PR_GET_MEM_MODEL 0x6d4d444c
#define PR_SET_MEM_MODEL 0x4d4d444c
#define TSO_MASK %d
static long mm_sets[2];
static void mm_report(void) {
  fprintf(stderr, "MEMMODEL mask=%%d arm_sets=%%ld tso_sets=%%ld\n", TSO_MASK, mm_sets[0], mm_sets[1]);
}
static void set_mem_model(int role) {
  static int once;
  if (!__atomic_exchange_n(&once, 1, __ATOMIC_SEQ_CST)) atexit(mm_report);
  long want = (role >= 0 && ((TSO_MASK >> role) & 1)) ? 1 : 0;
  if (prctl(PR_SET_MEM_MODEL, want, 0, 0, 0) != 0) { perror("PR_SET_MEM_MODEL"); exit(2); }
  long got = prctl(PR_GET_MEM_MODEL, 0, 0, 0, 0);
  if (got != want) { fprintf(stderr, "MEMMODEL mismatch role=%%d want=%%ld got=%%ld\n", role, want, got); exit(2); }
  __atomic_add_fetch(&mm_sets[want], 1, __ATOMIC_RELAXED);
}
/* ---- end hook ---- */
'''

ANCHOR = "#ifdef KVM\n    set_feature(c->role) ;"

def main(d, tsv):
    masks = {}
    for line in open(tsv).read().splitlines()[1:]:
        name, mask = line.split("\t")[:2]
        masks[name] = int(mask)
    for name, mask in masks.items():
        p = os.path.join(d, name + ".c")
        if not os.path.exists(p):
            continue
        src = open(p).read()
        if "set_mem_model" in src:
            continue
        if src.count(ANCHOR) == 1:            # -mode presi: roles move between OS threads
            src = src.replace(ANCHOR, "    set_mem_model(c->role) ;\n" + ANCHOR)
        else:                                 # -mode std: one function per role, P<k>(void *_vb)
            import re
            fns = re.findall(r"static void \*P(\d+)\(void \*_vb\) \{\n", src)
            assert fns, f"{name}: no presi or std anchor"
            src = re.sub(r"(static void \*P(\d+)\(void \*_vb\) \{\n)",
                         lambda m: m.group(1) + f"  set_mem_model({m.group(2)}) ;\n", src)
        # place definitions after the last top-level #include of the preamble
        i = src.index("#include", 0)
        j = src.index("\n", src.rindex("#include", 0, src.index("static", i))) + 1
        src = src[:j] + HOOK_DEFS % mask + src[j:]
        open(p, "w").write(src)
        print(f"patched {name} mask={mask}")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
