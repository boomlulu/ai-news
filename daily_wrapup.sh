#!/usr/bin/env bash
#
# daily_wrapup.sh — 日报生成后的「一键收尾」。日报正文（index.html / archive/<日期>.html /
# archive/index.html / AI每日精选_<日期>.md / broadcast.txt）写好后，跑这一个脚本即可：
#
#   1/4  tts/generate_missing_tts.sh  合成缺失的口播 mp3（需 AISpeak；--no-tts 可跳过）
#   2/4  fix_date_nav.py              历史页日期导航（次日 / 最新 + 「今天」改为各自日期）
#   3/4  build_bigevents.py           月度 / 年度大事件归并（最近两月→月度，更早→年度）
#   4/4  add_audio_button.py          每期日报页注入 / 刷新「语音播报」按钮
#
# 全部子脚本均幂等，可随时反复运行；任一步失败不阻断后续，末尾汇总并以失败步数为退出码。
# 不执行 git —— index.html / archive / -broadcast.mp3 由每天 07:00 的自动任务统一提交推送。
#
# 用法：bash daily_wrapup.sh [--no-tts]
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
export AINEWS_DIR="$SCRIPT_DIR"          # 让所有子脚本用同一个站点根

NO_TTS=0
for a in "$@"; do
  case "$a" in
    --no-tts) NO_TTS=1 ;;
    -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
    *) echo "未知参数：$a（用 -h 看用法）"; exit 2 ;;
  esac
done

fails=0
step(){
  local name="$1"; shift
  echo ""
  echo "============================================================"
  echo "▶ $name"
  echo "------------------------------------------------------------"
  if "$@"; then
    echo "✔ $name 完成"
  else
    local rc=$?
    echo "✘ $name 失败（退出码 $rc）"
    fails=$((fails + 1))
  fi
}

echo "每日收尾 · $(date '+%Y-%m-%d %H:%M') · 站点根 $SCRIPT_DIR"

if [ "$NO_TTS" -eq 0 ]; then
  step "1/4 合成口播音频" bash "$SCRIPT_DIR/tts/generate_missing_tts.sh"
else
  echo ""
  echo "（已按 --no-tts 跳过音频合成）"
fi
step "2/4 修复日期导航" python3 "$SCRIPT_DIR/fix_date_nav.py"
step "3/4 归并大事件"   python3 "$SCRIPT_DIR/build_bigevents.py"
step "4/4 注入播放按钮" python3 "$SCRIPT_DIR/add_audio_button.py"

echo ""
echo "============================================================"
if [ "$fails" -eq 0 ]; then
  echo "✅ 全部完成。等 07:00 自动任务提交推送即可上线。"
else
  echo "⚠ 有 $fails 步失败，请看上面日志（其余步骤已照常完成）。"
fi
echo "============================================================"
exit "$fails"
