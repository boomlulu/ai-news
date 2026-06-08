# Speakbox Worker (Mac-resident)

Long-lived TTS worker that runs on the Mac. It long-polls the Go server, synthesizes
audio locally by reusing `tts/speak.py` (CosyVoice), and uploads the finished WAV back.

The CosyVoice model loads **once** — this is a resident process, so the ~8s model load
only happens on the **first** task; every task afterwards reuses the warm model.

## Run

```sh
PYTHONPATH=/Users/boom/Demo/AINews \
  WORKER_TOKEN=<token> \
  SPEAKBOX_BASE_URL=http://124.220.6.174:8200 \
  /Users/boom/Demo/AINews/tts/.venv/bin/python \
  /Users/boom/Demo/AINews/speakbox/worker/worker.py
```

`PYTHONPATH=<repo root>` is required so `import tts` resolves. The venv
(`tts/.venv`, py3.10) already has numpy / soundfile / requests.

## Environment variables

| Var                 | Default                        | Notes                                                                 |
| ------------------- | ------------------------------ | --------------------------------------------------------------------- |
| `SPEAKBOX_BASE_URL` | `http://124.220.6.174:8200`    | Server base URL.                                                      |
| `WORKER_TOKEN`      | *(required, no default)*       | Sent as `X-Worker-Token` on every request. Missing → print + exit(1). |
| `POLL_INTERVAL_SEC` | `1.0`                          | Seconds to sleep between empty polls.                                 |

## Behavior

Resident loop, never crashes on a single task error:

1. `GET /api/worker/next` (header `X-Worker-Token`):
   - `200` → task `{id, text, voice}` → synthesize.
   - `204` → no task → sleep `POLL_INTERVAL_SEC`, poll again.
   - `401` → token mismatch → log + `exit(1)`.
   - network error → log + sleep + retry (server may be restarting).
2. Synthesize via `render_to_wav` (reuses `split_sentences` / `synth_one` /
   `apply_fade` / `silence` from `tts/speak.py`); `synth_one` already does
   句尾截断检测 + 重合成保最优. Per-sentence progress reported as
   `POST .../progress {"status":"generating","progress":N}` (0..90).
3. `POST .../progress {"status":"uploading"}`, then
   `POST .../wav` (raw body, `Content-Type: audio/wav`) — server marks the task done.
4. On any failure: `POST .../progress {"status":"failed","error":...}`,
   log `[fail]`, and continue with the next task.

Output is 24kHz / mono / float32 WAV (matches the `tts` stack). Logs stream live
(`flush=True`): startup banner, then per-task `claimed` / `synth` / `uploading` /
`done` | `fail`.
