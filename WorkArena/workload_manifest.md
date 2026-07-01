# WorkArena Manifest

## Workload role

- Category: enterprise / knowledge-work SaaS agent workload.
- Benchmark framework: WorkArena and WorkArena++ through BrowserGym.
- Upstream snapshot: `ServiceNow/WorkArena` commit `a772230`.
- Test cases: WorkArena-L1 atomic tasks and WorkArena++ compositional tasks.
- Environment: ServiceNow instances plus browser automation.
- Agent path: BrowserGym / AgentLab recommended by upstream.
- Scoring path: task-specific validation over ServiceNow UI/backend state.

## Representative task families

| Task family | What it does | CPU/host pressure |
| --- | --- | --- |
| Knowledge base | Search and answer from company KB pages. | Browser navigation, DOM/a11y extraction, text parsing, network wait. |
| Forms | Fill complex ServiceNow forms with specified fields. | DOM interaction, input dispatch, validation, retry loops. |
| Service catalog | Order items with specific configurations. | Multi-step UI state, backend transaction, form/list interaction. |
| Lists | Filter and inspect enterprise records. | Table parsing, filter UI manipulation, state validation. |
| Menus | Navigate enterprise app menus. | UI search/navigation, action latency, observation parsing. |
| Dashboards | Read charts and answer business questions. | Visual/chart parsing, screenshot cost, simple reasoning. |
| WorkArena++ | Compose atomic tasks into real workflows. | Long-horizon planning, memory, retries, backend state updates. |

## Why it matters for CPU agent workload

Enterprise agents spend substantial time outside pure LLM decode. The host CPU
drives browser automation, extracts DOM/accessibility state, serializes
observations, handles SaaS network waits, dispatches UI actions, and evaluates
business-state correctness. This makes WorkArena a useful benchmark for
enterprise copilots and internal process automation.

## Current evidence

- Upstream framework cloned locally.
- Local full execution is pending gated ServiceNow instance access.
- This is a prepared workload family, not a passed benchmark run yet.

## Formal-study TODO

- Request and configure `ServiceNow/WorkArena-Instances` access.
- Install `browsergym-workarena` and Playwright browsers.
- Run a small L1 subset first, then WorkArena++ L2 compositional tasks.
- Capture host metrics: browser CPU/RSS, Playwright overhead, DOM/a11y capture,
  screenshot latency, network wait, action latency, verifier latency, retries,
  and total wall-clock time.
