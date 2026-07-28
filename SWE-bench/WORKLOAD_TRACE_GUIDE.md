# SWE Agent Workload 进一步归因

## 1. Page fault 类型

`page-faults/minor-faults/major-faults` 只能统计数量，不能说明缺页原因。Linux 5.15
可以通过 MM 内核路径进一步拆成：

| 路径 | 含义 |
|---|---|
| `handle_mm_fault` | 进入 Linux MM fault handler 的总次数 |
| `do_anonymous_page` | 匿名页首次触碰，常见于 malloc/mmap 后第一次访问 |
| `do_wp_page` | 写保护 fault，主要包含 fork/COW |
| `do_fault` | file-backed VMA fault，包含动态库、Python module、mmap 文件等 |
| `do_swap_page` | swap fault |
| `do_huge_pmd_anonymous_page` | 匿名透明大页 fault |

采集命令：

```bash
PAGE_FAULT_CPUS=0-7 \
PAGE_FAULT_SECONDS=30 \
/home/higon/cunzhe/agent-workloads/SWE-bench/collect_page_fault_types.sh
```

该脚本只做 CPU0-7 全域统计。当前 Ubuntu 5.15 内核上，kprobe trace event 与
`perf --for-each-cgroup` 的组合验证出现挂起，不能用于正式采集。若需要按 Host
Agent/Sandbox 拆分，应安装 bpftrace/BCC 后按 cgroup ID 过滤。

以上方法可以区分 fault 大类，但不能直接报告“具体是哪一个 `.so`”。精确到文件
需要额外记录 fault address，并与进程当时的 VMA/file mapping 关联。

## 2. SDE 动态指令分布

快速统计 INT/FP/LDST/branch 不需要先生成 Pinball。直接对目标命令做动态执行：

```bash
SDE64=/home/higon/sde-external-9.48.0-2024-11-25-lin/sde64 \
/home/higon/cunzhe/agent-workloads/SWE-bench/run_sde_mix.sh \
python3 -c 'print(sum(range(100000)))'
```

脚本使用：

```text
-follow_subprocess
-mix
-iform 1
```

`-follow_subprocess` 会跟踪 shell 创建的 Python/pytest 子进程，并为每个子进程生成
单独的 mix 文件。`summarize_sde_mix.py` 将这些文件汇总为：

- 动态指令总数；
- CALL/RET/条件跳转/无条件跳转比例；
- integer ALU category 近似比例；
- SIMD-family category 近似比例；
- memory read/write operands `/KI`；
- FP elements 和 integer vector elements `/KI`；
- Top XED categories。

需要注意：

1. Memory read/write 是动态内存操作数次数，不是 load/store 指令数。
2. SSE/AVX category 可能混合整数、浮点和数据搬运，不能直接作为精确 FP 比例。
3. `elements_fp_*` 是浮点 lane operations，不是指令条数。
4. 精确 INT/FP opcode mix 需要继续按 XED iform 语义映射。

Pinball 适合“执行一次、反复做不同 SDE 分析”或截取稳定 ROI。当前已有的 SWE
trajectory 是 ToolCall 命令轨迹，不是 CPU Pinball；先用 trajectory 选择有代表性的
pytest、项目脚本和复现脚本，再分别运行 SDE，成本更低，也更容易解释。

对 SWE 镜像中的真实 ToolCall，可将 SDE 只读挂载进容器：

```bash
SDE_SWE_IMAGE=docker.io/swebench/sweb.eval.x86_64.pytest-dev_1776_pytest-11148:latest \
SDE_CPUSET=0 \
/home/higon/cunzhe/agent-workloads/SWE-bench/run_sde_swe_toolcall.sh \
  'python3 -m pytest testing/test_pathlib.py -x -q -k importlib'
```

该方法统计的是容器内 `bash -> python/pytest` 的动态指令，不会把宿主机 Docker
CLI 混入结果。它适合从 trajectory 中分别选择复现探针、pytest 和项目脚本；
不同 ToolCall 的指令量差异很大，应分别报告，不应先合并成一个“平均 opcode
mix”。

Intel Pin/SDE 在该服务器的 Docker PID namespace 内会在信号初始化阶段失败，
因此分析容器使用 `--pid=host`、`SYS_ADMIN`、`SYS_PTRACE` 和
`seccomp=unconfined`。这些权限仅用于离线 SDE 分析，容器仍使用
`--network=none`；它们不是正常 Agent Sandbox 的部署配置。

## 3. Python 在做什么

现有 Flash/Pro 各 30 条 Golden trajectory 可以直接按 ToolCall command 分类：

```bash
python3 /home/higon/cunzhe/agent-workloads/SWE-bench/analyze_trajectory_python_roles.py \
  /home/higon/cunzhe/swe_runs/golden_replay/flash/trajectories \
  /home/higon/cunzhe/swe_runs/golden_replay/pro/trajectories \
  --csv /home/higon/cunzhe/swe_runs/golden_replay/python_roles.csv \
  --json /home/higon/cunzhe/swe_runs/golden_replay/python_roles.json \
  --markdown /home/higon/cunzhe/swe_runs/golden_replay/python_roles.md
```

分类包括：

- `python_test`：pytest/unittest/tox；
- `python_edit_helper`：Agent 使用 Python 修改源码；
- `python_reproduction_probe`：`python -c`、heredoc 和 `/tmp` 复现脚本；
- `python_project_script`：直接执行仓库中的 Python 脚本；
- `python_package_or_env`：pip/conda/setup.py；
- `python_backed_cli`：pylint/sphinx-build/mypy 等。

该统计回答的是“ToolCall 想让 Python 做什么”，不是 CPU time。Host Agent 自身的
Python 负责 agent loop、请求构造、HTTP 等待、动作解析、Docker exec 和输出捕获，
不会作为 Sandbox command 出现在 trajectory 中。

若要得到各类 Python 的 CPU time，应在下一轮同时记录：

1. cgroup ID：区分 Host Agent 与 Sandbox；
2. exec 事件：记录 PID/PPID、时间和 argv；
3. sched switch：按 PID 累计 on-core runtime；
4. exit 事件：结束进程生命周期。

之后按 argv 将 PID 标注为 pytest、项目脚本、编辑 helper、包管理或 Host Agent，
再汇总 CPU time。
