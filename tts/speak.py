"""Realtime read-aloud CLI (MVP, single file).

`python -m tts.speak "<text>"` → splits into sentences, a producer thread
synthesizes them sequentially (one persistent process so the CosyVoice model
loads ONCE), and the main thread prebuffers just enough audio (sized by RTF)
to start playing早 — well before all sentences are generated. One persistent
sounddevice.OutputStream gives seamless back-to-back playback.

Audio fmt: 24000 Hz / mono / float32 (matches tts_service output).

Run (needs PYTHONPATH=repo root for `import tts`):
    PYTHONPATH=/Users/boom/Demo/AINews tts/.venv/bin/python -m tts.speak "..."
"""
from __future__ import annotations

import argparse
import os
import queue
import re
import shutil
import sys
import tempfile
import threading
import time

import numpy as np
import soundfile as sf

from tts import tts_service

SAMPLE_RATE = 24000
CHANNELS = 1
# write to soundcard in fixed-size blocks so a long sentence can't hog the
# stream and we get tight underrun accounting.
WRITE_BLOCK = 2400  # 0.1s @ 24kHz


def log(msg: str) -> None:
    """Human metrics/logs → stderr (stdout stays clean of audio)."""
    print(msg, file=sys.stderr, flush=True)


def save_audio(path: str, pieces):
    """Write concatenated `pieces` (list of float32 ndarrays, played order) to
    `path` plus per-segment files <dir>/<stem>.seg{i:02d}.wav. 24kHz mono.
    Side artifact for review — never affects playback. Logs saved paths→stderr."""
    if not pieces:
        log(f"[save] nothing to save → {path}")
        return
    full = np.concatenate(pieces).astype("float32")
    sf.write(path, full, SAMPLE_RATE)
    log(f"[save] {path}  ({len(full)/SAMPLE_RATE:.2f}s)")
    root, _ = os.path.splitext(path)
    for i, piece in enumerate(pieces):
        seg_path = f"{root}.seg{i:02d}.wav"
        sf.write(seg_path, np.ascontiguousarray(piece, dtype="float32"), SAMPLE_RATE)
        log(f"[save] {seg_path}  ({len(piece)/SAMPLE_RATE:.2f}s)")


def split_sentences(text: str):
    """Split on Chinese/ASCII sentence terminators, keeping the terminator.
    No terminator → whole text is one sentence."""
    parts = re.split(r'(?<=[。！？；!?;])', text)
    sents = [p.strip() for p in parts if p and p.strip()]
    return sents if sents else ([text.strip()] if text.strip() else [])


class AudioQueue:
    """queue.Queue of float32 ndarrays + a lock-guarded counter of total
    enqueued audio seconds, so the consumer can wait for the prebuffer
    threshold via a Condition."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self._cond = threading.Condition()
        self.enqueued_sec = 0.0
        self.producer_done = False

    def put_audio(self, samples: np.ndarray):
        dur = len(samples) / SAMPLE_RATE
        self.q.put(samples)
        with self._cond:
            self.enqueued_sec += dur
            self._cond.notify_all()

    def mark_done(self):
        self.q.put(None)  # sentinel
        with self._cond:
            self.producer_done = True
            self._cond.notify_all()

    def wait_prebuffer(self, threshold: float):
        """Block until enqueued audio ≥ threshold OR producer is done."""
        with self._cond:
            while self.enqueued_sec < threshold and not self.producer_done:
                self._cond.wait()


def producer(sents, audio_q: AudioQueue, voice: str, tmpdir: str, state: dict):
    """Synthesize each sentence sequentially in this ONE process (model cached
    after first synth) and enqueue float32 audio. Failures are logged + skipped
    so the consumer never deadlocks (sentinel always sent at the end)."""
    for i, sent in enumerate(sents):
        out = os.path.join(tmpdir, f"seg_{i:03d}.wav")
        t0 = time.monotonic()
        try:
            res = tts_service.synthesize(
                text=sent, output_path=out,
                provider="cosyvoice", voice=voice, fallback="",
            )
        except Exception as e:  # noqa: BLE001 — never kill the producer
            log(f"[gen] seg {i} EXCEPTION ({time.monotonic()-t0:.2f}s): {e}")
            continue
        gen_dt = time.monotonic() - t0
        if not res.ok:
            log(f"[gen] seg {i} FAILED status={res.status} ({gen_dt:.2f}s) — skip")
            continue
        try:
            data, sr = sf.read(res.audio_path, dtype="float32", always_2d=False)
        except Exception as e:  # noqa: BLE001
            log(f"[gen] seg {i} READ FAILED ({e}) — skip")
            continue
        if data.ndim > 1:  # safety: downmix to mono
            data = data.mean(axis=1).astype("float32")
        dur = len(data) / sr if sr else 0.0
        log(f"[gen] seg {i} {gen_dt:.2f}s  audio={dur:.2f}s  sr={sr}  '{sent[:18]}'")
        audio_q.put_audio(data)
    state["t_gen_done"] = time.monotonic()
    audio_q.mark_done()
    log(f"[gen] ALL DONE @ +{state['t_gen_done']-state['t_start']:.2f}s")


def consume_realtime(audio_q: AudioQueue, B: float, device, state: dict,
                     collect=None):
    """Prebuffer to threshold B, then open ONE persistent OutputStream and
    write queued chunks back-to-back until the sentinel. Counts underruns
    (queue empty but sentinel not yet arrived). If `collect` is a list, each
    played segment ndarray is appended (played order) for --save."""
    audio_q.wait_prebuffer(B)
    state["t_open"] = time.monotonic()
    log(f"[play] t_open @ +{state['t_open']-state['t_start']:.2f}s "
        f"(prebuffered {audio_q.enqueued_sec:.2f}s, B={B:.2f}s)")

    import sounddevice as sd
    underruns = 0
    stream = sd.OutputStream(samplerate=SAMPLE_RATE, channels=CHANNELS,
                             dtype="float32", device=device)
    stream.start()
    try:
        while True:
            try:
                item = audio_q.q.get(timeout=0.05)
            except queue.Empty:
                # queue starved mid-playback before sentinel → underrun
                if not audio_q.producer_done:
                    underruns += 1
                    log("[play] UNDERRUN")
                continue
            if item is None:  # sentinel
                break
            if collect is not None:
                collect.append(item)
            # write in blocks so playback stays responsive / blocking is bounded
            buf = np.ascontiguousarray(item, dtype="float32")
            for off in range(0, len(buf), WRITE_BLOCK):
                stream.write(buf[off:off + WRITE_BLOCK])
    finally:
        stream.stop()
        stream.close()
    state["underruns"] = underruns


def consume_baseline(sents, voice: str, tmpdir: str, device, state: dict,
                     save=None):
    """对照: gen ALL first (cumulative), concat, THEN play. t_open = total gen."""
    pieces = []
    for i, sent in enumerate(sents):
        out = os.path.join(tmpdir, f"base_{i:03d}.wav")
        t0 = time.monotonic()
        res = tts_service.synthesize(text=sent, output_path=out,
                                     provider="cosyvoice", voice=voice, fallback="")
        gen_dt = time.monotonic() - t0
        if not res.ok:
            log(f"[base] seg {i} FAILED status={res.status} ({gen_dt:.2f}s) — skip")
            continue
        data, sr = sf.read(res.audio_path, dtype="float32", always_2d=False)
        if data.ndim > 1:
            data = data.mean(axis=1).astype("float32")
        log(f"[base] seg {i} {gen_dt:.2f}s  audio={len(data)/sr:.2f}s")
        pieces.append(data)
    state["t_gen_done"] = time.monotonic()
    state["t_open"] = state["t_gen_done"]  # baseline opens only after all gen
    log(f"[base] ALL GEN DONE / t_open @ +{state['t_open']-state['t_start']:.2f}s "
        f"(total gen = open moment)")
    if not pieces:
        log("[base] nothing to play")
        return
    full = np.concatenate(pieces).astype("float32")
    if save:
        save_audio(save, pieces)
    import sounddevice as sd
    sd.play(full, samplerate=SAMPLE_RATE, device=device)
    sd.wait()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="speak", description="realtime read-aloud (MVP)")
    ap.add_argument("text", nargs="?", help="text to read; missing → read stdin")
    ap.add_argument("--voice", default="my_voice_zh")
    ap.add_argument("--rtf", type=float, default=1.4,
                    help="real-time factor (gen_time/audio_time), fixed const")
    ap.add_argument("--speak-rate", type=float, default=4.6,
                    help="字/s, to estimate total audio duration")
    ap.add_argument("--safety", type=float, default=0.3,
                    help="extra prebuffer seconds")
    ap.add_argument("--baseline", action="store_true",
                    help="gen ALL then play (对照 only)")
    ap.add_argument("--device", type=int, default=None,
                    help="sounddevice output device id (default: system default)")
    ap.add_argument("--save", default=None,
                    help="save played audio (24kHz mono WAV) for review; "
                         "also dumps per-segment files")
    args = ap.parse_args(argv)

    text = args.text if args.text is not None else sys.stdin.read()
    text = (text or "").strip()
    if not text:
        log("[err] empty text")
        return 2

    sents = split_sentences(text)
    total_chars = sum(len(s) for s in sents)
    t_est = total_chars / args.speak_rate if args.speak_rate else 0.0
    # prebuffer threshold: how much audio we must bank so that, while it plays,
    # the producer (running at RTF) catches up — B = (1 − 1/RTF)·T_est + safety.
    B = max(0.0, (1.0 - 1.0 / args.rtf) * t_est) + args.safety

    log(f"[init] sentences={len(sents)} chars={total_chars} "
        f"T_est={t_est:.2f}s RTF={args.rtf} speak_rate={args.speak_rate}")
    log(f"[init] B = (1 - 1/{args.rtf})*{t_est:.2f} + {args.safety} = {B:.2f}s")
    log(f"[init] mode={'BASELINE' if args.baseline else 'MVP'} voice={args.voice}")

    tmpdir = tempfile.mkdtemp(prefix="speak_")
    state = {"t_start": time.monotonic(), "t_open": None,
             "t_gen_done": None, "underruns": 0}
    try:
        if args.baseline:
            consume_baseline(sents, args.voice, tmpdir, args.device, state,
                             save=args.save)
        else:
            audio_q = AudioQueue()
            prod = threading.Thread(
                target=producer,
                args=(sents, audio_q, args.voice, tmpdir, state),
                daemon=True,
            )
            prod.start()
            played = [] if args.save else None
            consume_realtime(audio_q, B, args.device, state, collect=played)
            prod.join()
            if args.save:
                save_audio(args.save, played)
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)

    wall = time.monotonic() - state["t_start"]
    t_open = state["t_open"]
    t_gen = state["t_gen_done"]
    log("=" * 56)
    if t_open is not None:
        log(f"[metric] t_open      = +{t_open - state['t_start']:.2f}s")
    if t_gen is not None:
        log(f"[metric] t_gen_done  = +{t_gen - state['t_start']:.2f}s")
    if t_open is not None and t_gen is not None:
        lead = t_gen - t_open
        if args.baseline:
            log(f"[metric] lead (t_gen_done - t_open) = {lead:.2f}s "
                f"(baseline: ≈0, opens after all gen)")
        else:
            ok = "OK" if t_open < t_gen else "WARN"
            log(f"[metric] 提前量 (t_gen_done - t_open) = {lead:.2f}s  "
                f"[{ok}: t_open {'<' if t_open < t_gen else '>='} t_gen_done]")
    if not args.baseline:
        log(f"[metric] underruns   = {state['underruns']}")
    log(f"[metric] wallclock   = {wall:.2f}s")
    log("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
