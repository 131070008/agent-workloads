# Knowledge QA Dataset Inputs

This directory stores lightweight dataset inputs for the Knowledge QA / FAISS
workload harness.

Dataset inputs are separate from the harness code:

- `toy_smoke/`: tiny local corpus for no-dependency sanity checks.
- `beir_scifact_smoke/`: small classic BEIR/SciFact retrieval workload with
  official benchmark queries and qrels.

Large datasets such as NQ, HotpotQA, TriviaQA, or MS MARCO should not be checked
in here by default. Add download/build scripts and manifests first, then keep
large raw corpora in local cache or external storage.
