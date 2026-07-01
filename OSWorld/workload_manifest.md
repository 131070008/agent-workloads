# OSWorld Manifest

## Workload role

- Category: desktop / GUI / computer-use agent workload.
- Benchmark framework: OSWorld / OSWorld-Verified.
- Upstream snapshot: `xlang-ai/OSWorld` commit `fe8c78e1`.
- Test cases: upstream `evaluation_examples/*.json`.
- Observation spaces: screenshot, accessibility tree, screenshot + a11y tree,
  and set-of-mark style observations.
- Action spaces: pyautogui-style actions and OSWorld enumerated actions.
- Environment: VMware/VirtualBox/AWS/Docker provider managing desktop VMs.
- Scoring path: execution-based task evaluation from OSWorld.

## Representative domains

| Domain | Examples | CPU/host pressure |
| --- | --- | --- |
| Browser / Chrome | Website navigation, web app interactions | Screenshot capture, DOM/a11y extraction, network wait, GUI event dispatch. |
| LibreOffice | Writer, Calc, Impress document tasks | Application launch, file IO, document parsing/rendering, GUI state. |
| Multi-app | Cross-application desktop workflows | Long action loops, context/state tracking, window management. |
| OS / files | Desktop settings and file operations | Filesystem metadata, process launch, VM state, shell/GUI crossover. |
| VS Code | IDE/code editing operations | Editor startup, file tree IO, terminal integration, UI automation. |

## Why it matters for CPU agent workload

OSWorld exposes an agent path where CPU is not just feeding an LLM. The host
CPU manages VM/sandbox lifecycle, captures observations, serializes images and
accessibility trees, dispatches GUI actions, starts desktop apps, handles file
and document IO, and runs execution-based verifiers.

This is a good candidate for AI workstation or client-side agent workload
analysis, especially if combined with local multimodal models or remote/cloud
LLMs.

## Current evidence

- Upstream framework cloned locally.
- Local full execution is pending VM/provider setup.
- This should be treated as a prepared workload family, not a passed benchmark
  run yet.

## Formal-study TODO

- Prepare VMware Fusion VM on macOS or Docker/KVM on Linux.
- Run `evaluation_examples/test_small.json` first.
- Split results by domain and task length.
- Capture host metrics: CPU utilization, memory/RSS, screenshot latency,
  a11y-tree latency, action dispatch latency, VM reset latency, app launch
  time, file IO, and verifier time.
