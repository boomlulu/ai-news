# 效果留档 · 2026-06-09 · instruct2 情绪合成

## 对应改动
- commit `042dafb` fix(tts): instruct2 修复（指令不再被念出 + 传入 instruct 生效）
- 效果：`mode=instruct2` + `instruct=<自然语言语气>` 给克隆音色 `my_voice_zh` 加情绪，指令不入声。zero_shot/sft 不受影响。

## 复现
```
PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python -c '
from tts import tts_service
tts_service.synthesize(text="今天在干嘛呢，我的小宝贝～", output_path="/tmp/x.wav",
  provider="cosyvoice", voice="my_voice_zh", fallback="", mode="instruct2",
  instruct="用嗲嗲的、撒娇黏人的语气，慢一点、软一点说")'
```

## 样本（文本同为「今天在干嘛呢，我的小宝贝～」）
| 文件 | instruct（语气指令） |
|---|---|
| emo-00-verify.wav | 用嗲嗲的、撒娇黏人的语气，慢而软地说（最早验证条） |
| emo-01.wav | 用嗲嗲的、撒娇黏人的语气，慢一点、软一点说 |
| emo-02.wav | 像跟恋人撒娇那样，奶声奶气、娇滴滴地说，尾音拖长 |
| emo-03.wav | 温柔甜腻，黏人撒娇，语速放慢，语气上扬 |

## 验证
whisper 转写：指令不入声（修前 8.04s 念出 config 默认指令 → 修后 2.62s 只念目标句）。

## 备注
音频=个人克隆音色私人 demo；AINews 公开仓库 → 本目录音频默认 `.gitignore` 不发布，仅本机留档；本 manifest 入库即可复现效果。
