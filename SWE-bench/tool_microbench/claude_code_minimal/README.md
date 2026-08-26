# CC 文件工具与 GNU grep 最小微基准

本目录提供两组可以脱离 Agent、LLM、Docker 和网络运行的微基准：

- `Read / Write / Edit`：按 Claude Code 2.1.88 对应工具源码的核心路径实现。
- `grep`：直接执行 Golden trajectory 中实际出现的 GNU `grep` 命令，不替换为其他搜索工具。

Golden trajectory 只负责提供参数和编辑 payload，SWE-bench image 只负责提供固定输入文件；执行时不调用 SWE-agent `edit_anthropic`。

## 用例与输入

| ID | 实现口径 | 输入来源 |
|---|---|---|
| `read_full` | CC Read：完整读取、mtime 状态、行号格式化 | `django-14608 #12`，`django/forms/utils.py` |
| `read_range` | CC Read：指定行范围读取 | `django-14608 #9`，`formsets.py:290-298` |
| `write_create` | CC Write：建目录、全量写入、flush、更新状态 | `django-14608 #16` 的完整 payload |
| `edit_unique` | CC Edit：prior Read、陈旧检查、唯一匹配、patch、全文件重写 | `django-14608 #18` |
| `grep_single_file` | GNU `grep -n` | `django-14608 #14` |
| `grep_context` | GNU `grep -n -A 20` | `pytest-5221 #9` |
| `grep_recursive_include` | GNU `grep -r --include` | `pytest-5221 #3` |
| `grep_find_xargs` | `find | xargs grep -l | grep -v | head` | `django-14608 #5` |

完整 bundle 包含所有执行文件与输入：

```text
cc_file_tool.mjs        # 直接执行 CC Read/Write/Edit
cc_tool_microbench.mjs  # 重复运行、校验、CSV 输出
fixtures/
├── django/forms/       # 从 django-14608 image 提取，约 440 KB
└── pytest/_pytest/     # 从 pytest-5221 image 提取，约 824 KB
payloads/
├── reproduce.py        # Write 的完整输入
├── edit_old.txt        # Edit old_string
└── edit_new.txt        # Edit new_string
provenance/             # 轨迹原始 action/observation
manifest.json           # 镜像摘要、文件哈希、用例与 grep 命令
SHA256SUMS
```

## 祖冲之构建

检查依赖和镜像：

```bash
node --version          # >= 18
grep --version | head -1
docker image inspect \
  swebench/sweb.eval.x86_64.django_1776_django-14608:v1 \
  swebench/sweb.eval.x86_64.pytest-dev_1776_pytest-5221:v1 >/dev/null
```

构建 bundle：

```bash
cd /home/higon/cunzhe/agent-workloads/SWE-bench/tool_microbench/claude_code_minimal

python3 extract_from_swe.py \
  --trajectory 'django__django-14608=/home/higon/cunzhe/SWE/swe_runs/aws36_golden_single_cpu2_twice_zuchongzhi_20260813_135500/round1/cases/django__django-14608/django__django-14608_20260813_135657/django__django-14608.local.traj' \
  --trajectory 'pytest-dev__pytest-5221=/home/higon/cunzhe/SWE/swe_runs/aws36_golden_single_cpu2_twice_zuchongzhi_20260813_135500/round1/cases/pytest-dev__pytest-5221/pytest-dev__pytest-5221_20260813_140325/pytest-dev__pytest-5221.local.traj' \
  --output-dir /home/higon/cunzhe/cc_grep_tool_microbench_20260826_v2
```

校验静态文件：

```bash
cd /home/higon/cunzhe/cc_grep_tool_microbench_20260826_v2
sha256sum -c SHA256SUMS
```

后续命令统一使用：

```bash
B=/home/higon/cunzhe/cc_grep_tool_microbench_20260826_v2
```

## 直接执行 CC Read

完整文件：

```bash
time taskset -c 2 node "$B/cc_file_tool.mjs" read \
  --file "$B/fixtures/django/forms/utils.py"
```

指定 290-298 行：

```bash
time taskset -c 2 node "$B/cc_file_tool.mjs" read \
  --file "$B/fixtures/django/forms/formsets.py" \
  --offset 290 \
  --limit 9
```

## 直接执行 CC Write

准备独立输出目录，然后执行完整文件写入：

```bash
W="$B/direct_work/write_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$W"

time taskset -c 2 node "$B/cc_file_tool.mjs" write \
  --file "$W/reproduce.py" \
  --content-file "$B/payloads/reproduce.py"
```

## 直接执行 CC Edit

输入复制不计入 Edit 本身：

```bash
W="$B/direct_work/edit_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$W"
cp "$B/fixtures/django/forms/formsets.py" "$W/formsets.py"

time taskset -c 2 node "$B/cc_file_tool.mjs" edit \
  --file "$W/formsets.py" \
  --old-file "$B/payloads/edit_old.txt" \
  --new-file "$B/payloads/edit_new.txt"
```

`cc_file_tool.mjs edit` 会先建立 CC Edit 要求的完整 Read 状态，再执行陈旧检查、唯一匹配、patch 构造、全文件重写和 flush。批量 runner 则把 prior Read 放在计时区间外。

## 直接执行 GNU grep

以下命令不经过 Node 或 benchmark runner，可直接交给 `time`、`perf` 或 SDE。

### 1. 单文件匹配并打印行号

```bash
time taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"
```

### 2. 单文件匹配并返回 20 行后置上下文

```bash
time taskset -c 2 grep -n "def showfixtures" -A 20 --include="*.py" \
  "$B/fixtures/pytest/_pytest/python.py"
```

### 3. 递归扫描 Python 文件

```bash
time taskset -c 2 grep -r "def _fixtures" --include="*.py" \
  "$B/fixtures/pytest/_pytest"
```

此条轨迹预期无匹配；GNU `grep` 返回 `1` 表示没有匹配，不是执行故障。

### 4. 文件发现、内容搜索、路径过滤

```bash
time bash -lc '
  find "$1/fixtures/django/forms" -type f -name "*.py" -print0 |
    xargs -0 grep -l "FormSet" |
    grep -v "test" |
    head -10
' _ "$B"
```

## 直接 perf 采集 grep

计数器：

```bash
sudo perf stat -r 10 \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses \
  -- taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"
```

采样并保留汇编热点：

```bash
mkdir -p "$B/perf_results"

sudo perf record -F 999 -g \
  -o "$B/perf_results/grep_single_file.data" \
  -- taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"

sudo perf report \
  -i "$B/perf_results/grep_single_file.data"
```

递归搜索：

```bash
sudo perf record -F 999 -g \
  -o "$B/perf_results/grep_recursive.data" \
  -- taskset -c 2 grep -r "def _fixtures" --include="*.py" \
  "$B/fixtures/pytest/_pytest"
```

## CC 文件工具批量运行

批量 runner 只运行 CC `Read / Write / Edit`，不包装 GNU `grep`：

```bash
node "$B/cc_tool_microbench.mjs" --bundle "$B" --list

taskset -c 2 node "$B/cc_tool_microbench.mjs" \
  --bundle "$B" \
  --warmup 10 \
  --iterations 100
```

只运行 Edit：

```bash
taskset -c 2 node "$B/cc_tool_microbench.mjs" \
  --bundle "$B" \
  --case edit_unique \
  --warmup 10 \
  --iterations 100
```

结果保存在新的时间戳目录：

```text
results/YYYYMMDD_HHMMSS/
├── results.csv
├── results.json
├── artifacts/<case>/
└── work/
```

## 计时边界

- CC `Read`：文件读取、范围选择、mtime-backed 状态更新和行号格式化。
- CC `Write`：创建父目录、全内容写入、`fsync` 和状态更新。
- CC `Edit`：批量模式将 prior Read 放在计时外；计时包含全文件重读、陈旧检查、唯一匹配、patch/确认片段生成、全文件重写、`fsync` 和状态更新。
- GNU `grep`：README 中的直接命令只统计真实 `grep` 进程；pipeline 用例同时包含 `find/xargs/grep/head` 子进程。

源码核对版本和文件 SHA256 位于 `source_audit.json`；轨迹原始 action/observation 位于 `provenance/`；镜像摘要、fixture SHA256 和展开后的 GNU `grep` 命令位于 `manifest.json`。

## 祖冲之验证

```text
bundle: /home/higon/cunzhe/cc_grep_tool_microbench_20260826_v2
GNU grep: 3.7
Node.js: v24.19.0
grep: 4/4 命令执行结果符合原轨迹口径
direct file tools: Read/Write/Edit 全部通过内容校验
batch file tools: 20/20 valid=true，FAILURES=0
result: /home/higon/cunzhe/cc_grep_tool_microbench_20260826_v2/results/20260826_092439
```
