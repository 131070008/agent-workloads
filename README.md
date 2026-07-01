# Agent Workload Harnesses

This directory collects workload harnesses for agent/CPU workload studies.

The intent is to keep benchmark drivers separate from datasets. A dataset such
as BEIR/SciFact, NQ, HotpotQA, or TriviaQA is an input. A workload harness
defines how to run that input, which phases to measure, and which CPU-side
signals matter.

Initial workload families:

- `knowledge_qa_faiss/`: Knowledge QA / RAG agent path built around embedding,
  FAISS search, document fetch, context construction, and LLM answer generation.
- `SWE-bench/`: SWE-bench Lite smoke workload for coding-agent execution.
- `tau-bench/`: Tool/API transaction workload for user-agent-tool interaction
  with airline/retail-style backend state transitions.
- `WebArena/`: Web-agent workload for browser observation/action loops and
  functional task completion.
- `Terminal-Bench/`: Terminal/Bash-intensive agent workload for command-line
  tasks in Docker sandboxes with official verifier rewards.
- `OSWorld/`: Desktop/GUI computer-use workload for screenshot/a11y
  observation, GUI actions, application workflows, and VM-backed evaluation.
- `WorkArena/`: Enterprise SaaS / knowledge-work workload for ServiceNow-style
  business workflows, forms, knowledge bases, lists, dashboards, and
  compositional enterprise tasks.
