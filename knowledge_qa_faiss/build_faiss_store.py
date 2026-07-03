#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Build a FAISS FlatIP + SQLite docstore from a JSONL corpus.

The store layout matches ``retrieval_only.py``:

  store_dir/
    faiss/flat.index
    docstore/docs.sqlite3
    docstore/data/batch_*.jsonl

For qrels-backed datasets such as MS MARCO, the original corpus id is preserved
in document metadata and can also be used as the FAISS/docstore integer id.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

import numpy as np


def setup_threads(torch_threads: int, faiss_threads: int) -> None:
    os.environ.setdefault("CUDA_VISIBLE_DEVICES", "")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    os.environ.setdefault("MALLOC_ARENA_MAX", "2")
    os.environ.setdefault("OMP_NUM_THREADS", str(torch_threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(torch_threads))
    try:
        import torch

        torch.set_num_threads(int(torch_threads))
        torch.set_num_interop_threads(1)
    except Exception:
        pass
    try:
        import faiss

        faiss.omp_set_num_threads(int(faiss_threads))
    except Exception:
        pass


class DocStoreWriter:
    def __init__(self, root: Path, shard_docs: int = 200_000):
        self.root = Path(root)
        self.data_dir = self.root / "data"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "docs.sqlite3"
        self.shard_docs = int(shard_docs)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS docs(
              id INTEGER PRIMARY KEY,
              path TEXT NOT NULL,
              offset INTEGER NOT NULL,
              length INTEGER NOT NULL
            );
            """
        )
        self.conn.commit()
        row = self.conn.execute("SELECT COUNT(*) FROM docs").fetchone()
        self._doc_count = int(row[0] or 0)
        self._fh = None
        self._shard_name = None
        self._open_append_shard()

    def existing_ids(self) -> set[int]:
        cur = self.conn.execute("SELECT id FROM docs")
        return {int(row[0]) for row in cur}

    def _next_shard_name(self) -> str:
        idx = (self._doc_count // self.shard_docs) + 1
        return f"batch_{idx:06d}.jsonl"

    def _open_append_shard(self) -> None:
        name = self._next_shard_name()
        if self._fh and self._shard_name == name:
            return
        if self._fh:
            self._fh.flush()
            self._fh.close()
        self._shard_name = name
        self._fh = open(self.data_dir / name, "ab", buffering=0)

    def add_docs(self, ids: list[int], docs: list[dict], already_present: set[int]) -> int:
        cur = self.conn.cursor()
        added = 0
        for doc_id, doc in zip(ids, docs):
            if doc_id in already_present:
                continue
            self._open_append_shard()
            rec = (
                json.dumps({"content": doc["content"], "meta": doc.get("meta", {})}, ensure_ascii=False)
                .encode("utf-8")
                + b"\n"
            )
            offset = self._fh.tell()
            self._fh.write(rec)
            cur.execute(
                "INSERT OR IGNORE INTO docs(id, path, offset, length) VALUES(?,?,?,?)",
                (int(doc_id), str(self._shard_name), int(offset), int(len(rec))),
            )
            if cur.rowcount:
                already_present.add(int(doc_id))
                self._doc_count += 1
                added += 1
        self.conn.commit()
        return added

    def close(self) -> None:
        if self._fh:
            self._fh.flush()
            self._fh.close()
        self.conn.close()


def load_existing_index(index_path: Path, dim: int):
    import faiss

    if index_path.exists():
        index = faiss.read_index(str(index_path))
        if index.d != dim:
            raise ValueError(f"index dim mismatch: existing={index.d}, model={dim}")
        if not isinstance(index, faiss.IndexIDMap2):
            index = faiss.IndexIDMap2(index)
        return index
    base = faiss.IndexFlatIP(dim)
    return faiss.IndexIDMap2(base)


def existing_index_ids(index) -> set[int]:
    import faiss

    if hasattr(index, "id_map"):
        return {int(x) for x in faiss.vector_to_array(index.id_map)}
    return set()


def iter_corpus(path: Path, id_field: str, text_field: str, max_docs: int) -> Iterable[tuple[int, str, dict]]:
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for line_no, line in enumerate(fh, 1):
            if max_docs > 0 and line_no > max_docs:
                break
            if not line.strip():
                continue
            row = json.loads(line)
            raw_id = row.get(id_field)
            if raw_id is None:
                raise KeyError(f"missing id field {id_field!r} at line {line_no}")
            doc_id = int(raw_id)
            text = row.get(text_field) or row.get("content") or ""
            if not text:
                continue
            meta = row.get("meta") or row.get("metadata") or {}
            meta = dict(meta)
            meta.setdefault("source_id", str(raw_id))
            meta.setdefault("corpus_id", str(raw_id))
            yield doc_id, text, {"content": text, "meta": meta}


def write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def save_index(index, index_path: Path) -> None:
    import faiss

    tmp = index_path.with_suffix(index_path.suffix + ".tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, index_path)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a FAISS FlatIP/docstore from JSONL corpus")
    parser.add_argument("--corpus-jsonl", type=Path, required=True)
    parser.add_argument("--store-dir", type=Path, required=True)
    parser.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    parser.add_argument("--id-field", default="_id")
    parser.add_argument("--text-field", default="text")
    parser.add_argument("--batch-size", type=int, default=256, help="embedding batch size inside each worker")
    parser.add_argument("--buffer-docs", type=int, default=32_768, help="documents to encode/add per flush")
    parser.add_argument("--save-every-docs", type=int, default=1_000_000)
    parser.add_argument("--max-docs", type=int, default=0)
    parser.add_argument("--torch-threads", type=int, default=48)
    parser.add_argument("--faiss-threads", type=int, default=48)
    parser.add_argument("--workers", type=int, default=0, help="SentenceTransformer CPU worker processes")
    parser.add_argument("--mp-chunk", type=int, default=4096, help="texts per multi-process work chunk")
    parser.add_argument("--heartbeat-docs", type=int, default=100_000)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    setup_threads(args.torch_threads, args.faiss_threads)

    import faiss
    from sentence_transformers import SentenceTransformer

    args.store_dir.mkdir(parents=True, exist_ok=True)
    (args.store_dir / "faiss").mkdir(parents=True, exist_ok=True)
    docstore = DocStoreWriter(args.store_dir / "docstore")
    manifest_path = args.store_dir / "build_manifest.json"
    index_path = args.store_dir / "faiss" / "flat.index"

    print(f"[model] loading {args.model}", flush=True)
    model = SentenceTransformer(args.model, device="cpu")
    warm = model.encode(["warmup"], convert_to_numpy=True, normalize_embeddings=True)
    dim = int(warm.shape[1])
    print(f"[model] dim={dim}", flush=True)
    pool = None
    if args.workers > 0:
        print(f"[model] starting {args.workers} CPU embedding workers", flush=True)
        pool = model.start_multi_process_pool(target_devices=["cpu"] * int(args.workers))

    index = load_existing_index(index_path, dim) if args.resume else load_existing_index(Path("__missing__"), dim)
    indexed_ids = existing_index_ids(index) if args.resume else set()
    docstore_ids = docstore.existing_ids() if args.resume else set()
    print(f"[resume] index_ntotal={index.ntotal} indexed_ids={len(indexed_ids)} docstore_ids={len(docstore_ids)}", flush=True)

    started = time.time()
    last_save = int(index.ntotal)
    seen = 0
    added = int(index.ntotal)
    skipped_indexed = 0
    skipped_empty = 0
    pending_ids: list[int] = []
    pending_texts: list[str] = []
    pending_docs: list[dict] = []

    def flush(final: bool = False) -> None:
        nonlocal added, last_save, pending_ids, pending_texts, pending_docs
        if not pending_ids:
            return
        ids = np.asarray(pending_ids, dtype=np.int64)
        if pool is not None:
            embeddings = model.encode_multi_process(
                pending_texts,
                pool,
                batch_size=args.batch_size,
                chunk_size=args.mp_chunk,
                show_progress_bar=False,
                normalize_embeddings=True,
            ).astype("float32", copy=False)
        else:
            embeddings = model.encode(
                pending_texts,
                batch_size=args.batch_size,
                show_progress_bar=False,
                convert_to_numpy=True,
                normalize_embeddings=True,
            ).astype("float32", copy=False)
        docstore.add_docs(pending_ids, pending_docs, docstore_ids)
        faiss.normalize_L2(embeddings)
        index.add_with_ids(embeddings, ids)
        indexed_ids.update(int(x) for x in pending_ids)
        added = int(index.ntotal)
        pending_ids = []
        pending_texts = []
        pending_docs = []

        if final or added - last_save >= args.save_every_docs:
            elapsed = time.time() - started
            print(f"[save] ntotal={added:,} elapsed={elapsed:.1f}s", flush=True)
            save_index(index, index_path)
            write_json_atomic(
                manifest_path,
                {
                    "corpus_jsonl": str(args.corpus_jsonl),
                    "store_dir": str(args.store_dir),
                    "model": args.model,
                    "dim": dim,
                    "ntotal": added,
                    "seen_lines": seen,
                    "skipped_already_indexed": skipped_indexed,
                    "skipped_empty": skipped_empty,
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                    "elapsed_seconds": round(elapsed, 3),
                },
            )
            last_save = added

    try:
        for doc_id, text, doc in iter_corpus(args.corpus_jsonl, args.id_field, args.text_field, args.max_docs):
            seen += 1
            if doc_id in indexed_ids:
                skipped_indexed += 1
                continue
            if not text.strip():
                skipped_empty += 1
                continue
            pending_ids.append(doc_id)
            pending_texts.append(text)
            pending_docs.append(doc)
            if len(pending_ids) >= args.buffer_docs:
                flush()
            if args.heartbeat_docs > 0 and seen % args.heartbeat_docs == 0:
                elapsed = time.time() - started
                rate = seen / max(elapsed, 1e-6)
                print(
                    f"[hb] seen={seen:,} ntotal={index.ntotal:,} rate={rate:.1f} docs/s "
                    f"skipped={skipped_indexed:,}",
                    flush=True,
                )
        flush(final=True)
    finally:
        if pool is not None:
            model.stop_multi_process_pool(pool)
        docstore.close()

    elapsed = time.time() - started
    print(f"DONE ntotal={index.ntotal:,} seen={seen:,} elapsed={elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
