# Terminal-Bench Workload

Terminal-Bench is used here as the terminal/Bash-intensive agent workload
family. It exercises a full command-line agent loop:

1. Read task instruction.
2. Enter a Docker sandbox.
3. Decide shell commands through an LLM agent.
4. Execute commands through a tmux-backed terminal.
5. Run the official task verifier and produce a reward.

This is a stronger workload than a shell microbenchmark because the CPU-side
path includes agent orchestration, terminal IO, process creation, filesystem
metadata access, package/tool setup, and verifier execution.

## TODO for formal workload study

**TODO: move beyond smoke runs.** For a real CPU agent workload study, run a
curated multi-task subset across software engineering, file operations, data
processing, security, and system-administration tasks. Report pass rate,
wall-clock latency, LLM wait time, sandbox setup time, command count, verifier
time, process/syscall profile, filesystem IO, and memory/RSS peaks.

## What this benchmark is for

Terminal-Bench tasks are command-line tasks executed in isolated environments.
Examples include recovering Git history, editing files, debugging builds,
processing logs, configuring services, and running scientific or ML utilities.
It is useful for CPU agent workload work because many agent actions become
host-side terminal operations rather than pure LLM decode.

## Local status

Environment status:

- Harbor installed through `uv tool install harbor`.
- Docker runs through Colima on this Mac.
- Terminal-Bench 2 dataset downloaded under `upstream/terminal-bench-2`.
- Results are written under `results/` and ignored by git.

Verified runs:

- `fix-git` oracle: passed, reward `1.0`.
  Result: `results/2026-06-16__17-49-04/result.json`.
- `fix-git` with Terminus2 + local `qwen3:8b`: completed the full agent
  chain, but reward was `0.0`. The model explored `git status`, `git reflog`,
  and related commands but did not complete the recovery/merge.
  Result: `results/2026-06-16__17-40-56/result.json`.
- `regex-log` with Terminus2 + local `qwen3:8b`: completed the full agent
  chain, but reward was `0.0`; the first generated regex was incorrect and the
  agent did not recover.

Interpretation: the harness path is working; local small-model task success is
not yet established. For formal agent benchmarking, either use a stronger local
model, a cloud model, or a more capable terminal agent policy.

## Run commands

Run a local LLM agent on the default easy task:

```bash
workloads/Terminal-Bench/run_terminal_bench_agent.sh
```

Run the oracle verifier path on the same task:

```bash
workloads/Terminal-Bench/run_terminal_bench_oracle.sh
```

Override task/model when needed:

```bash
TB_TASK=regex-log TB_MODEL=qwen3.6:27b TB_MAX_TURNS=8 \
  workloads/Terminal-Bench/run_terminal_bench_agent.sh
```

The default agent script uses Ollama through LiteLLM:

- `OLLAMA_API_BASE=http://127.0.0.1:11434`
- Harbor model name: `ollama/<TB_MODEL>`

## Notes

- `fix-git` is an easy software-engineering task. It tests Git recovery from
  detached HEAD/reflog state and merging the recovered changes into `master`.
- `regex-log` is a medium data-processing task. It is useful later as a more
  difficult text/log-processing terminal task.
- Some tasks pull or run x86_64 containers under QEMU on Apple Silicon; those
  can be much slower than native arm64 tasks.
