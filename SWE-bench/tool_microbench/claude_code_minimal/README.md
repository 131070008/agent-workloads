# Coding Agent 文件与搜索工具微基准

这是一套可直接从 Git 仓库运行的独立 microbench，不需要 Agent、LLM、Docker、SWE-bench 或网络：

- `Read / Write / Edit`：复现 Claude Code 2.1.88 对应工具的核心执行路径。
- GNU `grep`：保留 Golden trajectory 中实际出现的命令语义。
- CC `Grep`：可选对照，按 Claude Code 的工具语义调用 `ripgrep`（`rg`）。

输入源码、编辑 payload 和用例清单均已冻结在本目录。GNU `grep` 和 CC `Grep/rg` 是两套不同实验口径，结果不要混为一组。

## 快速开始

进入克隆后的目录：

```bash
cd SWE-bench/tool_microbench/claude_code_minimal
B=$PWD
```

依赖：

```bash
node --version        # Read/Write/Edit 与 CC Grep wrapper，建议 >= 18
grep --version        # 原始轨迹 grep
rg --version          # 仅运行可选 CC Grep 时需要
```

校验冻结输入：

```bash
sha256sum -c SHA256SUMS
```

目录结构：

```text
cc_file_tool.mjs        # 直接执行 CC Read/Write/Edit
cc_rg_tool.mjs          # 直接执行 CC Grep，内部启动 rg
cc_tool_microbench.mjs  # Read/Write/Edit 重复运行、校验和 CSV 输出
fixtures/
├── django/forms/       # 真实 Django 源码子树
└── pytest/_pytest/     # 真实 pytest 源码子树
payloads/
├── reproduce.py        # Write 输入
├── edit_old.txt        # Edit old_string
└── edit_new.txt        # Edit new_string
manifest.json           # 用例、输入和命令清单
SHA256SUMS               # 静态文件校验
```

## 用例

| 类别 | 用例 | 核心操作 |
|---|---|---|
| CC Read | `read_full` | 完整读取、mtime 状态、行号格式化 |
| CC Read | `read_range` | 指定行范围读取和格式化 |
| CC Write | `write_create` | 建目录、全量写入、flush、更新状态 |
| CC Edit | `edit_unique` | prior Read、陈旧检查、唯一匹配、patch、全文件重写 |
| GNU grep | `grep_single_file` | 单文件匹配并输出行号 |
| GNU grep | `grep_context` | 单文件匹配并返回 20 行后置上下文 |
| GNU grep | `grep_recursive_include` | 递归扫描 Python 文件 |
| GNU grep | `grep_find_xargs` | `find | xargs grep | grep | head` pipeline |
| CC Grep | `cc_rg_*` | `rg` 子进程、过滤、输出模式、分页与路径处理 |

## CC Read

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

## CC Write

```bash
W="$B/direct_work/write_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$W"

time taskset -c 2 node "$B/cc_file_tool.mjs" write \
  --file "$W/reproduce.py" \
  --content-file "$B/payloads/reproduce.py"
```

## CC Edit

准备输入文件不计入 Edit 本身：

```bash
W="$B/direct_work/edit_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$W"
cp "$B/fixtures/django/forms/formsets.py" "$W/formsets.py"

time taskset -c 2 node "$B/cc_file_tool.mjs" edit \
  --file "$W/formsets.py" \
  --old-file "$B/payloads/edit_old.txt" \
  --new-file "$B/payloads/edit_new.txt"
```

直接执行入口会先建立 CC Edit 要求的完整 Read 状态，再执行陈旧检查、唯一匹配、patch 构造、全文件重写和 flush。批量 runner 把 prior Read 放在计时区间外。

## 原始 GNU grep

以下命令不经过 Node 或 runner，可以直接接 `time`、`perf` 或 SDE。

单文件匹配并打印行号：

```bash
time taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"
```

返回 20 行后置上下文：

```bash
time taskset -c 2 grep -n "def showfixtures" -A 20 --include="*.py" \
  "$B/fixtures/pytest/_pytest/python.py"
```

递归扫描 Python 文件：

```bash
time taskset -c 2 grep -r "def _fixtures" --include="*.py" \
  "$B/fixtures/pytest/_pytest"
```

该用例预期无匹配；GNU `grep` 返回 `1` 表示没有匹配，不是执行故障。

文件发现、内容搜索和路径过滤：

```bash
time bash -lc '
  find "$1/fixtures/django/forms" -type f -name "*.py" -print0 |
    xargs -0 grep -l "FormSet" |
    grep -v "test" |
    head -10
' _ "$B"
```

## 可选：CC Grep / ripgrep

`cc_rg_tool.mjs` 复现 CC Grep 的主要路径：启动 `rg`，搜索隐藏文件，排除 VCS 目录，限制超长行，支持 `content/files_with_matches/count`、上下文、glob/type、分页、相对路径转换，并在文件列表模式按 mtime 排序。

单文件内容模式：

```bash
time taskset -c 2 node "$B/cc_rg_tool.mjs" \
  --pattern nonfield \
  --path "$B/fixtures/django/forms/forms.py" \
  --output-mode content
```

20 行后置上下文：

```bash
time taskset -c 2 node "$B/cc_rg_tool.mjs" \
  --pattern "def showfixtures" \
  --path "$B/fixtures/pytest/_pytest/python.py" \
  --glob "*.py" \
  --output-mode content \
  -A 20
```

递归内容搜索：

```bash
time taskset -c 2 node "$B/cc_rg_tool.mjs" \
  --pattern "def _fixtures" \
  --path "$B/fixtures/pytest/_pytest" \
  --glob "*.py" \
  --output-mode content
```

返回匹配文件，按 mtime 排序并保留前 10 项：

```bash
time taskset -c 2 node "$B/cc_rg_tool.mjs" \
  --pattern FormSet \
  --path "$B/fixtures/django/forms" \
  --glob "*.py" \
  --output-mode files_with_matches \
  --head-limit 10
```

加 `--print-rg-command` 可在标准错误中打印实际展开的底层 `rg` 命令；加 `--json` 可查看结构化结果。

### 只测底层 rg

如果只分析搜索引擎本体，不计 Node、子进程创建和 CC 结果整理，可直接运行 `rg`：

```bash
RG_COMMON=(
  --hidden --with-filename
  --glob '!.git' --glob '!.svn' --glob '!.hg'
  --glob '!.bzr' --glob '!.jj' --glob '!.sl'
  --max-columns 500
)

time taskset -c 2 rg "${RG_COMMON[@]}" -n \
  "nonfield" "$B/fixtures/django/forms/forms.py"

time taskset -c 2 rg "${RG_COMMON[@]}" -n -A 20 --glob '*.py' \
  "def showfixtures" "$B/fixtures/pytest/_pytest/python.py"

time taskset -c 2 rg "${RG_COMMON[@]}" -n --glob '*.py' \
  "def _fixtures" "$B/fixtures/pytest/_pytest"

time taskset -c 2 rg "${RG_COMMON[@]}" -l --glob '*.py' \
  "FormSet" "$B/fixtures/django/forms"
```

最后一条原生 `rg -l` 不包含 CC wrapper 的 `stat + mtime sort + head_limit` 后处理。

## perf 示例

GNU grep：

```bash
sudo perf stat -r 10 \
  -e cycles,instructions,branches,branch-misses,cache-references,cache-misses \
  -- taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"

mkdir -p "$B/perf_results"
sudo perf record -F 999 -g \
  -o "$B/perf_results/grep_single_file.data" \
  -- taskset -c 2 grep -n "nonfield" \
  "$B/fixtures/django/forms/forms.py"
```

只测底层 `rg`：

```bash
sudo perf record -F 999 -g \
  -o "$B/perf_results/rg_single_file.data" \
  -- taskset -c 2 rg "${RG_COMMON[@]}" -n \
  "nonfield" "$B/fixtures/django/forms/forms.py"
```

测完整 CC Grep 路径时，把 `perf record` 后面的命令替换为对应的 `node "$B/cc_rg_tool.mjs" ...`。

## Read/Write/Edit 批量运行

批量 runner 只运行 CC `Read / Write / Edit`：

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

结果写入 `results/YYYYMMDD_HHMMSS/`，包含 `results.csv`、`results.json`、首轮输出和独立工作目录。

## 计时边界

- CC `Read`：文件读取、范围选择、mtime-backed 状态更新和行号格式化。
- CC `Write`：创建父目录、全内容写入、`fsync` 和状态更新。
- CC `Edit`：计时包含全文件重读、陈旧检查、唯一匹配、patch/确认片段生成、全文件重写、`fsync` 和状态更新；批量模式的 prior Read 在计时外。
- GNU `grep`：单命令只统计真实 `grep`；pipeline 同时包含 `find/xargs/grep/head`。
- CC `Grep`：包含 Node 工具逻辑、`rg` 子进程及结果后处理；原生 `rg` 命令只测搜索引擎本体。

## 附录：输入来源与重新生成

当前 `fixtures/` 和 `payloads/` 是从两条公开 SWE-bench 用例的已完成轨迹及其固定环境中抽取出的快照。它们现在是普通仓库文件，日常运行与 Docker image 没有关系。

只有在更换原始用例或重建输入时，才需要 `extract_from_swe.py`：向它提供对应 trajectory，并让本机具备原始 benchmark 环境，它会重新抽取源码子树、payload、manifest 和校验文件。这里属于来源审计与重建路径，不属于 microbench 的执行流程。

- `provenance/selected_actions.json`：仅保留选中 action 的摘要和索引。
- `source_audit.json`：记录 CC 工具源码版本、哈希和本实现覆盖的核心路径。
- `manifest.json`：记录冻结输入、用例和两类搜索命令。
