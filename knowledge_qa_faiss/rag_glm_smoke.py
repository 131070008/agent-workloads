#!/usr/bin/env python3
"""Run a small SciFact RAG smoke test against GLM/OpenAI-compatible chat APIs."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List, Optional

import requests

from retrieval_only import RetrievalOnly


def load_queries(query_file: Path, limit: int) -> List[str]:
    queries: List[str] = []
    with query_file.open("r", encoding="utf-8") as fh:
        for line in fh:
            query = line.strip()
            if query:
                queries.append(query)
            if limit > 0 and len(queries) >= limit:
                break
    return queries


def fmt_ms(seconds: float) -> str:
    return f"{seconds * 1000:.1f}ms"


def build_prompt(query: str, docs: Iterable[Dict[str, Any]], max_chars_per_doc: int) -> str:
    context_blocks = []
    for rank, doc in enumerate(docs, 1):
        title = doc.get("title") or doc.get("meta", {}).get("title") or ""
        content = doc.get("content") or doc.get("text") or ""
        text = " ".join(content[:max_chars_per_doc].split())
        context_blocks.append(f"[{rank}] {title}\n{text}")
    context = "\n\n".join(context_blocks)
    return (
        "You are a scientific knowledge QA assistant. Answer using only the retrieved context. "
        "If the context is insufficient, say that the evidence is insufficient.\n\n"
        f"Question or claim:\n{query}\n\n"
        f"Retrieved context:\n{context}\n\n"
        "Answer in Chinese, concise and evidence-grounded."
    )


def call_chat_completion(args: argparse.Namespace, prompt: str) -> Dict[str, Any]:
    api_key = args.llm_api_key or os.environ.get(args.llm_api_key_env, "")
    if not api_key:
        raise SystemExit(
            f"Missing API key. Export {args.llm_api_key_env}=<key> or pass --llm-api-key."
        )

    payload: Dict[str, Any] = {
        "model": args.llm_model,
        "messages": [
            {"role": "system", "content": "You answer RAG questions with retrieved evidence."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": args.llm_max_tokens,
        "temperature": args.llm_temperature,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    start = time.perf_counter()
    response = requests.post(args.llm_api_url, headers=headers, json=payload, timeout=args.llm_timeout)
    elapsed = time.perf_counter() - start
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(f"LLM request failed HTTP {response.status_code}: {data}")

    message = data.get("choices", [{}])[0].get("message", {})
    result = {
        "answer": message.get("content", ""),
        "llm_inference_s": elapsed,
        "usage": data.get("usage", {}),
        "request_id": data.get("request_id") or data.get("id"),
        "model": data.get("model", args.llm_model),
    }
    if args.include_reasoning and message.get("reasoning_content"):
        result["reasoning_content"] = message["reasoning_content"]
    return result


def make_retrieval_args(args: argparse.Namespace) -> SimpleNamespace:
    return SimpleNamespace(
        model=args.embed_model,
        backend=args.backend,
        provider=args.provider,
        embed_batch=args.embed_batch,
        ort_intra=args.ort_intra,
        ort_inter=args.ort_inter,
        truncate_dim=args.truncate_dim,
    )


def main() -> None:
    here = Path(__file__).resolve().parent
    default_store = here / "datasets" / "beir_scifact_smoke" / "prebuilt_store"
    default_queries = here / "datasets" / "beir_scifact_smoke" / "queries" / "evidence_5.txt"

    parser = argparse.ArgumentParser(description="Run GLM-backed RAG smoke over the local SciFact FAISS store")
    parser.add_argument("--store-dir", type=Path, default=default_store)
    parser.add_argument("--query-file", type=Path, default=default_queries)
    parser.add_argument("--limit", type=int, default=2)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-chars-per-doc", type=int, default=500)
    parser.add_argument("--embed-model", default=os.environ.get("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2"))
    parser.add_argument("--backend", default=os.environ.get("BACKEND", "torch"), choices=["torch", "onnx"])
    parser.add_argument("--provider", default=os.environ.get("PROVIDER", "CPUExecutionProvider"))
    parser.add_argument("--truncate-dim", type=int, default=None)
    parser.add_argument("--embed-batch", type=int, default=int(os.environ.get("EMBED_BATCH", "8")))
    parser.add_argument("--omp-threads", type=int, default=int(os.environ.get("OMP_THREADS", "4")))
    parser.add_argument("--ort-intra", type=int, default=int(os.environ.get("ORT_INTRA", "4")))
    parser.add_argument("--ort-inter", type=int, default=int(os.environ.get("ORT_INTER", "1")))
    parser.add_argument("--shard-cache", type=int, default=8)
    parser.add_argument("--disable-mmap", action="store_true")
    parser.add_argument("--llm-api-url", default=os.environ.get("LLM_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"))
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "glm-4.5-air"))
    parser.add_argument("--llm-api-key-env", default=os.environ.get("LLM_API_KEY_ENV", "ZHIPU_API_KEY"))
    parser.add_argument("--llm-api-key", default="")
    parser.add_argument("--llm-max-tokens", type=int, default=int(os.environ.get("LLM_MAX_TOKENS", "512")))
    parser.add_argument("--llm-temperature", type=float, default=float(os.environ.get("LLM_TEMPERATURE", "0.2")))
    parser.add_argument("--llm-timeout", type=int, default=int(os.environ.get("LLM_TIMEOUT", "120")))
    parser.add_argument("--include-reasoning", action="store_true")
    parser.add_argument("--output-jsonl", type=Path)
    args = parser.parse_args()

    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    queries = load_queries(args.query_file, args.limit)
    if not queries:
        raise SystemExit(f"No queries loaded from {args.query_file}")

    retrieval_args = make_retrieval_args(args)
    runner = RetrievalOnly(
        store_dir=args.store_dir,
        model_name=args.embed_model,
        backend=args.backend,
        provider=args.provider,
        embed_batch=args.embed_batch,
        omp_threads=args.omp_threads,
        ort_intra=args.ort_intra,
        ort_inter=args.ort_inter,
        truncate_dim=args.truncate_dim,
        shard_cache=args.shard_cache,
        use_mmap=not args.disable_mmap,
        args=retrieval_args,
    )

    records: List[Dict[str, Any]] = []
    try:
        start_total = time.perf_counter()
        docs_by_query, retrieval_stats = runner.retrieve_batch(queries, top_k=args.top_k)
        retrieval_elapsed = time.perf_counter() - start_total

        print(f"Loaded index: {runner.index_path} (ntotal={runner.index.ntotal})")
        print(f"Queries: {len(queries)} | top_k={args.top_k}")
        print("Retrieval timings: " + ", ".join(f"{k}={fmt_ms(v)}" for k, v in retrieval_stats.items()))

        for idx, (query, docs) in enumerate(zip(queries, docs_by_query), 1):
            prompt = build_prompt(query, docs, args.max_chars_per_doc)
            llm = call_chat_completion(args, prompt)
            total_query_time = sum(retrieval_stats.values()) / max(len(queries), 1) + llm["llm_inference_s"]
            record = {
                "query_index": idx,
                "query": query,
                "top_k": args.top_k,
                "retrieved_doc_ids": [doc.get("id") for doc in docs],
                "retrieval_stage_s_total": retrieval_stats,
                "retrieval_s_total": retrieval_elapsed,
                "answer": llm["answer"],
                "llm": {
                    "model": llm["model"],
                    "llm_inference_s": llm["llm_inference_s"],
                    "usage": llm["usage"],
                    "request_id": llm["request_id"],
                },
                "total_query_s_est": total_query_time,
            }
            if "reasoning_content" in llm:
                record["llm"]["reasoning_content"] = llm["reasoning_content"]
            records.append(record)

            print("\n" + "=" * 80)
            print(f"QUERY {idx}: {query}")
            print(f"ANSWER: {llm['answer']}")
            print(f"LLM: model={llm['model']} inference={fmt_ms(llm['llm_inference_s'])} usage={llm['usage']}")

        if args.output_jsonl:
            args.output_jsonl.parent.mkdir(parents=True, exist_ok=True)
            with args.output_jsonl.open("w", encoding="utf-8") as fh:
                for record in records:
                    fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            print(f"\nWrote JSONL: {args.output_jsonl}", file=sys.stderr)
    finally:
        runner.close()


if __name__ == "__main__":
    main()
