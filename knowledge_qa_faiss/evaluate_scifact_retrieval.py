#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Evaluate BEIR/SciFact retrieval quality for the local FAISS workload."""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Iterable

from retrieval_only import RetrievalOnly


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def load_queries(queries_jsonl: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with queries_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            out[str(row["_id"])] = row
    return out


def load_query_file(query_file: Path, queries_by_id: dict[str, dict]) -> list[dict]:
    by_text: dict[str, list[dict]] = defaultdict(list)
    for row in queries_by_id.values():
        by_text[normalize_text(row["text"])].append(row)

    selected: list[dict] = []
    with query_file.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "\t" in line:
                qid, _text = line.split("\t", 1)
                qid = qid.strip()
                if qid not in queries_by_id:
                    raise KeyError(f"query id not found in queries.jsonl: {qid}")
                selected.append(queries_by_id[qid])
                continue

            text = normalize_text(line)
            if not text:
                continue
            matches = by_text.get(text, [])
            if not matches:
                raise KeyError(f"query text not found in queries.jsonl: {text}")
            selected.append(matches[0])
    return selected


def load_qrels(qrels_tsv: Path) -> dict[str, set[str]]:
    qrels: dict[str, set[str]] = defaultdict(set)
    with qrels_tsv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if int(row.get("score", "0")) > 0:
                qrels[str(row["query-id"])].add(str(row["corpus-id"]))
    return dict(qrels)


def doc_external_id(doc: dict) -> str | None:
    meta = doc.get("meta") or {}
    for key in ("source_id", "_id", "doc_id", "corpus_id"):
        value = meta.get(key)
        if value is not None:
            return str(value)
    for key in ("_id", "source_id", "doc_id", "corpus_id"):
        value = doc.get(key)
        if value is not None:
            return str(value)
    return None


def dcg(relevances: Iterable[int]) -> float:
    total = 0.0
    for idx, rel in enumerate(relevances, 1):
        if rel:
            total += 1.0 / math.log2(idx + 1)
    return total


def label_set(query: dict) -> set[str]:
    labels: set[str] = set()
    metadata = query.get("metadata") or {}
    for entries in metadata.values():
        for entry in entries:
            label = entry.get("label")
            if label:
                labels.add(str(label))
    return labels


def evaluate(args: argparse.Namespace) -> None:
    queries_by_id = load_queries(args.queries_jsonl)
    selected_queries = load_query_file(args.query_file, queries_by_id)
    qrels = load_qrels(args.qrels_tsv)

    eval_queries = [q for q in selected_queries if str(q["_id"]) in qrels]
    skipped = len(selected_queries) - len(eval_queries)
    if not eval_queries:
        raise SystemExit("No selected queries have qrels; choose a qrels-backed query file.")

    runner = RetrievalOnly(
        store_dir=args.store_dir,
        model_name=args.model,
        backend=args.backend,
        provider=args.provider,
        embed_batch=args.embed_batch,
        omp_threads=args.omp_threads,
        ort_intra=args.ort_intra,
        ort_inter=args.ort_inter,
        truncate_dim=args.truncate_dim,
        shard_cache=args.shard_cache,
        use_mmap=not args.disable_mmap,
        args=args,
    )

    try:
        start = time.perf_counter()
        docs_by_query, stats = runner.retrieve_batch(
            [q["text"] for q in eval_queries],
            top_k=args.top_k,
        )
        total_time = time.perf_counter() - start
    finally:
        runner.close()

    hit_count = 0
    recall_sum = 0.0
    rr_sum = 0.0
    ndcg_sum = 0.0
    labeled_count = 0
    label_counts: dict[str, int] = defaultdict(int)

    rows: list[dict] = []
    for query, docs in zip(eval_queries, docs_by_query):
        qid = str(query["_id"])
        relevant = qrels[qid]
        retrieved = [doc_external_id(doc) for doc in docs]
        retrieved = [doc_id for doc_id in retrieved if doc_id is not None]

        ranks = [idx + 1 for idx, doc_id in enumerate(retrieved) if doc_id in relevant]
        hit = bool(ranks)
        recall = len(set(retrieved) & relevant) / max(len(relevant), 1)
        rr = 1.0 / ranks[0] if ranks else 0.0
        rels = [1 if doc_id in relevant else 0 for doc_id in retrieved]
        ideal_rels = [1] * min(len(relevant), args.top_k)
        ndcg = dcg(rels) / dcg(ideal_rels) if ideal_rels else 0.0

        labels = label_set(query)
        if labels:
            labeled_count += 1
            for label in labels:
                label_counts[label] += 1

        hit_count += int(hit)
        recall_sum += recall
        rr_sum += rr
        ndcg_sum += ndcg
        rows.append(
            {
                "qid": qid,
                "hit": hit,
                "recall": recall,
                "rr": rr,
                "ndcg": ndcg,
                "labels": ",".join(sorted(labels)) or "<none>",
                "relevant": ",".join(sorted(relevant)),
                "retrieved": ",".join(retrieved),
                "query": query["text"],
            }
        )

    n = len(eval_queries)
    print("SCIFACT RETRIEVAL EVALUATION")
    print("=" * 72)
    print(f"queries selected: {len(selected_queries)}")
    print(f"queries evaluated: {n}")
    print(f"queries skipped without qrels: {skipped}")
    print(f"top_k: {args.top_k}")
    print(f"Hit@{args.top_k}: {hit_count / n:.4f} ({hit_count}/{n})")
    print(f"Recall@{args.top_k}: {recall_sum / n:.4f}")
    print(f"MRR@{args.top_k}: {rr_sum / n:.4f}")
    print(f"nDCG@{args.top_k}: {ndcg_sum / n:.4f}")
    print(f"labeled claims: {labeled_count}/{n}")
    if label_counts:
        print("label distribution: " + ", ".join(f"{k}={v}" for k, v in sorted(label_counts.items())))
    print(f"total_time_ms: {total_time * 1000:.1f}")
    print("stage_timings_ms: " + ", ".join(f"{k}={v * 1000:.1f}" for k, v in stats.items()))

    if args.show_failures:
        misses = [row for row in rows if not row["hit"]]
        print("\nMISSES")
        print("=" * 72)
        for row in misses[: args.max_failures]:
            print(f"qid={row['qid']} labels={row['labels']}")
            print(f"  query: {row['query']}")
            print(f"  relevant: {row['relevant']}")
            print(f"  retrieved: {row['retrieved']}")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(
            json.dumps(
                {
                    "query_file": str(args.query_file),
                    "qrels_tsv": str(args.qrels_tsv),
                    "top_k": args.top_k,
                    "queries_selected": len(selected_queries),
                    "queries_evaluated": n,
                    "queries_skipped_without_qrels": skipped,
                    "hit_at_k": hit_count / n,
                    "recall_at_k": recall_sum / n,
                    "mrr_at_k": rr_sum / n,
                    "ndcg_at_k": ndcg_sum / n,
                    "labeled_claims": labeled_count,
                    "label_distribution": dict(label_counts),
                    "total_time_ms": total_time * 1000,
                    "stage_timings_ms": {k: v * 1000 for k, v in stats.items()},
                    "rows": rows,
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"\nSaved JSON: {args.output_json}")


def main() -> None:
    root = Path(__file__).resolve().parent
    dataset_root = root / "datasets" / "beir_scifact_smoke"
    parser = argparse.ArgumentParser(description="Evaluate local FAISS retrieval on BEIR/SciFact qrels")
    parser.add_argument("--store-dir", type=Path, default=dataset_root / "prebuilt_store")
    parser.add_argument("--index-file-name", default="flat.index")
    parser.add_argument("--hnsw-ef-search", type=int, default=64)
    parser.add_argument("--queries-jsonl", type=Path, default=dataset_root / "raw" / "queries.jsonl")
    parser.add_argument("--qrels-tsv", type=Path, default=dataset_root / "raw" / "qrels" / "test.tsv")
    parser.add_argument("--query-file", type=Path, default=dataset_root / "queries" / "scifact_qrels_test_20.txt")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--backend", default="torch", choices=["torch", "onnx"])
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--truncate-dim", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embed-batch", type=int, default=8)
    parser.add_argument("--omp-threads", type=int, default=4)
    parser.add_argument("--ort-intra", type=int, default=4)
    parser.add_argument("--ort-inter", type=int, default=1)
    parser.add_argument("--shard-cache", type=int, default=8)
    parser.add_argument("--disable-mmap", action="store_true")
    parser.add_argument("--show-failures", action="store_true")
    parser.add_argument("--max-failures", type=int, default=10)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--encode-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--queries-json", help=argparse.SUPPRESS)
    parser.add_argument("--embeddings-npy", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.encode_worker:
        from retrieval_only import encode_worker

        encode_worker(args)
        return

    evaluate(args)


if __name__ == "__main__":
    main()
