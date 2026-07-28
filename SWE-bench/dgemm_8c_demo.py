#!/usr/bin/env python3
import argparse
import os
import time


def parse_cpu_list(value: str) -> set[int]:
    cpus: set[int] = set()
    for part in value.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(item) for item in part.split("-", 1))
            cpus.update(range(start, end + 1))
        else:
            cpus.add(int(part))
    if not cpus:
        raise ValueError("CPU list must not be empty")
    return cpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Sustained DGEMM workload for PMU validation")
    parser.add_argument("--cpus", default="0-7")
    parser.add_argument("--threads", type=int, default=8)
    parser.add_argument("--size", type=int, default=6144)
    parser.add_argument("--seconds", type=float, default=50.0)
    args = parser.parse_args()

    cpus = parse_cpu_list(args.cpus)
    os.sched_setaffinity(0, cpus)
    for variable in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "BLIS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        os.environ[variable] = str(args.threads)
    os.environ["OPENBLAS_DYNAMIC"] = "0"
    os.environ["OMP_DYNAMIC"] = "FALSE"

    import numpy as np

    matrix_bytes = 3 * args.size * args.size * np.dtype(np.float64).itemsize
    print(
        f"DGEMM start: pid={os.getpid()} affinity={sorted(os.sched_getaffinity(0))} "
        f"threads={args.threads} size={args.size} duration={args.seconds:.1f}s "
        f"matrix_memory={matrix_bytes / (1024 ** 3):.2f}GiB",
        flush=True,
    )

    a = np.ones((args.size, args.size), dtype=np.float64)
    b = np.ones((args.size, args.size), dtype=np.float64)
    c = np.empty_like(a)

    np.matmul(a, b, out=c)
    flop_per_iteration = 2.0 * args.size**3
    start = time.perf_counter()
    last_report = start
    iterations = 0

    while time.perf_counter() - start < args.seconds:
        np.matmul(a, b, out=c)
        iterations += 1
        now = time.perf_counter()
        if now - last_report >= 5.0:
            elapsed = now - start
            gflops = iterations * flop_per_iteration / elapsed / 1e9
            print(
                f"progress: elapsed={elapsed:.1f}s iterations={iterations} "
                f"average={gflops:.1f}GFLOP/s",
                flush=True,
            )
            last_report = now

    elapsed = time.perf_counter() - start
    gflops = iterations * flop_per_iteration / elapsed / 1e9
    checksum = float(c[0, 0] + c[-1, -1])
    print(
        f"DGEMM done: elapsed={elapsed:.3f}s iterations={iterations} "
        f"average={gflops:.1f}GFLOP/s checksum={checksum:.1f}",
        flush=True,
    )


if __name__ == "__main__":
    main()
