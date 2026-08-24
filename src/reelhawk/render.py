"""ffmpeg rendering: vertical crop, karaoke caption burn-in, loudness
normalization, and audio fades.

Modes:
  face      9:16 fill crop centered on the tracked face x
  zoom      tighter punch-in centered on (cx, cy)
  panorama  full frame letterboxed over a blurred, darkened copy of itself
            (the safe default, and mandatory for multi-speaker moments)

Audio is normalized to the configured integrated loudness (default -14 LUFS,
what the short-form platforms normalize to anyway) so clips do not whisper or
clip next to neighboring content.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from .config import CaptionConfig, RenderConfig
from .subtitles import build_ass


def probe_geometry(video: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "json",
            str(video),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    stream = json.loads(result.stdout)["streams"][0]
    return int(stream["width"]), int(stream["height"])


def _filter_graph(
    mode: str,
    cfg: RenderConfig,
    src_w: int,
    src_h: int,
    duration: float,
    crop_cx: float | None,
    crop_cy: float | None = None,
    crop_h: int | None = None,
) -> str:
    keep_h = src_h - cfg.strip_px
    out_w, out_h = cfg.width, cfg.height

    if mode == "zoom":
        ch = crop_h or int(keep_h * 0.75)
        cw = round(ch * out_w / out_h)
        cx = crop_cx if crop_cx is not None else src_w / 2
        cy = crop_cy if crop_cy is not None else keep_h / 2
        x = int(max(0, min(src_w - cw, cx - cw / 2)))
        y = int(max(0, min(keep_h - ch, cy - ch / 2)))
        video = f"[0:v]crop={cw}:{ch}:{x}:{y},scale={out_w}:{out_h}[vout]"
    elif mode == "face":
        crop_w = round(keep_h * out_w / out_h)
        cx = crop_cx if crop_cx is not None else src_w / 2
        x = int(max(0, min(src_w - crop_w, cx - crop_w / 2)))
        video = f"[0:v]crop={crop_w}:{keep_h}:{x}:0,scale={out_w}:{out_h}[vout]"
    else:  # panorama
        video = (
            f"[0:v]split=2[bg][fg];"
            f"[bg]crop={src_w}:{keep_h}:0:0,scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=40:5,eq=brightness=-0.25[bgb];"
            f"[fg]crop={src_w}:{keep_h}:0:0,scale={out_w}:-2[fgs];"
            f"[bgb][fgs]overlay=0:(main_h-overlay_h)/2-140[vout]"
        )

    fade_out = max(0.0, duration - cfg.fade_seconds)
    audio = (
        f"[0:a]afade=t=in:d={cfg.fade_seconds},"
        f"afade=t=out:st={fade_out:.2f}:d={cfg.fade_seconds},"
        f"loudnorm=I={cfg.loudness_lufs}:TP=-1.5:LRA=11[aout]"
    )
    return video + ";" + audio


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {result.stderr[-2000:]}")


def render_clip(
    source: Path,
    workdir: Path,
    cid: str,
    start: float,
    end: float,
    mode: str,
    crop_cx: float | None,
    render_cfg: RenderConfig,
    caption_cfg: CaptionConfig,
    words: list[dict],
    fonts_dir: Path | None,
) -> Path:
    duration = end - start
    src_w, src_h = probe_geometry(source)
    nosub = workdir / f"clip-{cid}-nosub.mp4"

    _run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-to",
            f"{end:.3f}",
            "-i",
            str(source),
            "-filter_complex",
            _filter_graph(mode, render_cfg, src_w, src_h, duration, crop_cx),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-r",
            str(render_cfg.fps),
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(render_cfg.crf),
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-ar",
            "44100",
            "-ac",
            "2",
            str(nosub),
        ]
    )

    out = workdir / f"clip-{cid}.mp4"
    if caption_cfg.enabled and words:
        ass_path = workdir / f"captions-{cid}.ass"
        build_ass(words, duration, ass_path, caption_cfg, render_cfg.width, render_cfg.height)
        ass_esc = str(ass_path).replace(":", r"\:").replace("'", r"\'")
        vf = f"ass={ass_esc}"
        if fonts_dir is not None and fonts_dir.exists():
            fonts_esc = str(fonts_dir).replace(":", r"\:").replace("'", r"\'")
            vf += f":fontsdir={fonts_esc}"
        _run(
            [
                "ffmpeg",
                "-y",
                "-loglevel",
                "error",
                "-i",
                str(nosub),
                "-vf",
                vf,
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(render_cfg.crf),
                "-c:a",
                "copy",
                str(out),
            ]
        )
        nosub.unlink()
    else:
        nosub.rename(out)

    (workdir / f"clip-{cid}.render.json").write_text(
        json.dumps(
            {
                "cid": cid,
                "start": start,
                "end": end,
                "duration": round(duration, 2),
                "mode": mode,
                "crop_cx": crop_cx,
                "source_geometry": [src_w, src_h],
            }
        )
    )
    return out
