# Coding Agent ToolCall 微用例

本目录把真实 SWE-agent 轨迹中的搜索和文件操作抽成可在普通 Linux 主机上独立运行的微用例，供 `perf`、PMU、SDE 和跨平台性能分析使用。它不是人工构造的算法 benchmark：命令、参数、输入文件和编辑 payload 均来自既有 Golden trajectory。

## 数据口径

- 轨迹框架：SWE-agent 1.0.0。
- Sandbox 控制：SWE-ReX 1.1.0 + Docker。
- 轨迹使用的模型：Claude 3.7 Sonnet。
- 重要边界：这是“Claude 模型生成动作、SWE-agent 执行动作”，不是 Claude Code 轨迹。
- 原始 36 条轨迹中共有 224 条含 `grep` 的 ToolCall，没有 `rg`。因此本批只保留真实 `grep`；后续若增加 `rg`，必须标成等价对照，不得称为原始轨迹。

## 用例选择

| ID | 类型 | 原始轨迹位置 | 主要行为 |
|---|---|---|---|
| `grep_single_file` | 单文件搜索 | `django-14608 #14` | `grep -n` |
| `grep_context` | 单文件上下文 | `pytest-5221 #9` | `grep -n -A 20` |
| `grep_recursive_include` | 递归内容搜索 | `pytest-5221 #3` | `grep -r --include` |
| `grep_generated_output` | 生成输出过滤 | `pytest-5221 #2` | `pytest --help \| grep -A`；上游输出预先物化 |
| `grep_find_xargs` | 文件发现后内容搜索 | `django-14608 #5` | `find \| xargs grep \| grep \| head` |
| `grep_path_filter` | 路径流过滤 | `django-14608 #4` | `find \| grep \| grep`；不读取文件内容 |
| `editor_view_full` | 完整读取 | `django-14608 #12` | 小文件完整读取、编号和输出 |
| `editor_view_range` | 范围读取 | `django-14608 #9` | 指定行范围读取、编号和输出 |
| `editor_create` | 新建文件 | `django-14608 #16` | 写入完整复现脚本 |
| `editor_replace` | 精确编辑 | `django-14608 #18` | 全文件读取、唯一性检查、全文件重写和片段回显 |

`editor_view_full` 特意选择低于 16 KB 的文件，不触发 SWE-agent 的 file-map/tree-sitter 分支；这样可以先把基础 Read 路径分离出来。大文件 file-map 可作为后续独立用例。

## 1. 在有镜像的服务器提取

```bash
python3 extract_microcases.py \
  --trajectory 'pytest-dev__pytest-5221=/path/pytest-dev__pytest-5221.local.traj' \
  --trajectory 'django__django-14608=/path/django__django-14608.local.traj' \
  --editor-source /home/higon/cunzhe/swe-agent-v1.0.0-src/tools/edit_anthropic \
  --registry-source /home/higon/cunzhe/swe-agent-v1.0.0-src/tools/registry/lib \
  --output-dir /home/higon/cunzhe/coding_agent_tool_microbench_YYYYMMDD
```

构建器会：

1. 校验所选 action 的类型与索引；
2. 从两个固定 Docker image 中复制原始 `/testbed`；
3. 物化 `pytest --help`，使 pipeline grep 可以脱离 pytest 运行；
4. 复制 SWE-agent 的 `edit_anthropic` 实现与 registry 依赖；
5. 保存 image inspect、原始 action/observation 和全包 SHA256。

## 2. 脱离 Docker 运行

列出用例：

```bash
python3 run_microcases.py --bundle-dir /path/to/bundle --list
```

全部单次运行：

```bash
python3 run_microcases.py --bundle-dir /path/to/bundle
```

只跑 grep，并绑定 CPU2：

```bash
python3 run_microcases.py \
  --bundle-dir /path/to/bundle \
  --family grep \
  --cpu 2 \
  --repeat 10
```

只跑唯一字符串替换：

```bash
python3 run_microcases.py \
  --bundle-dir /path/to/bundle \
  --case editor_replace \
  --cpu 2
```

每次编辑均在新的工作目录中复制输入，`create/replace` 不会污染共享 fixture。输出包含逐次 stdout/stderr、实际命令、`results.csv`、wall/user/system 时间和与原轨迹 observation 的语义校验。

GNU grep 用返回码 `1` 表示“没有匹配”，不表示工具执行失败。校验器仅在原轨迹 observation 同样为空时接受该返回码；返回码大于 `1` 仍记为错误。本批的 `grep_recursive_include` 和 `grep_path_filter` 正是两条真实 no-match 轨迹。

## Claude Code 工具边界

Claude Code 确实对模型暴露 `Read`、`Write`、`Edit` 等工具，但 Claude Code 主程序仓库并未提供这些核心工具的可复现实现在本 benchmark 中直接编译替换。这里采用两条合法路径：

1. 当前微用例严格复用轨迹实际使用的 SWE-agent `edit_anthropic`；它的源码注释说明改编自 Anthropic Text Editor。
2. 若要建立更接近 Anthropic 当前 text-editor API 的对照实现，使用 Anthropic 官方 [`claude-quickstarts` 编辑器实现](https://github.com/anthropics/claude-quickstarts/blob/main/computer-use-demo/computer_use_demo/tools/edit.py)；该仓库采用 [MIT License](https://github.com/anthropics/claude-quickstarts/blob/main/LICENSE)。

Claude Code 的公开仓库是 [`anthropics/claude-code`](https://github.com/anthropics/claude-code)，但其 [LICENSE](https://github.com/anthropics/claude-code/blob/main/LICENSE.md) 是 Anthropic 保留权利并受商业条款约束，不应把“仓库公开可见”误写成“Claude Code 核心工具已开源”。

泄漏的 Claude Code 私有源码不作为实验依赖：来源、版本、完整性和许可都不可审计，也无法形成可公开复现的性能口径。

## Claude Code 核心路径最小微基准

[`claude_code_minimal/`](./claude_code_minimal/) 根据 Claude Code 2.1.88 的 `Read / Write / Edit / Grep` 核心工具行为，结合本批 Golden trajectory 的真实参数与 SWE-bench image 文件，提供了独立可执行的 8 条微基准。它不复制完整 Claude Code 程序，也不依赖 LLM；源码核对哈希、镜像摘要、轨迹 action、fixture SHA256、提取与运行命令均随 bundle 保存。
