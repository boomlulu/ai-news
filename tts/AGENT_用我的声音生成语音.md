# Agent 指南：用「用户本人声音」(my_voice_zh) 生成语音

> 读者 = 未来某个干净 session 的 Agent。照本文做就能正确生成。**一切已调好的参数都固化在
> `tts/config.json`，直接用、别覆盖**（别传 `speed`/`style`/`unit`/`gap`/`tail_*` 等，留空 = 用默认）。

## 一句话

用我的声音生成语音 = 调 `tts_service.synthesize(voice="my_voice_zh", ...)`。
其余参数（zero_shot 模式、CosyVoice2-0.5B 模型、参考音、smart 停顿管线）都已在 config 里配好，
Agent 啥都不用配，**也不要配**。

## 环境（硬性要求）

- repo：`/Users/boom/Demo/AINews`。
- Python **必须**用 `tts/.venv/bin/python`（py3.10）；系统 `python3` 是 3.9，没装 CosyVoice。
- import 时**必须**带 `PYTHONPATH=/Users/boom/Demo/AINews`。
- bash cwd 每次重置 —— **一律用绝对路径，别靠 `cd`**。
- 模型每个进程**首次合成加载约 8 秒**，之后同进程缓存复用。macOS / CPU。
- **别动 `transformers`**（锁 `==4.51.3`，见「必踩坑」）。

## 主路径 —— 生成音频文件（推荐）

### Python API

```python
from tts import tts_service

res = tts_service.synthesize(
    text="今天我们聊聊人工智能。",          # 或 text_path="<稿.txt>"
    output_path="tts/samples/out.wav",       # .wav 最稳；.mp3 需 ffmpeg（provider 自动转）
    voice="my_voice_zh",                      # ← 用户本人克隆音色
    # 不要传 speed/style/unit/gap/tail_* —— 调好的参数都在 config.json
)
print(res.ok, res.status, res.audio_path, res.error)   # 必须查 res.ok，别只看有没有文件
```

跑法：

```bash
PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python <脚本>.py
```

### CLI

> **注意：CLI `--voice` 默认是 `sweet_female_zh`，必须显式写 `--voice my_voice_zh`**（漏了会用错音色）。

```bash
PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python -m tts.tts_service \
  --text "今天我们聊聊人工智能。" --out tts/samples/out.wav --voice my_voice_zh
# 从文件：把 --text 换成 --text-path <稿.txt>
```

### 行为约定

- `synthesize()` **永不抛异常**，永远返回 `TTSResult`（`ok` / `status` / `audio_path` / `error`）。
  → 判成功一律看 `res.ok`，别只看「有没有报错 / 有没有文件」。
- `voice=my_voice_zh` 会自动用：zero_shot + CosyVoice2-0.5B + 已注册参考音 + **smart 停顿管线**
  （见下表）。Agent 啥都不用配。

## 已调好的参数（在 `tts/config.json`，仅供了解，**禁止覆盖**）

### 表 1 — `voices.my_voice_zh`

| 项 | 值 |
|---|---|
| `mode` | `zero_shot` |
| `model_type` | `cosyvoice2` |
| `model_dir` | `tts/models/CosyVoice2-0.5B` |
| `prompt_wav` | `tts/assets/ref_my_voice_zh_prompt.wav` |
| `prompt_text` | `这次罗斯凯利法的场景从设计到布局到致敬再到配色还有光追等技术的提高都太全面了` |
| `speed` | `1.0` |
| `style` | `warm_news` |

### 表 2 — `cosyvoice`（smart 停顿管线，对 my_voice_zh 同样生效）

| 项 | 值 | 含义 |
|---|---|---|
| `synth_unit` | `smart` | 合成单元升到条目/整段级 |
| `item_pause_ms` | `420` | 条目间停顿 |
| `within_pause_ms` | `0` | 条目内停顿（交给模型自带韵律） |
| `tail_keep_ms` | `160` | silero-vad 末端保留 |
| `pre_roll_ms` | `60` | 首端保留 |
| `min_unit_chars` | `22` | 单元最小字数 |
| `target_max_chars` | `140` | 单元目标最大字数 |
| `trim_segment_silence` | `true` | 裁段尾静音 |
| `trim_thresh_db` | `-40` | 裁切阈值（dB） |

**smart 一句话解释**：合成单元升到条目/整段级（只在 `。！？；` 切，**不按逗号切**），用 silero-vad
归一化端点 → 停顿一致、句末软音不丢。

## 可选 —— 实时朗读（边生成边播，不落文件）

要「听」而不要文件时用 `tts/speak.py`，它的 `--voice` 默认就是 my_voice_zh：

```bash
PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python -m tts.speak "今天我们聊聊人工智能。"
```

它自带一套调好的默认（同样别覆盖）：`--gap 0.30`（句间换气）、`--fade 0.02`（句尾淡出）、
`--tail-retries 3`、`--tail-thresh 0.08`（句尾截断重合成保最优）。

## 可选（进阶）—— 加情绪

默认不需要。只在确实要情绪时，给 my_voice_zh 调 `mode=instruct2` + `instruct="用<语气>说，如 温柔/俏皮"`
（2026-06-09 已修，指令不会被念出来）。

## 验收（必做，别只看「无报错 / 有文件」）

用 whisper 转写产物，核对念出全文（关键词都在）。whisper base 输出**繁体**，用 `zhconv` 转简体
（venv 已装）：

```python
import whisper, zhconv
t = whisper.load_model("base").transcribe("tts/samples/out.wav", language="zh", fp16=False)["text"]
print(zhconv.convert(t, "zh-cn"))
```

## 必踩坑（Agent 最容易中的）

1. **CLI 必须显式 `--voice my_voice_zh`** —— 默认不是它（默认 `sweet_female_zh`），漏了会用错音色。
2. **一个进程里别再合成「另一个 base 模型」的音色**（如 `sweet_female_zh` = SFT 与 `my_voice_zh` =
   CosyVoice2 混用）→ 第 2 个必炸 `ValueError: tn.__spec__ is None`（报 `status=error` / `0.00s`）。
   **只用 my_voice_zh 单独跑就安全**；要换别的音色就**新开进程**。
3. ~8s 冷启动每个进程都付一次，正常现象。
4. **别 `pip install transformers` 覆盖版本**（锁 `4.51.3`，否则疯狂超量生成、语速虚长 3-4 倍）。
5. 参考音 / `prompt_text` 已配好，**别动** my_voice_zh 的 `prompt_wav` / `prompt_text`
   （zero_shot 要求两者精确一致）。
