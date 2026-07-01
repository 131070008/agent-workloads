#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
WA_DIR="$ROOT_DIR/workloads/WorkArena/upstream/WorkArena"

cd "$WA_DIR"

python - <<'PY'
import random
from time import sleep

from browsergym.core.env import BrowserEnv
from browsergym.workarena import ATOMIC_TASKS

task = random.choice(list(ATOMIC_TASKS))
print("Task:", task)

env = BrowserEnv(task_entrypoint=task, headless=True)
try:
    env.reset()
    env.chat.add_message(role="assistant", msg="On it. Please wait...")
    cheat_messages = []
    env.task.cheat(env.page, cheat_messages)
    for cheat_msg in cheat_messages:
        env.chat.add_message(role=cheat_msg["role"], msg=cheat_msg["message"])
    reward, stop, message, info = env.task.validate(env.page, cheat_messages)
    print({"reward": reward, "stop": stop, "message": message, "info": info})
    sleep(1)
finally:
    env.close()
PY
