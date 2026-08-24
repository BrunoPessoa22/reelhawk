"""Configuration for a reelhawk run.

Everything is a pydantic model loaded from a YAML file (reelhawk.yaml by
default) with sane defaults, so `reelhawk run <url>` works with no config at
all. Secrets (ANTHROPIC_API_KEY, IG_ACCESS_TOKEN, IG_USER_ID) come from the
environment only and are never stored in config files.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class WhisperConfig(BaseModel):
    model: str = "large-v3-turbo"
    device: str = "auto"
    compute_type: str = "auto"
    language: str | None = None  # None = autodetect


class ClipConfig(BaseModel):
    min_seconds: float = 15.0
    max_seconds: float = 75.0
    candidates: int = Field(default=6, ge=1, le=20, description="segments to ask the miner for")
    pad_seconds: float = 0.35  # breathing room added after the last word


class CaptionConfig(BaseModel):
    enabled: bool = True
    font: str = "Noto Sans Bold"
    font_size: int = 54
    margin_v: int = 300
    max_words_per_line: int = 3
    max_chars_per_line: int = 26
    base_color: str = "FFFFFF"  # ASS BGR hex: white
    highlight_color: str = "00D7FF"  # ASS BGR hex: yellow karaoke sweep


class RenderConfig(BaseModel):
    width: int = 1080
    height: int = 1920
    mode: str = "auto"  # auto | face | panorama | zoom
    strip_px: int = 0  # bottom band to remove (burned-in captions on some broadcasts)
    crf: int = 20
    fps: int = 30
    loudness_lufs: float = -14.0
    fade_seconds: float = 0.15


class FaceConfig(BaseModel):
    enabled: bool = False
    models_dir: Path = Path("models")
    embedding: Path | None = None  # optional target-person .npy from build_face_embedding.py
    identity_threshold: float = 0.45
    sample_step_seconds: float = 1.0


class GateConfig(BaseModel):
    min_caption_coverage: float = 0.55  # fraction of the clip covered by caption lines
    require_sentence_end: bool = True
    min_face_pct: float = 0.5  # enforced only when face tracking is enabled
    llm_review: bool = True  # ask the model whether the clip delivers its payoff


class PostConfig(BaseModel):
    mode: str = "export"  # export | instagram
    disclosure: str = ""  # appended to every caption when set, e.g. "Clip selected by an AI agent."
    hashtags: list[str] = Field(default_factory=list)
    # instagram mode: the Graph API needs the video at a public URL. upload_cmd is a
    # shell template run with {path}; it must print a public URL on stdout.
    upload_cmd: str | None = None
    ig_api_version: str = "v21.0"


class Config(BaseModel):
    workdir: Path = Path("reelhawk-data")
    model: str = "claude-opus-5"
    whisper: WhisperConfig = WhisperConfig()
    clip: ClipConfig = ClipConfig()
    captions: CaptionConfig = CaptionConfig()
    render: RenderConfig = RenderConfig()
    face: FaceConfig = FaceConfig()
    gate: GateConfig = GateConfig()
    post: PostConfig = PostConfig()

    @classmethod
    def load(cls, path: Path | None) -> "Config":
        if path is None:
            default = Path("reelhawk.yaml")
            path = default if default.exists() else None
        if path is None:
            return cls()
        data = yaml.safe_load(Path(path).read_text()) or {}
        return cls.model_validate(data)
