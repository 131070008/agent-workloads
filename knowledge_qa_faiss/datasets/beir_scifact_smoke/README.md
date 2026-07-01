# BEIR SciFact Smoke Dataset

Small classic retrieval dataset for Knowledge QA / RAG-style smoke testing.

## Contents

```text
raw/corpus.jsonl
raw/queries.jsonl
raw/qrels/test.tsv
queries/evidence_5.txt
queries/scifact_qrels_test_20.txt
queries/scifact_queries_50.txt
prebuilt_store/
```

`prebuilt_store/` is a local FAISS Flat + SQLite docstore built from this
SciFact corpus with `sentence-transformers/all-MiniLM-L6-v2`.

## Query Cases

- `raw/queries.jsonl`: full SciFact query/claim set from the benchmark.
- `raw/qrels/test.tsv`: official relevance labels for evaluation queries.
- `queries/scifact_qrels_test_20.txt`: 20 official test queries with qrels.
- `queries/scifact_queries_50.txt`: first 50 official SciFact queries.
- `queries/evidence_5.txt`: small hand-picked smoke subset from official
  SciFact-style queries.

These are not self-authored QA questions, except for the separate `toy_smoke`
dataset under `../toy_smoke/`.

## Source

- Dataset family: BEIR
- Dataset: SciFact
- Local archive source used earlier:
  `https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/scifact.zip`

## License / Attribution Note

The SciFact data is third-party benchmark data. Keep this notice with copied
data. Before redistributing outside internal research, verify the upstream
dataset license and any SciFact-specific citation requirements.

For local workload exploration, treat this folder as benchmark input data, not
as original project code.
