from __future__ import annotations
from .base import TTSProvider, TTSRequest, TTSResult
from .cosyvoice import CosyVoiceProvider
from .macsay import MacSayProvider

PROVIDERS = {
    "cosyvoice": CosyVoiceProvider,
    "macsay": MacSayProvider,
}


def get_provider(name: str, config: dict) -> TTSProvider:
    if name not in PROVIDERS:
        raise KeyError(f"unknown TTS provider '{name}'. known: {list(PROVIDERS)}")
    return PROVIDERS[name](config)


__all__ = ["TTSProvider", "TTSRequest", "TTSResult", "PROVIDERS", "get_provider"]
