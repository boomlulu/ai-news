#!/usr/bin/env bash
# Install CosyVoice2 in an ISOLATED venv (tts/.venv). Does NOT touch system/global
# python. macOS arm64. Logs to tts/install.log. Re-runnable.
#
# EXACT REPRO (recommended): a frozen, KNOWN-WORKING dependency set lives in
#   tts/requirements-cosyvoice.lock.txt
# If that file exists, this script installs straight from it (skips all the
# version guesswork below — same wheels that produced working audio).
#
# CRITICAL GOTCHA: transformers MUST be ==4.51.3. Newer transformers break
# CosyVoice2's Qwen2 stop-token handling -> runaway over-generation (3-4x too
# long / repeated audio). Step 5b re-pins it explicitly even on the guesswork path.
set -uo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"; TTS="$ROOT/tts"; LOG="$TTS/install.log"
PY310="${PY310:-/opt/homebrew/bin/python3.10}"
VENV="$TTS/.venv"; VENDOR="$TTS/vendor/CosyVoice"; MODELDIR="$TTS/models/CosyVoice2-0.5B"
LOCK="$TTS/requirements-cosyvoice.lock.txt"
mkdir -p "$TTS"; exec > >(tee -a "$LOG") 2>&1
echo "=== CosyVoice install start ==="
step(){ echo; echo "### STEP: $*"; }

step "0 preflight"
command -v brew >/dev/null || { echo "FATAL: brew missing"; exit 1; }
[ -x "$PY310" ] || { echo "FATAL: python3.10 missing at $PY310 (brew install python@3.10)"; exit 1; }
"$PY310" --version

step "1 openfst (OPTIONAL — only needed if you build pynini; NOT required at runtime)"
# Runtime text-normalization uses `wetext` (pure-ish, no OpenFst build). pynini is
# optional on macOS. We still set these env vars in case someone opts into pynini.
if [ ! -d /opt/homebrew/include/fst ]; then brew install openfst || echo "WARN: brew openfst failed (OK — pynini is optional)"; else echo "openfst present"; fi
export CPATH="/opt/homebrew/include:${CPATH:-}"
export LIBRARY_PATH="/opt/homebrew/lib:${LIBRARY_PATH:-}"
export CFLAGS="-I/opt/homebrew/include ${CFLAGS:-}"
export LDFLAGS="-L/opt/homebrew/lib ${LDFLAGS:-}"

step "2 venv (isolated, python3.10)"
[ -d "$VENV" ] || "$PY310" -m venv "$VENV"
source "$VENV/bin/activate"
python -m pip install -U pip wheel setuptools

step "3 clone CosyVoice (+ Matcha-TTS submodule)"
if [ ! -d "$VENDOR/.git" ]; then
  mkdir -p "$TTS/vendor"
  git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git "$VENDOR" || echo "WARN: clone failed"
  ( cd "$VENDOR" && git submodule update --init --recursive ) || true
else ( cd "$VENDOR" && git pull --recurse-submodules ) || true; fi

# FAST PATH: if a frozen lock file exists, install the exact known-working set and
# skip the per-package guesswork (steps 4 / 5 / 5b are covered by the lock).
if [ -f "$LOCK" ]; then
  step "4-LOCK install EXACT working set from $LOCK (recommended, reproducible)"
  if pip install -r "$LOCK"; then
    echo "OK: installed from lock file (transformers pinned inside)."
    SKIP_GUESSWORK=1
  else
    echo "WARN: lock install failed — falling back to per-package guesswork below."
    SKIP_GUESSWORK=0
  fi
else
  echo "NOTE: no lock file ($LOCK) — using per-package guesswork (steps 4/5/5b)."
  SKIP_GUESSWORK=0
fi

if [ "${SKIP_GUESSWORK:-0}" != "1" ]; then
step "4 torch + core deps"
pip install torch torchaudio || echo "WARN: torch failed"
# Core + extra runtime deps actually needed by CosyVoice2 at synth time:
pip install modelscope huggingface_hub conformer hydra-core lightning gdown librosa soundfile onnxruntime inflect omegaconf || echo "WARN: some core deps failed"
pip install hyperpyyaml diffusers wget wetext pyworld torchcodec openai-whisper matplotlib pyarrow || echo "WARN: some extra runtime deps failed"

step "5 repo requirements (pynini/WeTextProcessing are OPTIONAL on macOS — wetext handles TN)"
[ -f "$VENDOR/requirements.txt" ] && { pip install -r "$VENDOR/requirements.txt" || echo "WARN: full requirements failed (likely pynini/ttsfrd) — OPTIONAL, see README troubleshooting"; }
# pynini is OPTIONAL: not required at runtime (wetext does text-normalization).
python -c "import pynini" 2>/dev/null && echo "pynini OK" || pip install pynini==2.1.6 || pip install pynini || echo "WARN: pynini unavailable — OPTIONAL; wetext handles TN, our script text is already normalized."

step "5b PIN transformers (CRITICAL: newer breaks CosyVoice2 Qwen2 stop-token -> runaway over-generation)"
pip install "transformers==4.51.3"
fi

step "6 download CosyVoice2-0.5B -> $MODELDIR"
mkdir -p "$TTS/models"
python - <<PY || echo "WARN: model download failed"
from modelscope import snapshot_download
snapshot_download('iic/CosyVoice2-0.5B', local_dir=r"$MODELDIR")
print("model at", r"$MODELDIR")
PY

step "7 reference prompt wav (sweet female via macOS Tingting) for instruct2/zero-shot"
mkdir -p "$TTS/assets"; A="$TTS/assets/_ref.aiff"; W="$TTS/assets/ref_sweet_female_zh.wav"
if command -v say >/dev/null; then
  say -v Tingting -r 165 -o "$A" "大家好，欢迎收听每日人工智能新闻，我会用温暖清晰的声音，为你播报今天的重点。"
  command -v ffmpeg >/dev/null && ffmpeg -y -i "$A" -ar 16000 -ac 1 "$W" && rm -f "$A" && echo "ref wav: $W"
else echo "WARN: say missing; supply your own 16k mono ref wav at $W"; fi

step "8 smoke import"
python - <<'PY' || echo "WARN: cosyvoice import failed"
import sys, os, importlib.util
repo=os.path.join(os.getcwd(),"tts","vendor","CosyVoice")
sys.path.insert(0,repo); sys.path.insert(0,os.path.join(repo,"third_party","Matcha-TTS"))
print("cosyvoice importable:", importlib.util.find_spec("cosyvoice") is not None)
PY
echo; echo "=== DONE. venv=$VENV model=$MODELDIR ref=$W ==="
echo "Run: source tts/.venv/bin/activate && python -m tts.tts_service --text-path tts/samples/<script>.txt --out tts/samples/<name>.wav --provider cosyvoice"
