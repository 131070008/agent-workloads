# Claude Code ToolCall 最小微基准

这是一套可脱离 Agent、LLM、Docker 和网络独立运行的 `Read / Write / Edit / Grep` 微基准。输入参数来自 AWS36 Golden trajectory，源文件从对应 SWE-bench Docker image 的 `/testbed` 提取；执行路径按 Claude Code 2.1.88 的四个核心工具源码复现。

## 用例

| 用例 | 核心路径 | 真实输入来源 |
|---|---|---|
| `read_full` | 完整读取、mtime 状态、行号格式化 | `django-14608 #12`，`django/forms/utils.py` |
| `read_range` | 指定行范围读取与格式化 | `django-14608 #9`，`formsets.py:290-298` |
| `write_create` | 建父目录、全量写入、flush、更新状态 | `django-14608 #16` 的完整 `reproduce.py` payload |
| `edit_unique` | 预先 Read、陈旧检查、唯一匹配、patch、全文件重写、flush | `django-14608 #18` |
| `grep_content_single` | `rg` 子进程、单文件匹配、行号、输出解析 | `django-14608 #14` |
| `grep_content_context` | `rg -A 20`、上下文输出和路径转换 | `pytest-5221 #9` |
| `grep_recursive_no_match` | 真实 `_pytest` 目录递归扫描、Python glob、无匹配路径 | `pytest-5221 #3` |
| `grep_files_with_matches` | Claude Code 默认 `-l` 路径、逐文件 `stat`、mtime 排序、`head_limit` | `django-14608 #5` 的 `FormSet` 文件发现行为 |

最小 fixture 只保留两个镜像中真正涉及的源码子树：

```text
fixtures/
├── django/forms/       # 约 440 KB
└── pytest/_pytest/     # 约 824 KB
```

## 祖冲之：一次构建

依赖检查：

```bash
node --version          # 要求 >= 18
rg --version
docker image inspect \
  swebench/sweb.eval.x86_64.django_1776_django-14608:v1 \
  swebench/sweb.eval.x86_64.pytest-dev_1776_pytest-5221:v1 >/dev/null
```

从 Golden trajectory 和 Docker image 生成完整 bundle：

```bash
cd /home/higon/cunzhe/agent-workloads/SWE-bench/tool_microbench/claude_code_minimal

python3 extract_from_swe.py \
  --trajectory 'django__django-14608=/home/higon/cunzhe/SWE/swe_runs/aws36_golden_single_cpu2_twice_zuchongzhi_20260813_135500/round1/cases/django__django-14608/django__django-14608_20260813_135657/django__django-14608.local.traj' \
  --trajectory 'pytest-dev__pytest-5221=/home/higon/cunzhe/SWE/swe_runs/aws36_golden_single_cpu2_twice_zuchongzhi_20260813_135500/round1/cases/pytest-dev__pytest-5221/pytest-dev__pytest-5221_20260813_140325/pytest-dev__pytest-5221.local.traj' \
  --output-dir /home/higon/cunzhe/claude_code_tool_microbench_20260826
```

构建器会校验轨迹 action、从镜像复制两个最小源码树、解析真实 Write/Edit payload、计算 image/fixture SHA256，并把执行器、README、源码核对记录一起放进 bundle。

构建后校验全部静态文件：

```bash
cd /home/higon/cunzhe/claude_code_tool_microbench_20260826
sha256sum -c SHA256SUMS
```

## 运行

```bash
cd /home/higon/cunzhe/claude_code_tool_microbench_20260826
```

列出全部用例：

```bash
node cc_tool_microbench.mjs --bundle "$PWD" --list
```

全部运行一次并做语义校验：

```bash
node cc_tool_microbench.mjs --bundle "$PWD"
```

绑定 CPU2，每项预热 10 次、正式运行 100 次：

```bash
taskset -c 2 node cc_tool_microbench.mjs \
  --bundle "$PWD" \
  --warmup 10 \
  --iterations 100
```

只跑一个用例：

```bash
taskset -c 2 node cc_tool_microbench.mjs \
  --bundle "$PWD" \
  --case grep_files_with_matches \
  --warmup 10 \
  --iterations 100
```

多选：

```bash
taskset -c 2 node cc_tool_microbench.mjs \
  --bundle "$PWD" \
  --case read_full \
  --case read_range \
  --case edit_unique \
  --warmup 10 \
  --iterations 100
```

指定结果目录：

```bash
taskset -c 2 node cc_tool_microbench.mjs \
  --bundle "$PWD" \
  --case grep_content_context \
  --iterations 100 \
  --output /home/higon/cunzhe/microbench_results/grep_context_$(date +%Y%m%d_%H%M%S)
```

## 单条可执行命令

```bash
# Read 完整文件
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case read_full --iterations 100

# Read 指定行范围
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case read_range --iterations 100

# Write 新文件
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case write_create --iterations 100

# Edit 唯一字符串
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case edit_unique --iterations 100

# Grep 单文件内容
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case grep_content_single --iterations 100

# Grep 带上下文
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case grep_content_context --iterations 100

# Grep 递归扫描无匹配
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case grep_recursive_no_match --iterations 100

# Grep 文件列表，并包含 stat + mtime 排序
taskset -c 2 node cc_tool_microbench.mjs --bundle "$PWD" --case grep_files_with_matches --iterations 100
```

## 结果

每次执行建立新的时间戳目录，不覆盖旧结果：

```text
results/YYYYMMDD_HHMMSS/
├── results.csv
├── results.json
├── artifacts/<case>/output.txt
├── artifacts/<case>/result.json
└── work/                         # Write/Edit 每轮独立输入与产物
```

`results.csv` 含：`wall_ns`、`wall_ms`、`user_cpu_us`、`system_cpu_us`、输出字节数和 `valid`。所有正式行必须为 `valid=true`，末尾必须为 `FAILURES=0`。

## 计时边界

- `Read`：文件读取、范围选择、mtime-backed 状态更新、行号格式化。
- `Write`：创建父目录、全内容写入、`fsync`、mtime/read-state 更新。
- `Edit`：要求的 prior Read 放在计时外；计时包含再次全文件读取、陈旧检查、唯一匹配、patch/确认片段生成、全文件重写、`fsync` 和状态更新。
- `Grep`：`rg` 进程创建、扫描、输出解析、分页；`files_with_matches` 还包含每个命中文件的 `stat` 和 mtime 排序。

不进入本微基准的路径为 LLM/网络、交互权限 UI、LSP/VSCode 通知、文件历史备份、遥测、React UI、图片/PDF/Notebook 和生产 tokenizer。它们不是本次要收敛的 Linux 文件与搜索执行路径。

源码核对版本、文件 SHA256 和边界记录在 `source_audit.json`；轨迹原始 action/observation 位于 `provenance/`，镜像摘要和每个 fixture 的 SHA256 位于 `manifest.json`。

## 祖冲之验证记录

2026-08-26 已在祖冲之使用服务器上的原始 trajectory 与 Docker image 完成构建和验证：

```text
bundle: /home/higon/cunzhe/claude_code_tool_microbench_20260826
result: /home/higon/cunzhe/claude_code_tool_microbench_20260826/results/20260826_072508
cases:  8
runs:   40（每项 warmup=2、iterations=5）
check:  FAILURES=0，40/40 valid=true
```
