# Coding Agent ToolCall 微基准

本目录提供 Claude Code `Read / Write / Edit` 核心路径与轨迹原始 GNU `grep` 微基准，主入口为 [`claude_code_minimal/`](./claude_code_minimal/)。

## 口径

- 文件工具行为依据 Claude Code 2.1.88 的 `FileReadTool`、`FileWriteTool` 和 `FileEditTool` 源码。
- 搜索用例直接执行 Golden trajectory 中的 GNU `grep` 命令，不替换为其他搜索工具。
- Golden trajectory 只用于选择真实文件、搜索参数和编辑 payload。
- SWE-bench Docker image 只用于提供固定的 `/testbed` 文件内容。
- 执行时不调用 SWE-agent `edit_anthropic`，也不采用它的 `view/create/str_replace` 语义。
- 不调用 LLM，不依赖网络，适合 `time`、`perf stat`、`perf record`、PMU 和 SDE 分析。

## 内容

```text
claude_code_minimal/
├── cc_file_tool.mjs       # 不经过 benchmark runner，直接执行 CC Read/Write/Edit
├── cc_tool_microbench.mjs # 批量、重复、校验和 CSV 结果
├── extract_from_swe.py    # 从轨迹和镜像提取固定输入
├── source_audit.json      # CC 源码版本与文件哈希
└── README.md              # 完整构建及直接执行命令
```

直接执行 GNU `grep`、CC 文件工具、`perf` 采集和批量测试命令均在子目录 README 中。
