# Speakbox

短文本语音合成的网页小工具（MVP）。浏览器输入 ≤100 字 + 选音色 → 服务器排队 → 本地 Mac worker 合成 → 网页下载 WAV，全程 SSE 实时进度。

- **服务端**：Go 单文件静态二进制（CGO-free，web 经 `go:embed`，零运行时依赖）。源码在 `server/`。
- **Worker**：本地 Mac 常驻 Python 进程，复用 `tts/` 的 CosyVoice 模型 + `speak.py` 句尾修复。源码在 `worker/`。
- **部署**：单台腾讯云 `124.220.6.174:8200`。完整步骤见 [DEPLOY.md](./DEPLOY.md)。

## 产品流程（一句话）

浏览器提交（≤100 字 + 音色）→ `POST /api/tasks` 入**内存队列** → 本地 worker `GET /api/worker/next` 领任务 → 本地合成（reuse `tts/speak.py` 句尾修复）→ `POST` 回 WAV → 标记 `done` → 网页下载；任务进度经 **SSE** 实时推到浏览器。

```
浏览器 ──POST /api/tasks──▶ 服务器(内存队列) ◀──GET /api/worker/next── 本地 Mac worker
   ▲                                │                                      │
   └────── GET /api/events (SSE) ───┘                            本地合成(CosyVoice)
   │                                ▲                                      │
   └──── GET /api/tasks/{id}/wav ───┴────── POST /api/worker/tasks/{id}/wav┘
```

## 音色

| key | 说明 | 模式 |
|---|---|---|
| `my_voice_zh` | 我的克隆音色 | zero_shot |
| `sweet_female_zh` | 甜美女声 | SFT 中文女 |

`GET /api/voices` 返回可用音色列表，网页下拉框据此渲染。

## API 契约

### 公开端点（无需鉴权）

| 方法 & 路径 | 说明 |
|---|---|
| `GET /` | 网页入口（embed 的单页） |
| `GET /api/voices` | 列出可用音色 |
| `POST /api/tasks` | 提交任务，body `{text, voice}`，**text ≤ 100 字** |
| `GET /api/tasks` | 列出任务（含状态/进度） |
| `GET /api/tasks/{id}/wav` | 下载合成结果 WAV |
| `GET /api/events` | SSE 实时进度流 |
| `GET /health` | 健康检查 |

### Worker 端点（需请求头 `X-Worker-Token`）

| 方法 & 路径 | 说明 |
|---|---|
| `GET /api/worker/next` | 领下一个待合成任务；**无任务返回 204** |
| `POST /api/worker/tasks/{id}/progress` | 上报合成进度（0-100） |
| `POST /api/worker/tasks/{id}/wav` | 回传合成好的 WAV |

`X-Worker-Token` 必须等于服务器 `.env` 的 `WORKER_TOKEN`，否则 worker 端点一律 401。

### 任务状态机

```
pending(待消费) ─▶ generating(生成中 progress 0-100) ─▶ uploading(上传中) ─▶ done(上传成功/可下载)
     │                      │                                  │
     └──────────────────────┴──────────────────────────────────┴──▶ failed(error，任一阶段出错)
```

## 已知边界 & TODO

MVP 取舍，明牌列出，别当成"以后忘了为什么这样"：

- **公网无鉴权**：任何拿到 URL 的人都能入队提交任务（MVP 暂时接受）。→ **TODO**：加登录/鉴权。
- **内存队列**：服务器一旦重启，**任务元数据全丢**（已落盘的 WAV 文件仍在 `/data/speakbox/wav/`，但任务列表/状态不恢复）。
- **WAV 无自动清理 / 无配额**：磁盘只增不减。→ **TODO**：手动清理 `/data/speakbox/wav/`（暂无定额/定期任务）。
- **冷启动 ~8s**：每次 worker 进程的**第 1 条**任务要等模型加载（约 8s）；worker 常驻后续任务不再付这笔，**只第 1 条付**。
- **单 worker**：同一时刻只有一个本地 Mac worker 在消费，任务串行处理，无横向扩展。

## 目录

```
speakbox/
├── README.md              # 本文件
├── DEPLOY.md              # 部署 / 运维（单服）
├── .env.example           # 服务端环境变量模板（占位，可入库）
├── deploy/
│   └── speakbox.service   # systemd unit 模板
├── server/                # Go 服务端（CGO-free，web go:embed）
│   ├── go.mod
│   └── internal/...
└── worker/                # 本地 Mac 常驻合成 worker（Python）
```

> 真实 `WORKER_TOKEN` 只存服务器 `/opt/speakbox/.env`，永不进 git（见仓库根 `.gitignore`）。
