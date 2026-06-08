# Speakbox — 部署文档（单服）

> **本服务只部署到一台机器：测试服 = 腾讯云 `124.220.6.174`（公网）。**
> 不像 LogReportSvr 那样双服同步——Speakbox 没有内网发布服、没有 VPN、没有 MCP，全部就这一台。
>
> 构建模型：**本地一次交叉编译（Mac）→ 单个静态二进制 rsync 推到这台 → 重启**。
> 项目 **CGO-free**，web 资源经 `go:embed` 打进二进制，服务器**零运行时依赖**（不需要装 Go，也不需要单独发 web 文件）。

---

## 一、总览

| 维度 | 值 |
|---|---|
| 角色 | 测试服（单台，MVP） |
| 公网 IP | `124.220.6.174` |
| 服务端口 | `8200`（⚠ 需手动开腾讯云安全组入站 TCP 8200，见下方红框） |
| Health | `http://124.220.6.174:8200/health` |
| 网页入口 | `http://124.220.6.174:8200/` |
| SSH 用户 | `ubuntu` |
| SSH 密钥 | `/Users/boom/Demo/Avalon/go_svr/sshkey/wepie_mac.pem` |
| 系统 | Ubuntu（腾讯云，sudo 可用） |
| 部署目录 | `/opt/speakbox`（bin + .env） + `/data/speakbox/wav`（WAV 产物） |
| systemd unit | `/etc/systemd/system/speakbox.service` |
| Worker | 跑在 **本地 Mac**（常驻），不部署到服务器，见第六节 |

> ### ⚠ 唯一的手动步骤：开安全组
> 部署前/后必须在 **腾讯云控制台 → 安全组 → 入站规则 → 加 TCP `8200`，来源 `0.0.0.0/0`**。
> 这是整个流程里 **唯一一步无法用脚本/SSH 自动完成** 的操作。不开 → 服务在机器内 `curl localhost:8200/health` 正常，但公网浏览器打不开。

### 端口确认（绑定前先查）

`8200` 选在已占用端口之外：`8080` = LogReport，`8090`/`8443` = MCP。绑之前确认 8200 空闲：

```bash
ssh -i /Users/boom/Demo/Avalon/go_svr/sshkey/wepie_mac.pem ubuntu@124.220.6.174 \
  "ss -ltnp | grep 8200"
```

- **无输出** = 8200 空闲，按本文档照常用 8200。
- **有输出**（被别的进程占了）= 改用 `8201`：把 `.env` 的 `ADDRESS=:8201`、安全组开 `8201`、所有 `:8200` 链接换 `:8201`，并**明确告知用户已切到 8201**。

---

## 二、构建策略：本地交叉编译，二进制推一台

本项目 **CGO-free**，可在 Mac 上直接交叉编译出 Linux 静态二进制，服务器**完全不需要装 Go**。网页（HTML/JS/CSS）通过 `go:embed` 打进二进制 → 部署只推这一个文件，**没有单独的 web 资源要同步**。

一次编译命令（产物为 `statically linked` ELF x86-64）：

```bash
cd /Users/boom/Demo/AINews/speakbox/server
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath -ldflags='-s -w' -o /tmp/speakbox ./cmd/server
file /tmp/speakbox   # 应含 "ELF 64-bit ... x86-64 ... statically linked"
```

> rsync 替换正在运行的二进制是安全的：rsync 写临时文件再 rename（原子替换），运行中的进程仍持旧 inode，`systemctl restart` 后才切到新二进制。

---

## 三、日常部署流程（一键）

> 单台，无双服同步红线。改完代码：本地交叉编译 → 推 → 重启 → 健康检查。

```bash
# ── 1. 本地一次交叉编译 ──
cd /Users/boom/Demo/AINews/speakbox/server
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath -ldflags='-s -w' -o /tmp/speakbox ./cmd/server

# ── 2. 推二进制 + 重启 + 健康检查 ──
rsync -az -e "ssh -i /Users/boom/Demo/Avalon/go_svr/sshkey/wepie_mac.pem -o StrictHostKeyChecking=no" \
  /tmp/speakbox ubuntu@124.220.6.174:/opt/speakbox/speakbox
ssh -i /Users/boom/Demo/Avalon/go_svr/sshkey/wepie_mac.pem ubuntu@124.220.6.174 \
  "sudo systemctl restart speakbox && sleep 2 && curl -s http://localhost:8200/health && echo"
```

> 改动只在 `worker/`（Mac 端 Python）时**不需要重新部署服务器**——重启本地 worker 进程即可（见第六节）。服务器只跑 Go bin。

---

## 四、服务信息

### 目录结构

```
/opt/speakbox/            # 项目根（ubuntu 用户所有）
├── .env                  # 配置文件（见下，不进 git）
└── speakbox              # 部署的二进制（由本地交叉编译推送，web 已 embed）
/data/speakbox/
└── wav/                  # WAV 产物，每任务一个 <id>.wav
```

### 环境变量（`/opt/speakbox/.env`）

```bash
ADDRESS=:8200
DATA_DIR=/data/speakbox
WORKER_TOKEN=<openssl rand -hex 32 生成；只留服务器，永不进 git>
```

- `ADDRESS`：监听地址。8200 被占则改 `:8201`（见第一节端口确认）。
- `DATA_DIR`：数据根目录，WAV 落盘到 `<DATA_DIR>/wav/<id>.wav`。
- `WORKER_TOKEN`：保护 `/api/worker/*`（worker 请求头 `X-Worker-Token` 必须匹配）。**空值 = 所有 worker 端点 401**，任务永远卡在 `pending`。模板见仓库 `speakbox/.env.example`。

### systemd（`/etc/systemd/system/speakbox.service`）

模板见仓库 `speakbox/deploy/speakbox.service`：

```ini
[Unit]
Description=Speakbox TTS Server
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/speakbox
EnvironmentFile=/opt/speakbox/.env
ExecStart=/opt/speakbox/speakbox
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 运维命令

```bash
sudo systemctl status speakbox       # 看运行状态
sudo systemctl restart speakbox      # 重启（部署后）
sudo journalctl -u speakbox -f       # 实时日志
curl http://localhost:8200/health    # 机器内健康检查
```

---

## 五、首次部署（新腾讯云机器）

```bash
# ── 在服务器上（已 ssh 进去，ubuntu 有 sudo）──
ssh -i /Users/boom/Demo/Avalon/go_svr/sshkey/wepie_mac.pem ubuntu@124.220.6.174

# 1. 建目录并改属主
sudo mkdir -p /opt/speakbox /data/speakbox/wav
sudo chown -R ubuntu:ubuntu /opt/speakbox /data/speakbox

# 2. 生成 WORKER_TOKEN 并写 .env（token 留在服务器，不进 git）
TOKEN=$(openssl rand -hex 32)
cat > /opt/speakbox/.env <<ENV
ADDRESS=:8200
DATA_DIR=/data/speakbox
WORKER_TOKEN=$TOKEN
ENV
echo "WORKER_TOKEN=$TOKEN   # 妥善保存：本地 worker 要用同一个值"

# 3. 写 systemd unit（内容见第四节 / 仓库 deploy/speakbox.service）
sudo tee /etc/systemd/system/speakbox.service > /dev/null <<'UNIT'
[Unit]
Description=Speakbox TTS Server
After=network.target
[Service]
Type=simple
User=ubuntu
WorkingDirectory=/opt/speakbox
EnvironmentFile=/opt/speakbox/.env
ExecStart=/opt/speakbox/speakbox
Restart=on-failure
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload && sudo systemctl enable speakbox

# ── 在本地 Mac：交叉编译并推二进制（见第二、三节）──
#   编译 → rsync /tmp/speakbox → ubuntu@124.220.6.174:/opt/speakbox/speakbox

# ── 回服务器：启动 + 验收 ──
sudo systemctl start speakbox
sleep 2 && curl -s http://localhost:8200/health && echo
```

> **第 4 步（唯一手动）：腾讯云控制台 → 安全组 → 入站 → 加 TCP `8200`（来源 `0.0.0.0/0`）。**
> 不开则公网打不开 `http://124.220.6.174:8200/`（机器内 `curl localhost:8200/health` 仍正常）。

部署完成后，回本地 Mac 拉起常驻 worker（第六节），用同一个 `WORKER_TOKEN`，否则网页能提交任务但永远没人合成。

---

## 六、Worker（本地 Mac，常驻）

合成发生在**本地 Mac**（复用 `tts/` 的 CosyVoice 模型 + `speak.py` 的句尾修复），服务器只做队列 + 网页 + 文件托管。Worker 是一个常驻 Python 进程，轮询服务器拿任务、本地合成、回传 WAV。

```bash
PYTHONPATH=/Users/boom/Demo/AINews \
WORKER_TOKEN=<与服务器 /opt/speakbox/.env 完全相同的值> \
SPEAKBOX_BASE_URL=http://124.220.6.174:8200 \
/Users/boom/Demo/AINews/tts/.venv/bin/python /Users/boom/Demo/AINews/speakbox/worker/worker.py
```

- `WORKER_TOKEN` 必须 **== 服务器 .env 的值**，否则 worker 调 `/api/worker/next` 一律 401。
- 模型只加载一次：**第 1 条任务约 8s 冷启动**，之后常驻内存，后续任务快。
- venv（`tts/.venv`）已含 `numpy` / `soundfile` / `requests`。
- 端口若切了 8201，`SPEAKBOX_BASE_URL` 同步改 `:8201`。

---

## 七、注意事项

- **单台部署**：只有腾讯云 `124.220.6.174` 一台，没有内网发布服、没有 wecli VPN、没有 MCP——这些都是 LogReportSvr 的概念，Speakbox 不涉及。
- **构建模型**：本地交叉编译 → 推单个静态二进制。CGO-free + web `go:embed`，服务器零运行时依赖。
- **唯一手动步骤 = 安全组开 8200**：脚本/SSH 全自动，唯独腾讯云安全组入站规则要在控制台点。
- **端口**：8200 默认；与 8080(LogReport)/8090/8443(MCP) 错开。绑前 `ss -ltnp | grep 8200` 确认空闲，被占则 8201 并告知用户。
- **WORKER_TOKEN 永不进 git**：服务器 .env 持有真实值；仓库只放 `.env.example` 占位。两边（服务器 + 本地 worker）必须用同一个值。
- **合成在本地**：服务器不跑模型 / 不装 Python。改 worker 代码只需重启本地进程，不必重新部署服务器。
- **已知边界**（公网无鉴权 / 内存队列重启丢任务元数据 / WAV 无自动清理 / 单 worker）见 `README.md` «已知边界 & TODO»。

*文档最近更新：2026-06-09（speakbox MVP 单服首版部署文档）*
