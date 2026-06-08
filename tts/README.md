# AINews TTS 层

把每日 AI 新闻「报纸版 HTML」转成中文播报稿，再合成语音。**provider 可插拔**：默认
CosyVoice2（甜美女声），未安装时自动 fallback 到 macOS `say`（婷婷），保证流程和样例音频
随时跑得通。业务代码只依赖 `tts_service` / `providers/base`，**不写死任何具体 TTS 引擎**。

## 目录结构

```
tts/
├── __init__.py
├── tts_service.py            # 门面：解析音色 profile / 选 provider / fallback 链（业务只调它）
├── scriptgen.py              # 报纸 HTML（或 JSON）-> 播报稿 .txt（纯文本，去标签/URL/占位符）
├── config.json               # 音色 profile + provider 配置（default/fallback、模型路径、参考音）
├── requirements-cosyvoice.txt     # CosyVoice 依赖清单（人读版，装进隔离 venv）
├── requirements-cosyvoice.lock.txt# 冻结的精确可用版本（pip freeze，含 transformers==4.51.3）
├── install_cosyvoice.sh      # 一键安装 CosyVoice2 到 tts/.venv（不污染系统）
├── README.md
├── providers/
│   ├── __init__.py           # 注册表 PROVIDERS + get_provider()
│   ├── base.py               # 抽象接口：TTSProvider / TTSRequest / TTSResult（业务唯一依赖面）
│   ├── cosyvoice.py          # 默认 provider：CosyVoice2（懒加载，没装也不会 import 失败）
│   └── macsay.py             # fallback provider：macOS `say`（零依赖）
├── samples/                  # 生成的播报稿 .txt + 音频 .wav/.mp3
├── assets/                   # 参考音 ref_sweet_female_zh.wav（安装脚本生成；git 忽略）
├── vendor/CosyVoice/         # 克隆的 CosyVoice 仓库（git 忽略）
├── models/CosyVoice2-0.5B/   # 下载的权重（git 忽略）
└── .venv/                    # 隔离的 Python3.10 venv（git 忽略）
```

## 设计

- **依赖倒置**：pipeline / 业务代码只 import `tts.tts_service` 或 `tts.providers.base` 的
  `TTSProvider/TTSRequest/TTSResult`。绝不直接 import `cosyvoice`、`torch`。
- **CosyVoice 不写死**：`cosyvoice.py` 对 `cosyvoice`/`torch` 全部**懒加载**，所以即便没装，
  `import tts.providers` 也不会炸；`is_available()` 只是返回 `(False, 原因)`。
- **永不抛异常**：`synthesize()` 失败返回 `TTSResult(status="error"/"unavailable", error=...)`，
  不会让定时任务挂掉。
- **换引擎 = 加文件**：新增一个 provider 只需在 `providers/` 写一个实现 `TTSProvider` 的文件，
  在 `providers/__init__.py` 的 `PROVIDERS` 注册，再在 `config.json` 加一项 voice 配置即可，
  业务代码一行不动。

## 安装 CosyVoice（默认音色）

```bash
bash tts/install_cosyvoice.sh
```

- 在隔离 venv `tts/.venv` 里装，**不污染系统 / 全局 python**。
- 权重落到 `tts/models/CosyVoice2-0.5B`，参考音落到 `tts/assets/ref_sweet_female_zh.wav`。
- 前置：Python 3.10（系统 `python3` 是 3.9，太老，脚本用 `/opt/homebrew/bin/python3.10`）。
- 脚本可重复运行，全程日志写 `tts/install.log`。

### 精确复现（推荐）

有一份**冻结的、已验证可用**的依赖清单 `tts/requirements-cosyvoice.lock.txt`，里面是产出过
正常音频的全部确切版本（含关键的 `transformers==4.51.3`）。想一步到位、不踩版本坑：

```bash
source tts/.venv/bin/activate
pip install -r tts/requirements-cosyvoice.lock.txt
```

`install_cosyvoice.sh` 也会**优先**检测并从这个 lock 文件安装，找不到才回退到逐包安装。

> 运行时文本规范化（TN）用的是 **wetext**，不需要 OpenFst / pynini 那套编译链。`pynini` /
> `WeTextProcessing` 在 macOS 上是**可选**的（且常编译失败），跳过不影响合成 —— 详见下方故障排除。

## 故障排除（Troubleshooting）

### ① 音频过长 / 重复 / 3-4 倍时长（runaway）—— 头号坑

`transformers` 版本太新，破坏了 CosyVoice2 的 Qwen2 停止符（stop-token）处理，导致**疯狂超量生成**。

```bash
source tts/.venv/bin/activate
pip install transformers==4.51.3   # CRITICAL 必须精确锁这个版本
```

判断指标：健康时约 **0.25 秒/字**；runaway 时约 **0.64 秒/字**（明显偏长即中招）。

### ② macOS 上 `pynini` 编译失败

`pynini` 是**可选**的，运行时用的是 **wetext** 做文本规范化，可以直接跳过。播报稿
（`scriptgen.py` 产出）本身已做归一化（无 URL / 标签 / 占位符、中文标点已处理），不依赖引擎侧 TN。
`ttsfrd` 仅 Linux，同样可忽略。若坚持要装 pynini：先 `brew install openfst` 再
`pip install pynini==2.1.6`（设置好 `CPATH/LIBRARY_PATH/CFLAGS/LDFLAGS` 指向 `/opt/homebrew`）。

### ③ TorchCodec `video_tensor must be kUInt8` / float-tensor 报错

torchaudio 2.11 的 load 走 TorchCodec，会**拒绝 float 张量**。解法是把参考音以**文件路径**而非已
解码的张量传入 —— provider 已经这么做了（传 `prompt_wav` 路径），正常不会碰到；自己改代码时别把
float 波形张量直接喂给加载/解码环节即可。

### ④ 句尾最后一个字被切掉 / 收得太急（句尾截断）

每句**最后一个音节**有时在没发完音的地方被硬切（比如「新闻早报」的「报」听起来像没说完就断了）。

**这是确定性的，不是随机抽风。** CosyVoice2 每次加载都会把随机种子重置到一个固定状态，于是
**在同一个进程里，输出取决于你第几次调用 `synthesize`**，跟你传什么文本几乎没关系。实测同一句话：
第 1 次合成必定把句尾切在满音量处（句尾 50ms 能量 RMS≈0.32），第 2 次干净（≈0.03），第 3 次又被切。
逐句独立合成时，每句的「第一句」正好对上「第 1 次调用」 → 每次必中。

为什么改标点没用：句末的 `。` / `，` 会被文本前端归一化掉，「…早报。」和「…早报，」规范化后是
**同一串 token**，输出逐位相同。

判断指标：量句子**最后 50ms** 的 RMS —— 干净收尾 `<0.03`，被切 `>0.3`，阈值取 `0.08`。

解法：检测句尾能量，超过阈值＝被截断 → **重合成一次**（每次合成都会推进 RNG，换一个确定性输出，
第 2 次通常就干净了），最后保留尾部 RMS 最低（最干净）的那一次；**标点不动**，所以句末降调仍然正确。
代价是偶尔多合成一次。

已内置在 `tts/speak.py`，自动处理（`--tail-retries` 默认 3，`--tail-thresh` 默认 0.08）。

> 注：整段一次性合成不会暴露这个问题（句尾后面还有内容，再加 0.18s 停顿；见 `cosyvoice.py`
> `_emit_seg_chunks` 末段不补 pad）。

## 用法

### ① 生成播报稿（HTML -> .txt）

```bash
python3 -m tts.scriptgen \
  --html archive/2026-06-07.html \
  --out  tts/samples/daily-ai-news-2026-06-07-script.txt
```

- `--out` 省略时，默认在源文件同目录写 `daily-ai-news-<date>-script.txt`。
- 也支持 `--json fields.json`（同一套字段 schema，见下方映射表）。
- 自动适配 HTML 里**任意条数** `<section id="story-N">`（2 条或 10 条都行）。

### ② 合成音频（.txt -> .wav/.mp3）

```bash
# 默认 provider=cosyvoice；未安装则自动 fallback 到 macsay
python3 -m tts.tts_service \
  --text-path tts/samples/daily-ai-news-2026-06-07-script.txt \
  --out       tts/samples/daily-ai-news-2026-06-07.mp3

# 显式指定 provider
python3 -m tts.tts_service --text-path <script> --out <out>.wav --provider cosyvoice
python3 -m tts.tts_service --text-path <script> --out <out>.mp3 --provider macsay
```

输出 JSON 含 `status` / `provider`（实际用到的）/ `audio_path` / `error` / `meta`。

### 实时朗读（speak）

边合成边播的实时朗读 CLI：单进程（模型只加载一次），拆句 → 逐句合成 → 用一条 `sounddevice` 流把
各句背靠背播出去，并按 RTF 预缓冲，让它**开口早于「整段生成完」**。

```bash
PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python -m tts.speak "各位听众早上好，今天的头条……"
# 缺省文本则从 stdin 读
```

| 参数 | 说明 |
|---|---|
| `--gap` | 句间停顿秒数（默认 0.30，留出换气） |
| `--fade` | 句尾淡出秒数（默认 0.02，磨平硬切、防爆音） |
| `--tail-retries` | 句尾截断重合成次数（默认 3，设 0 关闭） |
| `--tail-thresh` | 句尾截断判定阈值（默认 0.08） |
| `--rtf` | 实时因子＝生成耗时÷音频时长（默认 1.4） |
| `--speak-rate` | 估算语速，字/秒（默认 4.6） |
| `--safety` | 预缓冲余量秒数（默认 0.3） |
| `--voice` | 音色（默认 my_voice_zh） |
| `--save PATH` | 落盘已播音频 + 逐段文件，供审核 |
| `--baseline` | 全生成完再播（对照用） |
| `--device` | 输出设备号 |

句尾最后一个字被切掉的修复见上方故障排除 ④。

依赖：需要 `sounddevice`（`tts/.venv` 里已装）。

### Python API

```python
from tts import tts_service

res = tts_service.synthesize(
    text_path="tts/samples/daily-ai-news-2026-06-07-script.txt",
    output_path="tts/samples/daily-ai-news-2026-06-07.wav",
    provider="cosyvoice",        # 省略走 config.default_provider
    voice="sweet_female_zh",
    speed=0.95,
    style="warm_news",
)
print(res.ok, res.provider, res.audio_path, res.error)
```

`synthesize()` 永不抛异常，永远返回 `TTSResult`。也可直接传 `text="..."` 而非 `text_path`。

## 音色配置（config.json）

**默认合成模式 = `zero_shot`**：用甜美女声参考音 `tts/assets/ref_sweet_female_zh.wav` ＋ 与之匹配的
`prompt_text`（参考音那句台词）做声音克隆，效果稳定自然。

> `instruct2` 模式也存在（用自然语言 `instruct` 描述风格），但**当前 CosyVoice 构建下 instruct2 会
> 把 instruct 这串风格描述当成正文念出来**，所以**不作为默认**。默认走 `zero_shot`。

`voices.sweet_female_zh`：

- 全局：`speed`（默认 0.95，偏慢更亲和）、`style`（warm_news）。
- `cosyvoice`：`mode`（**zero_shot**，默认）、`prompt_wav`（参考音）、`prompt_text`（**参考音那句台词**，
  zero_shot 必需，要和参考音内容对得上）、`instruct`（仅 instruct2 模式用的风格 prompt，默认不用）、
  `spk_id`（sft 模式备用 "中文女"）。
- `macsay`：`say_voice`（Tingting）、`say_base_rate`（168 wpm，会乘以 speed）。

顶层 `default_provider` / `fallback_provider` 控制选用与降级；`cosyvoice` 段配 `model_type`、
`synth_mode`（**zero_shot**）、`repo_dir`、`model_dir`、`venv_python`、`prompt_wav`、`prompt_text`。

**换模型**：在 `providers/` 加一个新文件 + 在 `config.json` 的 voice 下加一段同名 provider
配置，业务代码不改。

## 路径 / 命名约定

| 项 | 路径 |
|---|---|
| CosyVoice 仓库 | `tts/vendor/CosyVoice` |
| 权重 | `tts/models/CosyVoice2-0.5B` |
| 隔离 venv | `tts/.venv`（python `tts/.venv/bin/python`） |
| 参考音 | `tts/assets/ref_sweet_female_zh.wav` |
| 报纸 HTML | `archive/YYYY-MM-DD.html` |
| 字段存档稿(full) | `tts/samples/daily-ai-news-YYYY-MM-DD-script.txt` |
| 口播稿(broadcast, TTS 读这份) | `tts/samples/daily-ai-news-YYYY-MM-DD-broadcast.txt` |
| 音频 | `tts/samples/daily-ai-news-YYYY-MM-DD.wav`（或 `.mp3`，`--text-path` 来源为 broadcast 稿） |

## 接每天 6:05 流程（仅文档，不改 SKILL.md）

日报生成出 `archive/YYYY-MM-DD.html` 之后，在现有流程末尾追加三段命令即可：

```bash
DATE=$(date +%F)
# 1) full 字段存档稿（确定性，仅存档，TTS 不读它）
python3 -m tts.scriptgen --html archive/${DATE}.html --out tts/samples/daily-ai-news-${DATE}-script.txt
# 2) 高密度口播稿（LLM 事实降调改写；claude 不可用时自动回退字段稿）
python3 -m tts.broadcast_rewrite --script tts/samples/daily-ai-news-${DATE}-script.txt --out tts/samples/daily-ai-news-${DATE}-broadcast.txt
# 3) 合成音频（TTS 只读 broadcast 版）
python3 -m tts.tts_service --text-path tts/samples/daily-ai-news-${DATE}-broadcast.txt --out tts/samples/daily-ai-news-${DATE}.mp3
```

口播稿降调规则的唯一真源是 `tts/broadcast_prompt.md`（含「事实降调 pass」）；每日 6:05 agent 直接据此写 broadcast 稿，`broadcast_rewrite.py` 供补跑历史期 / 纯 shell 流程。

未装 CosyVoice 时第三步会自动 fallback 到 macsay，仍能产出音频，不会中断定时任务。

## 字段映射表（HTML class -> 播报稿字段）

| HTML 选择器 | 播报稿用途 |
|---|---|
| `div.date` | 开场日期「每日 AI 新闻，YYYY 年 M 月 D 日。」 |
| `#cover .headline-stack span` | 「今天的主要内容是：」前 3 条头条 |
| `#story-N h2.news-title` | 「第N条，<标题>。」 |
| `#story-N p.big`（第 1 个） | 该条正文摘要（summary_main） |
| `#story-N p.big`（第 2 个） | 「为什么重要：…」 |
| `#story-N ul.impact-list li` | 「具体影响包括：一，…」逐条 |
| `#story-N .source-row`（主要来源） | 「信息来源：…」 |
| `#story-N .source-row`（可信度） | 「可信度：…」 |
| `#story-N .source-row`（待验证） | 「待验证信息：…」 |
| `#story-N .byline span`（兜底） | 没有 source-row 时从「来源：/可信度：」span 取 |
| `#tomorrow .mini-card strong/span` | 「明日观察：一，<标题>，<说明>」 |

播报稿固定以「以上就是今天的每日 AI 新闻。」收尾。所有字段经 `_clean()` 去标签 / 去 URL /
中文标点归一，确保对 TTS 友好。
