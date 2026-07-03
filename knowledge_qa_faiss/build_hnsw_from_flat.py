#!/usr/bin/env python3
# SPDX-License-Identifier: MIT

"""Build a FAISS HNSW index from an existing Flat IndexIDMap2 store.

This reuses embeddings already stored in ``flat.index`` and links the output
store to the source docstore, so HNSW can be built without re-embedding the
corpus text.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np


def setup_threads(faiss_threads: int) -> None:
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    os.environ.setdefault("MALLOC_ARENA_MAX", "2")
    os.environ.setdefault("OMP_NUM_THREADS", str(faiss_threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(faiss_threads))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(faiss_threads))


def write_json_atomic(path: Path, payload: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def save_index(index, path: Path) -> None:
    import faiss

    tmp = path.with_suffix(path.suffix + ".tmp")
    faiss.write_index(index, str(tmp))
    os.replace(tmp, path)


def link_docstore(source_store: Path, output_store: Path) -> None:
    source_docstore = source_store / "docstore"
    output_docstore = output_store / "docstore"
    if output_docstore.exists() or output_docstore.is_symlink():
        return
    rel = os.path.relpath(source_docstore, output_store)
    output_docstore.symlink_to(rel, target_is_directory=True)


def set_hnsw_ef_search(index, ef_search: int) -> None:
    import faiss

    target = index
    if hasattr(index, "index"):
        target = faiss.downcast_index(index.index)
    if hasattr(target, "hnsw"):
        target.hnsw.efSearch = int(ef_search)


def main() -> None:
    parser = argparse.ArgumentParser(description="Build HNSW index from an existing Flat FAISS store")
    parser.add_argument("--source-store-dir", type=Path, required=True)
    parser.add_argument("--output-store-dir", type=Path, required=True)
    parser.add_argument("--source-index-file-name", default="flat.index")
    parser.add_argument("--output-index-file-name", default="hnsw.index")
    parser.add_argument("--hnsw-m", type=int, default=32)
    parser.add_argument("--hnsw-ef-construction", type=int, default=100)
    parser.add_argument("--hnsw-ef-search", type=int, default=64)
    parser.add_argument("--add-batch-size", type=int, default=50_000)
    parser.add_argument("--save-every-docs", type=int, default=1_000_000)
    parser.add_argument("--heartbeat-docs", type=int, default=100_000)
    parser.add_argument("--max-docs", type=int, default=0)
    parser.add_argument("--faiss-threads", type=int, default=64)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()

    setup_threads(args.faiss_threads)
    import faiss

    faiss.omp_set_num_threads(int(args.faiss_threads))
    source_index_path = args.source_store_dir / "faiss" / args.source_index_file_name
    output_index_path = args.output_store_dir / "faiss" / args.output_index_file_name
    manifest_path = args.output_store_dir / "build_manifest.json"

    args.output_store_dir.mkdir(parents=True, exist_ok=True)
    output_index_path.parent.mkdir(parents=True, exist_ok=True)
    link_docstore(args.source_store_dir, args.output_store_dir)

    print(f"[load] source flat index: {source_index_path}", flush=True)
    source = faiss.read_index(str(source_index_path))
    if not hasattr(source, "id_map"):
        raise TypeError("source index must be IndexIDMap/IndexIDMap2 with original ids")
    inner = faiss.downcast_index(source.index) if hasattr(source, "index") else source
    if not hasattr(inner, "get_xb"):
        raise TypeError(f"source inner index must expose get_xb; got {type(inner)}")
    ids = faiss.vector_to_array(source.id_map).astype("int64", copy=False)
    xb = faiss.rev_swig_ptr(inner.get_xb(), source.ntotal * source.d).reshape(source.ntotal, source.d)
    total_source = int(source.ntotal)
    limit = min(total_source, int(args.max_docs)) if args.max_docs > 0 else total_source
    print(f"[load] vectors={total_source:,} dim={source.d} build_limit={limit:,}", flush=True)

    if args.resume and output_index_path.exists():
        print(f"[resume] loading output index: {output_index_path}", flush=True)
        output = faiss.read_index(str(output_index_path))
        if output.d != source.d:
            raise ValueError(f"dim mismatch: source={source.d}, output={output.d}")
        if not hasattr(output, "id_map"):
            output = faiss.IndexIDMap2(output)
        existing_ids = {int(x) for x in faiss.vector_to_array(output.id_map)}
    else:
        base = faiss.IndexHNSWFlat(int(source.d), int(args.hnsw_m), faiss.METRIC_INNER_PRODUCT)
        base.hnsw.efConstruction = int(args.hnsw_ef_construction)
        output = faiss.IndexIDMap2(base)
        existing_ids: set[int] = set()
    set_hnsw_ef_search(output, args.hnsw_ef_search)

    started = time.time()
    last_save = int(output.ntotal)
    seen = 0
    skipped = 0

    def maybe_save(final: bool = False) -> None:
        nonlocal last_save
        if not final and int(output.ntotal) - last_save < args.save_every_docs:
            return
        elapsed = time.time() - started
        print(f"[save] ntotal={int(output.ntotal):,} elapsed={elapsed:.1f}s", flush=True)
        save_index(output, output_index_path)
        write_json_atomic(
            manifest_path,
            {
                "source_store_dir": str(args.source_store_dir),
                "source_index_file_name": args.source_index_file_name,
                "output_store_dir": str(args.output_store_dir),
                "output_index_file_name": args.output_index_file_name,
                "index_type": "hnsw",
                "hnsw_m": args.hnsw_m,
                "hnsw_ef_construction": args.hnsw_ef_construction,
                "hnsw_ef_search": args.hnsw_ef_search,
                "dim": int(source.d),
                "ntotal": int(output.ntotal),
                "source_ntotal": total_source,
                "seen_vectors": seen,
                "skipped_already_indexed": skipped,
                "updated_at": time.strftime("%Y-%m-%d %H:%M:%S %z"),
                "elapsed_seconds": round(elapsed, 3),
                "docstore": str(args.output_store_dir / "docstore"),
            },
        )
        last_save = int(output.ntotal)

    for start in range(0, limit, int(args.add_batch_size)):
        end = min(start + int(args.add_batch_size), limit)
        chunk_ids = ids[start:end]
        if existing_ids:
            mask = np.fromiter((int(doc_id) not in existing_ids for doc_id in chunk_ids), dtype=bool)
            if not mask.any():
                skipped += int(end - start)
                seen = end
                continue
            add_ids = np.ascontiguousarray(chunk_ids[mask])
            add_vecs = np.ascontiguousarray(xb[start:end][mask])
        else:
            add_ids = np.ascontiguousarray(chunk_ids)
            add_vecs = np.ascontiguousarray(xb[start:end])
        output.add_with_ids(add_vecs, add_ids)
        existing_ids.update(int(x) for x in add_ids)
        seen = end
        if args.heartbeat_docs > 0 and seen % args.heartbeat_docs == 0:
            elapsed = time.time() - started
            rate = seen / max(elapsed, 1e-6)
            print(
                f"[hb] seen={seen:,} ntotal={int(output.ntotal):,} rate={rate:.1f} vec/s skipped={skipped:,}",
                flush=True,
            )
        maybe_save()

    maybe_save(final=True)
    elapsed = time.time() - started
    print(f"DONE ntotal={int(output.ntotal):,} seen={seen:,} elapsed={elapsed:.1f}s", flush=True)


if __name__ == "__main__":
    main()
