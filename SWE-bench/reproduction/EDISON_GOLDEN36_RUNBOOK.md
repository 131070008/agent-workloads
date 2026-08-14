# Edison Golden36 单核回放操作手册

本文记录在 Edison 上恢复并运行 AWS SWE-agent Golden36 固定轨迹时实际遇到的问题，供后续新平台复现。正式性能数据固定使用同一套脚本、轨迹、Docker 镜像和绑核口径，不能与早期自由调度结果混用。

## 1. 固定实验口径

- 输入：AWS SWE-agent 公开提交中的 38 条固定 trajectory。
- Golden 集：排除 `psf__requests-2674` 和 `pytest-dev__pytest-11148`，最终 36 条。
- 模型：ReplayModel，不请求云端 LLM，不读取 API Key。
- 执行：36 条 case 串行，每条轨迹内的 ToolCall 按原顺序回放。
- 绑核：Host Agent 与对应 Docker 容器内全部 ToolCall 固定到同一个逻辑 CPU，默认 `CPU_CORE=2`。
- 控制面：`dockerd`、`containerd` 和内核后台线程仍由操作系统自由调度。
- 正式数据：同一平台连续运行两轮，每轮独立保存结果。
- 超时：每条 case 默认 1800 秒。

这是一套 affinity-controlled 单逻辑 CPU 测试，不是严格的整机隔离实验。正式运行前仍需保证目标 CPU、它的 SMT sibling 和整机后台负载处于可接受状态。

## 2. 目录和资产

统一使用数据盘：

```text
/data/cunzhe/
├── agent-workloads/
├── swe-agent-v1.0.0-src/
├── sweagent-v1.0.0-venv/
├── swerex-runtime-1.1.0-shared/
├── swe-tool-wheelhouse-v1.0.0/
├── swe_flat_bundle_20260727/
├── swe_flat_bundle_aws_extra8_20260812/
└── swe_runs/
    └── aws_public_traces/
        └── 20250226_sweagent_claude-3-7-sonnet-20250219/
```

Git 仓库只包含 runner 和分析脚本，不包含几十 GiB 的 Docker rootfs、trajectory 或 Linux replay runtime。新机只执行 `git pull` 不足以恢复实验环境。

## 3. 首次检查磁盘和 Docker

轨迹和压缩包保存在 `/data/cunzhe`，但导入后的镜像保存在 DockerRootDir。两者可能不在同一块盘：

```bash
sudo docker info --format 'DockerRootDir={{.DockerRootDir}}'
DOCKER_ROOT=$(sudo docker info --format '{{.DockerRootDir}}')
df -h /data/cunzhe "$DOCKER_ROOT"
sudo docker system df
```

Edison 的 DockerRootDir 曾位于 `/var/lib/docker`，即使 `/data` 空间充足，根分区仍可能不足。不要因为 bundle 放在 `/data` 就认为镜像也写入 `/data`。

确认普通用户可以访问 Docker：

```bash
docker info >/dev/null
```

若出现 `/var/run/docker.sock` 权限错误：

```bash
sudo usermod -aG docker "$USER"
```

退出 SSH 并重新登录后再次运行 `docker info`。加入 `docker` 组等价于授予较高的主机权限，只应在受控实验服务器上使用。

## 4. 更新仓库并处理 ownership

内网需要代理时：

```bash
sudo env \
  HTTP_PROXY=http://10.59.41.92:7890 \
  HTTPS_PROXY=http://10.59.41.92:7890 \
  git -C /data/cunzhe/agent-workloads pull --ff-only origin main
```

若随后普通用户执行 Git 出现：

```text
fatal: detected dubious ownership in repository
```

说明仓库由 `root` 持有，而当前 Git 命令来自 `higon`。上面的 fast-forward 已经成功，报错通常来自后续的普通用户 Git 检查。推荐把研究目录归还给实验用户：

```bash
sudo chown -R higon:higon /data/cunzhe/agent-workloads
```

如果必须维持 root ownership，只添加该单一目录为可信目录：

```bash
git config --global --add safe.directory /data/cunzhe/agent-workloads
```

核对版本：

```bash
git -C /data/cunzhe/agent-workloads rev-parse --short HEAD
```

本轮绑核脚本基线至少应包含提交 `7faf129`。

## 5. 代理的两个独立边界

### 5.1 下载与 GitHub

Edison 的 `PATH` 中曾优先命中 `/home/wangleiyu/tools/bin/curl`，该二进制在 TLS CONNECT 后发生 segmentation fault。先检查：

```bash
type -a curl
/usr/bin/curl -V
```

下载脚本固定使用 `/usr/bin/curl --http1.1 -C -`：

- `--http1.1`：规避代理链上的 HTTP/2 `PROTOCOL_ERROR`。
- `-C -`：从现有文件断点续传，避免连接中断后丢弃 GiB 级进度。
- `sudo env HTTP_PROXY=... HTTPS_PROXY=...`：显式把代理交给 sudo 命令。

### 5.2 Replay 的 localhost 通信

SWE-ReX 通过宿主机映射的 localhost 端口控制容器。若 shell 设置了 HTTP/HTTPS 代理，却没有绕过 localhost，第一条 case 会表现为容器长期存活、Agent 几乎无 CPU、结果文件不再更新。

每次运行前设置：

```bash
export NO_PROXY='localhost,127.0.0.1,::1,.hygon.cn,10.0.0.0/8,172.16.0.0/12'
export no_proxy="$NO_PROXY"
```

Docker daemon 的代理与当前 shell 代理是两个配置面。需要在线拉镜像时可用下面的命令单独验证 daemon：

```bash
sudo systemctl show docker --property=Environment --no-pager
sudo docker pull hello-world
```

Golden36 正式回放设置 `pull=never`，镜像准备完成后不依赖 Docker Hub。

## 6. 恢复数据、runtime 和镜像

已有完整数据的服务器可以跳过下载，只需确认目录存在。缺少 AWS-38 增量包时，在仓库目录执行：

```bash
cd /data/cunzhe/agent-workloads/SWE-bench/reproduction

HTTPS_PROXY=http://10.59.41.92:7890 \
DATA_ROOT=/data/cunzhe \
  ./11_download_aws38_increment.sh all
```

该脚本串行下载、断点续传、校验 SHA256，并恢复 8 个新增镜像 rootfs 和完整 38 条轨迹。

导入原有 30 个和新增 8 个 flat-rootfs：

```bash
sudo python3 /data/cunzhe/swe_flat_bundle_20260727/load_flat_bundle.py \
  --bundle-dir /data/cunzhe/swe_flat_bundle_20260727

sudo python3 /data/cunzhe/swe_flat_bundle_aws_extra8_20260812/load_flat_bundle.py \
  --bundle-dir /data/cunzhe/swe_flat_bundle_aws_extra8_20260812
```

`load_flat_bundle.py` 必须传 `--bundle-dir`。所谓“导入镜像”是把压缩 rootfs 交给 `docker import`，在 DockerRootDir 中建立可运行的本地镜像；它不是把文件解压到 Git 仓库，也不会自动常驻内存。

如果镜像 bundle 导入的是 `:latest`，而 AWS trajectory 请求 `:v1`，运行标签准备脚本：

```bash
DATA_ROOT=/data/cunzhe \
  /data/cunzhe/agent-workloads/SWE-bench/reproduction/19_prepare_golden36_image_tags.sh
```

该脚本只为内容相同且已存在的 `:latest` 镜像增加 trajectory 要求的标签，不复制镜像层。成功标志为 `missing=0`。

runtime 包恢复后应存在：

```bash
ls -ld \
  /data/cunzhe/swe-agent-v1.0.0-src \
  /data/cunzhe/sweagent-v1.0.0-venv \
  /data/cunzhe/swerex-runtime-1.1.0-shared \
  /data/cunzhe/swe-tool-wheelhouse-v1.0.0
```

## 7. 准备结果目录并做统一校验

不要用 root 执行正式 benchmark。先修复结果目录权限：

```bash
sudo mkdir -p /data/cunzhe/swe_runs
sudo chown -R higon:higon /data/cunzhe/swe_runs
```

执行统一 validator：

```bash
cd /data/cunzhe/agent-workloads

DATA_ROOT=/data/cunzhe \
  SWE-bench/reproduction/15_validate_aws36_golden.sh
```

只有看到以下内容才进入测试：

```text
GOLDEN36_CASES=36
GOLDEN36_TRAJECTORIES=36
GOLDEN36_IMAGES=36
VALIDATION=PASS
```

常见输出含义：

- `MISSING_DIR`：Linux replay runtime 没有解压到约定目录。
- `MISSING_TRAJECTORIES`：AWS trajectory 包没有恢复完整或目录层级不对。
- `MISSING_IMAGES`：镜像未导入，或本地只有 `:latest` 而 trajectory 请求 `:v1`。
- `docker info` 权限错误：当前用户尚未获得 Docker socket 权限。

## 8. 清理旧任务和批次锁

正式启动前检查：

```bash
pgrep -af 'aws36|aws38|lifecycle_timing_probe.py|run-replay'
docker ps --format 'table {{.ID}}\t{{.Status}}\t{{.Names}}\t{{.Image}}'
sudo fuser -v /data/cunzhe/swe_runs/.aws38_timed_full.lock
```

若新任务报告 `Another AWS-38 timed batch is already running`，说明另一个进程仍持有 flock。锁文件本身不是问题，不要直接删除锁文件；应确认旧 PID，先发送 `TERM`，等待它退出：

```bash
kill -TERM <旧批次PID>
```

如旧批次异常退出后仍有带本实验标签的容器，再检查并逐个停止：

```bash
docker ps --filter label=com.hygon.swe-golden-run \
  --format '{{.ID}} {{.Names}} {{.Status}}'
```

不要使用不带过滤条件的批量 Docker 清理命令，避免影响同机其他用户。

## 9. 选择并检查单逻辑 CPU

当前 Golden 基线使用逻辑 CPU 2：

```bash
CPU_CORE=2
lscpu -e=CPU,CORE,SOCKET,NODE,ONLINE
cat /sys/devices/system/cpu/cpu${CPU_CORE}/topology/thread_siblings_list
```

确认 CPU 2 及其 SMT sibling 没有其他明显负载。若安装了 `sysstat`：

```bash
mpstat -P 2,194 1 5
```

其中 `194` 只是示例，必须替换为当前机器 `thread_siblings_list` 显示的 sibling。跨平台比较时保持相同规则：使用一个空闲的普通逻辑 CPU，不把不同平台的数据分别改成“整物理核”和“单 SMT thread”。

## 10. 单条冒烟并核对绑核

```bash
cd /data/cunzhe/agent-workloads

DATA_ROOT=/data/cunzhe \
CPU_CORE=2 \
CASE_IDS=astropy__astropy-14995 \
NO_PROXY="$NO_PROXY" \
no_proxy="$no_proxy" \
  SWE-bench/reproduction/17_run_aws36_golden_single_cpu.sh
```

冒烟成功应满足：

```text
cases=1
pass=1
incomplete=0
fail=0
```

运行期间可在另一终端核对 Host Agent 与容器：

```bash
PID=$(pgrep -n -f 'lifecycle_timing_probe.py run-replay')
taskset -pc "$PID"

CID=$(docker ps -q --filter label=com.hygon.swe-golden-run | head -1)
docker inspect "$CID" --format 'Cpuset={{.HostConfig.CpusetCpus}}'
```

两者都应显示 CPU 2。容器不是“一个运行在 CPU 2 上的 Docker daemon”；真正被 cpuset 限制的是容器 cgroup 中的 init、bash、Python、Git、pytest 等全部进程。

## 11. 正式运行双轮 Golden36

冒烟通过后后台运行：

```bash
nohup env \
  DATA_ROOT=/data/cunzhe \
  CPU_CORE=2 \
  ROUNDS=2 \
  CASE_TIMEOUT_SECONDS=1800 \
  NO_PROXY="$NO_PROXY" \
  no_proxy="$no_proxy" \
  /data/cunzhe/agent-workloads/SWE-bench/reproduction/18_run_aws36_golden_single_cpu_twice.sh \
  > /data/cunzhe/swe_runs/golden36_single_cpu_twice.log \
  2>&1 < /dev/null &

echo $!
```

不要在这条命令前加 `sudo`。脚本使用绝对 runtime 路径，不需要 API Key；以普通实验用户运行可以避免结果文件、Git ownership 和 root 环境混杂。

查看进度：

```bash
tail -f /data/cunzhe/swe_runs/golden36_single_cpu_twice.log
```

定位本次结果：

```bash
SERIES=$(ls -dt /data/cunzhe/swe_runs/aws36_golden_single_cpu2_twice_* | head -1)
echo "$SERIES"
cat "$SERIES/rounds.tsv"
tail -f "$SERIES/round1/batch.log"
```

每个 case 的默认最长时间是 1800 秒；单条超时后脚本会终止该 case、清理带本轮 label 的容器并继续后续 case。

## 12. Golden 验收

两轮完成后：

```bash
cat "$SERIES/round1/final_summary.txt"
cat "$SERIES/round2/final_summary.txt"
```

两轮都应满足：

```text
cases=36
pass=36
incomplete=0
fail=0
```

主要结果文件：

- `rounds.tsv`：两轮状态、起止时间和结果目录。
- `roundN/status.tsv`：逐 case PASS/INCOMPLETE/FAIL 与轨迹完整性。
- `roundN/case_phases.csv`：逐 case 生命周期阶段时延。
- `roundN/tool_calls.csv`：每次 ToolCall 的命令、类别与时延。
- `roundN/category_summary.csv`：ToolCall 分类聚合。
- `roundN/run_info.tsv`：主机、时间、`swe_cpuset` 与超时口径。
- `roundN/final_summary.txt`：本轮最终通过统计。

检查没有残留实验容器：

```bash
docker ps --filter label=com.hygon.swe-golden-run \
  --format '{{.ID}} {{.Names}} {{.Status}}'
```

## 13. 常见故障速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `dubious ownership` | sudo 更新后仓库属主与当前用户不同 | `chown` 给实验用户，或仅将该目录加入 `safe.directory` |
| launcher 日志 `Permission denied` | `/data/cunzhe/swe_runs` 由 root 持有 | 创建目录并 `chown` 给 `higon`，不要 sudo 跑 benchmark |
| 第一条 case 容器长期 Up | localhost 请求被 HTTP 代理接管 | 同时设置大写和小写 `NO_PROXY/no_proxy`，至少包含 localhost/127.0.0.1 |
| `MISSING_IMAGES ...:v1` | bundle 导入的是 `:latest` | 运行 `19_prepare_golden36_image_tags.sh` |
| `load_flat_bundle.py` 缺参数 | loader 要求显式 bundle 路径 | 增加 `--bundle-dir <目录>` |
| curl CONNECT 后 segfault | PATH 命中非系统 curl | 使用 `/usr/bin/curl` |
| HTTP/2 `PROTOCOL_ERROR` | 代理链 HTTP/2 不稳定 | 使用 `--http1.1 -C -` 串行断点下载 |
| `Another AWS-38 timed batch` | 旧进程仍持有 flock | 用 `fuser/pgrep` 找 PID，正常终止旧批次，不直接删锁文件 |
| `docker.sock permission denied` | 当前用户不在 docker 组 | 加入 docker 组并重新登录 |
| `/data` 有空间但导入失败 | DockerRootDir 所在根分区不足 | 同时检查 `/data` 与 DockerRootDir |

## 14. 可比性约束

以下任一项变化后，不应直接与当前单核 Golden 混算：

- 从固定 CPU 改回自由调度，或更换 cpuset 范围。
- Host Agent 与 Sandbox 不再使用同一个逻辑 CPU。
- 改变 Docker 镜像内容、trajectory、SWE-agent runtime 或 Python 环境。
- 从串行 36 条改成多 case 并发。
- 开启在线 LLM/API 等待。
- SMT sibling 有持续竞争，或服务器存在明显的其他用户负载。

早期自由调度实验与本轮绑核实验的平台排序一致，但差距幅度发生变化，因此当前双轮单逻辑 CPU 数据应作为新的跨平台 Golden 基线。

