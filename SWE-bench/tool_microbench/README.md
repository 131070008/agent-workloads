# Coding Agent ToolCall 微基准

主入口为 [`claude_code_minimal/`](./claude_code_minimal/)。该目录已经包含固定输入，可在普通 Linux 环境直接运行：

- Claude Code 语义的 `Read / Write / Edit` 核心路径。
- Golden trajectory 中实际使用的 GNU `grep` 命令。
- 可选的 Claude Code `Grep / ripgrep` 路径及原生 `rg` 对照命令。

执行不调用 LLM，不依赖网络或 Docker，适合 `time`、`perf stat`、`perf record`、PMU 和 SDE。冻结输入的来源与重建方式只放在子目录 README 附录中。

```text
claude_code_minimal/
├── cc_file_tool.mjs       # 直接执行 CC Read/Write/Edit
├── cc_rg_tool.mjs         # 直接执行 CC Grep，内部调用 rg
├── cc_tool_microbench.mjs # Read/Write/Edit 批量测试
├── fixtures/              # 已冻结的真实源码输入
├── payloads/              # Write/Edit 输入
├── manifest.json          # 用例和命令清单
└── README.md              # 直接执行与 perf 命令
```

GNU `grep` 与 CC `Grep/rg` 是两套独立口径，完整命令及计时边界见子目录 README。
