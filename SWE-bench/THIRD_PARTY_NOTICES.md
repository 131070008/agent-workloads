# Third-Party Notices

## SWE-bench Lite

This workload includes a local copy of SWE-bench Lite Arrow data for smoke
testing.

- Dataset family: SWE-bench
- Local copy:
  `workloads/SWE-bench/datasets/swe_bench_lite_smoke/raw/`
- Intended use: internal workload exploration and local smoke testing.

Before redistribution outside internal research, verify the upstream dataset
license, citation requirements, and any restrictions on repository-derived
problem statements and patches.

## mini-SWE-agent runner dependency

The current harness invokes the local mini-SWE-agent benchmark runner under:

```text
cpu-centric-agentic-ai/mini-swe-agent/
```

That source tree is part of the MIT-licensed `cpu-centric-agentic-ai` project:

```text
cpu-centric-agentic-ai/LICENSE
```

The workload harness in this directory is intentionally separated from the
runner dependency so the runner can later be replaced.

## Candidate: SWE-rebench

SWE-rebench is tracked as a candidate future dataset/workload extension. It is
not vendored into this repository in the first smoke version because it is
larger and should be added with a dedicated license/data review.
