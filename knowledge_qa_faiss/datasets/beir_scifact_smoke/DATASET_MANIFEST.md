# Dataset Manifest: BEIR SciFact Smoke

## Role

Classic lightweight retrieval benchmark input for the Knowledge QA / FAISS
workload.

## Files

- `raw/corpus.jsonl`: BEIR SciFact corpus.
- `raw/queries.jsonl`: BEIR SciFact query set.
- `raw/qrels/test.tsv`: relevance labels.
- `queries/evidence_5.txt`: five evidence-oriented smoke queries.
- `queries/scifact_qrels_test_20.txt`: 20 official qrels-backed test queries.
- `queries/scifact_queries_50.txt`: 50 official SciFact queries.
- `prebuilt_store/`: generated FAISS Flat index and SQLite document store.

## Scale

```text
corpus documents: 5183
raw queries: 1109
test qrels rows: 340
unique qrels-backed test queries: 300
prebuilt index vectors: 5183
embedding dimension: 384
```

## Intended Use

- Smoke test retrieval harness correctness.
- Measure phase split: embedding, FAISS search, doc fetch.
- Compare index variants later on the same corpus.

## Not Intended For

- Final architecture conclusions about large-scale vector search.
- Claims about production RAG latency.
- Redistribution without upstream license review.
