"""Provider-agnostic TTS interface. Business/pipeline code depends ONLY on this."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class TTSRequest:
    text: str                       # 播报稿正文 (TTS-clean plain text)
    output_path: str                # 目标音频路径 (.wav/.mp3)
    voice: str = "sweet_female_zh"  # 音色 profile 名 (resolved via config)
    speed: float = 1.0              # 语速倍率 (1.0=正常, <1 更慢)
    style: Optional[str] = None     # 风格, e.g. "warm_news"
    emotion: Optional[str] = None   # 情绪
    instruct: Optional[str] = None  # provider 级自然语言风格 prompt
    extra: dict = field(default_factory=dict)  # provider-specific params


@dataclass
class TTSResult:
    audio_path: Optional[str]       # 生成音频路径 (None on failure)
    status: str                     # "ok" | "error" | "unavailable"
    provider: str                   # 实际使用的 provider 名
    error: Optional[str] = None     # 错误信息
    meta: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class TTSProvider(ABC):
    """All TTS backends implement this. Swap providers w/o touching business code."""
    name: str = "base"

    def __init__(self, config: Optional[dict] = None):
        self.config = config or {}

    def is_available(self):
        """(usable: bool, reason: str). Check deps/weights WITHOUT raising."""
        return True, "ok"

    @abstractmethod
    def synthesize(self, req: TTSRequest) -> TTSResult:
        """text+voice+speed+style -> audio file. Never raise; return TTSResult."""
        raise NotImplementedError
