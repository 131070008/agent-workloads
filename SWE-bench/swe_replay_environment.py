"""Measured Docker environment with synchronous, confirmed teardown."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any

from minisweagent.environments.docker import DockerEnvironment


class MeasuredDockerEnvironment(DockerEnvironment):
    """Record Docker lifecycle timestamps and wait until removal completes."""

    def __init__(self, *, telemetry_path: str = "", **kwargs: Any) -> None:
        self.telemetry_path = Path(telemetry_path).expanduser().resolve() if telemetry_path else None
        self.telemetry: dict[str, Any] = {"format_version": 1}
        self._cleanup_complete = False
        super().__init__(**kwargs)

    def _write_telemetry(self) -> None:
        if self.telemetry_path is None:
            return
        self.telemetry_path.parent.mkdir(parents=True, exist_ok=True)
        self.telemetry_path.write_text(
            json.dumps(self.telemetry, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _start_container(self) -> None:
        started_at = time.time()
        started_monotonic = time.monotonic()
        self.telemetry["container_start_requested_at"] = started_at
        try:
            super()._start_container()
        finally:
            finished_at = time.time()
            self.telemetry.update(
                {
                    "container_running_at": finished_at,
                    "container_start_seconds": time.monotonic() - started_monotonic,
                    "container_id": self.container_id,
                }
            )
            self._write_telemetry()

    def _container_exists(self, container_id: str) -> bool:
        completed = subprocess.run(
            [self.config.executable, "inspect", container_id],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return completed.returncode == 0

    def cleanup(self) -> None:
        if self._cleanup_complete:
            return
        container_id = getattr(self, "container_id", None)
        if not container_id:
            self._cleanup_complete = True
            return

        cleanup_started_at = time.time()
        cleanup_started_monotonic = time.monotonic()
        self.telemetry["cleanup_requested_at"] = cleanup_started_at
        stop_returncode = None
        rm_returncode = None
        cleanup_error = None
        try:
            stopped = subprocess.run(
                [self.config.executable, "stop", "--time", "1", container_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
            stop_returncode = stopped.returncode
            deadline = time.monotonic() + 60
            while self._container_exists(container_id) and time.monotonic() < deadline:
                time.sleep(0.05)
            if self._container_exists(container_id):
                removed = subprocess.run(
                    [self.config.executable, "rm", "-f", container_id],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=60,
                    check=False,
                )
                rm_returncode = removed.returncode
            absent = not self._container_exists(container_id)
        except Exception as error:
            absent = False
            cleanup_error = repr(error)
        finished_at = time.time()
        self.telemetry.update(
            {
                "container_removed_at": finished_at,
                "container_teardown_seconds": time.monotonic() - cleanup_started_monotonic,
                "container_absent_confirmed": absent,
                "stop_returncode": stop_returncode,
                "rm_returncode": rm_returncode,
                "cleanup_error": cleanup_error,
                "sandbox_e2e_seconds": finished_at
                - float(self.telemetry.get("container_start_requested_at", finished_at)),
            }
        )
        self._write_telemetry()
        self._cleanup_complete = absent
        if absent:
            self.container_id = None

    def __del__(self) -> None:
        try:
            self.cleanup()
        except Exception:
            pass


def classify_command(command: str) -> str:
    text = command.lower()
    if any(token in text for token in ("pytest", "unittest", "tox ", "runtests")):
        return "test"
    if any(token in text for token in ("pip install", "apt-get", "apt install", "conda install")):
        return "install"
    if any(token in text for token in ("apply_patch", "sed -i", "perl -pi", "cat >", "cat <<", "tee ")):
        return "edit"
    if any(token in text for token in ("python ", "python3 ", "python -m", "python3 -m")):
        return "python"
    if text.lstrip().startswith("git "):
        return "git"
    if any(token in text for token in ("rg ", "grep ", "find ", "cat ", "sed -n", "head ", "tail ", "ls ")):
        return "inspect"
    return "shell"


class SDEMeasuredDockerEnvironment(MeasuredDockerEnvironment):
    """Run each ToolCall under Intel SDE while preserving one container per case."""

    def __init__(
        self,
        *,
        sde_output_root: str,
        sde_container_home: str = "/opt/intel-sde",
        sde_action_timeout: int = 1800,
        sde_max_actions: int = 0,
        **kwargs: Any,
    ) -> None:
        self.sde_output_root = Path(sde_output_root).expanduser().resolve()
        self.sde_output_root.mkdir(parents=True, exist_ok=True)
        self.sde_container_home = sde_container_home.rstrip("/")
        self.sde_action_timeout = sde_action_timeout
        self.sde_max_actions = sde_max_actions
        self.sde_action_index = 0
        super().__init__(**kwargs)

    def execute(self, action: dict, cwd: str = "", *, timeout: int | None = None) -> dict[str, Any]:
        self.sde_action_index += 1
        index = self.sde_action_index
        command = str(action.get("command", ""))
        action_dir = self.sde_output_root / f"action_{index:04d}"
        action_dir.mkdir(parents=True, exist_ok=True)
        instrument = not self.sde_max_actions or index <= self.sde_max_actions
        metadata = {
            "format_version": 1,
            "action_index": index,
            "category": classify_command(command),
            "command": command,
            "cwd": cwd or self.config.cwd,
            "instrumented": instrument,
            "started_at": time.time(),
        }
        (action_dir / "command.txt").write_text(command + "\n", encoding="utf-8")

        wrapped_action = dict(action)
        if instrument:
            container_action_dir = f"/sde-output/action_{index:04d}"
            sde64 = f"{self.sde_container_home}/sde64"
            wrapped_action["command"] = (
                f"mkdir -p {shlex.quote(container_action_dir)} && "
                f"{shlex.quote(sde64)} "
                "-follow_subprocess -mix -iform 1 "
                "-mix_disable_per_function_stats 1 "
                "-mix_disable_per_thread_stats 1 "
                f"-omix {shlex.quote(container_action_dir + '/mix.txt')} "
                f"-- bash -lc {shlex.quote(command)}"
            )

        started_monotonic = time.monotonic()
        result: dict[str, Any] = {}
        raised: Exception | None = None
        try:
            result = super().execute(
                wrapped_action,
                cwd,
                timeout=self.sde_action_timeout if instrument else timeout,
            )
        except Exception as error:
            raised = error
        finally:
            metadata.update(
                {
                    "finished_at": time.time(),
                    "elapsed_seconds": time.monotonic() - started_monotonic,
                    "returncode": result.get("returncode"),
                    "exception_info": (
                        result.get("exception_info", "")
                        if result
                        else repr(raised)
                    ),
                    "exception_type": type(raised).__name__ if raised else "",
                    "output_chars": len(str(result.get("output", ""))),
                    "mix_files": sorted(path.name for path in action_dir.glob("mix*.txt")),
                }
            )
            (action_dir / "action_metadata.json").write_text(
                json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        if raised is not None:
            raise raised
        return result
