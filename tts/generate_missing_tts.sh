#!/usr/bin/env bash
#
# generate_missing_tts.sh — 在宿主机用 AISpeak 把缺失的口播 mp3 补齐
#
# 作用：扫描 tts/samples/daily-ai-news-*-broadcast.txt，对「还没有对应 mp3」的
#       逐个调用 AISpeak 合成（CosyVoice 克隆音色 + smart 停顿）。
# 幂等：已成功生成（mp3 存在且体积达标）的直接跳过。
# 未来式：随时可重跑；只补缺的，不会重复劳动。失败不会留下半成品，下次自动重试。
#
# 用法：
#   bash tts/generate_missing_tts.sh                # 补齐所有缺失
#   bash tts/generate_missing_tts.sh 2026-06-17     # 只处理某一天
#   bash tts/generate_missing_tts.sh --force        # 强制重生成（忽略已存在）
#   bash tts/generate_missing_tts.sh 2026-06-17 -f  # 强制重生成某一天
#
# 可用环境变量覆盖：AISPEAK_DIR AINEWS_DIR VENV_PY TTS_PROVIDER TTS_VOICE TTS_UNIT TTS_MIN_BYTES

set -uo pipefail

# ===== 配置（可被同名环境变量覆盖）=====
AISPEAK_DIR="${AISPEAK_DIR:-/Users/boom/Demo/AISpeak}"
AINEWS_DIR="${AINEWS_DIR:-/Users/boom/Demo/AINews}"
SAMPLES_DIR="$AINEWS_DIR/tts/samples"
VENV_PY="${VENV_PY:-$AISPEAK_DIR/tts/.venv/bin/python}"
PROVIDER="${TTS_PROVIDER:-cosyvoice}"
VOICE="${TTS_VOICE:-my_voice_zh}"
UNIT="${TTS_UNIT:-smart}"
MIN_BYTES="${TTS_MIN_BYTES:-50000}"   # 小于此字节数视为未成功 → 重新生成

# ===== 解析参数 =====
FORCE=0
ONLY_DATE=""
usage(){ sed -n '3,21p' "$0"; }
for arg in "$@"; do
  case "$arg" in
    -f|--force) FORCE=1 ;;
    -h|--help)  usage; exit 0 ;;
    20[0-9][0-9]-[0-1][0-9]-[0-3][0-9]) ONLY_DATE="$arg" ;;
    *) echo "未知参数：$arg"; echo "用 -h 看用法"; exit 2 ;;
  esac
done

# ===== 预检 =====
if [ ! -x "$VENV_PY" ]; then
  echo "✗ 找不到 AISpeak 的 venv python：$VENV_PY"
  echo "  请确认 AISpeak 已安装好虚拟环境（或用 VENV_PY=... 指定）。"
  exit 1
fi
if [ ! -d "$SAMPLES_DIR" ]; then
  echo "✗ 找不到口播样本目录：$SAMPLES_DIR"
  exit 1
fi

# ===== 收集待处理的口播稿 =====
shopt -s nullglob 2>/dev/null || true
if [ -n "$ONLY_DATE" ]; then
  txts=( "$SAMPLES_DIR/daily-ai-news-$ONLY_DATE-broadcast.txt" )
else
  txts=( "$SAMPLES_DIR"/daily-ai-news-*-broadcast.txt )
fi

if [ "${#txts[@]}" -eq 0 ]; then
  echo "没有找到任何 daily-ai-news-*-broadcast.txt，无事可做。"
  exit 0
fi

echo "AISpeak : $AISPEAK_DIR"
echo "样本目录: $SAMPLES_DIR"
echo "音色/引擎: $VOICE / $PROVIDER  (unit=$UNIT, force=$FORCE)"
echo "------------------------------------------------------------"

total=0; gen=0; skip=0; fail=0
for txt in "${txts[@]}"; do
  if [ ! -e "$txt" ]; then
    echo "✗ 文本不存在：$txt"; fail=$((fail+1)); continue
  fi
  total=$((total+1))
  mp3="${txt%-broadcast.txt}-broadcast.mp3"
  base="$(basename "$txt")"

  # —— 幂等：已存在且体积达标 → 跳过 ——
  if [ "$FORCE" -eq 0 ] && [ -f "$mp3" ]; then
    size=$(wc -c < "$mp3" 2>/dev/null | tr -d ' ')
    if [ "${size:-0}" -ge "$MIN_BYTES" ]; then
      echo "⏭  跳过（已生成 ${size} 字节）：$(basename "$mp3")"
      skip=$((skip+1)); continue
    else
      echo "↻  发现疑似失败的残留（${size:-0} 字节），重新生成：$(basename "$mp3")"
      rm -f "$mp3"
    fi
  fi

  # —— 合成到临时文件，成功且达标才改名（失败不留半成品）——
  echo "▶  生成中：$base ..."
  tmp="${mp3%.mp3}.partial.mp3"
  rm -f "$tmp"
  # 注意：tts_service 的相对路径锚定在 AISpeak 仓库根；--text-path/--out 必须绝对路径
  ( cd "$AISPEAK_DIR" && PYTHONPATH="$AISPEAK_DIR" "$VENV_PY" -m tts.tts_service \
      --text-path "$txt" --out "$tmp" \
      --provider "$PROVIDER" --voice "$VOICE" --unit "$UNIT" )
  rc=$?

  size=0
  [ -f "$tmp" ] && size=$(wc -c < "$tmp" 2>/dev/null | tr -d ' ')
  if [ "$rc" -eq 0 ] && [ "${size:-0}" -ge "$MIN_BYTES" ]; then
    mv -f "$tmp" "$mp3"
    echo "✓  完成（${size} 字节）：$(basename "$mp3")"
    gen=$((gen+1))
  else
    rm -f "$tmp"
    echo "✗  生成失败（退出码 $rc，产物 ${size:-0} 字节），未写 mp3，下次可重试：$base"
    fail=$((fail+1))
  fi
done

echo "------------------------------------------------------------"
echo "汇总：共 $total 个口播稿 · 新生成 $gen · 跳过 $skip · 失败 $fail"
[ "$fail" -eq 0 ]
