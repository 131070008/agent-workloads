# SWE-bench Lite Smoke

Local smoke input for software-engineering agent workloads.

## Contents

```text
raw/swe-bench_lite-test.arrow
raw/swe-bench_lite-dev.arrow
raw/dataset_info.json
cases/smoke_cases.jsonl
cases/known_passed_local.txt
```

## Current Smoke Case

```text
instance: pallets__flask-4045
repo: pallets/flask
status on local run: Submitted
wall time on local run: 925.9s
```

## Why Lite First

SWE-bench Lite is the right first target because it is standard, small enough to
vendor for smoke testing, and already works with the current local runner.
Verified or larger variants should be added later after storage and license
review.
