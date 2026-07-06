#!/usr/bin/env python3
"""Run one RAG agent case against a resident retriever service."""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List

import requests


def fmt_ms(seconds: float) -> float:
    return seconds * 1000.0


def build_prompt(query: str, docs: Iterable[Dict[str, Any]], max_chars_per_doc: int) -> str:
    blocks: List[str] = []
    for rank, doc in enumerate(docs, 1):
        title = doc.get("title") or doc.get("meta", {}).get("title") or ""
        content = doc.get("content") or doc.get("text") or ""
        text = " ".join(str(content)[:max_chars_per_doc].split())
        blocks.append(f"[{rank}] {title}\n{text}")
    context = "\n\n".join(blocks)
    return (
        "You are a knowledge QA assistant. Answer using only the retrieved context. "
        "If the context is insufficient, say that the evidence is insufficient.\n\n"
        f"Question:\n{query}\n\n"
        f"Retrieved context:\n{context}\n\n"
        "Answer in Chinese, concise and evidence-grounded."
    )


def call_llm(args: argparse.Namespace, prompt: str) -> Dict[str, Any]:
    api_key = os.environ.get(args.llm_api_key_env, "")
    if not api_key:
        raise SystemExit(
            f"Missing {args.llm_api_key_env}. Source your private env file first, "
            "for example: set -a; . ~/cunzhe/.secrets/zhipu.env; set +a"
        )

    payload = {
        "model": args.llm_model,
        "messages": [
            {"role": "system", "content": "You answer RAG questions with retrieved evidence."},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "max_tokens": args.llm_max_tokens,
        "temperature": args.llm_temperature,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    start = time.perf_counter()
    response = requests.post(args.llm_api_url, headers=headers, json=payload, timeout=args.llm_timeout)
    elapsed = time.perf_counter() - start
    try:
        data = response.json()
    except ValueError:
        data = {"raw": response.text}
    if response.status_code >= 400:
        raise RuntimeError(f"LLM request failed HTTP {response.status_code}: {data}")
    data["_wall_ms"] = fmt_ms(elapsed)
    return data


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one RAG agent case against localhost retriever")
    parser.add_argument("--retriever-url", default=os.environ.get("RETRIEVER_URL", "http://127.0.0.1:18080"))
    parser.add_argument("--query", default=os.environ.get("QUERY", "what is paula deen's brother"))
    parser.add_argument("--top-k", type=int, default=int(os.environ.get("TOP_K", "5")))
    parser.add_argument("--max-chars-per-doc", type=int, default=int(os.environ.get("MAX_CHARS_PER_DOC", "500")))
    parser.add_argument("--retrieval-only", action="store_true")
    parser.add_argument("--llm-api-url", default=os.environ.get("LLM_API_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"))
    parser.add_argument("--llm-model", default=os.environ.get("LLM_MODEL", "glm-4.5-air"))
    parser.add_argument("--llm-api-key-env", default=os.environ.get("LLM_API_KEY_ENV", "ZHIPU_API_KEY"))
    parser.add_argument("--llm-max-tokens", type=int, default=int(os.environ.get("LLM_MAX_TOKENS", "512")))
    parser.add_argument("--llm-temperature", type=float, default=float(os.environ.get("LLM_TEMPERATURE", "0.2")))
    parser.add_argument("--llm-timeout", type=int, default=int(os.environ.get("LLM_TIMEOUT", "120")))
    parser.add_argument("--output-json", type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        print(f"[agent] affinity={sorted(os.sched_getaffinity(0))}")
    except AttributeError:
        pass
    print(f"[agent] query={args.query}")

    e2e_start = time.perf_counter()
    tool_build_start = time.perf_counter()
    request_payload = {"query": args.query, "top_k": args.top_k}
    tool_request_build_ms = fmt_ms(time.perf_counter() - tool_build_start)

    rpc_start = time.perf_counter()
    response = requests.post(f"{args.retriever_url.rstrip('/')}/search", json=request_payload, timeout=120)
    retriever_rpc_wall_ms = fmt_ms(time.perf_counter() - rpc_start)
    response.raise_for_status()
    retrieval = response.json()
    docs = retrieval.get("docs", [])

    prompt_start = time.perf_counter()
    prompt = build_prompt(args.query, docs, args.max_chars_per_doc)
    prompt_build_ms = fmt_ms(time.perf_counter() - prompt_start)

    record: Dict[str, Any] = {
        "query": args.query,
        "retriever_timings_ms": retrieval.get("timings_ms", {}),
        "tool_request_build_ms": tool_request_build_ms,
        "retriever_rpc_wall_ms": retriever_rpc_wall_ms,
        "prompt_build_ms": prompt_build_ms,
        "prompt_chars": len(prompt),
        "top_ids": [doc.get("id") for doc in docs],
    }

    print("[agent] retriever_timings_ms", json.dumps(record["retriever_timings_ms"], ensure_ascii=False))
    print(f"[agent] tool_request_build_ms={tool_request_build_ms:.2f}")
    print(f"[agent] retriever_rpc_wall_ms={retriever_rpc_wall_ms:.2f}")
    print(f"[agent] prompt_build_ms={prompt_build_ms:.2f} prompt_chars={len(prompt)}")
    print("[agent] top_ids", record["top_ids"])

    if not args.retrieval_only:
        llm = call_llm(args, prompt)
        message = llm.get("choices", [{}])[0].get("message", {})
        answer = message.get("content", "")
        usage = llm.get("usage", {})
        record.update({"answer": answer, "llm_usage": usage, "llm_wall_ms": llm.get("_wall_ms")})
        print(f"[agent] llm_wall_ms={record['llm_wall_ms']:.2f}")
        print("[agent] llm_usage", json.dumps(usage, ensure_ascii=False))
        print("[agent] answer", answer)

    record["e2e_wall_ms"] = fmt_ms(time.perf_counter() - e2e_start)
    print(f"[agent] e2e_wall_ms={record['e2e_wall_ms']:.2f}")

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
