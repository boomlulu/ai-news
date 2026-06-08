# emotion-lab — 女生日常情绪库评测 harness

用途：用 CosyVoice2 `instruct2` 把一套女生日常情绪（撒娇/害羞/求哄/温柔/委屈/吃醋…）批量合成成音频样本，
人工试听打分，按反馈迭代 `instruct` 文案，逐轮（round）逼近"自然好听又情绪到位"的私人克隆音色表现。

声音：`my_voice_zh`（私人克隆音色，zero_shot prompt 参考），合成模式 `instruct2`。

---

## 评分体系

每条样本 5 个维度，各 1–5 分，**情绪契合权重 ×2**：

| 维度 | 权重 | 含义 |
|---|---|---|
| 情绪契合 | ×2（满 10） | 听感是否就是这个情绪（撒娇像撒娇、委屈像委屈） |
| 自然 | ×1（满 5） | 不机械、不僵、像真人说话 |
| 音色保真 | ×1（满 5） | 是否还是 `my_voice_zh` 本人的音色，没跑偏 |
| 清晰 | ×1（满 5） | 吐字清楚、无吞字/糊音 |
| 可用 | ×1（满 5） | 能不能直接拿去用（无明显瑕疵/气口断裂/尾字硬切） |

**满分 = 30**。每个情绪的两个变体里挑一个在 `最佳√` 列打 √，并在 `备注` 写改进方向。

---

## 工作流

1. 生成一轮：`generate.py --round round-XX` → 产出 `round-XX/*.mp3` + `round-XX/SCORING.md`。
2. 试听 `round-XX/*.mp3`，在 `SCORING.md` 填分（或口头告诉我每条评价）。
3. 我把每情绪的赢家 + 反馈整理进 `feedback/winners.md`。
4. 据反馈改 `taxonomy.json`（调 `instruct` 文案 / 换变体 / 改测试句），重跑出 `round-(XX+1)`。
5. 循环 2–4，直到每个情绪都有满意的最佳变体。

---

## 文件说明

| 文件 | 作用 | 入库? |
|---|---|---|
| `taxonomy.json` | 情绪/测试句/变体/instruct 真源（18 情绪 × 2 变体 = 36 条） | 是 |
| `generate.py` | 读 taxonomy → 合成 wav → ffmpeg 转 mp3 → 出 SCORING.md | 是 |
| `README.md` | 本说明 | 是 |
| `feedback/winners.md` | 每轮赢家 + 用户反馈 + 迭代记录 | 是 |
| `round-XX/*.mp3` | 各轮音频样本 | 否（gitignore，本机留档） |
| `round-XX/SCORING.md` | 各轮评分表 | 是（属 md） |

---

## 复现命令

```bash
# 全 36 条 → round-01
PYTHONPATH=/Users/boom/Demo/AINews \
  tts/.venv/bin/python tts/effect-archive/emotion-lab/generate.py --round round-01

# 只跑指定情绪（如 撒娇01、害羞02）
PYTHONPATH=/Users/boom/Demo/AINews \
  tts/.venv/bin/python tts/effect-archive/emotion-lab/generate.py --round round-02 --only 01,02
```

---

## 备注

- 音频是私人克隆音色，`tts/effect-archive/**/*.{wav,mp3}` 已在 `.gitignore` 忽略，本机留档不发布；
  `taxonomy.json` / `generate.py` / `*.md`（含 SCORING.md / winners.md）入库。
- 模型（CosyVoice2-0.5B）首条 ~8s 加载一次，后续逐条更快；`mode=instruct2` 走 zero_shot prompt。
- 每次 run **覆盖**该 round 的同名文件，不做"已生成跳过"，想保留旧轮请用新的 `--round`。
