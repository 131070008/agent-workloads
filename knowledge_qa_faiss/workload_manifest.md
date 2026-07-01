# Workload Manifest: Knowledge QA / RAG Agent

## Goal

Measure the CPU-side execution path of a knowledge QA / RAG agent.

- question answering over external knowledge
- document retrieval before LLM generation
- context construction before agent planning or answer generation
- LLM-backed answer generation over standard query cases

This workload has two modes:

- `retrieval_only`: phase microbench for embedding, FAISS search, and doc fetch.
- `rag_agent`: agent bench mode, where the system retrieves evidence and calls
  an LLM to generate an answer.

## First Supported Input

- Dataset family: BEIR
- Dataset: SciFact
- Scale: 5183 corpus documents, 5 smoke queries
- Purpose: fast local smoke test, phase timing, and RAG agent path validation
- Local dataset path: `workloads/knowledge_qa_faiss/datasets/beir_scifact_smoke`

## Harness Code

The retrieval-only workload driver is:

```text
workloads/knowledge_qa_faiss/retrieval_only.py
```

The RAG agent wrapper is:

```text
workloads/knowledge_qa_faiss/run_rag_agent.sh
```

It currently calls:

```text
cpu-centric-agentic-ai/haystack/retrieval.py batch-query-rag
```

This is the path that connects the standard query set, FAISS retrieval, context
construction, and local/cloud OpenAI-compatible LLM generation.

## Phase Breakdown

1. `embed`
   Convert query text into dense vectors.

2. `search`
   Run FAISS vector search.

3. `doc_fetch`
   Fetch document payload and metadata from docstore.

4. `context_build`
   Optional phase for constructing prompt context.

5. `llm_generate`
   Generate the final answer using the retrieved context.

6. `answer_eval`
   Optional scoring against labels/qrels or manual correctness checks.

## Implemented Scoring

Retrieval quality is now evaluated against BEIR/SciFact qrels:

```bash
workloads/knowledge_qa_faiss/run_scifact_retrieval_eval.sh
```

Reported metrics:

- `Hit@K`
- `Recall@K`
- `MRR@K`
- `nDCG@K`

The evaluator also reports how many selected claims have SciFact label metadata
available for later answer-level scoring.

Latest full qrels-backed run:

```text
query file: datasets/beir_scifact_smoke/queries/scifact_qrels_test_all.tsv
queries evaluated: 300
Hit@5: 0.7533
Recall@5: 0.7379
MRR@5: 0.5997
nDCG@5: 0.6293
```

## Initial Local Result

BEIR/SciFact retrieval-only, 5 queries:

```text
total: 2661.6 ms
embed: 2654.8 ms
search: 0.7 ms
doc_fetch: 6.1 ms
mean/query: 532.3 ms
```

FAISS search-only, same index:

```text
batch=1    per_query=0.1108 ms
batch=8    per_query=0.0315 ms
batch=32   per_query=0.0091 ms
batch=128  per_query=0.0047 ms
```

Interpretation: on the small SciFact smoke index, query embedding dominates.
FAISS Flat search is already sub-millisecond for this scale. Larger corpora or
ANN indexes should be used before drawing conclusions about memory pressure and
search-side bottlenecks.

## Agent-Bench Criteria

This workload counts as a knowledge QA agent bench when run through
`run_rag_agent.sh` because it has:

- standard query cases from BEIR/SciFact
- a retrieval tool path over an external knowledge store
- context construction from retrieved evidence
- LLM answer generation through an OpenAI-compatible endpoint
- E2E timing and per-phase timing

It is not a multi-tool transaction benchmark like tau-bench, but multi-turn is
not required for this workload family.
