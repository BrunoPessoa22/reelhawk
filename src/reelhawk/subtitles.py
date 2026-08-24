"""Karaoke ASS subtitles: white text with a per-word color sweep, grouped into
short lines that never outrun the reader.

The style ships tuned for 1080x1920 vertical video: bold sans, max 3 words per
line, line breaks forced by both word count and character width, word timing
driven by the transcriber's word timestamps via ASS \\kf tags.
"""

from __future__ import annotations

from pathlib import Path

from .config import CaptionConfig

ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
ScaledBorderAndShadow: yes
WrapStyle: 2

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Karaoke,{font},{size},&H00{base},&H00{highlight},&H00000000,&H88000000,1,0,0,0,100,100,0,0,1,6,3,2,60,60,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

MAX_LINE_SECONDS = 2.0


def _fmt_ts(t: float) -> str:
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _sanitize(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")")


def group_words_into_lines(
    words: list[dict],
    duration: float,
    max_words_per_line: int = 3,
    max_chars: int = 26,
) -> list[dict]:
    """Chunk clip-relative words into caption lines.

    A line closes when it reaches max_words_per_line, would exceed max_chars,
    or would span more than MAX_LINE_SECONDS on screen.
    """
    lines: list[dict] = []
    i = 0
    while i < len(words):
        chunk = [words[i]]
        while len(chunk) < max_words_per_line and i + len(chunk) < len(words):
            nxt = words[i + len(chunk)]
            if (nxt["end"] - chunk[0]["start"]) > MAX_LINE_SECONDS:
                break
            joined = " ".join(w["word"] for w in chunk) + " " + nxt["word"]
            if len(joined) > max_chars:
                break
            chunk.append(nxt)
        start = chunk[0]["start"]
        end = min(chunk[-1]["end"], duration)
        if start >= duration:
            break
        line_words = []
        for w in chunk:
            w_start = max(0.0, w["start"] - start)
            w_end = max(w_start + 0.05, w["end"] - start)
            line_words.append((w_start, w_end, w["word"]))
        lines.append({"start": start, "end": end, "words": line_words})
        i += len(chunk)
    return lines


def build_karaoke_line(line: dict, base: str, highlight: str) -> str:
    parts = [f"{{\\1c&H{base}&}}"]
    cursor = 0.0
    for w_start, w_end, word in line["words"]:
        if w_start > cursor + 0.02:
            silent_cs = int((w_start - cursor) * 100)
            if silent_cs > 0:
                parts.append(f"{{\\k{silent_cs}}}")
        dur_cs = max(1, int((w_end - w_start) * 100))
        parts.append(f"{{\\kf{dur_cs}\\1c&H{highlight}&}}{_sanitize(word)} {{\\1c&H{base}&}}")
        cursor = w_end
    return "".join(parts).strip()


def build_ass(
    words: list[dict],
    duration: float,
    out_path: Path,
    cfg: CaptionConfig,
    play_w: int,
    play_h: int,
) -> Path:
    lines = [
        ASS_HEADER.format(
            w=play_w,
            h=play_h,
            font=cfg.font,
            size=cfg.font_size,
            base=cfg.base_color,
            highlight=cfg.highlight_color,
            margin_v=cfg.margin_v,
        )
    ]
    for ln in group_words_into_lines(
        words, duration, cfg.max_words_per_line, cfg.max_chars_per_line
    ):
        lines.append(
            f"Dialogue: 0,{_fmt_ts(ln['start'])},{_fmt_ts(ln['end'])},Karaoke,,0,0,0,,"
            + build_karaoke_line(ln, cfg.base_color, cfg.highlight_color)
        )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def caption_coverage(words: list[dict], duration: float) -> float:
    """Fraction of the clip covered by caption lines (gate input)."""
    if duration <= 0:
        return 0.0
    covered = sum(min(w["end"], duration) - max(w["start"], 0.0) for w in words)
    return max(0.0, min(1.0, covered / duration))
