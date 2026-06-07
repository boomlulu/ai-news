"""Facade over pluggable TTS providers. Pipeline code calls ONLY this.
Resolves named voice profiles + speed/style from config.json, picks provider,
optional fallback chain. Never raises on synth failure — returns TTSResult.

Example (matches project spec):
    from tts import tts_service
    tts_service.synthesize(
        text_path="tts/samples/daily-ai-news-2026-06-07-script.txt",
        output_path="tts/samples/daily-ai-news-2026-06-07.wav",
        provider="cosyvoice", voice="sweet_female_zh", speed=0.95, style="warm_news")
"""
from __future__ import annotations
import json
import os
from typing import Optional
from .providers import get_provider, TTSRequest, TTSResult

_DEF_CONFIG = os.path.join(os.path.dirname(__file__), "config.json")


class TTSService:
    def __init__(self, config_path: Optional[str] = None):
        self.config_path = config_path or _DEF_CONFIG
        with open(self.config_path, "r", encoding="utf-8") as f:
            self.config = json.load(f)
        self.base_dir = os.path.dirname(os.path.abspath(self.config_path))  # tts/
        self.root = os.path.dirname(self.base_dir)                          # project root

    def _abs(self, p: str) -> str:
        if not p:
            return p
        p = os.path.expanduser(p)
        return p if os.path.isabs(p) else os.path.join(self.root, p)

    def _resolve(self, provider, voice, speed, style, emotion, extra):
        vp = self.config.get("voices", {}).get(voice, {})
        eff_speed = speed if speed is not None else vp.get("speed", 1.0)
        eff_style = style if style is not None else vp.get("style")
        pv = dict(vp.get(provider, {}))
        if "prompt_wav" in pv:
            pv["prompt_wav"] = self._abs(pv["prompt_wav"])
        instruct = pv.pop("instruct", None) or self.config.get("default_instruct")
        merged = dict(pv)
        merged.update(extra or {})
        return eff_speed, eff_style, emotion, instruct, merged

    def _make_provider(self, name):
        cfg = dict(self.config)
        cv = dict(cfg.get("cosyvoice", {}))
        for k in ("repo_dir", "model_dir", "venv_python", "prompt_wav"):
            if cv.get(k):
                cv[k] = self._abs(cv[k])
        cfg["cosyvoice"] = cv
        return get_provider(name, cfg)

    def synthesize(self, text: Optional[str] = None, *, text_path: Optional[str] = None,
                   output_path: str, provider: Optional[str] = None,
                   voice: str = "sweet_female_zh", speed: Optional[float] = None,
                   style: Optional[str] = None, emotion: Optional[str] = None,
                   fallback: Optional[str] = None, **extra) -> TTSResult:
        if text is None:
            if not text_path:
                raise ValueError("provide text or text_path")
            with open(self._abs(text_path), "r", encoding="utf-8") as f:
                text = f.read().strip()
        prov_name = provider or self.config.get("default_provider", "cosyvoice")
        fb = fallback if fallback is not None else self.config.get("fallback_provider")
        out = self._abs(output_path)

        chain = [prov_name] + ([fb] if fb and fb != prov_name else [])
        last = None
        for name in chain:
            sp, st, em, instruct, merged = self._resolve(name, voice, speed, style, emotion, extra)
            prov = self._make_provider(name)
            avail, why = prov.is_available()
            if not avail:
                last = TTSResult(None, "unavailable", name, why)
                continue
            req = TTSRequest(text=text, output_path=out, voice=voice, speed=sp,
                             style=st, emotion=em, instruct=instruct, extra=merged)
            res = prov.synthesize(req)
            if res.ok:
                return res
            last = res
        return last or TTSResult(None, "error", prov_name, "no provider available")


_default_service = None


def _svc():
    global _default_service
    if _default_service is None:
        _default_service = TTSService()
    return _default_service


def synthesize(**kwargs) -> TTSResult:
    return _svc().synthesize(**kwargs)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="synthesize broadcast script -> audio")
    ap.add_argument("--text-path")
    ap.add_argument("--text")
    ap.add_argument("--out", required=True)
    ap.add_argument("--provider")
    ap.add_argument("--voice", default="sweet_female_zh")
    ap.add_argument("--speed", type=float)
    ap.add_argument("--style")
    ap.add_argument("--fallback")
    a = ap.parse_args()
    r = TTSService().synthesize(text=a.text, text_path=a.text_path, output_path=a.out,
                                provider=a.provider, voice=a.voice, speed=a.speed,
                                style=a.style, fallback=a.fallback)
    print(json.dumps({"status": r.status, "provider": r.provider,
                      "audio_path": r.audio_path, "error": r.error, "meta": r.meta},
                     ensure_ascii=False, indent=2))
    raise SystemExit(0 if r.ok else 1)
