"""Speakbox Mac-resident TTS worker.

MVP flow: browser → Go server (124.220.6.174:8200) enqueues a TTS task →
THIS worker (resident on the Mac) long-polls the server, synthesizes the audio
locally using the existing `tts/speak.py` stack, and uploads the finished WAV
back to the server.

The CosyVoice model loads ONCE: this is a long-lived process, so the ~8s model
load only happens on the FIRST task. Every task after that reuses the warm model.

This worker REUSES the TTS implementation in `tts/speak.py` — it does NOT
reimplement synthesis. It imports `split_sentences`, `synth_one`, `apply_fade`,
`silence`, `SAMPLE_RATE`, drives the per-sentence loop, and reports progress.

Run (PYTHONPATH must be the repo root so `import tts` resolves):

    PYTHONPATH=/Users/boom/Demo/AINews \
      WORKER_TOKEN=<token> \
      SPEAKBOX_BASE_URL=http://124.220.6.174:8200 \
      /Users/boom/Demo/AINews/tts/.venv/bin/python \
      /Users/boom/Demo/AINews/speakbox/worker/worker.py

Environment variables:
    SPEAKBOX_BASE_URL  default "http://124.220.6.174:8200"
    WORKER_TOKEN       REQUIRED, no default — sent as the `X-Worker-Token`
                       header on EVERY request. Missing => print + exit(1).
    POLL_INTERVAL_SEC  default "1.0" (float) — sleep between empty polls.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time

import numpy as np
import requests
import soundfile as sf

from tts.speak import (
    SAMPLE_RATE,
    apply_fade,
    silence,
    split_sentences,
    synth_one,
)

BASE_URL = os.environ.get("SPEAKBOX_BASE_URL", "http://124.220.6.174:8200").rstrip("/")
WORKER_TOKEN = os.environ.get("WORKER_TOKEN")
POLL_INTERVAL_SEC = float(os.environ.get("POLL_INTERVAL_SEC", "1.0"))

HEADERS = {"X-Worker-Token": WORKER_TOKEN or ""}


def log(msg: str) -> None:
    """Single logging entry point. flush=True so logs stream live under a
    resident process (no buffering)."""
    print(msg, flush=True)


def render_to_wav(text, voice, out_path, on_progress):
    """Synthesize `text` with `voice` into a 24kHz mono WAV at `out_path`.

    Splits into sentences, synthesizes each via synth_one (which already does
    句尾截断检测 + 重合成保最优), tail-fades each piece, and joins them with
    0.30s of silence between sentences. Reports 0..90 progress via on_progress.
    Raises RuntimeError if no audio was produced.
    """
    sents = split_sentences(text)
    tmp = tempfile.mkdtemp(prefix="speakbox_")
    try:
        pieces = []
        for i, s in enumerate(sents):
            on_progress(int(i / len(sents) * 90))
            data, _rms = synth_one(s, i, os.path.join(tmp, f"s{i}.wav"),
                                   voice, retries=3, thresh=0.08)
            if data is None:
                continue
            pieces.append(apply_fade(data, 0.02))
        if not pieces:
            raise RuntimeError("synthesis produced no audio")
        gap = silence(0.30)
        parts = []
        for i, p in enumerate(pieces):
            if i:
                parts.append(gap)
            parts.append(p)
        full = np.concatenate(parts).astype("float32")
        sf.write(out_path, full, SAMPLE_RATE)
        on_progress(90)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def post_progress(task_id, payload):
    """Best-effort POST of a progress/status report. Swallows network errors
    so a flaky server can never crash the worker loop. payload is one of:
        {"status":"generating","progress":N}
        {"status":"uploading"}
        {"status":"failed","error":"..."}
    """
    try:
        requests.post(
            f"{BASE_URL}/api/worker/tasks/{task_id}/progress",
            headers=HEADERS,
            json=payload,
            timeout=10,
        )
    except requests.RequestException as e:
        log(f"[warn] progress POST failed id={task_id}: {e}")


def upload_wav(task_id, wav_path):
    """Upload the finished WAV as a raw audio/wav body. Server marks the task
    done on success. Raises on a non-2xx response so the caller fails the task."""
    with open(wav_path, "rb") as f:
        body = f.read()
    r = requests.post(
        f"{BASE_URL}/api/worker/tasks/{task_id}/wav",
        headers={**HEADERS, "Content-Type": "audio/wav"},
        data=body,
        timeout=120,
    )
    r.raise_for_status()


def main():
    if not WORKER_TOKEN:
        log("[fatal] WORKER_TOKEN is required (sent as X-Worker-Token header). "
            "Set it in the environment and restart.")
        sys.exit(1)

    log("=" * 60)
    log("[startup] speakbox worker")
    log(f"[startup] base_url   = {BASE_URL}")
    log(f"[startup] poll       = {POLL_INTERVAL_SEC:.2f}s")
    log(f"[startup] token set  = {'yes' if WORKER_TOKEN else 'no'}")
    log("[startup] note: CosyVoice model loads ~8s on the 1st task only "
        "(resident process keeps it warm afterwards)")
    log("=" * 60)

    while True:
        # --- claim next task ---
        try:
            r = requests.get(
                f"{BASE_URL}/api/worker/next",
                headers=HEADERS,
                timeout=30,
            )
        except requests.RequestException as e:
            # server may be restarting / network blip — never crash, just retry
            log(f"[warn] poll failed (server may be restarting): {e}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        if r.status_code == 401:
            log("[fatal] 401 unauthorized — WORKER_TOKEN does not match the "
                "server's. Fix the token and restart.")
            sys.exit(1)
        if r.status_code == 204:
            # no task queued
            time.sleep(POLL_INTERVAL_SEC)
            continue
        if r.status_code != 200:
            log(f"[warn] unexpected status {r.status_code} from /next: "
                f"{r.text[:200]}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        try:
            task = r.json()
            task_id = task["id"]
            text = task["text"]
            voice = task["voice"]
        except (ValueError, KeyError) as e:
            log(f"[warn] bad task payload from /next ({e}): {r.text[:200]}")
            time.sleep(POLL_INTERVAL_SEC)
            continue

        log(f"[claimed] id={task_id} voice={voice} chars={len(text)} "
            f"text='{text[:40]}{'…' if len(text) > 40 else ''}'")

        # --- synthesize + upload ---
        out = None
        try:
            fd, out = tempfile.mkstemp(prefix=f"speakbox_{task_id}_", suffix=".wav")
            os.close(fd)

            sents = split_sentences(text)
            log(f"[synth] id={task_id} sentences={len(sents)}")

            def on_progress(p, _id=task_id):
                post_progress(_id, {"status": "generating", "progress": p})

            render_to_wav(text, voice, out, on_progress)

            log(f"[uploading] id={task_id}")
            post_progress(task_id, {"status": "uploading"})
            upload_wav(task_id, out)

            log(f"[done] id={task_id}")
        except Exception as e:  # noqa: BLE001 — loop must survive any task error
            try:
                post_progress(task_id, {"status": "failed", "error": str(e)})
            except Exception:  # noqa: BLE001
                pass
            log(f"[fail] id={task_id} err={e}")
        finally:
            if out and os.path.exists(out):
                try:
                    os.remove(out)
                except OSError:
                    pass


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\n[shutdown] interrupted — exiting")
        sys.exit(0)
