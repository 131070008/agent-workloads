# tau-bench Workload Manifest

## Workload Family

- Name: `tau-bench`
- Type: tool/API transaction agent workload
- Upstream: https://github.com/sierra-research/tau-bench
- Current successor to track: https://github.com/sierra-research/tau2-bench
- License: MIT

## Current Local Asset

```text
datasets/historical_trajectories/gpt-4o-airline.json
```

Source:

```text
https://raw.githubusercontent.com/sierra-research/tau-bench/main/historical_trajectories/gpt-4o-airline.json
```

## Agent Command

```bash
workloads/tau-bench/run_tau_agent.sh
```

This is the target benchmark path. It should run standard tau-bench tasks with
an LLM-backed user simulator, an LLM-backed tool-calling agent, tool/API
execution, environment state updates, and reward/pass scoring.

Local default:

```text
env=airline
task_ids=0
model=qwen3:8b
model_provider=ollama
user_model=qwen3:8b
user_model_provider=ollama
```

Validated local smoke:

```text
TAU_MAX_STEPS=6 workloads/tau-bench/run_tau_agent.sh
completed with reward=0.0
trajectory included LLM-generated tool calls and real search_direct_flight
environment tool execution.
```

## Historical Smoke Command

```bash
workloads/tau-bench/run_tau_smoke.sh
```

This is offline trajectory analysis only. It is useful for workload shape
inspection but is not the final agent benchmark.

## Measured/Derived Fields

Agent run:

- task success / reward
- E2E latency
- number of user-agent turns
- number of tool calls
- tool/API latency
- LLM generation latency
- failure type

Historical smoke:

- number of tasks
- reward/pass count from historical run metadata
- message count per task
- user/assistant/tool-result turns
- top tool names and target actions

## CPU-Relevant Pressure Points

- orchestration loop overhead across many short turns
- JSON/tool-call parse and validation
- policy/system-prompt context scan
- backend state lookup and transactional update path
- latency sensitivity from sequential user-agent-tool dependencies
