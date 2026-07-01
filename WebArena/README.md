# WebArena Agent Workload

This directory is the planned entry point for web-agent benchmarks.

# TODO Before Formal Benchmark Analysis

This folder is currently a target placeholder, not a completed benchmark run.
Before using it for formal CPU agent workload analysis, install a real
WebArena-compatible runner and run standard web-agent tasks with local LLM.

Required next steps:

- Install or vendor a WebArena / BrowserGym-compatible runner.
- Set up the required reproducible web environments or selected standard task
  subset.
- Connect local Ollama/Qwen first, then optionally compare with cloud models.
- Run real observe -> act -> browser-state-update loops, not offline action
  prediction only.
- Report task success rate, E2E latency, step count, browser action latency,
  DOM/accessibility serialization time, screenshot cost if used, and failure
  categories.
- Keep any tiny browser smoke only as path validation, not as formal benchmark
  evidence.

## What This Benchmark Does

This benchmark represents web-browsing agents. The agent receives a web task,
observes a page through DOM/accessibility tree and sometimes screenshots,
decides browser actions, executes clicks/typing/navigation, and is scored by
whether the web task is completed.

Typical tasks:

- search or navigate a website to find information
- fill forms, update settings, or complete checkout-style workflows in a
  controlled web environment
- interact with dynamic pages where state changes after clicks, typing, or
  navigation
- measure browser-side overhead such as DOM serialization, screenshot capture,
  JS/rendering, and action latency

The primary target is WebArena because it is a standard web-agent benchmark
with reproducible websites, browser interaction, task definitions, and
functional correctness evaluation. BrowserGym can be used later as a runner
layer, and Mind2Web is useful as an offline web-action dataset, but the first
full agent benchmark target should be WebArena-style execution.

## Agent-Bench Definition

A web workload counts as an agent bench only when it has:

- standard task cases
- an LLM-backed agent policy
- a browser or browser-like environment
- observation -> action -> browser state update loop
- final success/failure scoring

Opening a visible desktop browser is not required. On Linux or Mac, the browser
can run headless through Playwright, Selenium, or a benchmark-provided browser
controller.

## Candidate Benchmarks

- WebArena: primary full web-agent target. It uses realistic, reproducible
  websites and evaluates functional task completion.
- VisualWebArena: similar direction, but with stronger visual grounding.
- Mind2Web: broad real-website action dataset; useful, but often closer to
  supervised/offline action prediction than full live execution.
- BrowserGym: useful harness/runtime layer for browser-based agents.

## CPU-Relevant Pressure Points

- browser process startup and sandbox overhead
- DOM extraction, accessibility tree serialization, screenshot capture
- HTML/DOM filtering before sending observations to the LLM
- repeated short observe/act loops
- network and storage IO from web app backends
- JavaScript execution and rendering if using a real browser engine
- orchestration latency between LLM, browser controller, and evaluator

## Current Status

This folder now vendors the canonical WebArena runner under
`upstream/webarena-src` and has a local smoke path that connects to Ollama/Qwen.

Current validated smoke:

```text
config: config_files/examples/2.json
task: Check out the classification section
mode: llm
model: qwen3:8b through Ollama OpenAI-compatible endpoint
score: 1.0
actions: 2
```

Run the default local LLM smoke from repo root:

```bash
workloads/WebArena/run_web_agent.sh
```

Run teacher-forcing browser/evaluator validation:

```bash
MODE=teacher workloads/WebArena/run_web_agent.sh
```

The smoke uses a small WebArena example task that does not require logging into
the full self-hosted WebArena websites. Formal benchmark analysis still needs
the reproducible website environment and a standard WebArena task subset.
