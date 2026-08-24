"""Word-level transcription via faster-whisper.

Produces two artifacts per video:
  words.json      [{"start": s, "end": s, "word": "..."}]  (absolute seconds)
  transcript.txt  ~15-second paragraph blocks with [mm:ss] markers, the
                  format the highlight miner reads
"""

from __future__ import annotations

import json
from pathlib import Path

from .config import WhisperConfig

BLOCK_SECONDS = 15.0


def transcribe(source: Path, workdir: Path, cfg: WhisperConfig) -> list[dict]:
    words_path = workdir / "words.json"
    if words_path.exists():
        return json.loads(words_path.read_text())

    from faster_whisper import WhisperModel

    model = WhisperModel(cfg.model, device=cfg.device, compute_type=cfg.compute_type)
    segments, info = model.transcribe(
        str(source),
        language=cfg.language,
        word_timestamps=True,
        vad_filter=True,
    )

    words: list[dict] = []
    for seg in segments:
        for w in seg.words or []:
            token = w.word.strip()
            if token:
                words.append({"start": round(w.start, 2), "end": round(w.end, 2), "word": token})

    words_path.write_text(json.dumps(words, ensure_ascii=False))
    (workdir / "transcript.txt").write_text(blocked_transcript(words), encoding="utf-8")
    (workdir / "transcribe-info.json").write_text(
        json.dumps({"language": info.language, "duration": round(info.duration, 1)})
    )
    return words


def blocked_transcript(words: list[dict]) -> str:
    """Merge words into ~15s blocks with [mm:ss] markers for highlight scouting."""
    blocks: list[str] = []
    cur: list[str] = []
    cur_start: float | None = None
    for w in words:
        if cur_start is None:
            cur_start = w["start"]
        cur.append(w["word"])
        if w["end"] - cur_start >= BLOCK_SECONDS:
            blocks.append(_stamp(cur_start) + " " + " ".join(cur))
            cur, cur_start = [], None
    if cur:
        blocks.append(_stamp(cur_start or 0.0) + " " + " ".join(cur))
    return "\n".join(blocks)


def _stamp(t: float) -> str:
    mm, ss = divmod(int(t), 60)
    return f"[{mm:02d}:{ss:02d}]"
