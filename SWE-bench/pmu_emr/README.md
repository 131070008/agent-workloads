# EMR Top-down L1-L4 采集口径

## 结论

- 实验平台是 Intel Xeon Platinum 8558P，按 Emerald Rapids（CPUID 6-CF）处理。
- L1/L2 使用固定 `PERF_METRICS` 事件组直接采集。
- L3/L4 使用 Intel EMR 官方 event JSON 中的 raw encoding 采集。
- 公式以 Intel EMR metrics v1.4 / TMA 5.2 为唯一计算基线。
- 服务器当前 pmu-tools 的 `spr_server_ratios.py` 是 SPR TMA 5.1，只用于参考事件调度，不能作为 EMR L4 公式基线。
- EMR TMA 5.2 使用 `L3_Miss_Bound`；不要把
  `MEMORY_ACTIVITY.STALLS_L3_MISS / cycles` 直接命名为 `DRAM_Bound`，
  因为 L3 miss 不等于一定访问 DRAM。

官方源：

- `https://raw.githubusercontent.com/intel/perfmon/main/EMR/metrics/emeraldrapids_metrics.json`
- `https://raw.githubusercontent.com/intel/perfmon/main/EMR/events/emeraldrapids_core.json`

## L1/L2

固定事件必须作为一个 pinned group 采集，且 `slots` 必须是 group leader：

```text
slots
topdown-retiring
topdown-bad-spec
topdown-fe-bound
topdown-be-bound
topdown-br-mispredict
topdown-mem-bound
topdown-heavy-ops
topdown-fetch-lat
```

还必须同时采集：

```text
INT_MISC.UOP_DROPPING = event 0xad, umask 0x10
```

定义：

```text
S = FE_raw + Bad_raw + Retiring_raw + BE_raw
D = UOP_DROPPING / slots

Frontend_Bound   = FE_raw / S - D
Backend_Bound    = BE_raw / S
Retiring         = Retiring_raw / S
Bad_Speculation  = max(1 - Frontend_Bound - Backend_Bound - Retiring, 0)

Fetch_Latency      = FetchLatency_raw / S - D
Fetch_Bandwidth    = max(Frontend_Bound - Fetch_Latency, 0)
Branch_Mispredicts = BranchMispredict_raw / S
Machine_Clears     = max(Bad_Speculation - Branch_Mispredicts, 0)
Memory_Bound       = MemoryBound_raw / S
Core_Bound         = max(Backend_Bound - Memory_Bound, 0)
Heavy_Operations   = HeavyOperations_raw / S
Light_Operations   = max(Retiring - Heavy_Operations, 0)
```

不能使用单个 `PERF_METRICS / slots` 作为正式 L1/L2 结果，也不能遗漏
`UOP_DROPPING` 修正。

## L3/L4

完整公式、父子关系、常量和 raw event encoding：

- `EMR_TOPDOWN_L1_L4.md`
- `emr_topdown_l1_l4.csv`
- `emr_topdown_l1_l4.json`

当前清单包含：

| 项目 | 数量 |
|---|---:|
| L1-L4 TMA 节点 | 85 |
| 唯一事件 | 108 |
| 固定 PERF_METRICS 事件 | 9 |
| architectural fixed 事件 | 2 |
| 仅允许独占编程的事件 | 4 |
| offcore response 事件 | 5 |
| 仅能使用 programmable counter 0-3 的事件 | 49 |
| 可使用 programmable counter 0-7 的事件 | 48 |

在 8558P 上逐个执行短 `perf stat` 验证，108 个事件全部通过。验证结果见
`emr_topdown_event_validation_8558p.csv`。

### 结果计算

计算脚本：

- `../evaluate_emr_tma52_l1_l4.py`

以正式采集目录为例：

```bash
RESULT_DIR=/home/higon/cunzhe/agent-workloads/experiment_results/fixed_pool_96_8c_20260724_044736/perf_collect/formal_detailed/official_emr_tma52

python3 /home/higon/cunzhe/agent-workloads/SWE-bench/evaluate_emr_tma52_l1_l4.py \
  --result-dir "$RESULT_DIR" \
  --formula-manifest /home/higon/cunzhe/agent-workloads/SWE-bench/pmu_emr/emr_topdown_l1_l4.json \
  --tsc-mhz 2700 \
  --threads-per-core 2 \
  --slots-per-cycle 6 \
  --cgroup-seconds 5 \
  --global-seconds 3 \
  --output-csv "$RESULT_DIR/tma52_l1_l4_metrics.csv" \
  --output-json "$RESULT_DIR/tma52_l1_l4_metrics.json" \
  --output-markdown "$RESULT_DIR/tma52_l1_l4_metrics.md"
```

脚本会在计算前检查 85 个公式节点与 108 个事件的覆盖关系；计算后检查：

- L1 四项合计为 100%。
- 每组 L2 子项与其 L1 父项闭合。
- `L1/L2/L3/L3_Miss Bound` 与 `BOUND_ON_LOADS` 链闭合。
- I-cache、ITLB、branch resteer、divider 和 FP arithmetic 等可严格加和的
  L4 子树闭合。

常量替换与 Intel PerfSpect 一致：`SYSTEM_TSC_FREQ` 使用 TSC Hz，
`DURATIONTIMEINMILLISECONDS` 按归一化的一秒窗口取 `1000`。实际采集时长只影响
raw count 的统计稳定性，不应再次缩放已经按 cycles/ref-cycles 构造的比例。

`L1_Bound` 的公式、语义和 false sharing 示例解释见
`L1_BOUND_EXPLAINED.md`。

## 采集约束

1. `PERF_METRICS` 必须以 `slots` 为 leader 整组采集；拆开会返回
   `EINVAL` 或 `<not supported>`。
2. `INT_MISC.UNKNOWN_BRANCH_CYCLES` 和三个 `UOPS_RETIRED.MS` 变体使用
   Frontend MSR，官方标记为 `TakenAlone=1`，必须单独成 pass。
3. offcore response 事件依赖 `MSR_OFFCORE_RSP_0/1`，正式分组必须限制每
   pass 的 offcore filter 数量，并在真机上验证。
4. 49 个事件只能占用 counter 0-3，不能只按“机器有 8 个 programmable
   counters”粗略装箱。
5. 每个 pass 都必须检查 `time_running / time_enabled = 100%`；出现
   multiplex、`<not counted>` 或 `<not supported>`，该 pass 作废。
6. 使用 `CPU_CLK_UNHALTED.DISTRIBUTED` 的指标属于 core-shared 口径。
   开启 SMT 时，兄弟线程必须一起纳入采集，并避免不同 cgroup 混跑在同一
   物理核的两个线程上，否则不能做干净的 Host/Sandbox 归因。
7. L4 中大量指标是估算量，不是可加和的槽位分解。例如 `L1/L2/L3
   Bound` 的单位是 `%Stalls`，而 `Frontend/Backend/Retiring/Bad Spec`
   是 `%Slots`。
8. 多 pass 计算要求工作负载具有统计稳定性。SWE 场景应维持固定并发池，
   每个 pass 使用相同持续时间，并至少重复两轮检查波动。

## 校验链

1. Intel EMR metrics JSON 提供公式、常量、父子关系和 CountDomain。
2. Intel EMR core event JSON 提供 EventCode、UMask、Counter、MSR、
   TakenAlone 和 Offcore 属性。
3. `build_emr_topdown_manifest.py` 检查公式别名、父子层级和事件映射。
4. `validate_emr_topdown_events.py` 在目标 8558P 上验证 raw event 可编程性。
5. `summarize_emr_topdown_l1_l2.py` 严格按 EMR TMA 5.2 计算 L1/L2。

任何一层版本变化，都必须重新生成 manifest 并重新执行事件验证。
