# OSWorld Workload

OSWorld is the desktop / GUI / computer-use agent workload family. It covers
real operating-system tasks across browser, office software, media tools,
filesystem operations, IDE usage, and multi-application workflows.

This fills a different slot from the other workloads:

- `WebArena`: web page observation/action loop.
- `Terminal-Bench`: shell/terminal command loop.
- `OSWorld`: desktop screen observation, GUI action, application state, and
  execution-based task evaluation.

## TODO for formal workload study

**TODO: prepare a real desktop execution environment before treating this as a
measured benchmark.** OSWorld needs a VM/provider setup such as VMware Fusion on
macOS, VirtualBox, AWS, or Docker with KVM support on Linux. After that, run a
curated subset from `evaluation_examples/test_small.json` and report success
rate, step count, wall-clock latency, screenshot/a11y observation cost, GUI
action latency, VM reset/setup cost, application launch time, filesystem IO,
and verifier time.

## What this benchmark is for

Desktop agents are important because they stress the CPU and host platform in a
different way from text-only agents:

- Repeated screenshot capture, image encoding, and accessibility-tree capture.
- GUI action dispatch through mouse/keyboard or pyautogui-like APIs.
- Application startup and cross-application state transitions.
- VM lifecycle, reset, snapshot, and remote desktop control.
- File/document processing through real desktop applications.
- Long-horizon action loops with visual feedback.

For CPU agent workload research, OSWorld is useful as the "agent execution
plane" closest to an end-user desktop or AI workstation.

## Local status

Current state:

- Official OSWorld repository cloned to `upstream/OSWorld`.
- Upstream license: Apache-2.0.
- Local benchmark execution has not been completed on this Mac.

Reason: OSWorld is not a simple Python-only smoke. It requires a desktop VM or
provider backend. The upstream README notes VMware/VirtualBox for desktop or
laptop use, Docker with KVM for Linux servers, and AWS for parallel evaluation.
On macOS hosts, Docker/KVM is not the recommended path; VMware Fusion is the
more realistic route.

## Run commands

After configuring a provider/VM, run the upstream quickstart through:

```bash
workloads/OSWorld/run_osworld_quickstart.sh
```

For an actual agent run:

```bash
OSW_PROVIDER=vmware \
OSW_VM_PATH="/path/to/Ubuntu.vmx" \
OSW_MODEL=gpt-4o \
OSW_MAX_STEPS=15 \
workloads/OSWorld/run_osworld_agent.sh
```

For Docker/KVM on a Linux server:

```bash
OSW_PROVIDER=docker \
OSW_MODEL=gpt-4o \
OSW_MAX_STEPS=15 \
workloads/OSWorld/run_osworld_agent.sh
```

The default task list is `evaluation_examples/test_small.json`, which includes
Chrome, GIMP, LibreOffice, multi-app, OS, Thunderbird, VLC, and VS Code tasks.

## Notes

- OSWorld currently targets multimodal/GUI-capable models. Local text-only
  Ollama models are not enough for the normal screenshot-based setting.
- For local CPU workload work, the most useful measurements are host-side VM
  control, screenshot/a11y capture, image preprocessing, application launch,
  filesystem/document IO, and verifier overhead.
- Keep `results/` out of git; OSWorld trajectories can contain screenshots,
  recordings, and task artifacts.
