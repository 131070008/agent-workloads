# Knowledge QA / RAG Agent Workload

This is the harness area for knowledge QA / RAG-style agent workloads.

# TODO Before Formal Benchmark Analysis

Before using this workload for formal CPU agent workload analysis, add
answer-level scoring. The current objective evaluator scores retrieval quality
against BEIR/SciFact qrels, but formal RAG workflow evaluation also needs to
judge whether the LLM's final answer is correct.

Required next steps:

- Add SciFact answer scoring for `SUPPORT` / `CONTRADICT` / insufficient
  evidence labels.
- Report answer accuracy together with retrieval metrics and latency.
- Expand beyond the local SciFact smoke corpus when needed, for example BEIR
  multi-dataset runs or NQ / HotpotQA / TriviaQA style QA sets.
- Keep retrieval-only results as phase microbench data, not as the final
  workflow benchmark result.

## What This Benchmark Does

This benchmark represents a knowledge-base question answering / RAG workflow.
A user asks a question or gives a claim, the host side embeds the query,
searches a FAISS/vector index, fetches evidence documents, builds context, and
sends the augmented prompt to an LLM to generate an answer.

Typical tasks:

- answer questions over a document corpus
- verify scientific claims using retrieved evidence
- measure whether retrieval finds the right evidence and whether the final
  LLM answer is correct

Important distinction:

- BEIR, SciFact, NQ, HotpotQA, TriviaQA: datasets / query sets.
- FAISS, HNSW, Flat, IVF: vector-index implementations.
- `run_retrieval_only.sh`: phase microbench for embedding, FAISS search, and
  doc fetch.
- `run_rag_agent.sh`: knowledge QA agent bench path with retrieval, context
  construction, LLM generation, and answer output.

Under our current definition, a knowledge QA workload can count as an agent
bench when it has standard cases, an LLM-backed answer path, tool/retrieval
execution, and measurable outputs. It does not have to be multi-turn.

## Workload Path

```text
query set
-> embedding model
-> FAISS index search
-> document fetch
-> context construction
-> LLM generation
-> answer / evidence / timing output
```

For CPU analysis, keep both levels:

- Retrieval-only isolates embedding, FAISS search, and document fetch.
- RAG agent mode captures the actual knowledge QA path users care about:
  retrieval plus LLM answer generation.

## Current Smoke Dataset

The current local smoke input is BEIR/SciFact:

```text
corpus docs: 5183
queries: workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke/queries/evidence_5.txt
index: workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke/prebuilt_store/faiss/flat.index
```

The dataset and prebuilt smoke index now live under
`workloads/knowledge_qa_faiss/datasets/`.

## Run

From repo root:

Run the RAG agent bench with local Ollama/OpenAI-compatible endpoint:

```bash
workloads/knowledge_qa_faiss/run_rag_agent.sh
```

Run the self-contained GLM smoke path. This is the current quick path for
validating retrieval plus cloud LLM generation without the external Haystack
wrapper:

```bash
workloads/knowledge_qa_faiss/setup_glm_smoke_env.sh
export ZHIPU_API_KEY='<your-bigmodel-key>'
workloads/knowledge_qa_faiss/run_glm_smoke.sh
```

Defaults:

```text
LLM endpoint: https://open.bigmodel.cn/api/paas/v4/chat/completions
LLM model: glm-4.5-air
queries: datasets/beir_scifact_smoke/queries/evidence_5.txt, first 2 claims
output: terminal only unless --output-jsonl is set
```

Run retrieval-only phase timing:

```bash
workloads/knowledge_qa_faiss/run_retrieval_only.sh
```

Run SciFact retrieval scoring against BEIR qrels:

```bash
workloads/knowledge_qa_faiss/run_scifact_retrieval_eval.sh
```

Run the full qrels-backed SciFact test set:

```bash
workloads/knowledge_qa_faiss/run_scifact_retrieval_eval.sh \
  --query-file workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke/queries/scifact_qrels_test_all.tsv \
  --output-json workloads/knowledge_qa_faiss/results/scifact_retrieval_eval_all.json
```

The retrieval-only Python harness is local to this workload folder:

```text
workloads/knowledge_qa_faiss/retrieval_only.py
```

The RAG agent wrapper currently calls the RAG harness under
`cpu-centric-agentic-ai/haystack/retrieval.py` and uses the SciFact smoke data
under `workloads/knowledge_qa_faiss/datasets/`.

## License Notes

The retrieval harness was derived from the MIT-licensed `cpu-centric-agentic-ai`
codebase. See `THIRD_PARTY_NOTICES.md` for attribution and compliance notes.

Override paths as needed:

```bash
QUERY_FILE=cpu-centric-agentic-ai/data/scifact_queries_evidence_5.txt \
STORE_DIR=cpu-centric-agentic-ai/data/scifact_store \
workloads/knowledge_qa_faiss/run_retrieval_only.sh
```

## Metrics To Keep

- `embed`: query embedding latency
- `search`: FAISS search latency
- `doc_fetch`: SQLite/doc shard fetch latency
- `llm_generate`: answer generation latency
- `total_e2e`: end-to-end query latency
- `Hit@K` / `Recall@K` / `MRR@K` / `nDCG@K`: retrieval quality against qrels
- `top_k`: retrieved documents per query
- `batch_size`: query batch size
- `index_type`: Flat, HNSW, IVF, etc.
- `ntotal`: number of indexed vectors

## Why This Matters

Knowledge QA / RAG is a valid agent workload family when evaluated as an
LLM-backed answer path over standard cases. It is simpler than SWE-bench or
tau-bench because the action space is mostly retrieval plus answer generation,
but it is important for CPU architecture work because it exposes embedding
compute, memory-heavy vector search, metadata lookup, document materialization,
prompt/context construction, and LLM serving interaction.

## Evaluation Status

Current objective scoring:

- BEIR/SciFact retrieval scoring is implemented through
  `run_scifact_retrieval_eval.sh`.
- It evaluates standard qrels-backed SciFact queries and reports Hit@K,
  Recall@K, MRR@K, and nDCG@K.

Latest full SciFact retrieval result:

```text
queries evaluated: 300
Hit@5: 0.7533
Recall@5: 0.7379
MRR@5: 0.5997
nDCG@5: 0.6293
stage timings: embed=2920.2ms, search=1.6ms, doc_fetch=15.3ms
```

Next scoring step:

- Add answer-level scoring for SciFact labels (`SUPPORT` / `CONTRADICT` /
  insufficient evidence). The local `queries.jsonl` already contains label
  metadata for many claims, so this can be added without inventing private test
  cases.
