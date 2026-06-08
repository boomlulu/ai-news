"""DEFAULT provider: CosyVoice / CosyVoice2 (FunAudioLLM).
Lazy-imports the `cosyvoice` package so importing THIS module never fails when
CosyVoice isn't installed yet — is_available() reports the reason instead.
Business code never imports cosyvoice directly; only this provider does."""
from __future__ import annotations
import importlib.util
import os
import sys
from .base import TTSProvider, TTSRequest, TTSResult

_MODEL_CACHE = {}  # model_dir -> loaded model (avoid reloading per call)


def _split_for_tts(text, max_chars=32):
    """Split into SHORT sentences so CosyVoice frontend can't re-merge into
    60-80 token blocks (which make the 0.5B model over-generate). Splits on
    newlines + sentence terminators, further splits over-long sentences on
    commas, merges tiny fragments forward."""
    import re
    segs = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        for p in re.split(r'(?<=[。！？!?；;])', line):
            p = p.strip()
            if not p:
                continue
            if len(p) > max_chars:
                buf = ""
                for s in re.split(r'(?<=[，,：:、])', p):
                    if buf and len(buf) + len(s) > max_chars:
                        segs.append(buf)
                        buf = s
                    else:
                        buf += s
                if buf.strip():
                    segs.append(buf)
            else:
                segs.append(p)
    out = []
    for s in segs:
        s = s.strip()
        if not s:
            continue
        if out and len(out[-1]) < 6:
            out[-1] += s
        else:
            out.append(s)
    return out


def _merge_short(segs, max_chars, min_seg):
    """Merge sub-min_seg fragments with a neighbor (forward first, then backward)
    as long as the merged length stays <= max_chars. Prevents ultra-short segments
    that make CosyVoice2 zero_shot over-generate garbage breath artifacts. Length
    cap keeps each synth unit short enough to avoid the 0.5B over-generation runaway."""
    if not segs:
        return segs
    # forward: pull following fragments into a too-short seg while it fits
    fwd = []
    i = 0
    while i < len(segs):
        seg = segs[i]
        while len(seg) < min_seg and i + 1 < len(segs) and len(seg) + len(segs[i + 1]) <= max_chars:
            i += 1
            seg = seg + segs[i]
        fwd.append(seg)
        i += 1
    # backward: any still-short seg merges into the previous if it fits
    out = []
    for seg in fwd:
        if out and len(seg) < min_seg and len(out[-1]) + len(seg) <= max_chars:
            out[-1] = out[-1] + seg
        else:
            out.append(seg)
    return out


def _split_with_gaps(text, max_chars, comma_gap, sentence_gap, para_gap, min_seg=12):
    """Paragraph-aware, boundary-typed inter-segment silence. Blank lines split
    paragraphs (news items / sections). Within a paragraph, _split_for_tts keeps
    short segments for synth quality, but the silence AFTER each segment depends
    on its boundary: comma-class end -> comma_gap (flow), 。！？ end -> sentence_gap,
    last segment of a paragraph -> para_gap (a real breath). Last piece overall: 0."""
    import re
    out = []
    for para in re.split(r'\n[ \t]*\n', text):
        if not para.strip():
            continue
        base = _split_for_tts(para, max_chars)
        base = _merge_short(base, max_chars, min_seg)
        for si, seg in enumerate(base):
            if si == len(base) - 1:
                gap = para_gap
            else:
                tail = seg.rstrip()
                last = tail[-1] if tail else ''
                gap = sentence_gap if last in '。！？!?…' else comma_gap
            out.append((seg, gap))
    if out:
        out[-1] = (out[-1][0], 0.0)
    return out


_SENT_END = '。！？!?；;…'


def _split_units(text, unit, sentence_gap, para_gap):
    """Larger synthesis units: feed whole sentences (commas kept INSIDE, model's own
    prosody handles them) or whole paragraphs. NO comma-splitting / merge / trim needed.
    unit='paragraph': one unit per blank-line paragraph; gap=para_gap between.
    unit='sentence': split each paragraph at sentence terminators (。！？；…, terminator
    kept); gap=sentence_gap within a paragraph, para_gap at paragraph end.
    Returns list[(text, gap_after)], last overall gap 0.0."""
    import re
    paras = [p for p in re.split(r'\n[ \t]*\n', text) if p.strip()]
    out = []
    for para in paras:
        block = re.sub(r'\s*\n\s*', '', para).strip()  # join multi-line paragraph into one block
        if not block:
            continue
        if unit == 'paragraph':
            out.append([block, para_gap])
        else:  # sentence
            parts = re.split(r'([%s]+)' % re.escape(_SENT_END), block)
            sents, buf = [], ''
            for i, p in enumerate(parts):
                buf += p
                if i % 2 == 1:        # terminator group -> close sentence
                    if buf.strip():
                        sents.append(buf.strip())
                    buf = ''
            if buf.strip():
                sents.append(buf.strip())
            if not sents:
                sents = [block]
            for si, s in enumerate(sents):
                out.append([s, para_gap if si == len(sents) - 1 else sentence_gap])
    if out:
        out[-1][1] = 0.0
    return [(t, g) for t, g in out]


def _install_tn_shim_if_needed():
    """CosyVoice frontend imports WeTextProcessing (`tn.*`, needs pynini) at init.
    If absent (common on macOS), inject identity-normalizer stubs so model init
    works. Our broadcast script is already TTS-normalized, so TN is a no-op."""
    import importlib.util
    import sys
    import types
    if importlib.util.find_spec("tn") is not None:
        return False  # real WeTextProcessing present
    class _Identity:
        def __init__(self, *a, **k):
            pass
        def normalize(self, text):
            return text
    mods = {}
    for name in ("tn", "tn.chinese", "tn.english"):
        m = types.ModuleType(name)
        m.__path__ = []
        mods[name] = m
    zhn = types.ModuleType("tn.chinese.normalizer"); zhn.Normalizer = _Identity
    enn = types.ModuleType("tn.english.normalizer"); enn.Normalizer = _Identity
    mods["tn.chinese.normalizer"] = zhn
    mods["tn.english.normalizer"] = enn
    for k, v in mods.items():
        sys.modules.setdefault(k, v)
    return True


def _trim_speech(wav, sr, thresh_db=-28.0, win_ms=20, margin_ms=50):
    """Trim leading/trailing non-speech (silence + detached breath artifacts) from
    a segment waveform [1, N] using a windowed-RMS energy gate. Keeps a small margin
    so soft consonant tails aren't clipped. If the whole clip is below threshold,
    returns it unchanged (never nuke to empty)."""
    import torch
    if wav is None or wav.numel() == 0:
        return wav
    n = wav.shape[-1]
    win = max(1, int(sr * win_ms / 1000))
    nf = n // win
    if nf < 1:
        return wav
    frames = wav[0, :nf * win].reshape(nf, win)
    rms = frames.pow(2).mean(dim=1).clamp_min(1e-10).sqrt()
    thr = 10.0 ** (thresh_db / 20.0)
    above = (rms >= thr).nonzero().flatten()
    if above.numel() == 0:
        return wav
    first = int(above[0].item())
    last = int(above[-1].item())
    margin = int(sr * margin_ms / 1000)
    start = max(0, first * win - margin)
    end = min(n, (last + 1) * win + margin)
    return wav[:, start:end]


class CosyVoiceProvider(TTSProvider):
    name = "cosyvoice"

    def _cv(self):
        return self.config.get("cosyvoice", {})

    def _model_dir(self):
        return os.path.expanduser(self._cv().get("model_dir", ""))

    def _repo_dir(self):
        return os.path.expanduser(self._cv().get("repo_dir", ""))

    def _ensure_path(self):
        repo = self._repo_dir()
        if repo and os.path.isdir(repo):
            for p in (repo, os.path.join(repo, "third_party", "Matcha-TTS")):
                if os.path.isdir(p) and p not in sys.path:
                    sys.path.insert(0, p)

    def is_available(self):
        md = self._model_dir()
        if not md or not os.path.isdir(md):
            return False, f"model_dir missing: {md or '(unset)'} — run tts/install_cosyvoice.sh"
        self._ensure_path()
        if importlib.util.find_spec("cosyvoice") is None:
            return False, "python pkg `cosyvoice` not importable — activate tts/.venv or run install_cosyvoice.sh"
        return True, "ok"

    @staticmethod
    def _has_real_tn():
        """True if a real text-normalizer backend is importable (WeTextProcessing
        `tn`, or the newer pure-python `wetext`). The vendored frontend prefers
        `wetext` (no pynini needed); when present, enabling text_frontend keeps
        sentence-splitting working without depending on pynini.

        NOTE: the tn-shim may have already injected a stub `tn` into sys.modules
        (with __spec__=None, which makes importlib.find_spec raise), so detect the
        real `tn` only when it is NOT our injected stub, and probe `wetext` safely."""
        import importlib.util
        import sys
        tn_mod = sys.modules.get("tn")
        # A stub we injected has __spec__ is None; a real WeTextProcessing has a spec.
        has_tn = tn_mod is not None and getattr(tn_mod, "__spec__", None) is not None
        if not has_tn and tn_mod is None:
            try:
                has_tn = importlib.util.find_spec("tn") is not None
            except (ValueError, ModuleNotFoundError):
                has_tn = False
        has_wetext = "wetext" in sys.modules
        if not has_wetext:
            try:
                has_wetext = importlib.util.find_spec("wetext") is not None
            except (ValueError, ModuleNotFoundError):
                has_wetext = False
        return has_tn or has_wetext

    def _load_model(self, model_dir=None, model_type=None):
        # Per-voice override: a voice's `cosyvoice` block can pin its own
        # model_dir/model_type (arrives via req.extra). Fall back to top-level
        # config when not given. Cache keyed by the RESOLVED model_dir so the
        # SFT v1 model (中文女) and the 0.5B v2 model coexist without reloads.
        md = os.path.expanduser(model_dir or self._cv().get("model_dir", ""))
        mtype = model_type or self._cv().get("model_type", "cosyvoice2")
        if md in _MODEL_CACHE:
            return _MODEL_CACHE[md]
        self._ensure_path()
        self._shimmed = _install_tn_shim_if_needed()
        if mtype == "cosyvoice2":
            from cosyvoice.cli.cosyvoice import CosyVoice2 as M
            model = M(md, load_jit=False, load_trt=False, fp16=False)
        else:
            from cosyvoice.cli.cosyvoice import CosyVoice as M
            model = M(md)
        self._force_float32_cpu(model)
        _MODEL_CACHE[md] = model
        return model

    @staticmethod
    def _force_float32_cpu(model):
        """The CosyVoice2 llm.pt checkpoint may load in bfloat16 (newer transformers
        keeps native dtype), but on CPU the embeddings/inputs stay float32 -> a
        'mat1 and mat2 must have the same dtype (Float vs BFloat16)' error in the
        Qwen2 LLM. With fp16=False on CPU we want everything float32. Cast the inner
        sub-models in place. Vendor code is left untouched."""
        try:
            import torch
        except Exception:
            return
        if torch.cuda.is_available():
            return  # GPU path keeps its own dtype handling
        inner = getattr(model, "model", None)
        if inner is None:
            return
        for attr in ("llm", "flow", "hift"):
            sub = getattr(inner, attr, None)
            if sub is not None and hasattr(sub, "to"):
                try:
                    sub.to(torch.float32)
                except Exception:
                    pass

    def synthesize(self, req: TTSRequest) -> TTSResult:
        ok, why = self.is_available()
        if not ok:
            return TTSResult(None, "unavailable", self.name, why)
        try:
            import torch
            import torchaudio
            from cosyvoice.utils.file_utils import load_wav
            cv = self._cv()
            # Per-voice model override: the voice's `cosyvoice` block may pin its
            # own model_dir/model_type (e.g. sft 中文女 -> CosyVoice-300M-SFT v1
            # while zero_shot voices stay on CosyVoice2-0.5B v2). mdir should
            # already be absolute from the service; expanduser is just safety.
            mdir = os.path.expanduser(req.extra.get("model_dir") or cv.get("model_dir", ""))
            mtype = req.extra.get("model_type") or cv.get("model_type", "cosyvoice2")
            model = self._load_model(mdir, mtype)
            mode = req.extra.get("mode", cv.get("synth_mode", "instruct2"))
            instruct = (req.instruct or req.extra.get("instruct")
                        or self.config.get("default_instruct", "中文普通话，年轻女性，声音甜美，语速中等偏慢，温暖如早间新闻主播。"))
            speed = float(req.speed or 1.0)
            out = os.path.abspath(req.output_path)
            os.makedirs(os.path.dirname(out) or ".", exist_ok=True)

            # text_frontend controls CosyVoice's built-in text normalization + sentence
            # splitting. With the tn-shim active (no real WeTextProcessing), TN itself
            # is a no-op anyway. Enable the frontend only if a real normalizer (`tn` or
            # the newer pure-python `wetext`) is importable — preserving sentence splitting
            # where possible; otherwise pass it through (script is already TTS-normalized).
            tf = (not getattr(self, "_shimmed", False)) or self._has_real_tn()

            # Split text into SHORT sentences ourselves and call inference PER
            # SEGMENT. The vendored CosyVoice frontend re-merges per-line input
            # into 60-80 token blocks (split_paragraph token_min_n=60,token_max_n=80),
            # which makes CosyVoice2-0.5B over-generate (~0.6 s/char). The frontend
            # cannot merge a single short input, so per-segment inference keeps each
            # generation short. text_frontend stays True so numbers/%/letters still
            # normalize within each segment.
            comma_gap = float(req.extra.get("comma_gap_sec", cv.get("comma_gap_sec", 0.0)))
            sentence_gap = float(req.extra.get("sentence_gap_sec", cv.get("sentence_gap_sec", 0.12)))
            para_gap = float(req.extra.get("paragraph_gap_sec", cv.get("paragraph_gap_sec", 0.5)))
            unit = req.extra.get("synth_unit", cv.get("synth_unit", "fragment"))
            if unit in ("sentence", "paragraph"):
                pieces = _split_units(req.text, unit, sentence_gap, para_gap)
            elif cv.get("per_line", True):
                pieces = _split_with_gaps(req.text, cv.get("seg_max_chars", 32), comma_gap, sentence_gap, para_gap, cv.get("min_seg_chars", 12))
            else:
                pieces = [(req.text, 0.0)]
            if not pieces:
                pieces = [(req.text, 0.0)]
            segs = [p[0] for p in pieces]
            gaps = [p[1] for p in pieces]
            print(f"[cosyvoice] {len(segs)} segs unit={unit}, pacing comma={comma_gap} sent={sentence_gap} para={para_gap}", file=sys.stderr)

            sr = model.sample_rate
            trim_on = bool(req.extra.get("trim_segment_silence", cv.get("trim_segment_silence", True)))
            trim_thresh = float(req.extra.get("trim_thresh_db", cv.get("trim_thresh_db", -40.0)))
            trim_margin = float(req.extra.get("trim_margin_ms", cv.get("trim_margin_ms", 60.0)))
            _sil = {}
            def _silence(sec):
                if sec not in _sil:
                    _sil[sec] = torch.zeros(1, max(1, int(sec * sr)))
                return _sil[sec]
            chunks = []
            def _emit_seg_chunks(seg_chunks, gap_after):
                if seg_chunks:
                    seg_audio = torch.cat(seg_chunks, dim=1) if len(seg_chunks) > 1 else seg_chunks[0]
                    if trim_on:
                        seg_audio = _trim_speech(seg_audio, sr, thresh_db=trim_thresh, margin_ms=trim_margin)
                    chunks.append(seg_audio)
                if gap_after > 0:
                    chunks.append(_silence(gap_after))

            if mode == "sft":
                spk_id = req.extra.get("spk_id", "中文女")
                for i, seg in enumerate(segs):
                    seg_chunks = []
                    for o in model.inference_sft(seg, spk_id, stream=False, speed=speed,
                                                 text_frontend=tf):
                        sp = o["tts_speech"]
                        print(f"[cosyvoice] seg {i} yield speech len {sp.shape[-1]/sr:.2f}s",
                              file=sys.stderr)
                        seg_chunks.append(sp)
                    _emit_seg_chunks(seg_chunks, gaps[i])
            else:
                ref = os.path.expanduser(req.extra.get("prompt_wav") or cv.get("prompt_wav", ""))
                if not ref or not os.path.isfile(ref):
                    return TTSResult(None, "error", self.name,
                                     f"prompt_wav missing for mode={mode}: {ref}")
                # The vendored CosyVoice2 frontend re-loads the prompt wav internally
                # (inference_instruct2 -> _extract_speech_feat -> load_wav(prompt_wav)),
                # so it expects a FILE PATH. Older CosyVoice APIs expected a pre-loaded
                # 16k tensor instead. Try the path first (current vendor), then fall back
                # to a loaded tensor for older builds. (Passing a Tensor to the newer
                # torchaudio->torchcodec load() raises, hence the path-first order.)
                prompt_path = ref
                prompt_16k = load_wav(ref, 16000)
                ptext = req.extra.get("prompt_text", cv.get("prompt_text", ""))

                def _infer_seg(seg, prompt_arg):
                    if mode == "instruct2":
                        return model.inference_instruct2(seg, instruct, prompt_arg,
                                                         stream=False, speed=speed,
                                                         text_frontend=tf)
                    elif mode == "zero_shot":
                        return model.inference_zero_shot(seg, ptext, prompt_arg,
                                                         stream=False, speed=speed,
                                                         text_frontend=tf)
                    else:
                        return None

                if mode not in ("instruct2", "zero_shot"):
                    return TTSResult(None, "error", self.name, f"unknown mode {mode}")

                # Pick the working prompt form once (path-first then tensor), reuse it
                # for all remaining segments to avoid retrying the failing form each time.
                prompt_arg = None
                for i, seg in enumerate(segs):
                    seg_chunks = []
                    if prompt_arg is not None:
                        gen = _infer_seg(seg, prompt_arg)
                        for o in gen:
                            sp = o["tts_speech"]
                            print(f"[cosyvoice] seg {i} yield speech len {sp.shape[-1]/sr:.2f}s",
                                  file=sys.stderr)
                            seg_chunks.append(sp)
                    else:
                        for cand in (prompt_path, prompt_16k):
                            try:
                                seg_chunks = []
                                gen = _infer_seg(seg, cand)
                                for o in gen:
                                    sp = o["tts_speech"]
                                    print(f"[cosyvoice] seg {i} yield speech len {sp.shape[-1]/sr:.2f}s",
                                          file=sys.stderr)
                                    seg_chunks.append(sp)
                                prompt_arg = cand  # this form works; lock it in
                                break
                            except Exception:
                                seg_chunks = []
                                if cand is prompt_16k:
                                    raise  # both forms failed
                                # path form failed -> retry with loaded tensor (older API)
                    _emit_seg_chunks(seg_chunks, gaps[i])

            if not chunks:
                return TTSResult(None, "error", self.name, "no audio produced")
            audio = torch.cat(chunks, dim=1)
            wav = out if out.lower().endswith(".wav") else out + ".wav"
            torchaudio.save(wav, audio, model.sample_rate)
            if wav != out:
                import shutil
                import subprocess
                ff = shutil.which("ffmpeg")
                if ff:
                    subprocess.run([ff, "-y", "-i", wav, out],
                                   check=True, capture_output=True)
                    os.remove(wav)
                else:
                    out = wav
            return TTSResult(out, "ok", self.name,
                             meta={"mode": mode, "segments": len(segs),
                                   "sample_rate": getattr(model, "sample_rate", None)})
        except Exception as e:
            import traceback
            return TTSResult(None, "error", self.name, f"{e}\n{traceback.format_exc()}")
