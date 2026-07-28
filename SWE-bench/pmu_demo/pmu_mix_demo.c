#define _GNU_SOURCE

#include <immintrin.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

static volatile uint64_t integer_sink;
static volatile double fp_sink;

static uint64_t now_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000000000ULL + (uint64_t)ts.tv_nsec;
}

__attribute__((noinline))
static uint64_t integer_kernel(uint64_t state, uint64_t iterations) {
    uint64_t sum = state ^ 0x9e3779b97f4a7c15ULL;
    for (uint64_t i = 0; i < iterations; ++i) {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        state *= 0xd6e8feb86659fd93ULL;
        sum += (state ^ (state >> 29)) + i;
    }
    integer_sink = sum;
    return state ^ sum;
}

__attribute__((noinline, optimize("no-if-conversion,no-if-conversion2")))
static uint64_t branch_kernel(uint64_t state, uint64_t iterations) {
    uint64_t sum = state;
    for (uint64_t i = 0; i < iterations; ++i) {
        state ^= state << 13;
        state ^= state >> 7;
        state ^= state << 17;
        if (state & 1) {
            sum += state + i;
        } else {
            sum ^= state - i;
        }
    }
    integer_sink = sum;
    return state ^ sum;
}

__attribute__((noinline))
static double fp_kernel(uint64_t iterations) {
    __m512d a = _mm512_set1_pd(1.00000011920928955078125);
    __m512d b = _mm512_set1_pd(1.000000059604644775390625);
    __m512d c0 = _mm512_set1_pd(0.25);
    __m512d c1 = _mm512_set1_pd(0.50);
    __m512d c2 = _mm512_set1_pd(0.75);
    __m512d c3 = _mm512_set1_pd(1.00);
    for (uint64_t i = 0; i < iterations; ++i) {
        c0 = _mm512_fmadd_pd(a, b, c0);
        c1 = _mm512_fmadd_pd(b, a, c1);
        c2 = _mm512_fmadd_pd(a, b, c2);
        c3 = _mm512_fmadd_pd(b, a, c3);
        a = _mm512_add_pd(a, _mm512_set1_pd(1.0e-15));
        b = _mm512_sub_pd(b, _mm512_set1_pd(1.0e-15));
    }
    __m512d sum01 = _mm512_add_pd(c0, c1);
    __m512d sum23 = _mm512_add_pd(c2, c3);
    double result = _mm512_reduce_add_pd(_mm512_add_pd(sum01, sum23));
    fp_sink = result;
    return result;
}

static void run_mode(const char *mode, double seconds) {
    const uint64_t deadline = now_ns() + (uint64_t)(seconds * 1.0e9);
    uint64_t state = 0x123456789abcdef0ULL;
    double result = 0.0;

    while (now_ns() < deadline) {
        if (strcmp(mode, "int") == 0) {
            state = integer_kernel(state, 1U << 18);
        } else if (strcmp(mode, "fp") == 0) {
            result += fp_kernel(1U << 16);
        } else if (strcmp(mode, "branch") == 0) {
            state = branch_kernel(state, 1U << 18);
        } else if (strcmp(mode, "mixed") == 0) {
            state = integer_kernel(state, 1U << 16);
            result += fp_kernel(1U << 14);
            state = branch_kernel(state, 1U << 16);
        } else {
            fprintf(stderr, "unknown mode: %s\n", mode);
            exit(2);
        }
    }

    printf(
        "mode=%s seconds=%.3f integer_sink=%llu fp_sink=%.6f state=%llu result=%.6f\n",
        mode,
        seconds,
        (unsigned long long)integer_sink,
        fp_sink,
        (unsigned long long)state,
        result
    );
}

int main(int argc, char **argv) {
    if (argc != 3) {
        fprintf(stderr, "usage: %s int|fp|branch|mixed SECONDS\n", argv[0]);
        return 2;
    }
    char *end = NULL;
    double seconds = strtod(argv[2], &end);
    if (end == argv[2] || *end != '\0' || seconds <= 0.0) {
        fprintf(stderr, "SECONDS must be positive\n");
        return 2;
    }
    run_mode(argv[1], seconds);
    return 0;
}
