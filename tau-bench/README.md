# tau-bench API/Tool-Call Agent Workload

This directory collects tau-bench style tool-agent-user interaction workloads.

# TODO Before Formal Benchmark Analysis

The current local run proves the API/tool-call agent path works, but it is
still a short local smoke. Before using this workload for formal CPU agent
workload analysis, run a larger standard task set and report reward/pass
metrics.

Required next steps:

- Prefer tau2/tau3-bench for formal analysis because the classic tau-bench
  README says the old airline/retail tasks are outdated.
- Run more than one task, covering at least airline and retail-style
  transaction flows.
- Use a stronger local model such as `qwen3.6:27b` with enough `TAU_MAX_STEPS`,
  then compare against cloud models if needed.
- Report reward/pass rate, E2E latency, turn count, tool-call count, tool/API
  latency, repeated-tool loops, and failure categories.
- Treat `run_tau_smoke.sh` historical-trajectory analysis as workload-shape
  inspection only, not as benchmark evidence.

## What This Benchmark Does

This benchmark represents API/tool-call transaction agents, especially
customer-service agents. A simulated user asks for a real-world service task,
the LLM agent talks with the user, calls domain APIs/tools, updates backend
state, and receives reward/pass based on whether the requested transaction was
completed correctly.

It is not only "booking flights." The classic tau-bench domains include:

- airline: book a flight, change/cancel a reservation, add baggage, handle
  refund/certificate requests, and transfer to a human agent
- retail: look up orders, cancel pending orders, modify address/payment/items,
  and return or exchange delivered products

Typical measurements:

- whether the agent follows policy and asks for required information
- whether it calls the correct tool/API with valid arguments
- whether the backend state transition is correct
- how many turns, tool calls, repeated calls, and failed attempts occur

Why this is the third workload family:

- `knowledge_qa_faiss/` covers retrieval and context construction.
- `SWE-bench/` covers coding-agent execution in a repository.
- `tau-bench/` covers business/tool transaction agents: a simulated user talks
  to an agent, the agent calls domain APIs, and the environment checks whether
  the requested state transition was completed correctly.

## Benchmark Positioning

tau-bench is a benchmark for dynamic conversations between a user simulator and
a language agent equipped with domain-specific API tools and policy guidelines.
The classic repo contains airline and retail domains. Its upstream README now
notes that these tasks are outdated and points to `tau2-bench` / tau3-bench for
latest fixed tasks and new domains, but classic tau-bench is still useful as a
small, MIT-licensed first smoke target.

For architecture/workload study, this family stresses:

- repeated short LLM turns and tool-call decisions
- JSON/function-call construction and parsing
- policy/context scanning over long system prompts
- API/tool dispatch and backend state lookup/update
- transactional correctness rather than pure text answer quality

## Agent-Bench Mode

The target mode is a real agent benchmark:

```text
standard tau-bench task
-> LLM user simulator
-> LLM agent
-> tool/API calls
-> environment state update
-> reward/pass scoring
```

Run entry point:

```bash
workloads/tau-bench/run_tau_agent.sh
```

The local default runs one standard airline task through Ollama/Qwen:

```text
env: airline
task id: 0
agent strategy: tool-calling
model: qwen3:8b
provider: ollama
user simulator: llm, also qwen3:8b
```

Useful overrides:

```bash
MODEL=qwen3.6:27b USER_MODEL=qwen3.6:27b TAU_MAX_STEPS=12 \
workloads/tau-bench/run_tau_agent.sh
```

For cloud comparisons, set `MODEL`, `MODEL_PROVIDER`, `USER_MODEL`, and
`USER_MODEL_PROVIDER` to a provider supported by LiteLLM and configure the
provider credentials in the environment.

The script is intentionally separate from the historical trajectory smoke below
so we do not confuse offline analysis with a real agent run.

## Local Ollama Adapter

The upstream tau-bench runner was installed under:

```text
workloads/tau-bench/upstream/tau-bench-src
```

For local Ollama smoke runs, the local clone has a small compatibility adapter:

- bounded LiteLLM requests via `TAU_LLM_TIMEOUT`, `TAU_LLM_NUM_CTX`, and
  `TAU_LLM_THINK=false`
- `TAU_MAX_STEPS` to keep smoke runs short
- fallback parsing for local models that return a function call as JSON text in
  `content` instead of native `tool_calls`

This does not change task definitions, tools, environment state, or reward
logic. It only makes local OpenAI-compatible/Ollama execution practical.

Latest local smoke result:

```text
command: TAU_MAX_STEPS=6 workloads/tau-bench/run_tau_agent.sh
result: completed, reward=0.0
observed loop: LLM user -> LLM agent -> search_direct_flight tool -> env result
note: qwen3:8b repeated the same flight-search tool, so it did not complete
      the booking task within the short smoke limit.
```

## Historical-Trajectory Smoke

The local smoke run analyzes upstream historical trajectories only. It does not
call an LLM and does not count as the final agent bench.

```bash
workloads/tau-bench/run_tau_smoke.sh
```

Default input:

```text
datasets/historical_trajectories/gpt-4o-airline.json
```

This file contains 200 historical airline task trajectories from the upstream
classic tau-bench repository.

## Full Benchmark Notes

A full official tau-bench run requires an agent model, a user-simulator model,
and provider API keys or compatible local adapters. The upstream command shape
is documented in `upstream/README.md`.

For a later formal run, prefer evaluating tau3/tau2 as the current benchmark
line, while retaining this classic smoke as a stable local parser and workload
sanity check.
