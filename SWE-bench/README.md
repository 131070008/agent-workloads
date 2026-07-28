# SWE-bench Workload

This directory collects SWE-bench workload inputs and harness drivers.

# TODO Before Formal Benchmark Analysis

The current local run is a path-validation smoke. Before using this workload
for formal CPU agent workload analysis, run a larger standard SWE-bench subset
and score patches with the official evaluation flow.

Required next steps:

- Run a meaningful subset of SWE-bench Lite or SWE-bench Verified, not only the
  single `pallets__flask-4045` smoke case.
- Use local LLM runs first, then optionally compare with cloud models.
- Add official patch validation / grading so results report solved rate, not
  only `Submitted`.
- Record E2E latency, agent step count, shell/python/test execution time,
  patch size, retry count, and pass/fail reason.
- Keep single-case smoke runs only as path validation, not as formal benchmark
  evidence.

## What This Benchmark Does

This benchmark represents a coding-agent workload. The agent receives a real
GitHub issue or bug-fix task from SWE-bench, explores the repository, edits
code, runs shell/python/test commands, and submits a patch. The benchmark then
checks whether the patch fixes the issue.

Typical tasks:

- fix a failing behavior in an existing Python project
- inspect source files, tests, and error messages
- run commands in a sandbox or local environment
- generate and validate a code patch

Important distinction:

- SWE-bench / SWE-bench Lite / SWE-bench Verified: benchmark datasets.
- mini-swe-agent / SWE-agent / OpenHands / Codex-style agents: agent runners.
- This folder: local workload harness and case manifests for running standard
  SWE-style tasks in a controlled way.

## First Workload

The first supported workload is `swe_bench_lite_smoke`:

```text
dataset: SWE-bench Lite
split: test
cases: 300
local smoke case: pallets__flask-4045
```

The local smoke case has already been run successfully with Ollama/Qwen:

```text
instance: pallets__flask-4045
status: Submitted
wall time: 925.9s
```

## Run

List local smoke cases:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh --list-cases
```

Dry-run the command without invoking the model:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh --dry-run
```

Run the default smoke case:

```bash
workloads/SWE-bench/run_swe_lite_smoke.sh
```

Run one official SWE-bench Lite case from the local 300-case test split. This
does not use the 20-case smoke manifest.

```bash
cd ~/cunzhe/agent-workloads
set -a
. ~/cunzhe/.secrets/zhipu.env
set +a

SWE_INSTANCE_ID=astropy__astropy-12907 \
SWE_OUTPUT_DIR=~/cunzhe/swe_runs/swe_lite_official_one \
SWE_STEP_LIMIT=40 \
SWE_AGENT_CORE=1 \
SWE_CONTAINER_CPUSET=2 \
SWE-bench/run_swe_lite_official_case.sh
```

Evaluate the generated patch with the official SWE-bench harness:

```bash
cd ~/cunzhe/agent-workloads
.venv-swe/bin/python - <<'PY'
import json
from pathlib import Path
from datasets import Dataset

repo = Path.home() / "cunzhe/agent-workloads"
out = Path.home() / "cunzhe/swe_runs/swe_lite_official_one"
iid = "astropy__astropy-12907"
ds = Dataset.from_file(str(repo / "SWE-bench/datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow"))
row = next(dict(r) for r in ds if r["instance_id"] == iid)
(out / "dataset_one.json").write_text(json.dumps([row], ensure_ascii=False, indent=2), encoding="utf-8")
PY

.venv-swe/bin/python -m swebench.harness.run_evaluation \
  --dataset_name ~/cunzhe/swe_runs/swe_lite_official_one/dataset_one.json \
  --split test \
  --instance_ids astropy__astropy-12907 \
  --predictions_path ~/cunzhe/swe_runs/swe_lite_official_one/preds.json \
  --max_workers 1 \
  --timeout 1800 \
  --run_id glm_air_astropy12907 \
  --namespace swebench \
  --cache_level env \
  --clean false \
  --report_dir ~/cunzhe/swe_runs/swe_lite_official_one/eval_report
```

CPU placement knobs:

```text
SWE_AGENT_CORE=1          pins the host-side mini-SWE-agent Python process.
SWE_CONTAINER_CPUSET=2    passes --cpuset-cpus=2 to docker run for the sandbox.
SWE_CONTAINER_CGROUP_PARENT=swe-sandbox.slice
                          passes --cgroup-parent to group sandbox processes.
```

Recommended trace setup:

```text
core 1: agent/control path
        mini-SWE-agent Python process, LLM orchestration, docker client calls

core 2: sandbox/tool path
        bash, git, python, pytest, and other commands inside the Docker sandbox
```

This split avoids chasing short-lived tool-call PIDs. Commands directly forked
by the agent inherit the agent CPU affinity, while commands inside Docker are
created by the container runtime and should be controlled through
`SWE_CONTAINER_CPUSET`.

Start `perf` in separate terminals before launching the SWE case:

```bash
# Host-side agent/control path.
sudo perf stat -a -C 1 \
  -e cycles,instructions,branches,branch-misses,cache-misses,context-switches,cpu-migrations,page-faults \
  -- sleep 1200

# Sandbox/tool path.
sudo perf stat -a -C 2 \
  -e cycles,instructions,branches,branch-misses,cache-misses,context-switches,cpu-migrations,page-faults \
  -- sleep 1200
```

For call-stack sampling of the sandbox/tool path:

```bash
sudo perf record -a -C 2 -g \
  -o ~/cunzhe/swe_runs/sandbox_core2.data \
  -- sleep 1200

sudo perf report -i ~/cunzhe/swe_runs/sandbox_core2.data
```

Inspect the running sandbox and confirm its CPU set:

```bash
docker ps --filter name=minisweagent
CID=$(docker ps -q --filter name=minisweagent | head -n 1)
docker inspect --format '{{.Name}} pid={{.State.Pid}} cpuset={{.HostConfig.CpusetCpus}}' "$CID"
docker top "$CID"
```

## EMR PMU 分轮采集（CPU 0-7）

`collect_emr_pmu_8c.sh` 面向 96-agent 固定池实验。主采集范围是 CPU
`0-7`，并通过 `-A` 保留逐核结果：既能汇总整个 8 核池，也能在同一份结果中
单独检查某个 core。基础指标和 raw event 同时按 host-agent、sandbox、
system services 三个 cgroup 统计；Top-down 按 8 核池全域统计；DDR IMC 是
socket 级指标，独立贯穿整轮。

这里不是“有 12 个 port 可以同时采”。12 是我们希望观察的事件数量；处理器
虽有多组 PMU counter，但不少 cache/TLB raw event 只能使用部分 counter。一次
塞入 12 个事件时，本机实测事件仅获得约 33% 的 PMU 运行时间。因此脚本把受限
事件拆成每组 4 个，避免严重分时复用。每组另外携带固定计数器 `cycles` 和
`instructions`，它们不占这 4 个 programmable counter，MPKI 可以使用同一
采集窗口的 retired instructions 计算。

先启动带 cgroup 分组的固定池，再在另一个终端运行：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/collect_emr_pmu_8c.sh latest 10 3
```

参数依次是运行目录、每组采集秒数、轮数。默认值也是 `latest 10 3`：每组
10 秒，一轮 9 组约 90 秒，三轮约 4.5 分钟。10 秒窗口内有 96 个并发 agent，
通常足以覆盖多个短 burst；重复三轮用于覆盖 LLM 返回时序不同造成的阶段偏差。
三轮分别从 `01/04/07` 开始并循环执行，避免固定 pass 顺序把某一指标长期绑定到
启动、稳态或收尾阶段。准确顺序写入 `config.txt`。

每轮包含：

```text
01 Top-down L1/L2（8 核池）
02 cycles/instructions/branch/scheduler/page fault，包含 minor/major fault（按 cgroup）
03 retired load 的 L1/L2/L3 命中与 L3 miss（按 cgroup）
04 local/remote DRAM locality（按 cgroup）
05 L2/LLC request 与 miss（按 cgroup）
06 DTLB（按 cgroup）
07 ITLB/I-cache（按 cgroup）
08 memory-stall depth（按 cgroup）
09 demand data read、L1D/L2 hardware-prefetch read 与 useless L2 HWPF（按 cgroup）
DDR IMC read/write CAS（socket 级，并行覆盖全程）
```

不启动 SWE、也不调用 LLM 的独立 DGEMM 验证：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/run_emr_pmu_dgemm_validation.sh
```

该命令把一个 8-thread、`6144 x 6144` 的 DGEMM transient service 放进
`swe-sandbox.slice`，限制在 CPU `0-7`，同时执行 `5 秒 x 9 组 x 1 轮`
采集，总耗时约 55 秒。其目的只是确认 PMU 事件、cgroup 归因和 DDR 数据合理；
正式 agent 实验仍使用前面的 `10 秒 x 9 组 x 3 轮`。

96-agent 正式实验的一键编排：

```bash
nohup /home/higon/cunzhe/agent-workloads/SWE-bench/run_formal_swe_pmu_96.sh \
  > /home/higon/cunzhe/swe_runs/formal_swe_pmu_supervisor.log 2>&1 &
```

编排器先用当前 DeepSeek 配置完成一次 1-token API 预检，再等待 96 个 agent
slot 和至少 88 个 sandbox 连续稳定三次，然后采集三轮 PMU；同时记录 30 秒
`perf sched`、99 Hz 的全域 cgroup-aware `comm` 样本，以及采集窗口内的网卡
吞吐。后者直接生成 `host_agent / sandbox / system_services / other x comm`，用于
区分 host Python 与 sandbox Python。采集结束后立即停止 workload，并自动生成
0-7 核、CPU0 调度报告以及 `formal_summary.md/json`。`formal_status.txt`、
`formal_readiness.tsv` 和 `formal_stop.log` 分别记录实验状态、稳态判定与回收结果。

这里的全域样本仍限定在受控 CPU `0-7`，目的是与 PMU 和调度结果保持同一观测
边界；它不是 192-logical-CPU 全机采样。`dockerd/containerd` 没有随 workload
绑定到 CPU0-7，可能在池外 CPU 运行，因此 `system_services=0` 只能解释为该窗口
在 CPU0-7 无样本，不能解释为 Docker/runtime 没有 CPU 开销。若研究 runtime
控制面，应另做短窗口全机 placement trace，不能混入 8 核池的微架构比例。

结果保存在当前 workload 运行目录下的
`perf_collect/emr_pmu_<date>_<pid>/`。每个 CSV 都带 1 秒时间戳；
`timeline.tsv` 记录各 pass 的准确边界。脚本会先用 CPU0 对每个事件组做一次
system-wide counter 调度自检；`event_unsupported.txt` 记录真正不支持的事件，
`cgroup_idle_samples.txt` 则表示某个 cgroup 在某核、某秒内没有任务运行，二者
不能混为一谈。DDR 的 CAS 计数乘以 64 字节，再除以采样间隔即可换算带宽。

### 细粒度 Top-down 与指令类别

`pmu-tools` 验证脚本先用可控的 integer、AVX-512 FP64、unpredictable branch
和 mixed 四种负载检查事件响应：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/pmu_demo/validate_pmu_tools_demo.sh
```

正式 96-agent 采集使用：

```bash
nohup /home/higon/cunzhe/agent-workloads/SWE-bench/run_formal_swe_pmu_detailed_96.sh \
  > /home/higon/cunzhe/swe_runs/formal_swe_pmu_detailed.log 2>&1 &
```

默认配置是 96 个真实 API agent，Host Agent 和 Sandbox 都限制在逻辑 CPU
`0-7`，分别进入 `swe-agent.slice` 与 `swe-sandbox.slice`。脚本等待
`96 active jobs` 和至少 88 个容器达到稳态，再执行以下采集：

```text
13 组 cgroup PMU：
  cycles/instructions、scheduler/fault、branch type、load/store、
  FP32/FP64 scalar/128/256/512-bit、cache、TLB、stall、prefetch

cgroup Top-down：
  slots 及 L1/L2 PERF_METRICS，Host/Sandbox/system 同窗统计

细粒度 Top-down：
  pmu-tools L6，no-multiplex，对 CPU0-7 所在物理核做全域统计
```

每个原始事件组只包含固定计数器和最多 4 个 programmable event，脚本检查
hardware running percentage，低于 99% 会判为失败。`fp_arith_inst_retired`
可以区分 single/double 和向量宽度；FMA 在该事件语义下通常按两个算术操作计数。
PMU 不能给出严格互斥的 scalar-int/FP/branch 指令饼图：branch、load/store 和
FP 可以独立计数，Retiring 子树可以给出 slot/uop 分类，但精确 opcode mix 仍需
Intel SDE。

细粒度 `toplev` 不能可靠处理“任务不断迁核的动态 cgroup + 多 CPU +
no-multiplex”：实测会在所有底层轮次结束后触发 `verify_rev` 断言。因此脚本只把
稳定的 L1/L2 PERF_METRICS 按 cgroup 拆分，L6 保持 8 核池全域口径。由于
CPU0-7 的 SMT siblings 也共享部分 core-level 资源，L6 会自动把 sibling logical
CPU 加入观测集合；workload 的 affinity 仍然只有 CPU0-7，不能把观测集合误写成
workload 使用了 16 个逻辑 CPU。

### Fault 与网络包长专项复测

只复测 minor/major page fault 和物理网卡 RX/TX 包长分布时，运行：

```bash
nohup /home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_fault_network_96.sh \
  > /home/higon/cunzhe/swe_runs/fault_network_supervisor.log 2>&1 &
```

脚本等待 96-agent 固定池达到稳态后同步采集 60 秒：`page-faults`、
`minor-faults`、`major-faults` 按 Host Agent/Sandbox/System Services cgroup
拆分；`ens16f0` 按 RX/TX 分别保存每包前 96 byte 和原始 frame length。结果包含
全流量与 TCP/443 的 min/max/mean/P50/P90/P99，以及 64B 到 1518B 的包长分桶。
pcap 不保存完整 TLS/application payload；`>1522B` 单列为可能受 GRO/GSO/TSO
影响的 host-side 大包。结束后脚本自动停止 workload，结果位于
`perf_collect/fault_network/` 和运行目录下的 `fault_network_summary.md`。

### 正式实验中的预取口径

正式第 09 pass 只回答当前最需要的两个问题：demand data read 与 core L1D/L2
hardware-prefetch read 各占多少，以及有多少 L2 HW-prefetched line 在 demand 使用
前就被驱逐。所有指标按 host-agent / sandbox cgroup 分开，并携带同窗
`cycles/instructions`。

```text
HWPF request share = L1D/L2 HWPF offcore read request /
                     (demand data read request + L1D/L2 HWPF read request)
confirmed bad   = L2_LINES_OUT.USELESS_HWPF
waste proxy     = useless L2 HWPF eviction / L2 HWPF true-miss request
```

`L2 HWPF true miss` 只表示预取请求访问到 L2 以下层级，本身不是 bad；最后一个
比值因 request 与 eviction 生命周期不完全对齐，只作为近似。第一个比值是
offcore read-request 构成，不是 DDR 字节流量；它也不含 code fetch、software
prefetch、RFO/write prefetch 和 L3-only prefetch。因此正式结论使用“已确认的
useless 下界”，不延伸成完整 prefetch accuracy。

### 可选预取深挖

需要继续区分软件预取、L3-only prefetch 或研究 timely/late 时，才追加运行：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/collect_emr_prefetch_8c.sh latest 10 2
```

脚本按 host-agent / sandbox cgroup 分别采集 8 组事件，每组都带同窗
`cycles/instructions`：

```text
01 L1D/L2 hardware prefetch 活动、L2 HWPF true miss、unused-prefetch eviction
02 L2 lines-in、L2 demand request/miss、offcore L3-miss demand read
03 software prefetch hit/miss 与 fill-buffer hit
04 outstanding L1D miss、fill-buffer full、L2 resource stall
05 Offcore demand data 与 L1D hardware prefetch 流量
06 Offcore L2 hardware prefetch 与 demand-data L3 miss
07 L3-only hardware prefetch 的 L3 hit/miss
08 PREFETCHNTA/T0/T1/T2/W 软件预取指令类型
DDR IMC read/write CAS（socket 级，并行覆盖全程）
```

结果保存在 `perf_collect/emr_prefetch_<date>_<pid>/`，并自动生成
`prefetch_summary.md/json`。`L2_RQSTS.HWPF_MISS` 表示预取请求需要访问 L2
以下层级，不代表预取无效；`L2_LINES_OUT.USELESS_HWPF` 才表示预取线被驱逐前
没有被 demand 使用。单次观测可以确认预取活动和浪费，判断净收益仍需在同一
workload 上逐项关闭 L1 DCU streamer、L1 DCU IP、L2 streamer、L2
adjacent-line prefetcher 做 A/B，并同时比较吞吐、demand MPKI、memory stall
和 DDR 带宽。

推荐把预取结论拆成三个指标，避免把“发过请求”误写成“有效”：

```text
Accuracy proxy = 1 - unused L2 HWPF eviction / L2 HWPF true-miss request
Coverage       = (demand miss with PF off - demand miss with PF on) / demand miss with PF off
Net benefit    = throughput_on / throughput_off，同时检查 stall 与 DDR traffic
```

第一个只能视作长稳态窗口下的近似 accuracy，因为 request、fill、eviction 的
生命周期不完全对齐；后两个必须依靠开关预取器的同 workload A/B。术语上，
只要预取线后来被 demand 使用，就属于 accurate/useful prefetch；其中再区分
timely 和 late。late prefetch 仍然预测正确，只是 demand 到达时数据还在路上，
可通过调整触发阈值、预取距离或动态训练步长改善。性能收益是另一个正交维度：
accurate prefetch 可能因访存延迟已被 OoO、MLP 或 SMT 隐藏而没有明显 speedup。

## Golden trajectory 录制与回放

平台性能和预取 A/B 不再重复请求在线 LLM。先由 Flash/Pro 各自生成同一组
30 个 SWE-bench Lite case 的 trajectory，再通过 mini-SWE-agent 的
deterministic model 回放历史模型动作。回放时只固定模型决定；Docker container、
shell command、测试、输出捕获和最终 patch 都会在当前平台重新执行。

单条轨迹严格验证：

```bash
/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/replay_swe_trajectory.py \
  --trajectory /path/to/source.traj.json \
  --output-dir /home/higon/cunzhe/swe_runs/replay_validation/one_case \
  --cpuset 0-7 \
  --network-none \
  --delay-scale 0 \
  --strict
```

`--strict` 要求 command 序列、return-code 序列、退出状态和最终 patch 全部一致。
`delay_scale=0` 删除 LLM 等待，用于跨平台性能和吞吐对比；`delay_scale=1` 保留
Golden 轨迹记录的模型反压节奏，用于 PMU、Top-down、scheduler、page fault 和
DDR 等微架构采集。两类实验都纳入全部 case，不以 resolved 结果筛选 workload；
网络包不在本轮研究范围内。第一条模型动作无法从旧轨迹中单独拆出 Docker startup
与首次 LLM 延迟，因此固定为零；批量实验依靠 stagger 避免所有任务同时进入首次
工具调用。

录制 Pro 轨迹时从独立 secret 文件导出环境变量。直连模型类保留 mini-SWE-agent
的文本协议、action 解析和 API 计数，但不经过 LiteLLM 的 HTTP transport；脚本
只把带 `exit_status` 的终态 trajectory 计为已完成，因此中断后可直接重跑：

```bash
set -a
source /home/higon/cunzhe/.secrets/deepseek-pro.env
set +a
export SWE_MODEL=openai/deepseek-v4-pro
export PYTHONPATH=/home/higon/cunzhe/agent-workloads/SWE-bench

/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/record_swe_trajectories.py \
  --selected-tsv /home/higon/cunzhe/swe_runs/image_pull_selected/selected_30_cases.tsv \
  --output-dir /home/higon/cunzhe/swe_runs/selected_30_deepseek_pro_golden_source \
  --existing-root /home/higon/cunzhe/swe_runs/selected_12_deepseek_pro_noon \
  --existing-root /home/higon/cunzhe/swe_runs/selected_30_deepseek_pro_golden_source \
  --workers 2 --agent-core-start 8 --container-cpuset 0-7 \
  --container-memory 16g --container-pids-limit 4096 \
  --step-limit 80 --max-tokens 8192 --llm-timeout 180 \
  --model-class swe_direct_openai_model.DirectOpenAITextbasedModel
```

在 Golden 打包前运行官方 evaluator。`--python` 必须保留 venv 中的路径，不能
手工展开为 `/usr/bin/python3.10`：

```bash
/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/evaluate_swe_golden_set.py \
  --selected-tsv /home/higon/cunzhe/swe_runs/image_pull_selected/selected_30_cases.tsv \
  --source-root /path/to/trajectory/root \
  --output-dir /path/to/evaluation/output \
  --arrow /home/higon/cunzhe/agent-workloads/SWE-bench/datasets/swe_bench_lite_smoke/raw/swe-bench_lite-test.arrow \
  --python /home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  --workers 4 --timeout 1800 --run-id MODEL_GOLDEN30
```

已有轨迹封装为 Golden Set：

```bash
/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/build_swe_golden_set.py \
  --label deepseek-v4-flash \
  --selected-tsv /home/higon/cunzhe/swe_runs/image_pull_selected/selected_30_cases.tsv \
  --source-root /home/higon/cunzhe/swe_runs/selected_30_deepseek_batch \
  --output-dir /home/higon/cunzhe/swe_runs/golden_replay/flash \
  --evaluation-report /path/to/evaluator/report.json
```

输出包括原始 trajectory、SHA256、image ID/digest、API/action 数量、token usage、
动作到达间隔、工具执行时间和 evaluator 元数据。镜像本体不放 Git；跨平台使用
`docker save/load` 传输，并按 manifest 校验 `linux/amd64` 与 image digest。

批量最大压力回放：

```bash
/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_golden_replay.py \
  --golden-dir /home/higon/cunzhe/swe_runs/golden_replay/flash \
  --output-dir /home/higon/cunzhe/swe_runs/golden_results/flash_throughput \
  --workers 96 \
  --repeats 4 \
  --delay-scale 0 \
  --agent-cpuset 0-7 \
  --sandbox-cpuset 0-7 \
  --network-none \
  --validation-mode semantic
```

同样命令切换到 Pro Golden Set 即可比较两种模型形成的 tool-call 数量、命令组合
和 sandbox CPU service demand。跨平台性能与吞吐对比使用 `--delay-scale 0`；
PMU、Top-down 等微架构采集使用 `--delay-scale 1`。录制新轨迹才需要 API key，
Golden 打包与所有 replay 均不读取模型环境文件。

### Golden 零延迟性能

单个 case 串行重复三次：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_golden_single_perf.sh \
  pytest-dev__pytest-11148 3
```

30 个 case 使用 8 个并发 worker：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_golden_multi_perf.sh 8 1
```

上面的有限 30-job 批次适合快速检查。正式固定八核吞吐使用持续补充任务的
closed-loop Rate harness：

```bash
/home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_golden_rate_perf.sh 8 60 300
```

三个参数依次是 worker 数、预热发单窗口和正式测量窗口。预热窗口结束后先等待
在途任务完全 drain，再开始测量；正式窗口结束后停止发新任务并单独记录收尾。
主吞吐是测量窗口内完成的 case 数除以测量秒数，`rate_summary.json` 同时保留
窗口后完成数、drain 时间、每核利用率、case mix、每条 job 和逐 step 明细。

两条脚本都使用 `delay_scale=0`，Host Agent 与 Sandbox 均允许在 CPU `0-7`
自由调度。单 case 表示同一时刻只有一个 job，不表示绑定单核；多 case 的第一个
参数是 worker 数，第二个参数是完整 30-case Golden Set 的重复次数。

每次运行生成独立时间戳目录，关键结果包括：

```text
performance_summary.json   整批吞吐、case 延迟分位数、CPU0-7 平均利用率
replay_summary.json        每条 case 的开始、结束和端到端时间（多 case）
step_timeline.json/tsv     每一步命令、类别、action gap、tool wall、返回码和输出大小
cpu_stat_start/end.txt     CPU0-7 运行前后的 /proc/stat 快照
```

即使删除模型等待，单个 Agent 的工具链通常仍以串行 burst 为主，不能自动占满 8 核。
因此先用 `1/8/16/32/...` workers 扫描吞吐，找到吞吐不再明显增长的饱和点；不能直接
沿用带模型等待实验所需的 96-agent 并发度。
低并发正确性验证使用默认的 `exact`，要求 return code 也一致；饱和压力与跨平台
实验使用 `semantic`，仍要求命令序列、退出状态和 patch 一致，同时保留并单列因
固定 60 秒命令超时造成的 return-code 漂移。该漂移本身是平台性能结果，不是
trajectory 损坏。

### 固定 case 并发扩展与逐 case 时延

跨平台比较使用完全相同的 30 条 Golden trajectory，并固定 CPU 集合。下面的扫描中，
`workers` 是并发任务槽，不是 CPU 核；所有 worker 共享 `SWE_CPUSET`，由 Linux 调度。

```bash
SWE_CPUSET=0-7 \
SWE_WORKER_SWEEP="1 2 4 8 16 30" \
SWE_REPEATS=3 \
/home/higon/cunzhe/agent-workloads/SWE-bench/run_swe_golden_fixed_sweep.sh
```

每个并发度执行相同 case、相同次数。结果包括：

- `comparison/concurrency_summary.tsv`：整批 makespan、吞吐、CPU 利用率和相对 `k1` 的配对几何平均 slowdown。
- `comparison/per_case_concurrency.tsv`：按 `instance_id` 配对的排队等待、service E2E、arrival E2E，以及 replay 进程开销、启动、Agent 控制间隙、tool 执行和结束回收阶段时延。
- `comparison/per_case_k1_vs_k16.tsv`：单 case 基线与主并发点的 30 行并排对比表；可通过 `SWE_PRIMARY_CONCURRENCY` 改主并发点。
- 每个 `k*/jobs/.../step_timeline.tsv`：逐条 tool call 的命令类别与 wall time。

固定批次吞吐可用于观察扩展拐点；正式平台结论以同名 case 的配对 E2E 为主，避免不同
case mix 导致总体平均值失真。

Flash/Pro 清单对比：

```bash
/home/higon/cunzhe/agent-workloads/.venv-swe/bin/python \
  /home/higon/cunzhe/agent-workloads/SWE-bench/compare_swe_golden_sets.py \
  --left /home/higon/cunzhe/swe_runs/golden_replay/flash/manifest.json \
  --right /home/higon/cunzhe/swe_runs/golden_replay/pro/manifest.json \
  --output-dir /home/higon/cunzhe/swe_runs/golden_replay/comparison
```

跨服务器复制 benchmark、恢复 flat-rootfs 镜像、执行 K=1/K=16 Golden replay
以及生成三平台横向对比的完整流程见
[`reproduction/README.md`](reproduction/README.md)。

## Notes

The harness currently uses the mini-SWE-agent runner already present under
`cpu-centric-agentic-ai/mini-swe-agent/`. This folder owns the workload dataset,
case selection, launch policy, and results path. The runner dependency is
explicit so it can later be swapped for OpenHands, SWE-agent, or another local
agent runner.
