#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
#
# Derived from the MIT-licensed cpu-centric-agentic-ai project:
# Copyright (c) 2025 Ritik Raj
#
# Local modifications are maintained under this workload harness directory.

"""Retrieval-only runner for the FAISS/docstore path.

This avoids Haystack and LLM dependencies so we can isolate CPU-side embedding,
FAISS search, and document fetching before adding generation.
"""

from __future__ import annotations

import argparse
import io
import json
import mmap
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np


class StageTimer:
    def __init__(self) -> None:
        self.events: Dict[str, float] = {}

    @contextmanager
    def track(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self.events[name] = self.events.get(name, 0.0) + time.perf_counter() - start


class ShardCache:
    def __init__(self, max_open: int = 16, use_mmap: bool = True):
        self.max_open = int(max_open)
        self.use_mmap = bool(use_mmap)
        self._fds: "OrderedDict[str, Tuple[io.BufferedReader, Optional[mmap.mmap]]]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, path: Path):
        key = str(path)
        with self._lock:
            if key in self._fds:
                fh, mm = self._fds.pop(key)
                self._fds[key] = (fh, mm)
                return fh, mm
            fh = open(path, "rb", buffering=0)
            mm = mmap.mmap(fh.fileno(), 0, access=mmap.ACCESS_READ) if self.use_mmap else None
            self._fds[key] = (fh, mm)
            while len(self._fds) > self.max_open:
                _, (old_fh, old_mm) = self._fds.popitem(last=False)
                if old_mm:
                    old_mm.close()
                old_fh.close()
            return fh, mm

    def close(self) -> None:
        with self._lock:
            for fh, mm in self._fds.values():
                if mm:
                    mm.close()
                fh.close()
            self._fds.clear()


class ReadOnlyDocStore:
    def __init__(self, root: Path, shard_cache_size: int = 16, use_mmap: bool = True):
        self.root = Path(root)
        self.db_path = self.root / "docs.sqlite3"
        if not self.db_path.exists():
            raise FileNotFoundError(f"Docstore not found: {self.db_path}")
        self._conn = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        self._cache = ShardCache(max_open=shard_cache_size, use_mmap=use_mmap)

    def fetch_many(self, ids: Sequence[int]) -> Dict[int, dict]:
        unique = []
        seen = set()
        for doc_id in ids:
            doc_id = int(doc_id)
            if doc_id != -1 and doc_id not in seen:
                unique.append(doc_id)
                seen.add(doc_id)
        if not unique:
            return {}

        marks = ",".join("?" for _ in unique)
        with self._lock:
            rows = self._conn.execute(
                f"SELECT id, path, offset, length FROM docs WHERE id IN ({marks})",
                unique,
            ).fetchall()

        out: Dict[int, dict] = {}
        for row in rows:
            doc_id = int(row["id"])
            fh, mm = self._cache.get(Path(row["path"]))
            offset = int(row["offset"])
            length = int(row["length"])
            raw = mm[offset : offset + length] if mm else fh.read(length)
            out[doc_id] = json.loads(raw)
        return out

    def close(self) -> None:
        self._cache.close()
        self._conn.close()


class Embedder:
    def __init__(
        self,
        model_name: str,
        backend: str,
        provider: str,
        ort_intra: int,
        ort_inter: int,
        truncate_dim: Optional[int],
    ):
        from sentence_transformers import SentenceTransformer

        model_kwargs = {}
        if backend == "onnx":
            import onnxruntime as ort

            so = ort.SessionOptions()
            so.intra_op_num_threads = int(ort_intra)
            so.inter_op_num_threads = int(ort_inter)
            so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
            so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            model_kwargs = {
                "provider": provider,
                "export": True,
                "session_options": so,
            }
        self.model = SentenceTransformer(
            model_name,
            backend=backend,
            truncate_dim=truncate_dim,
            device="cpu",
            model_kwargs=model_kwargs,
        )
        self.dim = int(self.model.encode(["warmup"], convert_to_numpy=True, normalize_embeddings=True).shape[1])

    def encode(self, queries: Sequence[str], batch_size: int) -> np.ndarray:
        return self.model.encode(
            list(queries),
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32", copy=False)


def encode_worker(args: argparse.Namespace) -> None:
    with open(args.queries_json, "r", encoding="utf-8") as fh:
        queries = json.load(fh)
    embedder = Embedder(
        args.model,
        args.backend,
        args.provider,
        args.ort_intra,
        args.ort_inter,
        args.truncate_dim,
    )
    embeddings = embedder.encode(queries, batch_size=args.embed_batch)
    np.save(args.embeddings_npy, embeddings)


def encode_queries_subprocess(args: argparse.Namespace, queries: Sequence[str]) -> np.ndarray:
    with tempfile.TemporaryDirectory(prefix="retrieval_only_") as tmpdir:
        tmp = Path(tmpdir)
        queries_json = tmp / "queries.json"
        embeddings_npy = tmp / "embeddings.npy"
        with queries_json.open("w", encoding="utf-8") as fh:
            json.dump(list(queries), fh)
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--encode-worker",
            "--queries-json",
            str(queries_json),
            "--embeddings-npy",
            str(embeddings_npy),
            "--model",
            args.model,
            "--backend",
            args.backend,
            "--provider",
            args.provider,
            "--embed-batch",
            str(args.embed_batch),
            "--ort-intra",
            str(args.ort_intra),
            "--ort-inter",
            str(args.ort_inter),
        ]
        if args.truncate_dim is not None:
            cmd.extend(["--truncate-dim", str(args.truncate_dim)])
        env = os.environ.copy()
        env.setdefault("TOKENIZERS_PARALLELISM", "false")
        subprocess.run(cmd, check=True, env=env)
        return np.load(embeddings_npy).astype("float32", copy=False)


class RetrievalOnly:
    def __init__(
        self,
        store_dir: Path,
        model_name: str,
        backend: str,
        provider: str,
        embed_batch: int,
        omp_threads: int,
        ort_intra: int,
        ort_inter: int,
        truncate_dim: Optional[int],
        shard_cache: int,
        use_mmap: bool,
        args: argparse.Namespace,
    ):
        import faiss

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        faiss.omp_set_num_threads(int(omp_threads))
        self.store_dir = Path(store_dir)
        self.embed_batch = int(embed_batch)
        self.index_path = self.store_dir / "faiss" / "flat.index"
        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.index_path}")
        self.index = faiss.read_index(str(self.index_path))
        self.docstore = ReadOnlyDocStore(self.store_dir / "docstore", shard_cache_size=shard_cache, use_mmap=use_mmap)
        self._faiss = faiss
        self._args = args

    def retrieve_batch(self, queries: Sequence[str], top_k: int) -> Tuple[List[List[dict]], Dict[str, float]]:
        timer = StageTimer()
        with timer.track("embed"):
            q = encode_queries_subprocess(self._args, queries)
        with timer.track("search"):
            self._faiss.normalize_L2(q)
            scores, ids = self.index.search(q, int(top_k))
        flat_ids = [int(doc_id) for row in ids for doc_id in row if int(doc_id) != -1]
        with timer.track("doc_fetch"):
            fetched = self.docstore.fetch_many(flat_ids)

        results: List[List[dict]] = []
        for row_ids, row_scores in zip(ids, scores):
            docs = []
            for doc_id, score in zip(row_ids, row_scores):
                doc_id = int(doc_id)
                if doc_id == -1 or doc_id not in fetched:
                    continue
                payload = dict(fetched[doc_id])
                payload["score"] = float(score)
                payload["id"] = doc_id
                docs.append(payload)
            results.append(docs)
        return results, timer.events

    def close(self) -> None:
        self.docstore.close()


def load_queries(args: argparse.Namespace) -> List[str]:
    queries: List[str] = []
    if args.question:
        queries.extend(args.question)
    if args.query_file:
        with open(args.query_file, "r", encoding="utf-8") as fh:
            queries.extend(line.strip() for line in fh if line.strip())
    if not queries:
        queries = [
            "What is machine learning?",
            "How do neural networks process language?",
            "What causes high retrieval latency in vector search?",
        ]
    return queries


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval-only FAISS/docstore queries")
    parser.add_argument("--store-dir", default="data/rag_smoke_store")
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--backend", default="torch", choices=["torch", "onnx"])
    parser.add_argument("--provider", default="CPUExecutionProvider")
    parser.add_argument("--truncate-dim", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--embed-batch", type=int, default=16)
    parser.add_argument("--omp-threads", type=int, default=8)
    parser.add_argument("--ort-intra", type=int, default=4)
    parser.add_argument("--ort-inter", type=int, default=1)
    parser.add_argument("--shard-cache", type=int, default=8)
    parser.add_argument("--disable-mmap", action="store_true")
    parser.add_argument("--question", action="append")
    parser.add_argument("--query-file")
    parser.add_argument("--preview-chars", type=int, default=220)
    parser.add_argument("--encode-worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--queries-json", help=argparse.SUPPRESS)
    parser.add_argument("--embeddings-npy", help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.encode_worker:
        encode_worker(args)
        return

    queries = load_queries(args)
    runner = RetrievalOnly(
        store_dir=Path(args.store_dir),
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
        results, stats = runner.retrieve_batch(queries, top_k=args.top_k)
        total = time.perf_counter() - start
        print(f"Loaded index: {runner.index_path} (ntotal={runner.index.ntotal})")
        print(f"Queries: {len(queries)} | top_k={args.top_k} | total={fmt_ms(total)}")
        print("Stage timings: " + ", ".join(f"{k}={fmt_ms(v)}" for k, v in stats.items()))
        print(f"Mean per query: {fmt_ms(total / max(len(queries), 1))}")

        for query, docs in zip(queries, results):
            print("\n" + "=" * 80)
            print(f"QUERY: {query}")
            for rank, doc in enumerate(docs, 1):
                meta = doc.get("meta", {})
                text = doc.get("content") or doc.get("text") or ""
                snippet = " ".join(text[: args.preview_chars].split())
                print(f"[{rank}] id={doc['id']} score={doc['score']:.4f} source={meta.get('source_file', '')}")
                print(f"    {snippet}")

        if len(queries) > 1:
            per_stage = {k: v / len(queries) for k, v in stats.items()}
            print("\nPer-query stage mean: " + ", ".join(f"{k}={fmt_ms(v)}" for k, v in per_stage.items()))
    finally:
        runner.close()


if __name__ == "__main__":
    main()
