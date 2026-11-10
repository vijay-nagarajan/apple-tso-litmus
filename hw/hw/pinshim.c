/* LD_PRELOAD shim: spread litmus7 worker threads one-per-CPU within the process's allowed mask.
   Why: on Asahi M2 with a mixed E+P taskset mask, Linux EAS can stack two spin-barrier threads on one
   CPU (seen: 2 threads at 50% on cpu5, cpu0 idle) -> each barrier round needs a context switch -> 100-1000x
   slowdown. Each new thread is pinned to the least-loaded allowed CPU (ties broken at random, so the
   test-thread -> core-type mapping varies across runs). PIN_SKIP=k leaves the first k threads created by
   the main thread unpinned (litmus7's sleeping zyva helper threads, n_exe-1 of them). */
#define _GNU_SOURCE
#include <pthread.h>
#include <sched.h>
#include <dlfcn.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/syscall.h>
static int (*real_create)(pthread_t*,const pthread_attr_t*,void*(*)(void*),void*);
static int cpus[CPU_SETSIZE], ncpu = -1, load[CPU_SETSIZE], skip;
static pthread_mutex_t mu = PTHREAD_MUTEX_INITIALIZER;
static unsigned seed;
typedef struct { void *(*f)(void*); void *a; int cpu; } box_t;
static void *tramp(void *p) {
  box_t b = *(box_t*)p; free(p);
  if (b.cpu >= 0) { cpu_set_t s; CPU_ZERO(&s); CPU_SET(b.cpu,&s); sched_setaffinity(0,sizeof s,&s); }
  void *r = b.f(b.a);
  if (b.cpu >= 0) { pthread_mutex_lock(&mu); load[b.cpu]--; pthread_mutex_unlock(&mu); }
  return r;
}
int pthread_create(pthread_t *t, const pthread_attr_t *at, void *(*f)(void*), void *a) {
  pthread_mutex_lock(&mu);
  if (!real_create) real_create = dlsym(RTLD_NEXT,"pthread_create");
  if (ncpu < 0) {
    cpu_set_t s; sched_getaffinity(0,sizeof s,&s); ncpu = 0;
    for (int c = 0; c < CPU_SETSIZE; c++) if (CPU_ISSET(c,&s)) cpus[ncpu++] = c;
    char *e = getenv("PIN_SKIP"); skip = e ? atoi(e) : 0; seed = getpid();
  }
  box_t *b = malloc(sizeof *b); b->f = f; b->a = a; b->cpu = -1;
  if (syscall(SYS_gettid) == getpid() && skip > 0) skip--;
  else if (ncpu > 1) {
    int st = rand_r(&seed) % ncpu, best = -1;
    for (int i = 0; i < ncpu; i++) { int c = cpus[(st+i)%ncpu]; if (best < 0 || load[c] < load[best]) best = c; }
    b->cpu = best; load[best]++;
  }
  pthread_mutex_unlock(&mu);
  return real_create(t,at,tramp,b);
}
