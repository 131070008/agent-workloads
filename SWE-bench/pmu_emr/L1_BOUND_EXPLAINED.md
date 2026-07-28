# EMR TMA 5.2：怎样理解 L1 Bound

## 一句话结论

`L1_Bound` 不是“L1 cache miss 导致的 stall”，而是：

> 执行端已经因未完成的 load 停顿，但当时没有 demand load 处于
> L1D miss 状态。

因此，数据可以命中 L1D，程序仍然可能是 `L1_Bound`。

## 官方公式

EMR TMA 5.2 的定义为：

```text
L1_Bound =
    max(EXE_ACTIVITY.BOUND_ON_LOADS
        - MEMORY_ACTIVITY.STALLS_L1D_MISS,
        0)
    / CPU_CLK_UNHALTED.THREAD
```

事件含义：

- `BOUND_ON_LOADS`：执行端停顿，同时内存子系统中存在未完成的 load。
- `STALLS_L1D_MISS`：执行端停顿，同时存在尚未完成的 demand L1D miss。
- 两者相减：留下“load 造成了执行停顿，但不能归因于 L1D miss”的周期。

相邻层级使用同一条差分链：

```text
L2_Bound      = (STALLS_L1D_MISS - STALLS_L2_MISS) / cycles
L3_Bound      = (STALLS_L2_MISS  - STALLS_L3_MISS) / cycles
L3_Miss_Bound =  STALLS_L3_MISS / cycles
```

## L1 Bound 可能包含什么

Intel EMR TMA 5.2 在 L4 下继续列出：

- `L1_Latency_Dependency`：load 命中 L1D，但依赖链暴露了 L1 hit latency。
- `Store_Fwd_Blk`：load 等待更早的重叠 store，store forwarding 不能及时完成。
- `DTLB_Load`：地址翻译延迟，数据本身不一定 miss L1D。
- `Split_Loads`：load 跨 cache line。
- `Lock_Latency`：锁操作引起的停顿按该模型归到 L1 Bound，数据来源不一定是 L1。
- `FB_Full`：fill buffer 满，新的 L1 miss 请求无法继续发出。

所以 `L1_Bound` 是一个“L1D miss 之前及核内 load 路径的剩余 stall 桶”，
不是一个纯粹的 cache hit-rate 指标。

## 它是否表示 L1 带宽不足

有这种可能，但仅凭 `L1_Bound` 不能得出这个结论。

- 多个互不依赖的 load/store 把 load/store port 或 AGU 吞吐打满，更可能同时表现为
  `Core_Bound / Ports_Utilization`。
- 同一地址反复执行 `load -> modify -> store -> next load`，即使全部 L1 hit，
  也可能因为 loop-carried RAW 依赖和 store-to-load forwarding latency 表现为
  `L1_Bound / L1_Latency_Dependency`。
- DTLB、split load、锁和 fill-buffer 压力也会落入 L1 Bound，和 L1D 供给带宽
  不是同一个问题。

必须结合 L4 子项、执行端口、汇编依赖链和必要时的 PEBS/perf-c2c 采样判断。

## False sharing 示例

宋宝华的示例中，两个线程访问同一 cache line 上的不同变量，其中至少一个线程写：

```text
未 padding：
  line 在两个 core 之间发生无效化、RFO 和所有权转移
  -> L2 miss / L3 hit 或 sibling-core contention
  -> L3_Bound 较高

padding 后：
  两个变量进入不同 cache line
  -> coherence ping-pong 消失
  -> 数据稳定留在各自 core 的 L1D
  -> 原先被长延迟掩盖的本地执行瓶颈成为主要剩余项
  -> 可能显示 L1_Bound 或 Ports_Utilization
```

示例中的 writer 循环执行 `d.writer++`。在 `volatile` 约束下，每轮都包含对同一
地址的 read-modify-write，下一轮又依赖前一轮写出的值。padding 后它虽然通常
L1 hit，但这条串行依赖和 store/load 路径延迟仍可能限制迭代速度。

因此更严谨的说法是：

> padding 将瓶颈从跨核 coherence/L3 路径移走；新的 L1 Bound 表明剩余停顿发生在
> “没有 L1D miss 的 load 路径”，不能仅凭这一项认定为 L1 带宽不足。

## 本轮数据的计算口径

正式结果使用 Intel EMR metrics v1.4 / TMA 5.2：

- Metrics SHA256：
  `43b6c9a7658fa08a0046e48cb6ea8b52a3d26b139e9408cc6cace4b7df21ce17`
- Events SHA256：
  `085202edceb96e7717c07a09b1125163350cb9327024f764ad81ab4dec7e2545`

官方源：

- <https://github.com/intel/perfmon/blob/main/EMR/metrics/emeraldrapids_metrics.json>
- <https://github.com/intel/perfmon/blob/main/EMR/events/emeraldrapids_core.json>

参考示例：

- <https://blog.csdn.net/21cnbao/article/details/160063346>
- <https://www.intel.com/content/www/us/en/docs/vtune-profiler/cookbook/2024-2/top-down-microarchitecture-analysis-method.html>
