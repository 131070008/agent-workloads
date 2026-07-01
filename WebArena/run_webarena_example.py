#!/usr/bin/env python3
"""Run a small WebArena example task through the local WebArena stack."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_DIR = ROOT / "workloads" / "WebArena"
UPSTREAM_DIR = WORKLOAD_DIR / "upstream" / "webarena-src"


def set_default_site_env() -> None:
    defaults = {
        "REDDIT": "http://metis.lti.cs.cmu.edu:9999",
        "SHOPPING": "http://metis.lti.cs.cmu.edu:7770",
        "SHOPPING_ADMIN": "http://metis.lti.cs.cmu.edu:7780/admin",
        "GITLAB": "http://metis.lti.cs.cmu.edu:8023",
        "MAP": "http://metis.lti.cs.cmu.edu:3000",
        "WIKIPEDIA": (
            "http://metis.lti.cs.cmu.edu:8888/wikipedia_en_all_maxi_2022-05/"
            "A/User:The_other_Kiwix_guy/Landing"
        ),
        "HOMEPAGE": "http://metis.lti.cs.cmu.edu:4399",
    }
    for key, value in defaults.items():
        os.environ.setdefault(key, value)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="config_files/examples/2.json",
        help="Path relative to the upstream WebArena directory.",
    )
    parser.add_argument(
        "--mode",
        choices=["teacher", "llm"],
        default="teacher",
        help="teacher replays reference actions; llm calls an OpenAI-compatible model.",
    )
    parser.add_argument("--model", default=os.environ.get("MODEL", "qwen3:8b"))
    parser.add_argument(
        "--api-base",
        default=os.environ.get("OPENAI_API_BASE", "http://127.0.0.1:11434/v1"),
    )
    parser.add_argument("--api-key", default=os.environ.get("OPENAI_API_KEY", "EMPTY"))
    parser.add_argument("--max-steps", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-obs-length", type=int, default=1600)
    parser.add_argument("--viewport-width", type=int, default=1280)
    parser.add_argument("--viewport-height", type=int, default=720)
    parser.add_argument(
        "--result-json",
        default="workloads/WebArena/results/webarena_example_result.json",
    )
    return parser.parse_args()


def make_action(action_set_tag: str, action_str: str) -> dict[str, Any]:
    from browser_env import create_id_based_action, create_playwright_action

    if action_set_tag == "playwright":
        return create_playwright_action(action_str)
    if action_set_tag == "id_accessibility_tree":
        return create_id_based_action(action_str)
    raise ValueError(f"Unsupported action_set_tag: {action_set_tag}")


def build_llm_agent(args: argparse.Namespace) -> Any:
    from agent import construct_agent
    from agent.prompts import to_json

    to_json.run()
    instruction_path = "agent/prompts/jsons/p_direct_id_actree_2s.json"
    agent_args = SimpleNamespace(
        agent_type="prompt",
        action_set_tag="id_accessibility_tree",
        instruction_path=instruction_path,
        provider="openai",
        model=args.model,
        mode="chat",
        temperature=args.temperature,
        top_p=0.9,
        context_length=0,
        max_tokens=args.max_tokens,
        stop_token=None,
        max_obs_length=args.max_obs_length,
        max_retry=1,
        model_endpoint="",
    )
    return construct_agent(agent_args)


def run() -> int:
    args = parse_args()
    set_default_site_env()
    os.environ["OPENAI_API_BASE"] = args.api_base
    os.environ["OPENAI_API_KEY"] = args.api_key
    sys.path.insert(0, str(UPSTREAM_DIR))
    os.chdir(UPSTREAM_DIR)

    from browser_env import (
        ActionTypes,
        ScriptBrowserEnv,
        create_stop_action,
    )
    from evaluation_harness import evaluator_router

    config_path = Path(args.config)
    if not config_path.exists():
        raise FileNotFoundError(config_path)
    with config_path.open() as f:
        config = json.load(f)

    env = ScriptBrowserEnv(
        headless=True,
        observation_type="accessibility_tree",
        current_viewport_only=True,
        viewport_size={
            "width": args.viewport_width,
            "height": args.viewport_height,
        },
    )

    started = time.perf_counter()
    trajectory: list[Any] = []
    actions: list[str] = []
    score = 0.0
    error = ""
    try:
        obs, info = env.reset(options={"config_file": str(config_path)})
        state_info = {"observation": obs, "info": info}
        trajectory.append(state_info)
        print("=" * 80)
        print("WEBARENA EXAMPLE")
        print("=" * 80)
        print(f"mode: {args.mode}")
        print(f"config: {config_path}")
        print(f"task_id: {config.get('task_id')}")
        print(f"intent: {config.get('intent')}")
        print(f"start_url: {config.get('start_url')}")
        print(f"initial_url: {info['page'].url}")
        print(f"initial_observation_chars: {len(obs['text'])}")

        if args.mode == "teacher":
            ref = config["reference_action_sequence"]
            action_set_tag = ref["action_set_tag"]
            planned_actions = ref["action_sequence"]
            for action_str in planned_actions:
                action = make_action(action_set_tag, action_str)
                action["raw_prediction"] = action_str
                actions.append(action_str)
                trajectory.append(action)
                if action["action_type"] == ActionTypes.STOP:
                    break
                obs, _, terminated, _, info = env.step(action)
                state_info = {"observation": obs, "info": info}
                trajectory.append(state_info)
                if terminated:
                    break
        else:
            agent = build_llm_agent(args)
            meta_data = {"action_history": ["None"]}
            for step in range(args.max_steps):
                action = agent.next_action(
                    trajectory,
                    config["intent"],
                    meta_data=meta_data,
                )
                raw = action.get("raw_prediction", "")
                actions.append(raw)
                trajectory.append(action)
                print("-" * 80)
                print(f"step: {step + 1}")
                print(f"raw_prediction: {raw}")
                print(f"action_type: {action['action_type']}")
                if action["action_type"] == ActionTypes.STOP:
                    break
                if action["action_type"] == ActionTypes.NONE:
                    meta_data["action_history"].append("None")
                    break
                obs, _, terminated, _, info = env.step(action)
                state_info = {"observation": obs, "info": info}
                trajectory.append(state_info)
                meta_data["action_history"].append(raw)
                if terminated:
                    trajectory.append(create_stop_action(""))
                    break

        evaluator = evaluator_router(str(config_path))
        score = float(
            evaluator(
                trajectory=trajectory,
                config_file=str(config_path),
                page=env.page,
                client=env.get_page_client(env.page),
            )
        )
        print("=" * 80)
        print(f"score: {score}")
        print(f"final_url: {env.page.url}")
        print(f"actions: {len(actions)}")
        print(f"e2e_ms: {(time.perf_counter() - started) * 1000:.1f}")
    except Exception as exc:
        error = repr(exc)
        print(f"ERROR: {error}", file=sys.stderr)
        raise
    finally:
        result = {
            "mode": args.mode,
            "config": str(config_path),
            "task_id": config.get("task_id"),
            "intent": config.get("intent"),
            "score": score,
            "actions": actions,
            "error": error,
            "e2e_ms": (time.perf_counter() - started) * 1000,
        }
        result_path = ROOT / args.result_json
        result_path.parent.mkdir(parents=True, exist_ok=True)
        result_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
        env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
