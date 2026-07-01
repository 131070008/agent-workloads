# WorkArena Workload

WorkArena is the enterprise / knowledge-work agent workload family. It is built
on ServiceNow and BrowserGym, and focuses on routine enterprise software tasks
rather than generic browsing or terminal work.

This fills the enterprise slot in the workload taxonomy:

- `tau-bench`: tool/API transaction and backend state update.
- `WebArena`: general web navigation and web task completion.
- `OSWorld`: desktop/GUI computer-use tasks.
- `WorkArena`: enterprise SaaS workflows: knowledge base, forms, service
  catalog, lists, menus, dashboards, and compositional business tasks.

## TODO for formal workload study

**TODO: obtain ServiceNow instance access and run an LLM agent through
BrowserGym/AgentLab.** WorkArena requires gated ServiceNow instances from
Hugging Face and browser automation. After access is configured, run a small
L1/L2 subset and report success rate, step count, wall-clock latency, browser
observation cost, DOM/a11y extraction cost, API/network wait, form/list action
latency, verifier latency, and memory/RSS peaks.

## What this benchmark is for

Enterprise agents are important because they exercise the path between LLM
planning and real business software:

- Querying and reading a company knowledge base.
- Filling structured enterprise forms.
- Ordering items from a service catalog.
- Filtering lists and navigating menus.
- Reading dashboards and charts.
- Executing multi-step compositional workflows over enterprise UI state.

This is the closest workload category to internal copilots, service-desk
automation, ITSM/CRM-like workflows, and enterprise process agents.

## Local status

Current state:

- Official WorkArena repository cloned to `upstream/WorkArena`.
- Upstream snapshot: `ServiceNow/WorkArena` commit `a772230`.
- Upstream license: Apache-2.0.
- Local full execution has not been completed.

Reason: WorkArena requires access to ServiceNow instances through the gated
`ServiceNow/WorkArena-Instances` dataset on Hugging Face. Without those
instances, the framework code can be installed and inspected, but real
benchmark tasks cannot be executed correctly.

## Run commands

Install/check the local package after creating a Python environment:

```bash
workloads/WorkArena/setup_workarena_local.sh
```

After ServiceNow access is configured, run the upstream oracle demo:

```bash
workloads/WorkArena/run_workarena_oracle_demo.sh
```

For real LLM-agent evaluation, use AgentLab + BrowserGym as recommended by the
upstream project. This workload intentionally does not claim a local pass until
ServiceNow instances and an agent runner are configured.

## Enterprise workload signal

For CPU agent workload research, WorkArena should be profiled as a browser/SaaS
enterprise execution plane:

- browser process and Playwright control overhead;
- DOM/a11y extraction and screenshot/visual observation cost;
- network wait and backend state transitions;
- long-horizon action planning and retries;
- structured form/list manipulation;
- verifier and business-rule evaluation.
