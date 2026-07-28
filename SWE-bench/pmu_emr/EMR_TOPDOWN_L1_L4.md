# Emerald Rapids Top-down L1-L4 公式与事件清单

该文件由 Intel EMR 官方 metrics/event JSON 机械生成，不手抄公式。

## 固定版本

- 平台：Performance Monitoring Metrics for 5th Generation Intel(R) Xeon(R) Processor Scalable Family0
- TMA：5.2 / Full
- Metrics：v1.4，07/09/2026
- Metrics SHA256：`43b6c9a7658fa08a0046e48cb6ea8b52a3d26b139e9408cc6cace4b7df21ce17`
- Events SHA256：`085202edceb96e7717c07a09b1125163350cb9327024f764ad81ab4dec7e2545`

## 公式

| Level | Metric | Parent | Domain | Intel Formula | BaseFormula | Events | Constants |
|---:|---|---|---|---|---|---|---|
| 1 | Backend_Bound |  | Slots | `100 * ( a / ( b + c + d + a ) )` | `perf_metrics.backend_bound / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound )` | a=PERF_METRICS.BACKEND_BOUND, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING |  |
| 1 | Bad_Speculation |  | Slots | `100 * ( max( 1 - ( ( a / ( a + b + c + d ) - e / ( f ) ) + ( d / ( a + b + c + d ) ) + ( c / ( a + b + c + d ) ) ) , 0 ) )` | `max( 1 - ( tma_frontend_bound + tma_backend_bound + tma_retiring ) , 0 )` | a=PERF_METRICS.FRONTEND_BOUND, b=PERF_METRICS.BAD_SPECULATION, c=PERF_METRICS.RETIRING, d=PERF_METRICS.BACKEND_BOUND, e=INT_MISC.UOP_DROPPING, f=TOPDOWN.SLOTS:perf_metrics |  |
| 1 | Frontend_Bound |  | Slots | `100 * ( a / ( a + b + c + d ) - e / ( f ) )` | `perf_metrics.frontend_bound / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound ) - int_misc.uop_dropping / tma_info_thread_slots` | a=PERF_METRICS.FRONTEND_BOUND, b=PERF_METRICS.BAD_SPECULATION, c=PERF_METRICS.RETIRING, d=PERF_METRICS.BACKEND_BOUND, e=INT_MISC.UOP_DROPPING, f=TOPDOWN.SLOTS:perf_metrics |  |
| 1 | Retiring |  | Slots | `100 * ( a / ( b + c + a + d ) )` | `perf_metrics.retiring / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND |  |
| 2 | Branch_Mispredicts | Bad_Speculation | Slots | `100 * ( a / ( b + c + d + e ) )` | `perf_metrics.branch_mispredicts / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound )` | a=PERF_METRICS.BRANCH_MISPREDICTS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND |  |
| 2 | Core_Bound | Backend_Bound | Slots | `100 * ( max( 0 , ( a / ( b + c + d + a ) ) - ( e / ( b + c + d + a ) ) ) )` | `max( 0 , tma_backend_bound - tma_memory_bound )` | a=PERF_METRICS.BACKEND_BOUND, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.MEMORY_BOUND |  |
| 2 | Fetch_Bandwidth | Frontend_Bound | Slots | `100 * ( max( 0 , ( a / ( a + b + c + d ) - e / ( f ) ) - ( ( g / ( a + b + c + d ) - e / ( f ) ) ) ) )` | `max( 0 , tma_frontend_bound - tma_fetch_latency )` | a=PERF_METRICS.FRONTEND_BOUND, b=PERF_METRICS.BAD_SPECULATION, c=PERF_METRICS.RETIRING, d=PERF_METRICS.BACKEND_BOUND, e=INT_MISC.UOP_DROPPING, f=TOPDOWN.SLOTS:perf_metrics, g=PERF_METRICS.FETCH_LATENCY |  |
| 2 | Fetch_Latency | Frontend_Bound | Slots | `100 * ( ( a / ( b + c + d + e ) - f / ( g ) ) )` | `( perf_metrics.fetch_latency / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound ) - int_misc.uop_dropping / tma_info_thread_slots )` | a=PERF_METRICS.FETCH_LATENCY, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND, f=INT_MISC.UOP_DROPPING, g=TOPDOWN.SLOTS:perf_metrics |  |
| 2 | Heavy_Operations | Retiring | Slots | `100 * ( a / ( b + c + d + e ) )` | `perf_metrics.heavy_operations / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound )` | a=PERF_METRICS.HEAVY_OPERATIONS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND |  |
| 2 | Light_Operations | Retiring | Slots | `100 * ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) )` | `max( 0 , tma_retiring - tma_heavy_operations )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS |  |
| 2 | Machine_Clears | Bad_Speculation | Slots | `100 * ( max( 0 , ( max( 1 - ( ( a / ( a + b + c + d ) - e / ( f ) ) + ( d / ( a + b + c + d ) ) + ( c / ( a + b + c + d ) ) ) , 0 ) ) - ( g / ( a + b + c + d ) ) ) )` | `max( 0 , tma_bad_speculation - tma_branch_mispredicts )` | a=PERF_METRICS.FRONTEND_BOUND, b=PERF_METRICS.BAD_SPECULATION, c=PERF_METRICS.RETIRING, d=PERF_METRICS.BACKEND_BOUND, e=INT_MISC.UOP_DROPPING, f=TOPDOWN.SLOTS:perf_metrics, g=PERF_METRICS.BRANCH_MISPREDICTS |  |
| 2 | Memory_Bound | Backend_Bound | Slots | `100 * ( a / ( b + c + d + e ) )` | `perf_metrics.memory_bound / ( perf_metrics.frontend_bound + perf_metrics.bad_speculation + perf_metrics.retiring + perf_metrics.backend_bound )` | a=PERF_METRICS.MEMORY_BOUND, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND |  |
| 3 | AMX_Busy | Core_Bound | Core_Clocks | `100 * ( a / ( b if smt_on else ( c ) ) )` | `exe.amx_busy / tma_info_core_core_clks` | a=EXE.AMX_BUSY, b=CPU_CLK_UNHALTED.DISTRIBUTED, c=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 3 | Branch_Resteers | Fetch_Latency | Clocks | `100 * ( a / ( b ) + ( c / ( b ) ) )` | `int_misc.clear_resteer_cycles / tma_info_thread_clks + tma_unknown_branches` | a=INT_MISC.CLEAR_RESTEER_CYCLES, b=CPU_CLK_UNHALTED.THREAD, c=INT_MISC.UNKNOWN_BRANCH_CYCLES |  |
| 3 | DSB | Fetch_Bandwidth | Slots_Estimated | `100 * ( ( a - b ) / ( c if smt_on else ( d ) ) / 2 )` | `( idq.dsb_cycles_any - idq.dsb_cycles_ok ) / tma_info_core_core_clks / 2` | a=IDQ.DSB_CYCLES_ANY, b=IDQ.DSB_CYCLES_OK, c=CPU_CLK_UNHALTED.DISTRIBUTED, d=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 3 | DSB_Switches | Fetch_Latency | Clocks | `100 * ( a / ( b ) )` | `dsb2mite_switches.penalty_cycles / tma_info_thread_clks` | a=DSB2MITE_SWITCHES.PENALTY_CYCLES, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | Divider | Core_Bound | Clocks | `100 * ( a / ( b ) )` | `arith.div_active / tma_info_thread_clks` | a=ARITH.DIV_ACTIVE, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | FP_Arith | Light_Operations | Uops | `100 * ( ( ( a / ( b + c + a + d ) ) * e / f ) + ( ( g + h ) / ( ( a / ( b + c + a + d ) ) * ( i ) ) ) + ( ( j + k ) / ( ( a / ( b + c + a + d ) ) * ( i ) ) ) )` | `tma_x87_use + tma_fp_scalar + tma_fp_vector` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=UOPS_EXECUTED.X87, f=UOPS_EXECUTED.THREAD, g=FP_ARITH_INST_RETIRED.SCALAR, h=FP_ARITH_INST_RETIRED2.SCALAR, i=TOPDOWN.SLOTS:perf_metrics, j=FP_ARITH_INST_RETIRED.VECTOR, k=FP_ARITH_INST_RETIRED2.VECTOR |  |
| 3 | Few_Uops_Instructions | Heavy_Operations | Slots | `100 * ( max( 0 , ( a / ( b + c + d + e ) ) - ( f / ( g ) ) ) )` | `max( 0 , tma_heavy_operations - tma_microcode_sequencer )` | a=PERF_METRICS.HEAVY_OPERATIONS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND, f=UOPS_RETIRED.MS, g=TOPDOWN.SLOTS:perf_metrics |  |
| 3 | Fused_Instructions | Light_Operations | Slots | `100 * ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * f / ( ( a / ( b + c + a + d ) ) * ( g ) ) )` | `tma_light_operations * inst_retired.macro_fused / ( tma_retiring * tma_info_thread_slots )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=INST_RETIRED.MACRO_FUSED, g=TOPDOWN.SLOTS:perf_metrics |  |
| 3 | ICache_Misses | Fetch_Latency | Clocks | `100 * ( a / ( b ) )` | `icache_data.stalls / tma_info_thread_clks` | a=ICACHE_DATA.STALLS, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | ITLB_Misses | Fetch_Latency | Clocks | `100 * ( a / ( b ) )` | `icache_tag.stalls / tma_info_thread_clks` | a=ICACHE_TAG.STALLS, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | Int_Operations | Light_Operations | Uops | `100 * ( ( ( a + b ) / ( ( c / ( d + e + c + f ) ) * ( g ) ) ) + ( ( h + i + j ) / ( ( c / ( d + e + c + f ) ) * ( g ) ) ) )` | `tma_int_vector_128b + tma_int_vector_256b` | a=INT_VEC_RETIRED.ADD_128, b=INT_VEC_RETIRED.VNNI_128, c=PERF_METRICS.RETIRING, d=PERF_METRICS.FRONTEND_BOUND, e=PERF_METRICS.BAD_SPECULATION, f=PERF_METRICS.BACKEND_BOUND, g=TOPDOWN.SLOTS:perf_metrics, h=INT_VEC_RETIRED.ADD_256, i=INT_VEC_RETIRED.MUL_256, j=INT_VEC_RETIRED.VNNI_256 |  |
| 3 | L1_Bound | Memory_Bound | Stalls | `100 * ( max( ( a - b ) / ( c ) , 0 ) )` | `max( ( exe_activity.bound_on_loads - memory_activity.stalls_l1d_miss ) / tma_info_thread_clks , 0 )` | a=EXE_ACTIVITY.BOUND_ON_LOADS, b=MEMORY_ACTIVITY.STALLS_L1D_MISS, c=CPU_CLK_UNHALTED.THREAD |  |
| 3 | L2_Bound | Memory_Bound | Stalls | `100 * ( ( a - b ) / ( c ) )` | `( memory_activity.stalls_l1d_miss - memory_activity.stalls_l2_miss ) / tma_info_thread_clks` | a=MEMORY_ACTIVITY.STALLS_L1D_MISS, b=MEMORY_ACTIVITY.STALLS_L2_MISS, c=CPU_CLK_UNHALTED.THREAD |  |
| 3 | L3_Bound | Memory_Bound | Stalls | `100 * ( ( a - b ) / ( c ) )` | `( memory_activity.stalls_l2_miss - memory_activity.stalls_l3_miss ) / tma_info_thread_clks` | a=MEMORY_ACTIVITY.STALLS_L2_MISS, b=MEMORY_ACTIVITY.STALLS_L3_MISS, c=CPU_CLK_UNHALTED.THREAD |  |
| 3 | L3_Miss_Bound | Memory_Bound | Stalls | `100 * ( ( a / ( b ) ) )` | `( memory_activity.stalls_l3_miss / tma_info_thread_clks )` | a=MEMORY_ACTIVITY.STALLS_L3_MISS, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | LCP | Fetch_Latency | Clocks | `100 * ( a / ( b ) )` | `decode.lcp / tma_info_thread_clks` | a=DECODE.LCP, b=CPU_CLK_UNHALTED.THREAD |  |
| 3 | MITE | Fetch_Bandwidth | Slots_Estimated | `100 * ( ( a - b ) / ( c if smt_on else ( d ) ) / 2 )` | `( idq.mite_cycles_any - idq.mite_cycles_ok ) / tma_info_core_core_clks / 2` | a=IDQ.MITE_CYCLES_ANY, b=IDQ.MITE_CYCLES_OK, c=CPU_CLK_UNHALTED.DISTRIBUTED, d=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 3 | MS | Fetch_Bandwidth | Slots_Estimated | `100 * ( max( a , b / ( c / d ) ) / ( e if smt_on else ( f ) ) / 2.4 )` | `max( idq.ms_cycles_any , uops_retired.ms:c1 / ( uops_retired.slots / uops_issued.any ) ) / tma_info_core_core_clks / 2.4` | a=IDQ.MS_CYCLES_ANY, b=UOPS_RETIRED.MS:c1, c=UOPS_RETIRED.SLOTS, d=UOPS_ISSUED.ANY, e=CPU_CLK_UNHALTED.DISTRIBUTED, f=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 3 | MS_Switches | Fetch_Latency | Clocks_Estimated | `100 * ( ( 3 ) * a / ( b / c ) / ( d ) )` | `( 3 ) * uops_retired.ms:c1:e1 / ( uops_retired.slots / uops_issued.any ) / tma_info_thread_clks` | a=UOPS_RETIRED.MS:c1:e1, b=UOPS_RETIRED.SLOTS, c=UOPS_ISSUED.ANY, d=CPU_CLK_UNHALTED.THREAD |  |
| 3 | Memory_Operations | Light_Operations | Slots | `100 * ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * f / ( ( a / ( b + c + a + d ) ) * ( g ) ) )` | `tma_light_operations * mem_uop_retired.any / ( tma_retiring * tma_info_thread_slots )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=MEM_UOP_RETIRED.ANY, g=TOPDOWN.SLOTS:perf_metrics |  |
| 3 | Microcode_Sequencer | Heavy_Operations | Slots | `100 * ( a / ( b ) )` | `uops_retired.ms / tma_info_thread_slots` | a=UOPS_RETIRED.MS, b=TOPDOWN.SLOTS:perf_metrics |  |
| 3 | Non_Fused_Branches | Light_Operations | Slots | `100 * ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * ( f - g ) / ( ( a / ( b + c + a + d ) ) * ( h ) ) )` | `tma_light_operations * ( br_inst_retired.all_branches - inst_retired.macro_fused ) / ( tma_retiring * tma_info_thread_slots )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=BR_INST_RETIRED.ALL_BRANCHES, g=INST_RETIRED.MACRO_FUSED, h=TOPDOWN.SLOTS:perf_metrics |  |
| 3 | Other_Light_Ops | Light_Operations | Slots | `100 * ( max( 0 , ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) - ( ( ( ( a / ( b + c + a + d ) ) * f / g ) + ( ( h + i ) / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) + ( ( k + l ) / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) ) + ( ( ( m + n ) / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) + ( ( o + p + q ) / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) ) + ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * r / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) + ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * s / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) + ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * ( t - s ) / ( ( a / ( b + c + a + d ) ) * ( j ) ) ) ) ) )` | `max( 0 , tma_light_operations - ( tma_fp_arith + tma_int_operations + tma_memory_operations + tma_fused_instructions + tma_non_fused_branches ) )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=UOPS_EXECUTED.X87, g=UOPS_EXECUTED.THREAD, h=FP_ARITH_INST_RETIRED.SCALAR, i=FP_ARITH_INST_RETIRED2.SCALAR, j=TOPDOWN.SLOTS:perf_metrics, k=FP_ARITH_INST_RETIRED.VECTOR, l=FP_ARITH_INST_RETIRED2.VECTOR, m=INT_VEC_RETIRED.ADD_128, n=INT_VEC_RETIRED.VNNI_128, o=INT_VEC_RETIRED.ADD_256, p=INT_VEC_RETIRED.MUL_256, q=INT_VEC_RETIRED.VNNI_256, r=MEM_UOP_RETIRED.ANY, s=INST_RETIRED.MACRO_FUSED, t=BR_INST_RETIRED.ALL_BRANCHES |  |
| 3 | Other_Mispredicts | Branch_Mispredicts | Slots | `100 * ( max( ( a / ( b + c + d + e ) ) * ( 1 - f / ( g - h ) ) , 0.0001 ) )` | `max( tma_branch_mispredicts * ( 1 - br_misp_retired.all_branches / ( int_misc.clears_count - machine_clears.count ) ) , 0.0001 )` | a=PERF_METRICS.BRANCH_MISPREDICTS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND, f=BR_MISP_RETIRED.ALL_BRANCHES, g=INT_MISC.CLEARS_COUNT, h=MACHINE_CLEARS.COUNT |  |
| 3 | Other_Nukes | Machine_Clears | Slots | `100 * ( max( ( max( 0 , ( max( 1 - ( ( a / ( a + b + c + d ) - e / ( f ) ) + ( d / ( a + b + c + d ) ) + ( c / ( a + b + c + d ) ) ) , 0 ) ) - ( g / ( a + b + c + d ) ) ) ) * ( 1 - h / i ) , 0.0001 ) )` | `max( tma_machine_clears * ( 1 - machine_clears.memory_ordering / machine_clears.count ) , 0.0001 )` | a=PERF_METRICS.FRONTEND_BOUND, b=PERF_METRICS.BAD_SPECULATION, c=PERF_METRICS.RETIRING, d=PERF_METRICS.BACKEND_BOUND, e=INT_MISC.UOP_DROPPING, f=TOPDOWN.SLOTS:perf_metrics, g=PERF_METRICS.BRANCH_MISPREDICTS, h=MACHINE_CLEARS.MEMORY_ORDERING, i=MACHINE_CLEARS.COUNT |  |
| 3 | Ports_Utilization | Core_Bound | Clocks | `100 * ( ( ( ( a + max( b - c , 0 ) ) / ( d ) * ( e - f ) / ( d ) ) * ( d ) + ( g + ( h / ( i + j + h + k ) ) * l ) ) / ( d ) if ( m < ( e - f ) ) else ( g + ( h / ( i + j + h + k ) ) * l ) / ( d ) )` | `( tma_ports_utilized_0 * tma_info_thread_clks + ( exe_activity.1_ports_util + tma_retiring * exe_activity.2_3_ports_util ) ) / tma_info_thread_clks if ( arith.div_active < ( cycle_activity.stalls_total - exe_activity.bound_on_loads ) ) else ( exe_activity.1_ports_util + tma_retiring * exe_activity.2_3_ports_util ) / tma_info_thread_clks` | a=EXE_ACTIVITY.EXE_BOUND_0_PORTS, b=RS.EMPTY_RESOURCE, c=RESOURCE_STALLS.SCOREBOARD, d=CPU_CLK_UNHALTED.THREAD, e=CYCLE_ACTIVITY.STALLS_TOTAL, f=EXE_ACTIVITY.BOUND_ON_LOADS, g=EXE_ACTIVITY.1_PORTS_UTIL, h=PERF_METRICS.RETIRING, i=PERF_METRICS.FRONTEND_BOUND, j=PERF_METRICS.BAD_SPECULATION, k=PERF_METRICS.BACKEND_BOUND, l=EXE_ACTIVITY.2_3_PORTS_UTIL, m=ARITH.DIV_ACTIVE |  |
| 3 | Serializing_Operation | Core_Bound | Clocks | `100 * ( a / ( b ) + ( c / ( b ) ) )` | `resource_stalls.scoreboard / tma_info_thread_clks + tma_c02_wait` | a=RESOURCE_STALLS.SCOREBOARD, b=CPU_CLK_UNHALTED.THREAD, c=CPU_CLK_UNHALTED.C02 |  |
| 3 | Store_Bound | Memory_Bound | Stalls | `100 * ( a / ( b ) )` | `exe_activity.bound_on_stores / tma_info_thread_clks` | a=EXE_ACTIVITY.BOUND_ON_STORES, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Assists | Microcode_Sequencer | Slots_Estimated | `100 * ( ( ( 99 * 3 + 63 + 30 ) / 5 ) * a / ( b ) )` | `( ( 99 *3 + 63 + 30 ) / 5 ) * assists.any / tma_info_thread_slots` | a=ASSISTS.ANY, b=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | C01_Wait | Serializing_Operation | Clocks | `100 * ( a / ( b ) )` | `cpu_clk_unhalted.c01 / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.C01, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | C02_Wait | Serializing_Operation | Clocks | `100 * ( a / ( b ) )` | `cpu_clk_unhalted.c02 / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.C02, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | CISC | Microcode_Sequencer | Slots | `100 * ( max( 0 , ( a / ( b ) ) - ( ( ( 99 * 3 + 63 + 30 ) / 5 ) * c / ( b ) ) ) )` | `max( 0 , tma_microcode_sequencer - tma_assists )` | a=UOPS_RETIRED.MS, b=TOPDOWN.SLOTS:perf_metrics, c=ASSISTS.ANY |  |
| 4 | Clears_Resteers | Branch_Resteers | Clocks | `100 * ( ( 1 - ( ( a / ( b + c + d + e ) ) / ( max( 1 - ( ( b / ( b + c + d + e ) - f / ( g ) ) + ( e / ( b + c + d + e ) ) + ( d / ( b + c + d + e ) ) ) , 0 ) ) ) ) * h / ( i ) )` | `( 1 - ( tma_branch_mispredicts / tma_bad_speculation ) ) * int_misc.clear_resteer_cycles / tma_info_thread_clks` | a=PERF_METRICS.BRANCH_MISPREDICTS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND, f=INT_MISC.UOP_DROPPING, g=TOPDOWN.SLOTS:perf_metrics, h=INT_MISC.CLEAR_RESTEER_CYCLES, i=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Code_L2_Hit | ICache_Misses | Clocks_Retired | `100 * ( max( 0 , ( a / ( b ) ) - ( c / ( b ) ) ) )` | `max( 0 , tma_icache_misses - tma_code_l2_miss )` | a=ICACHE_DATA.STALLS, b=CPU_CLK_UNHALTED.THREAD, c=OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_CODE_RD |  |
| 4 | Code_L2_Miss | ICache_Misses | Clocks_Retired | `100 * ( a / ( b ) )` | `offcore_requests_outstanding.cycles_with_demand_code_rd / tma_info_thread_clks` | a=OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_CODE_RD, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Code_STLB_Hit | ITLB_Misses | Clocks_Retired | `100 * ( max( 0 , ( a / ( b ) ) - ( c / ( b ) ) ) )` | `max( 0 , tma_itlb_misses - tma_code_stlb_miss )` | a=ICACHE_TAG.STALLS, b=CPU_CLK_UNHALTED.THREAD, c=ITLB_MISSES.WALK_ACTIVE |  |
| 4 | Code_STLB_Miss | ITLB_Misses | Clocks_Retired | `100 * ( a / ( b ) )` | `itlb_misses.walk_active / tma_info_thread_clks` | a=ITLB_MISSES.WALK_ACTIVE, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Contested_Accesses | L3_Bound | Clocks_Estimated | `100 * ( ( ( ( 81 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) - ( 4.4 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) ) * ( e * ( f / ( f + g ) ) ) + ( ( 79 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) - ( 4.4 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) ) * ( h ) ) * ( 1 + ( i / j ) / 2 ) / ( a ) )` | `( ( ( 81 * tma_info_system_core_frequency ) - ( 4.4 * tma_info_system_core_frequency ) ) * ( mem_load_l3_hit_retired.xsnp_fwd * ( ocr.demand_data_rd.l3_hit.snoop_hitm / ( ocr.demand_data_rd.l3_hit.snoop_hitm + ocr.demand_data_rd.l3_hit.snoop_hit_with_fwd ) ) ) + ( ( 79 * tma_info_system_core_frequency ) - ( 4.4 * tma_info_system_core_frequency ) ) * ( mem_load_l3_hit_retired.xsnp_miss ) ) * ( 1 + ( mem_load_retired.fb_hit / mem_load_retired.l1_miss ) / 2 ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=CPU_CLK_UNHALTED.REF_TSC, e=MEM_LOAD_L3_HIT_RETIRED.XSNP_FWD, f=OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HITM, g=OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HIT_WITH_FWD, h=MEM_LOAD_L3_HIT_RETIRED.XSNP_MISS, i=MEM_LOAD_RETIRED.FB_HIT, j=MEM_LOAD_RETIRED.L1_MISS | c=SYSTEM_TSC_FREQ, durationtimeinmilliseconds=DURATIONTIMEINMILLISECONDS |
| 4 | DTLB_Load | L1_Bound | Clocks_Estimated | `100 * ( min( ( 7 ) * a + b , max( c - d , 0 ) ) / ( e ) )` | `min( ( 7 ) * dtlb_load_misses.stlb_hit:c1 + dtlb_load_misses.walk_active , max( cycle_activity.cycles_mem_any - memory_activity.cycles_l1d_miss , 0 ) ) / tma_info_thread_clks` | a=DTLB_LOAD_MISSES.STLB_HIT:c1, b=DTLB_LOAD_MISSES.WALK_ACTIVE, c=CYCLE_ACTIVITY.CYCLES_MEM_ANY, d=MEMORY_ACTIVITY.CYCLES_L1D_MISS, e=CPU_CLK_UNHALTED.THREAD |  |
| 4 | DTLB_Store | Store_Bound | Clocks_Estimated | `100 * ( ( ( 7 ) * a + b ) / ( c if smt_on else ( d ) ) )` | `( ( 7 ) * dtlb_store_misses.stlb_hit:c1 + dtlb_store_misses.walk_active ) / tma_info_core_core_clks` | a=DTLB_STORE_MISSES.STLB_HIT:c1, b=DTLB_STORE_MISSES.WALK_ACTIVE, c=CPU_CLK_UNHALTED.DISTRIBUTED, d=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 4 | Data_Sharing | L3_Bound | Clocks_Estimated | `100 * ( ( ( 79 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) - ( 4.4 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) ) * ( e + f * ( 1 - ( g / ( g + h ) ) ) ) * ( 1 + ( i / j ) / 2 ) / ( a ) )` | `( ( 79 * tma_info_system_core_frequency ) - ( 4.4 * tma_info_system_core_frequency ) ) * ( mem_load_l3_hit_retired.xsnp_no_fwd + mem_load_l3_hit_retired.xsnp_fwd * ( 1 - ( ocr.demand_data_rd.l3_hit.snoop_hitm / ( ocr.demand_data_rd.l3_hit.snoop_hitm + ocr.demand_data_rd.l3_hit.snoop_hit_with_fwd ) ) ) ) * ( 1 + ( mem_load_retired.fb_hit / mem_load_retired.l1_miss ) / 2 ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=CPU_CLK_UNHALTED.REF_TSC, e=MEM_LOAD_L3_HIT_RETIRED.XSNP_NO_FWD, f=MEM_LOAD_L3_HIT_RETIRED.XSNP_FWD, g=OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HITM, h=OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HIT_WITH_FWD, i=MEM_LOAD_RETIRED.FB_HIT, j=MEM_LOAD_RETIRED.L1_MISS | c=SYSTEM_TSC_FREQ, durationtimeinmilliseconds=DURATIONTIMEINMILLISECONDS |
| 4 | Decoder0_Alone | MITE | Slots_Estimated | `100 * ( ( a - b ) / ( c if smt_on else ( d ) ) / 2 )` | `( inst_decoded.decoders:c1 - inst_decoded.decoders:c2 ) / tma_info_core_core_clks / 2` | a=INST_DECODED.DECODERS:c1, b=INST_DECODED.DECODERS:c2, c=CPU_CLK_UNHALTED.DISTRIBUTED, d=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 4 | FB_Full | L1_Bound | Clocks_Calculated | `100 * ( a / ( b ) )` | `l1d_pend_miss.fb_full / tma_info_thread_clks` | a=L1D_PEND_MISS.FB_FULL, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | FP_Divider | Divider | Clocks | `100 * ( a / ( b ) )` | `arith.fpdiv_active / tma_info_thread_clks` | a=ARITH.FPDIV_ACTIVE, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | FP_Scalar | FP_Arith | Uops | `100 * ( ( a + b ) / ( ( c / ( d + e + c + f ) ) * ( g ) ) )` | `( fp_arith_inst_retired.scalar + fp_arith_inst_retired2.scalar ) / ( tma_retiring * tma_info_thread_slots )` | a=FP_ARITH_INST_RETIRED.SCALAR, b=FP_ARITH_INST_RETIRED2.SCALAR, c=PERF_METRICS.RETIRING, d=PERF_METRICS.FRONTEND_BOUND, e=PERF_METRICS.BAD_SPECULATION, f=PERF_METRICS.BACKEND_BOUND, g=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | FP_Vector | FP_Arith | Uops | `100 * ( ( a + b ) / ( ( c / ( d + e + c + f ) ) * ( g ) ) )` | `( fp_arith_inst_retired.vector + fp_arith_inst_retired2.vector ) / ( tma_retiring * tma_info_thread_slots )` | a=FP_ARITH_INST_RETIRED.VECTOR, b=FP_ARITH_INST_RETIRED2.VECTOR, c=PERF_METRICS.RETIRING, d=PERF_METRICS.FRONTEND_BOUND, e=PERF_METRICS.BAD_SPECULATION, f=PERF_METRICS.BACKEND_BOUND, g=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | False_Sharing | Store_Bound | Clocks_Estimated | `100 * ( ( ( 170 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) * e + ( 81 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) * f ) / ( a ) )` | `( ( 170 * tma_info_system_core_frequency ) * ocr.demand_rfo.l3_miss:ocr_msr_val=0x103b800002 + ( 81 * tma_info_system_core_frequency ) * ocr.demand_rfo.l3_hit.snoop_hitm ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=CPU_CLK_UNHALTED.REF_TSC, e=OCR.DEMAND_RFO.L3_MISS:ocr_msr_val=0x103b800002, f=OCR.DEMAND_RFO.L3_HIT.SNOOP_HITM | c=SYSTEM_TSC_FREQ, durationtimeinmilliseconds=DURATIONTIMEINMILLISECONDS |
| 4 | INT_Divider | Divider | Clocks | `100 * ( ( a / ( b ) ) - ( c / ( b ) ) )` | `tma_divider - tma_fp_divider` | a=ARITH.DIV_ACTIVE, b=CPU_CLK_UNHALTED.THREAD, c=ARITH.FPDIV_ACTIVE |  |
| 4 | Int_Vector_128b | Int_Operations | Uops | `100 * ( ( a + b ) / ( ( c / ( d + e + c + f ) ) * ( g ) ) )` | `( int_vec_retired.add_128 + int_vec_retired.vnni_128 ) / ( tma_retiring * tma_info_thread_slots )` | a=INT_VEC_RETIRED.ADD_128, b=INT_VEC_RETIRED.VNNI_128, c=PERF_METRICS.RETIRING, d=PERF_METRICS.FRONTEND_BOUND, e=PERF_METRICS.BAD_SPECULATION, f=PERF_METRICS.BACKEND_BOUND, g=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | Int_Vector_256b | Int_Operations | Uops | `100 * ( ( a + b + c ) / ( ( d / ( e + f + d + g ) ) * ( h ) ) )` | `( int_vec_retired.add_256 + int_vec_retired.mul_256 + int_vec_retired.vnni_256 ) / ( tma_retiring * tma_info_thread_slots )` | a=INT_VEC_RETIRED.ADD_256, b=INT_VEC_RETIRED.MUL_256, c=INT_VEC_RETIRED.VNNI_256, d=PERF_METRICS.RETIRING, e=PERF_METRICS.FRONTEND_BOUND, f=PERF_METRICS.BAD_SPECULATION, g=PERF_METRICS.BACKEND_BOUND, h=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | L1_Latency_Dependency | L1_Bound | Clocks_Estimated | `100 * ( min( 2 * ( a - b - c ) * dependentloadsweight / 100 , max( e - f , 0 ) ) / ( g ) )` | `min( 2 * ( mem_inst_retired.all_loads - mem_load_retired.fb_hit - mem_load_retired.l1_miss ) * 20 / 100 , max( cycle_activity.cycles_mem_any - memory_activity.cycles_l1d_miss , 0 ) ) / tma_info_thread_clks` | a=MEM_INST_RETIRED.ALL_LOADS, b=MEM_LOAD_RETIRED.FB_HIT, c=MEM_LOAD_RETIRED.L1_MISS, e=CYCLE_ACTIVITY.CYCLES_MEM_ANY, f=MEMORY_ACTIVITY.CYCLES_L1D_MISS, g=CPU_CLK_UNHALTED.THREAD | dependentloadsweight=20 |
| 4 | L2_Hit_Latency | L2_Bound | Clocks_Retired | `100 * ( ( 4.4 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) * e * ( 1 + ( f / g ) / 2 ) / ( a ) )` | `( 4.4 * tma_info_system_core_frequency ) * mem_load_retired.l2_hit * ( 1 + ( mem_load_retired.fb_hit / mem_load_retired.l1_miss ) / 2 ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=CPU_CLK_UNHALTED.REF_TSC, e=MEM_LOAD_RETIRED.L2_HIT, f=MEM_LOAD_RETIRED.FB_HIT, g=MEM_LOAD_RETIRED.L1_MISS | c=SYSTEM_TSC_FREQ, durationtimeinmilliseconds=DURATIONTIMEINMILLISECONDS |
| 4 | L3_Hit_Latency | L3_Bound | Clocks_Estimated | `100 * ( ( ( 37 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) - ( 4.4 * ( ( ( a ) / b ) * c / ( 1000000000 ) / ( ( durationtimeinmilliseconds / 1000 ) ) ) ) ) * ( e * ( 1 + ( f / g ) / 2 ) ) / ( a ) )` | `( ( 37 * tma_info_system_core_frequency ) - ( 4.4 * tma_info_system_core_frequency ) ) * ( mem_load_retired.l3_hit * ( 1 + ( mem_load_retired.fb_hit / mem_load_retired.l1_miss ) / 2 ) ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=CPU_CLK_UNHALTED.REF_TSC, e=MEM_LOAD_RETIRED.L3_HIT, f=MEM_LOAD_RETIRED.FB_HIT, g=MEM_LOAD_RETIRED.L1_MISS | c=SYSTEM_TSC_FREQ, durationtimeinmilliseconds=DURATIONTIMEINMILLISECONDS |
| 4 | Lock_Latency | L1_Bound | Clocks | `100 * ( a / ( b ) )` | `lock_cycles.cache_lock_duration / tma_info_thread_clks` | a=LOCK_CYCLES.CACHE_LOCK_DURATION, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | MEM_Bandwidth | L3_Miss_Bound | Clocks | `100 * ( ( min( a , b ) ) / ( a ) )` | `( min( cpu_clk_unhalted.thread , offcore_requests_outstanding.all_data_rd:c12 ) ) / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.THREAD, b=OFFCORE_REQUESTS_OUTSTANDING.ALL_DATA_RD:c12 |  |
| 4 | MEM_Latency | L3_Miss_Bound | Clocks | `100 * ( ( min( a , b ) ) / ( a ) - ( ( min( a , c ) ) / ( a ) ) )` | `( min( cpu_clk_unhalted.thread , offcore_requests_outstanding.cycles_with_data_rd ) ) / tma_info_thread_clks - tma_mem_bandwidth` | a=CPU_CLK_UNHALTED.THREAD, b=OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DATA_RD, c=OFFCORE_REQUESTS_OUTSTANDING.ALL_DATA_RD:c12 |  |
| 4 | Memory_Fence | Serializing_Operation | Clocks | `100 * ( 13 * a / ( b ) )` | `13 * misc2_retired.lfence / tma_info_thread_clks` | a=MISC2_RETIRED.LFENCE, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Mispredicts_Resteers | Branch_Resteers | Clocks | `100 * ( ( ( a / ( b + c + d + e ) ) / ( max( 1 - ( ( b / ( b + c + d + e ) - f / ( g ) ) + ( e / ( b + c + d + e ) ) + ( d / ( b + c + d + e ) ) ) , 0 ) ) ) * h / ( i ) )` | `( tma_branch_mispredicts / tma_bad_speculation ) * int_misc.clear_resteer_cycles / tma_info_thread_clks` | a=PERF_METRICS.BRANCH_MISPREDICTS, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.RETIRING, e=PERF_METRICS.BACKEND_BOUND, f=INT_MISC.UOP_DROPPING, g=TOPDOWN.SLOTS:perf_metrics, h=INT_MISC.CLEAR_RESTEER_CYCLES, i=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Nop_Instructions | Other_Light_Ops | Slots | `100 * ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * f / ( ( a / ( b + c + a + d ) ) * ( g ) ) )` | `tma_light_operations * inst_retired.nop / ( tma_retiring * tma_info_thread_slots )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=INST_RETIRED.NOP, g=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | Ports_Utilized_0 | Ports_Utilization | Clocks | `100 * ( ( a + max( b - c , 0 ) ) / ( d ) * ( e - f ) / ( d ) )` | `( exe_activity.exe_bound_0_ports + max( rs.empty_resource - resource_stalls.scoreboard , 0 ) ) / tma_info_thread_clks * ( cycle_activity.stalls_total - exe_activity.bound_on_loads ) / tma_info_thread_clks` | a=EXE_ACTIVITY.EXE_BOUND_0_PORTS, b=RS.EMPTY_RESOURCE, c=RESOURCE_STALLS.SCOREBOARD, d=CPU_CLK_UNHALTED.THREAD, e=CYCLE_ACTIVITY.STALLS_TOTAL, f=EXE_ACTIVITY.BOUND_ON_LOADS |  |
| 4 | Ports_Utilized_1 | Ports_Utilization | Clocks | `100 * ( a / ( b ) )` | `exe_activity.1_ports_util / tma_info_thread_clks` | a=EXE_ACTIVITY.1_PORTS_UTIL, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Ports_Utilized_2 | Ports_Utilization | Clocks | `100 * ( a / ( b ) )` | `exe_activity.2_ports_util / tma_info_thread_clks` | a=EXE_ACTIVITY.2_PORTS_UTIL, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Ports_Utilized_3m | Ports_Utilization | Clocks | `100 * ( a / ( b ) )` | `uops_executed.cycles_ge_3 / tma_info_thread_clks` | a=UOPS_EXECUTED.CYCLES_GE_3, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | SQ_Full | L3_Bound | Clocks | `100 * ( ( a + b ) / ( c ) )` | `( xq.full_cycles + l1d_pend_miss.l2_stalls ) / tma_info_thread_clks` | a=XQ.FULL_CYCLES, b=L1D_PEND_MISS.L2_STALLS, c=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Shuffles_256b | Other_Light_Ops | Slots | `100 * ( ( max( 0 , ( a / ( b + c + a + d ) ) - ( e / ( b + c + a + d ) ) ) ) * f / ( ( a / ( b + c + a + d ) ) * ( g ) ) )` | `tma_light_operations * int_vec_retired.shuffles / ( tma_retiring * tma_info_thread_slots )` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=PERF_METRICS.HEAVY_OPERATIONS, f=INT_VEC_RETIRED.SHUFFLES, g=TOPDOWN.SLOTS:perf_metrics |  |
| 4 | Slow_Pause | Serializing_Operation | Clocks | `100 * ( a / ( b ) )` | `cpu_clk_unhalted.pause / tma_info_thread_clks` | a=CPU_CLK_UNHALTED.PAUSE, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Split_Loads | L1_Bound | Clocks_Calculated | `100 * ( a * ( b / c ) / ( d ) )` | `mem_inst_retired.split_loads * tma_info_memory_load_miss_real_latency / tma_info_thread_clks` | a=MEM_INST_RETIRED.SPLIT_LOADS, b=L1D_PEND_MISS.PENDING, c=MEM_LOAD_COMPLETED.L1_MISS_ANY, d=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Split_Stores | Store_Bound | Core_Utilization | `100 * ( a / ( b if smt_on else ( c ) ) )` | `mem_inst_retired.split_stores / tma_info_core_core_clks` | a=MEM_INST_RETIRED.SPLIT_STORES, b=CPU_CLK_UNHALTED.DISTRIBUTED, c=CPU_CLK_UNHALTED.THREAD | smt_on=HYPERTHREADING_ON, threads=THREADS_PER_CORE |
| 4 | Store_Fwd_Blk | L1_Bound | Clocks_Estimated | `100 * ( 13 * a / ( b ) )` | `13 * ld_blocks.store_forward / tma_info_thread_clks` | a=LD_BLOCKS.STORE_FORWARD, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Store_Latency | Store_Bound | Clocks_Estimated | `100 * ( ( ( a * ( 10 ) * ( 1 - ( b / c ) ) ) + ( 1 - ( b / c ) ) * ( min( d , e ) ) ) / ( d ) )` | `( ( mem_store_retired.l2_hit * ( 10 ) * ( 1 - ( mem_inst_retired.lock_loads / mem_inst_retired.all_stores ) ) ) + ( 1 - ( mem_inst_retired.lock_loads / mem_inst_retired.all_stores ) ) * ( min( cpu_clk_unhalted.thread , offcore_requests_outstanding.cycles_with_demand_rfo ) ) ) / tma_info_thread_clks` | a=MEM_STORE_RETIRED.L2_HIT, b=MEM_INST_RETIRED.LOCK_LOADS, c=MEM_INST_RETIRED.ALL_STORES, d=CPU_CLK_UNHALTED.THREAD, e=OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_RFO |  |
| 4 | Streaming_Stores | Store_Bound | Clocks_Estimated | `100 * ( 9 * a / ( b ) )` | `9 * ocr.streaming_wr.any_response / tma_info_thread_clks` | a=OCR.STREAMING_WR.ANY_RESPONSE, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | Unknown_Branches | Branch_Resteers | Clocks | `100 * ( a / ( b ) )` | `int_misc.unknown_branch_cycles / tma_info_thread_clks` | a=INT_MISC.UNKNOWN_BRANCH_CYCLES, b=CPU_CLK_UNHALTED.THREAD |  |
| 4 | X87_Use | FP_Arith | Uops | `100 * ( ( a / ( b + c + a + d ) ) * e / f )` | `tma_retiring * uops_executed.x87 / uops_executed.thread` | a=PERF_METRICS.RETIRING, b=PERF_METRICS.FRONTEND_BOUND, c=PERF_METRICS.BAD_SPECULATION, d=PERF_METRICS.BACKEND_BOUND, e=UOPS_EXECUTED.X87, f=UOPS_EXECUTED.THREAD |  |

## 原始事件

| Event | perf syntax | Counter | Alone | Offcore | MSR index/value | Errata |
|---|---|---|---:|---:|---|---|
| ARITH.DIV_ACTIVE | `cpu/event=0xb0,umask=0x09,cmask=1/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| ARITH.FPDIV_ACTIVE | `cpu/event=0xb0,umask=0x01,cmask=1/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| ASSISTS.ANY | `cpu/event=0xc1,umask=0x1b/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| BR_INST_RETIRED.ALL_BRANCHES | `cpu/event=0xc4,umask=0x00/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| BR_MISP_RETIRED.ALL_BRANCHES | `cpu/event=0xc5,umask=0x00/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CPU_CLK_UNHALTED.C01 | `cpu/event=0xec,umask=0x10/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CPU_CLK_UNHALTED.C02 | `cpu/event=0xec,umask=0x20/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CPU_CLK_UNHALTED.DISTRIBUTED | `cpu/event=0xec,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CPU_CLK_UNHALTED.PAUSE | `cpu/event=0xec,umask=0x40/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CPU_CLK_UNHALTED.REF_TSC | `ref-cycles` | architectural fixed | 0 | 0 | n/a/n/a | null |
| CPU_CLK_UNHALTED.THREAD | `cycles` | architectural fixed | 0 | 0 | n/a/n/a | null |
| CYCLE_ACTIVITY.CYCLES_MEM_ANY | `cpu/event=0xa3,umask=0x10,cmask=16/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| CYCLE_ACTIVITY.STALLS_TOTAL | `cpu/event=0xa3,umask=0x04,cmask=4/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| DECODE.LCP | `cpu/event=0x87,umask=0x01/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| DSB2MITE_SWITCHES.PENALTY_CYCLES | `cpu/event=0x61,umask=0x02/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| DTLB_LOAD_MISSES.STLB_HIT:c1 | `cpu/event=0x12,umask=0x20,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| DTLB_LOAD_MISSES.WALK_ACTIVE | `cpu/event=0x12,umask=0x10,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| DTLB_STORE_MISSES.STLB_HIT:c1 | `cpu/event=0x13,umask=0x20,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| DTLB_STORE_MISSES.WALK_ACTIVE | `cpu/event=0x13,umask=0x10,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| EXE.AMX_BUSY | `cpu/event=0xb7,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.1_PORTS_UTIL | `cpu/event=0xa6,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.2_3_PORTS_UTIL | `cpu/event=0xa6,umask=0xc/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.2_PORTS_UTIL | `cpu/event=0xa6,umask=0x04/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.BOUND_ON_LOADS | `cpu/event=0xa6,umask=0x21,cmask=5/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.BOUND_ON_STORES | `cpu/event=0xa6,umask=0x40,cmask=2/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| EXE_ACTIVITY.EXE_BOUND_0_PORTS | `cpu/event=0xa6,umask=0x80/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| FP_ARITH_INST_RETIRED.SCALAR | `cpu/event=0xc7,umask=0x03/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| FP_ARITH_INST_RETIRED.VECTOR | `cpu/event=0xc7,umask=0xfc/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| FP_ARITH_INST_RETIRED2.SCALAR | `cpu/event=0xcf,umask=0x03/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| FP_ARITH_INST_RETIRED2.VECTOR | `cpu/event=0xcf,umask=0x1c/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| ICACHE_DATA.STALLS | `cpu/event=0x80,umask=0x04/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| ICACHE_TAG.STALLS | `cpu/event=0x83,umask=0x04/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| IDQ.DSB_CYCLES_ANY | `cpu/event=0x79,umask=0x08,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| IDQ.DSB_CYCLES_OK | `cpu/event=0x79,umask=0x08,cmask=6/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| IDQ.MITE_CYCLES_ANY | `cpu/event=0x79,umask=0x04,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| IDQ.MITE_CYCLES_OK | `cpu/event=0x79,umask=0x04,cmask=6/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| IDQ.MS_CYCLES_ANY | `cpu/event=0x79,umask=0x20,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| INST_DECODED.DECODERS:c1 | `cpu/event=0x75,umask=0x01,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| INST_DECODED.DECODERS:c2 | `cpu/event=0x75,umask=0x01,cmask=2/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| INST_RETIRED.MACRO_FUSED | `cpu/event=0xc0,umask=0x10/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INST_RETIRED.NOP | `cpu/event=0xc0,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_MISC.CLEARS_COUNT | `cpu/event=0xad,umask=0x01,cmask=1,edge=1/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_MISC.CLEAR_RESTEER_CYCLES | `cpu/event=0xad,umask=0x80/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_MISC.UNKNOWN_BRANCH_CYCLES | `cpu/event=0xad,umask=0x40,frontend=0x7/` | 0,1,2,3,4,5,6,7 | 1 | 0 | 0x3F7/0x7 | null |
| INT_MISC.UOP_DROPPING | `cpu/event=0xad,umask=0x10/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.ADD_128 | `cpu/event=0xe7,umask=0x03/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.ADD_256 | `cpu/event=0xe7,umask=0x0c/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.MUL_256 | `cpu/event=0xe7,umask=0x80/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.SHUFFLES | `cpu/event=0xe7,umask=0x40/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.VNNI_128 | `cpu/event=0xe7,umask=0x10/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| INT_VEC_RETIRED.VNNI_256 | `cpu/event=0xe7,umask=0x20/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| ITLB_MISSES.WALK_ACTIVE | `cpu/event=0x11,umask=0x10,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| L1D_PEND_MISS.FB_FULL | `cpu/event=0x48,umask=0x02/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| L1D_PEND_MISS.L2_STALLS | `cpu/event=0x48,umask=0x04/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| L1D_PEND_MISS.PENDING | `cpu/event=0x48,umask=0x01/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| LD_BLOCKS.STORE_FORWARD | `cpu/event=0x03,umask=0x82/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| LOCK_CYCLES.CACHE_LOCK_DURATION | `cpu/event=0x42,umask=0x02/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MACHINE_CLEARS.COUNT | `cpu/event=0xc3,umask=0x01,cmask=1,edge=1/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| MACHINE_CLEARS.MEMORY_ORDERING | `cpu/event=0xc3,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| MEMORY_ACTIVITY.CYCLES_L1D_MISS | `cpu/event=0x47,umask=0x02,cmask=2/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEMORY_ACTIVITY.STALLS_L1D_MISS | `cpu/event=0x47,umask=0x03,cmask=3/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEMORY_ACTIVITY.STALLS_L2_MISS | `cpu/event=0x47,umask=0x05,cmask=5/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEMORY_ACTIVITY.STALLS_L3_MISS | `cpu/event=0x47,umask=0x09,cmask=9/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_INST_RETIRED.ALL_LOADS | `cpu/event=0xd0,umask=0x81/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_INST_RETIRED.ALL_STORES | `cpu/event=0xd0,umask=0x82/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_INST_RETIRED.LOCK_LOADS | `cpu/event=0xd0,umask=0x21/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_INST_RETIRED.SPLIT_LOADS | `cpu/event=0xd0,umask=0x41/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_INST_RETIRED.SPLIT_STORES | `cpu/event=0xd0,umask=0x42/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_COMPLETED.L1_MISS_ANY | `cpu/event=0x43,umask=0xfd/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_L3_HIT_RETIRED.XSNP_FWD | `cpu/event=0xd2,umask=0x04/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_L3_HIT_RETIRED.XSNP_MISS | `cpu/event=0xd2,umask=0x01/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_L3_HIT_RETIRED.XSNP_NO_FWD | `cpu/event=0xd2,umask=0x02/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_RETIRED.FB_HIT | `cpu/event=0xd1,umask=0x40/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_RETIRED.L1_MISS | `cpu/event=0xd1,umask=0x08/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_RETIRED.L2_HIT | `cpu/event=0xd1,umask=0x02/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_LOAD_RETIRED.L3_HIT | `cpu/event=0xd1,umask=0x04/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_STORE_RETIRED.L2_HIT | `cpu/event=0x44,umask=0x01/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| MEM_UOP_RETIRED.ANY | `cpu/event=0xe5,umask=0x03/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| MISC2_RETIRED.LFENCE | `cpu/event=0xe0,umask=0x20/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HITM | `cpu/event=0x2a,umask=0x01,offcore_rsp=0x10003c0001/` | 0,1,2,3 | 0 | 1 | 0x1a6,0x1a7/0x10003C0001 | null |
| OCR.DEMAND_DATA_RD.L3_HIT.SNOOP_HIT_WITH_FWD | `cpu/event=0x2a,umask=0x01,offcore_rsp=0x8003c0001/` | 0,1,2,3 | 0 | 1 | 0x1a6,0x1a7/0x8003C0001 | null |
| OCR.DEMAND_RFO.L3_HIT.SNOOP_HITM | `cpu/event=0x2a,umask=0x01,offcore_rsp=0x10003c0002/` | 0,1,2,3 | 0 | 1 | 0x1a6,0x1a7/0x10003C0002 | null |
| OCR.DEMAND_RFO.L3_MISS:ocr_msr_val=0x103b800002 | `cpu/event=0x2a,umask=0x01,offcore_rsp=0x3f3fc00002,config1=0x103b800002/` | 0,1,2,3 | 0 | 1 | 0x1a6,0x1a7/0x3F3FC00002 | null |
| OCR.STREAMING_WR.ANY_RESPONSE | `cpu/event=0x2a,umask=0x01,offcore_rsp=0x10800/` | 0,1,2,3 | 0 | 1 | 0x1a6,0x1a7/0x10800 | null |
| OFFCORE_REQUESTS_OUTSTANDING.ALL_DATA_RD:c12 | `cpu/event=0x20,umask=0x08,cmask=12/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DATA_RD | `cpu/event=0x20,umask=0x08,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_CODE_RD | `cpu/event=0x20,umask=0x02,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| OFFCORE_REQUESTS_OUTSTANDING.CYCLES_WITH_DEMAND_RFO | `cpu/event=0x20,umask=0x04,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |
| PERF_METRICS.BACKEND_BOUND | `cpu/topdown-be-bound/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.BAD_SPECULATION | `cpu/topdown-bad-spec/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.BRANCH_MISPREDICTS | `cpu/topdown-br-mispredict/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.FETCH_LATENCY | `cpu/topdown-fetch-lat/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.FRONTEND_BOUND | `cpu/topdown-fe-bound/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.HEAVY_OPERATIONS | `cpu/topdown-heavy-ops/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.MEMORY_BOUND | `cpu/topdown-mem-bound/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| PERF_METRICS.RETIRING | `cpu/topdown-retiring/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| RESOURCE_STALLS.SCOREBOARD | `cpu/event=0xa2,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| RS.EMPTY_RESOURCE | `cpu/event=0xa5,umask=0x01/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| TOPDOWN.SLOTS:perf_metrics | `cpu/slots/` | fixed PERF_METRICS | 0 | 0 | n/a/n/a | null |
| UOPS_EXECUTED.CYCLES_GE_3 | `cpu/event=0xb1,umask=0x01,cmask=3/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| UOPS_EXECUTED.THREAD | `cpu/event=0xb1,umask=0x01/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| UOPS_EXECUTED.X87 | `cpu/event=0xb1,umask=0x10/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| UOPS_ISSUED.ANY | `cpu/event=0xae,umask=0x01/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| UOPS_RETIRED.MS | `cpu/event=0xc2,umask=0x04,frontend=0x8/` | 0,1,2,3,4,5,6,7 | 1 | 0 | 0x3F7/0x8 | null |
| UOPS_RETIRED.MS:c1 | `cpu/event=0xc2,umask=0x04,cmask=1,frontend=0x8/` | 0,1,2,3,4,5,6,7 | 1 | 0 | 0x3F7/0x8 | null |
| UOPS_RETIRED.MS:c1:e1 | `cpu/event=0xc2,umask=0x04,cmask=1,edge=1,frontend=0x8/` | 0,1,2,3,4,5,6,7 | 1 | 0 | 0x3F7/0x8 | null |
| UOPS_RETIRED.SLOTS | `cpu/event=0xc2,umask=0x02/` | 0,1,2,3,4,5,6,7 | 0 | 0 | 0x00/0x00 | null |
| XQ.FULL_CYCLES | `cpu/event=0x2d,umask=0x01,cmask=1/` | 0,1,2,3 | 0 | 0 | 0x00/0x00 | null |

## 自动校验

- 指标数：85
- 唯一事件数：108
- 校验错误数：0
- 校验警告数：7
- 结果：公式别名、父子层级和事件映射全部通过。
- WARNING: AMX_Busy: declared but unused aliases ['threads']
- WARNING: DSB: declared but unused aliases ['threads']
- WARNING: MITE: declared but unused aliases ['threads']
- WARNING: MS: declared but unused aliases ['threads']
- WARNING: DTLB_Store: declared but unused aliases ['threads']
- WARNING: Decoder0_Alone: declared but unused aliases ['threads']
- WARNING: Split_Stores: declared but unused aliases ['threads']
