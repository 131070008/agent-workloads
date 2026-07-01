# Terminal-Bench Manifest

## Workload role

- Category: terminal / Bash / system-operation agent workload.
- Benchmark framework: Terminal-Bench through Harbor.
- Test cases: official Terminal-Bench 2 tasks downloaded into
  `upstream/terminal-bench-2`.
- LLM path: Terminus2 agent through LiteLLM + local Ollama.
- Sandbox path: Docker container per task, running under Colima on macOS.
- Scoring path: official task verifier, reward in `result.json`.

## Representative tasks

| Task | Difficulty | Category | Why keep it |
| --- | --- | --- | --- |
| `fix-git` | easy | software-engineering | Good smoke for git, shell commands, filesystem metadata, verifier path. |
| `regex-log` | medium | data-processing | Good terminal/log-processing task; exposes model command quality issues. |
| `log-summary-date-ranges` | medium | data-processing | Candidate for later IO/text-processing profile. |
| `headless-terminal` | medium | software-engineering | Candidate for terminal-control behavior. |

## CPU-side signals to collect later

- Sandbox/container setup latency.
- Agent command count and command mix.
- Shell/process creation rate.
- Filesystem metadata and small-file IO.
- Package install/build time where tasks require it.
- Verifier runtime.
- LLM wait time versus host-side execution time.
- Peak RSS and memory spikes across agent, Docker, and verifier phases.

## Current evidence

- Oracle path passes `fix-git`: reward `1.0`.
- Local Ollama `qwen3:8b` path executes the full agent loop but did not pass
  `fix-git` or `regex-log` in the first local smoke attempts.
- The failure mode is not environment failure: commands are sent, trajectory is
  recorded, verifier runs, and reward is produced.
