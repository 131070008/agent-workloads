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

## 8. 发布到私有 GitHub Release

镜像包约 41 GiB，不应提交进 Git 历史。GitHub Release 的单个附件必须小于 2 GiB，因此先把完整目录流式切成 1900 MiB 分卷：

```bash
./06_prepare_github_release_assets.sh \
  /path/to/swe_flat_bundle_20260727 \
  /path/to/swe_flat_bundle_20260727_release
```

脚本生成分卷、`SHA256SUMS` 和 `RESTORE.txt`，并验证拼接后的 tar 数据流可以读取。完成 GitHub CLI 授权后逐文件上传：

```bash
./07_upload_github_release_assets.sh \
  /path/to/swe_flat_bundle_20260727_release
```

上传脚本默认发布到私有仓库 `131070008/agent-workloads` 的 `swe-images-20260727` Release。脚本会跳过已经成功上传的同名附件，网络中断后重新执行即可继续。

下载全部附件并校验后，恢复原目录：

```bash
shasum -a 256 -c SHA256SUMS
cat swe_flat_bundle_20260727.tar.part.* | tar -xf -
```

### AWS-38 增量镜像与公开轨迹

新增 8 个 flat-rootfs 镜像和完整 38 条 AWS SWE-agent 轨迹位于 Release
`swe-aws38-20260812`。它不重复包含原有 30 个镜像。在空间较大的内网数据盘执行：

```bash
DATA_ROOT=/data/cunzhe \
  ./11_download_aws38_increment.sh all
```

脚本串行下载，固定使用 `/usr/bin/curl --http1.1 -C -`。网络中断后重新运行同一命令，
会跳过 `.done` 文件并从未完成文件的现有字节继续；恢复前会校验全部 SHA256。

若要分阶段执行：

```bash
./11_download_aws38_increment.sh download
./11_download_aws38_increment.sh verify
./11_download_aws38_increment.sh restore
```

恢复后加载新增 8 个镜像：

```bash
sudo python3 /data/cunzhe/swe_flat_bundle_aws_extra8_20260812/load_flat_bundle.py \
  --bundle-dir /data/cunzhe/swe_flat_bundle_aws_extra8_20260812
```

### Golden36 单平台回放

CPU 平台性能对比固定使用 AWS-38 中的 36 条轨迹，排除包含外部网络访问的：

- `psf__requests-2674`
- `pytest-dev__pytest-11148`

默认数据根目录为 `/data/cunzhe`。更新仓库后先审计环境：

```bash
cd /data/cunzhe/agent-workloads
git pull --ff-only

DATA_ROOT=/data/cunzhe \
  SWE-bench/reproduction/15_validate_aws36_golden.sh
```

成功标志为 `VALIDATION=PASS`。随后前台执行一次完整 Golden36：

若要用于单核CPU平台对比，Host Agent与Docker内全部ToolCall应固定到同一个逻辑CPU。
下面的入口默认使用CPU 2；Docker daemon与containerd控制面仍由系统自由调度：

```bash
DATA_ROOT=/data/cunzhe CPU_CORE=2 \
  ./17_run_aws36_golden_single_cpu.sh
```

正式Golden数据运行两轮，并为每轮建立独立结果目录：

```bash
nohup env DATA_ROOT=/data/cunzhe CPU_CORE=2 ROUNDS=2 \
  ./18_run_aws36_golden_single_cpu_twice.sh \
  > /data/cunzhe/swe_runs/golden36_single_cpu_twice.log 2>&1 < /dev/null &
```

两轮均通过后，将第一轮整理为正式 Golden 数据；第二轮只用于复核，不参与平均：

```bash
SERIES=$(ls -dt /data/cunzhe/swe_runs/aws36_golden_single_cpu2_twice_* | head -1)
python3 ./20_extract_aws36_golden.py --series-dir "$SERIES"
cat "$SERIES/golden/golden_summary.txt"
```

输出目录 `$SERIES/golden/` 包含正式逐 case、逐 ToolCall、分类与阶段统计 CSV，
以及校验摘要和 `SHA256SUMS`。这些数据全部来自第一轮，不包含 R1/R2 对比列。

默认每条case超时为1800秒，可通过 `CASE_TIMEOUT_SECONDS` 修改。每轮记录
`case_phases.csv`、`tool_calls.csv`、`category_summary.csv`、`status.tsv` 和
`run_info.tsv`；后者包含实际 `swe_cpuset`。运行前应确认目标逻辑CPU及其SMT兄弟线程空闲。

```bash
DATA_ROOT=/data/cunzhe \
  SWE-bench/reproduction/16_run_aws36_golden.sh
```

建议在 `tmux` 内前台运行。若放到后台：

```bash
mkdir -p /data/cunzhe/swe_runs
nohup env DATA_ROOT=/data/cunzhe \
  /data/cunzhe/agent-workloads/SWE-bench/reproduction/16_run_aws36_golden.sh \
  > /data/cunzhe/swe_runs/golden36_launcher.log 2>&1 < /dev/null &
echo $!
```

运行目录会打印为 `RUN_DIR=...`，其中主要结果为：

- `status.tsv`：每条 case 的完成状态和 ToolCall 完整性；
- `case_phases.csv`：生命周期阶段时间；
- `tool_calls.csv`：逐 ToolCall 时间、类别和命令；
- `category_summary.csv`：ToolCall 分类聚合；
- `final_summary.txt`：36 条最终通过统计。

这套回放不读取云端 API Key，不调用 LLM；所有动作来自固定 trajectory。

Edison 上从代理下载、镜像导入、runtime 恢复、权限修复、绑核冒烟到正式双轮运行的完整流程，见
[`EDISON_GOLDEN36_RUNBOOK.md`](EDISON_GOLDEN36_RUNBOOK.md)。

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
