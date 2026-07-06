#!/usr/bin/env python3
"""Resident retriever service for one-query RAG agent flow tests."""

from __future__ import annotations

import argparse
import json
import os
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import numpy as np

from retrieval_only import Embedder, ReadOnlyDocStore


def fmt_ms(seconds: float) -> float:
    return seconds * 1000.0


def set_hnsw_ef_search(index: Any, ef_search: int) -> None:
    if ef_search <= 0:
        return
    import faiss

    target = index
    if hasattr(index, "index"):
        target = faiss.downcast_index(index.index)
    if hasattr(target, "hnsw"):
        target.hnsw.efSearch = int(ef_search)


class ResidentRetriever:
    def __init__(self, args: argparse.Namespace):
        import faiss

        self.args = args
        self.store_dir = Path(args.store_dir).expanduser().resolve()
        self.index_path = self.store_dir / "faiss" / args.index_file_name
        if not self.index_path.exists():
            raise FileNotFoundError(f"FAISS index not found: {self.index_path}")

        self.boot_start = time.perf_counter()
        print("[retriever] boot", flush=True)
        try:
            print(f"[retriever] affinity={sorted(os.sched_getaffinity(0))}", flush=True)
        except AttributeError:
            pass
        print(f"[retriever] store={self.store_dir}", flush=True)

        faiss.omp_set_num_threads(int(args.omp_threads))
        model_start = time.perf_counter()
        self.embedder = Embedder(
            args.model,
            args.backend,
            args.provider,
            args.ort_intra,
            args.ort_inter,
            args.truncate_dim,
        )
        print(f"[retriever] model_load_ms={fmt_ms(time.perf_counter() - model_start):.1f}", flush=True)

        warm_start = time.perf_counter()
        self.embedder.encode(["warmup"], batch_size=1)
        print(f"[retriever] model_warmup_ms={fmt_ms(time.perf_counter() - warm_start):.1f}", flush=True)

        index_start = time.perf_counter()
        self.index = faiss.read_index(str(self.index_path))
        set_hnsw_ef_search(self.index, args.hnsw_ef_search)
        print(
            f"[retriever] index_load_ms={fmt_ms(time.perf_counter() - index_start):.1f} "
            f"ntotal={self.index.ntotal}",
            flush=True,
        )

        doc_start = time.perf_counter()
        self.docstore = ReadOnlyDocStore(
            self.store_dir / "docstore",
            shard_cache_size=args.shard_cache,
            use_mmap=not args.disable_mmap,
        )
        print(f"[retriever] docstore_open_ms={fmt_ms(time.perf_counter() - doc_start):.1f}", flush=True)
        print(
            f"[retriever] READY resident_ready_ms={fmt_ms(time.perf_counter() - self.boot_start):.1f}",
            flush=True,
        )

    def search(self, query: str, top_k: int) -> Tuple[List[Dict[str, Any]], Dict[str, float]]:
        timer: Dict[str, float] = {}

        start = time.perf_counter()
        q = self.embedder.encode([query], batch_size=1).astype("float32", copy=False)
        timer["embed"] = time.perf_counter() - start

        start = time.perf_counter()
        q = np.ascontiguousarray(q)
        self._normalize(q)
        scores, ids = self.index.search(q, int(top_k))
        timer["search"] = time.perf_counter() - start

        doc_ids = [int(doc_id) for doc_id in ids[0] if int(doc_id) != -1]
        start = time.perf_counter()
        fetched = self.docstore.fetch_many(doc_ids)
        timer["doc_fetch"] = time.perf_counter() - start

        docs: List[Dict[str, Any]] = []
        for rank, (doc_id, score) in enumerate(zip(ids[0], scores[0]), 1):
            doc_id = int(doc_id)
            if doc_id == -1 or doc_id not in fetched:
                continue
            payload = dict(fetched[doc_id])
            meta = payload.get("meta") or payload.get("metadata") or {}
            title = payload.get("title") or meta.get("title") or ""
            content = payload.get("content") or payload.get("text") or ""
            docs.append(
                {
                    "rank": rank,
                    "id": doc_id,
                    "score": float(score),
                    "title": title,
                    "content": content,
                    "meta": meta,
                }
            )

        timer["total"] = sum(timer.values())
        timings_ms = {name: round(fmt_ms(value), 3) for name, value in timer.items()}
        print(f"[retriever] query={query!r} timings_ms={timings_ms} ids={[doc['id'] for doc in docs]}", flush=True)
        return docs, {name: fmt_ms(value) for name, value in timer.items()}

    @staticmethod
    def _normalize(q: np.ndarray) -> None:
        import faiss

        faiss.normalize_L2(q)


def make_handler(retriever: ResidentRetriever):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, status: int, data: Dict[str, Any]) -> None:
            raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self) -> None:
            if self.path != "/health":
                self._send_json(404, {"error": "not found"})
                return
            self._send_json(
                200,
                {
                    "ok": True,
                    "store_dir": str(retriever.store_dir),
                    "index_path": str(retriever.index_path),
                    "ntotal": int(retriever.index.ntotal),
                    "ef_search": int(retriever.args.hnsw_ef_search),
                },
            )

        def do_POST(self) -> None:
            if self.path != "/search":
                self._send_json(404, {"error": "not found"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                query = str(payload.get("query") or "").strip()
                if not query:
                    raise ValueError("missing query")
                top_k = int(payload.get("top_k") or retriever.args.top_k)
                start = time.perf_counter()
                docs, timings = retriever.search(query, top_k=top_k)
                timings["wall"] = fmt_ms(time.perf_counter() - start)
                self._send_json(200, {"query": query, "top_k": top_k, "timings_ms": timings, "docs": docs})
            except Exception as exc:  # pragma: no cover - interactive service diagnostics
                self._send_json(500, {"error": str(exc)})

        def log_message(self, fmt: str, *args: Any) -> None:
            return

    return Handler


def parse_args() -> argparse.Namespace:
    home_store = Path.home() / "cunzhe" / "datasets" / "msmarco" / "faiss_hnsw_m48_efc500_store"
    local_model = Path.home() / "cunzhe" / "models" / "all-MiniLM-L6-v2"
    default_model = str(local_model) if local_model.is_dir() else "sentence-transformers/all-MiniLM-L6-v2"

    parser = argparse.ArgumentParser(description="Serve a resident FAISS retriever over localhost HTTP")
    parser.add_argument("--host", default=os.environ.get("RETRIEVER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("RETRIEVER_PORT", "18080")))
    parser.add_argument("--store-dir", type=Path, default=Path(os.environ.get("STORE_DIR", str(home_store))))
    parser.add_argument("--index-file-name", default=os.environ.get("INDEX_FILE_NAME", "hnsw.index"))
    parser.add_argument("--hnsw-ef-search", type=int, default=int(os.environ.get("HNSW_EF_SEARCH", "200")))
    parser.add_argument("--model", default=os.environ.get("MODEL", default_model))
    parser.add_argument("--backend", default=os.environ.get("BACKEND", "torch"), choices=["torch", "onnx"])
    parser.add_argument("--provider", default=os.environ.get("PROVIDER", "CPUExecutionProvider"))
    parser.add_argument("--truncate-dim", type=int, default=None)
    parser.add_argument("--top-k", type=int, default=int(os.environ.get("TOP_K", "5")))
    parser.add_argument("--embed-batch", type=int, default=int(os.environ.get("EMBED_BATCH", "1")))
    parser.add_argument("--omp-threads", type=int, default=int(os.environ.get("OMP_THREADS", "1")))
    parser.add_argument("--ort-intra", type=int, default=int(os.environ.get("ORT_INTRA", "1")))
    parser.add_argument("--ort-inter", type=int, default=int(os.environ.get("ORT_INTER", "1")))
    parser.add_argument("--shard-cache", type=int, default=int(os.environ.get("SHARD_CACHE", "8")))
    parser.add_argument("--disable-mmap", action="store_true")
    return parser.parse_args()


def main() -> None:
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
    os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

    args = parse_args()
    retriever = ResidentRetriever(args)
    server = ThreadingHTTPServer((args.host, args.port), make_handler(retriever))
    print(f"[retriever] serving http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    finally:
        retriever.docstore.close()


if __name__ == "__main__":
    main()
