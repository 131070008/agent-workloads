# SWE Golden Replay 跨平台复现手册

本目录记录 `agent -> zuchongzhi -> shenkuo` 横向性能实验的可复现流程。目标是在一台新的 Ubuntu 22.04 x86_64 服务器上恢复同一套 benchmark、30 条 Flash Golden trajectory 和 30 个 SWE 镜像，然后执行 K=1、K=16 两组无 LLM 等待回放。

## 固定测试口径

- mini-SWE-agent：2.4.4。
- Case：同一组 30 条 Flash Golden trajectory，每条只重复一次。
- K=1：串行运行 30 个 case。
- K=16：最多 16 个 case 并发。
- Agent 与 Sandbox：均限制在 CPU0-7，由 Linux 调度器在 8 个逻辑 CPU 内调度。
- LLM/API 等待：`delay_scale=0`，只回放已经记录的 ToolCall。
- 网络：容器 `--network=none`。
- 容器资源：16 GiB memory、4096 PIDs。
- 采集结果：每个 case 的 container start、Agent control gap、ToolCall、result capture、container teardown 和端到端时延。

这套测试用于比较 CPU 执行与并发承载能力，不代表带在线 LLM 延迟的用户端到端体验。

## 目录约定

目标服务器默认使用以下路径：

```text
/home/higon/cunzhe/
├── agent-workloads/
│   ├── .venv-swe/
│   └── SWE-bench/
├── swe_flat_bundle_20260727/
│   ├── images/
│   ├── manifest.json
│   └── load_flat_bundle.py
└── swe_runs/
    ├── golden_replay/flash/
    └── golden_lifecycle_30_<host>_<timestamp>/
```

可以通过 `CUNZHE_ROOT` 覆盖 `/home/higon/cunzhe`，但现有 runner 内有该绝对路径，因此正式横向对比仍建议保持默认目录。

## 1. 从已有服务器传输数据

如果目标服务器只能从源服务器访问，可以从本地使用 Agent Forwarding 登录源服务器：

```bash
ssh -A <源服务器SSH别名>
ssh-add -l
ssh <目标服务器SSH别名> hostname
```

这会临时转发本地 SSH Agent，不需要把私钥复制到源服务器。确认源服务器能够登录目标服务器后，在已经保存完整数据的源服务器执行：

```bash
./00_transfer_data_between_servers.sh <目标服务器SSH别名>
```

脚本使用 `rsync --partial --append-verify`，连接中断后重新执行即可继续。它不会传输密码、API Key 或 `.secrets`。

脚本按 Ubuntu 服务器上的 rsync 3.x 编写。若从 macOS 自带的旧版 rsync 手工回传结果，将 `--info=progress2` 换成 `--progress --stats`。

传输内容：

1. `swe_flat_bundle_20260727`：约 41 GiB，30 个压缩 rootfs。
2. `agent-workloads`：benchmark、runner 和 Linux `.venv-swe`。
3. `swe_runs/golden_replay/flash`：30 条 Golden trajectory。

## 2. 安装与源服务器一致的 Docker

登录目标服务器后执行：

```bash
./01_install_docker_ubuntu22.sh
```

脚本安装并锁定：

```text
docker.io  29.1.3-0ubuntu3~22.04.2
containerd 2.2.1-0ubuntu1~22.04.2
runc       1.3.4-0ubuntu1~22.04.1
```

安装完成后退出并重新登录，使 `docker` 用户组生效。验证时不应使用 sudo：

```bash
id
docker version
docker info
```

预期为 Docker 29.1.3、`overlayfs` storage driver、systemd cgroup driver 和 cgroup v2。

## 3. 恢复并审计 30 个镜像

```bash
./02_restore_and_audit_images.sh
```

默认 4 路并行，先校验每个 rootfs 的 SHA256，再导入镜像。若压缩包已经完成独立 SHA256 审计，可以跳过重复哈希计算：

```bash
SKIP_ARCHIVE_HASH=1 ./02_restore_and_audit_images.sh
```

导入后的镜像是内容等价的单层 flat-rootfs，镜像 ID 和原始多层镜像不同。脚本最后会逐个启动离线容器，检查 `/testbed` 和 Python，成功标志为：

```text
VERIFIED 30 runnable images
```

## 4. 正式运行前审计

```bash
./03_validate_golden_environment.sh
```

它检查主机拓扑、CPU0-7、Docker、30 条 trajectory、30 个镜像、mini-SWE-agent 版本以及关键 runner 的 SHA256。若 runner 哈希发生变化，应先确认变更内容，不能直接与既有平台结果横向比较。

## 5. 执行 K=1/K=16

建议在 `tmux` 中前台运行，日志最直观：

```bash
./04_run_golden_k1_k16.sh
```

也可以安全地放到后台：

```bash
nohup ./04_run_golden_k1_k16.sh > run_launcher.log 2>&1 &
echo $!
```

脚本会打印 `OUTPUT_ROOT=...`。检查状态：

```bash
tail -f <OUTPUT_ROOT>/controller.log
cat <OUTPUT_ROOT>/controller_returncode.txt
```

成功条件：

- `controller_returncode.txt` 为 `0`。
- `k1/performance_summary.json` 与 `k16/performance_summary.json` 均存在。
- 两组各包含 30 个 case，semantic validation 为 30/30。
- 结束后 `docker ps` 为空。

## 6. 打包并取回结果

```bash
./05_package_results.sh <OUTPUT_ROOT>
```

脚本生成 `.tar.zst` 和对应 `.sha256`。随后在能够连接服务器的机器上执行：

```bash
rsync -a --partial --append-verify \
  <服务器SSH别名>:<结果包.tar.zst> \
  ./experiment_results/
```

## 7. 生成三平台横向对比

把三台服务器的完整结果目录取回同一台分析机后执行：

```bash
python3 analyze_three_platforms.py \
  --agent-run /path/to/agent/run \
  --zuchongzhi-run /path/to/zuchongzhi/run \
  --shenkuo-run /path/to/shenkuo/run \
  --output-dir /path/to/comparison/output
```

分析器强制检查三平台的 30 个 `instance_id` 和每条 case 的 `step_count` 完全一致，随后输出逐 case 绝对值、三组成对比值、阶段聚合、K16/K1 扩展性、JSON 汇总和中文 Markdown 报告。

## 关键可比性说明

- `zuchongzhi` 与 `shenkuo` 使用同一份 flat-rootfs 包，镜像布局一致，可直接比较 Hygon 7490 与 7480。
- `agent` 的历史基线使用原始多层镜像；其 container start/storage 指标会混入镜像层布局差异，不应全部归因于 CPU。
- ToolCall、service E2E、同 case 的 K=16/K=1 放大倍数，是三平台更稳妥的主要比较指标。
- 正式运行前应确认目标 CPU0-7 没有其他明显负载，且没有残留容器。

## 本次成功执行记录

- 目标平台：`shenkuo`，Hygon C86-4G OPN 7480，4S、32C/S、SMT2、8 NUMA，503 GiB memory。
- Docker：29.1.3，containerd 2.2.1，runc 1.3.4，overlayfs，systemd cgroup driver，cgroup v2。
- 镜像恢复：30/30，错误 0，最终 `VERIFIED 30 runnable images`。
- 环境审计：trajectory 30、image 30、runner SHA256 全部通过，mini-SWE-agent 2.4.4。
- 正式结果：`/home/higon/cunzhe/swe_runs/golden_lifecycle_30_shenkuo_20260728_041926`。
- K=1：30/30，958.572 秒，0.03130 case/s，CPU0-7 平均利用率 17.81%。
- K=16：30/30，249.029 秒，0.12047 case/s，CPU0-7 平均利用率 60.02%。
- 测试结束：controller return code 0，`docker ps` 为空，本地与远端结果聚合 SHA256 一致。
