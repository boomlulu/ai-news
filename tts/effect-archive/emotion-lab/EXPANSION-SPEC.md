# Round-02 候选扩充需求：每个情绪赛道 ≥10 个 instruct 候选

## 背景
emotion-lab 是「女生日常情绪」TTS 评测库。真源 = `taxonomy.json`（18 个情绪赛道，每赛道当前 2 个 instruct 候选）。`generate.py` 读它，用 CosyVoice2 `instruct2` + 克隆音色 `my_voice_zh` 合成评测样本。现每赛道候选太少 → 目标：**每赛道 ≥10 个不同 instruct 候选**（保留现有 2 个，再加 ≥8 个，总数 ≥10）。

## 什么是「instruct 候选」
一句**中文自然语言「语气/情绪」指令**，描述「**怎么说**」——情绪、语速、音调、音色质感、气息、尾音处理——**不含要念的内容**。
例：`像跟恋人撒娇那样，奶声奶气、娇滴滴地说，尾音拖长`。喂给 CosyVoice2 instruct2，模型据此调整克隆音色的演绎。

## 任务
为指定的情绪赛道，产出 **≥10 个 instruct 候选**，要求**彼此真正不同**（不是换近义词堆砌），覆盖该情绪的不同**子风格 / 强度 / 发声技巧**。

可变维度（用来制造实质差异）：
- 强度：轻微 → 浓烈
- 语速：放慢 / 正常 / 加快
- 音调：低沉 / 平 / 上扬 / 起伏
- 音色质感：气声 / 鼻音 / 沙哑 / 清亮 / 绵软糯
- 尾音：拖长 / 上扬 / 下沉 / 渐弱 / 短促
- 子风格：例「撒娇」可分 恋人撒娇 / 小女生奶音 / 邀宠 / 卖萌 / 慵懒撒娇 / 糯叽叽 / 嘟嘴耍赖 …

## 约束
- 每个 instruct ≤ 40 字，中文，结尾近似「…地说 / …的语气说」。
- 同赛道内 instruct 不重复、不雷同（必须是实质不同的演绎）。
- **不改 sample sentence（text）**——只扩 variants。
- 必须**契合该情绪**，别跑偏成别的情绪。
- 保留现有 v1/v2，新增顺延编号 v3、v4…

## 每条候选字段
```json
{ "v": "v3", "slug": "邀宠-黏人-糯音", "instruct": "像邀宠一样黏着撒娇，糯糯的、奶气十足地说" }
```
- `v`：v1..vN 顺序编号。
- `slug`：文件名安全的短关键词，**无空格无标点、用 `-` 分隔**，同赛道内唯一（会进 mp3 文件名）。
- `instruct`：候选指令本身。

## 交付格式（每赛道独立文件，避免多 agent 冲突）
每个赛道输出一个 JSON 文件：`tts/effect-archive/emotion-lab/expansion/<id>_<name>.json`，内容 = 该赛道完整 emotion 对象（含 ≥10 variants）：
```json
{
  "id": "01",
  "name": "撒娇",
  "text": "今天在干嘛呢，我的小宝贝～",
  "variants": [
    { "v": "v1", "slug": "恋人撒娇-奶声奶气-尾音拖长", "instruct": "像跟恋人撒娇那样，奶声奶气、娇滴滴地说，尾音拖长" },
    { "v": "v2", "slug": "嗲嗲黏人-慢而软-尾音上扬", "instruct": "用嗲嗲的、黏人撒娇的语气，慢而软，尾音上扬" }
    // … 续到 ≥10 条
  ]
}
```
（多个 agent 各负责若干赛道、各写各的文件，互不冲突；之后由主开发合并进 `taxonomy.json` 跑 `generate.py --round round-02`。）

## 现有 18 赛道（id/name/text/现有候选）以 `taxonomy.json` 为准
开工前先 `cat tts/effect-archive/emotion-lab/taxonomy.json`，按里面每个赛道的 id/name/text 和已有 2 条 instruct 续扩。

## 验收
- 文件是合法 JSON。
- 每赛道 variants ≥10、slug 同赛道唯一、instruct 同赛道不重复。
- 每条 instruct 契合该情绪、≤40 字、描述「怎么说」。

## 可直接粘给 agent 的任务模板
> 你负责情绪赛道：【填，如 `01 撒娇`、`11 委屈`】。先读 `/Users/boom/Demo/AINews/tts/effect-archive/emotion-lab/taxonomy.json` 拿到这些赛道的 id/name/text 与现有 2 条 instruct，再读 `EXPANSION-SPEC.md`。按其中「可变维度 / 约束 / 字段 / 交付格式」，为每个负责赛道产出 ≥10 个**实质不同**的 instruct 候选（保留现有 2 条、顺延编号），写到 `tts/effect-archive/emotion-lab/expansion/<id>_<name>.json`。完成自检：合法 JSON、≥10 条、slug 唯一、契合情绪、每条 ≤40 字。
