"""Highlight mining: an LLM reads the transcript and proposes clip-worthy
segments; word timestamps then snap every boundary to real sentence edges.

Two rules here were learned the hard way in production (docs/lessons.md):

1. A clip must CONTAIN ITS PAYOFF. The miner is asked for segments with a
   complete arc, and the gate later re-checks the ending.
2. When a segment is too long, trim the HEAD to a later sentence start —
   never the tail. Tail-trimming cuts the payoff and produces clips that end
   mid-thought.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import anthropic

SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")

MINER_PROMPT = """You are a short-form video editor reviewing the transcript of a long video. \
Find the {n} strongest self-contained moments to publish as vertical clips \
({min_s:.0f}-{max_s:.0f} seconds each).

A strong clip:
- opens with a hook in the first sentence (a claim, a number, a tension)
- is a COMPLETE thought: setup and payoff both inside the clip
- stands alone with zero surrounding context
- is not a list of pleasantries, logistics, or filler

The transcript below has [mm:ss] markers roughly every 15 seconds.

Reply with ONLY a JSON array, no prose. Each element:
{{"start": "mm:ss", "end": "mm:ss", "hook": "the opening line, verbatim",
  "why": "one sentence on why this works", "score": 1-10,
  "title": "short title", "caption": "a 1-3 sentence social caption in the video's language"}}

TRANSCRIPT:
{transcript}"""


@dataclass
class Candidate:
    cid: str
    start: float
    end: float
    hook: str
    why: str
    score: float
    title: str
    caption: str
    words: list[dict]  # clip-relative word timestamps for captions


def mine(
    workdir: Path, words: list[dict], model: str, n: int, min_s: float, max_s: float
) -> list[Candidate]:
    out_path = workdir / "candidates.json"
    if out_path.exists():
        return [Candidate(**c) for c in json.loads(out_path.read_text())]

    transcript = (workdir / "transcript.txt").read_text()
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=model,
        max_tokens=16000,
        messages=[
            {
                "role": "user",
                "content": MINER_PROMPT.format(
                    n=n, min_s=min_s, max_s=max_s, transcript=transcript
                ),
            }
        ],
    )
    text = next((b.text for b in response.content if b.type == "text"), "")
    raw = _extract_json_array(text)

    candidates: list[Candidate] = []
    for i, item in enumerate(raw):
        window = snap_to_sentences(
            _ts(item.get("start", "0:00")), _ts(item.get("end", "0:00")), words, min_s, max_s
        )
        if window is None:
            continue
        start, end = window
        candidates.append(
            Candidate(
                cid=f"c{i:02d}",
                start=start,
                end=end,
                hook=str(item.get("hook", "")),
                why=str(item.get("why", "")),
                score=float(item.get("score", 0)),
                title=str(item.get("title", "")),
                caption=str(item.get("caption", "")),
                words=clip_words(words, start, end),
            )
        )

    candidates.sort(key=lambda c: c.score, reverse=True)
    out_path.write_text(json.dumps([asdict(c) for c in candidates], ensure_ascii=False))
    return candidates


def _extract_json_array(text: str) -> list[dict]:
    """Parse the model reply, tolerating fences or stray prose around the array."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", text, re.DOTALL)
        if not match:
            raise ValueError("miner reply contained no JSON array")
        data = json.loads(match.group(0))
    if not isinstance(data, list):
        raise ValueError("miner reply was not a JSON array")
    return [d for d in data if isinstance(d, dict)]


def _ts(stamp: str) -> float:
    parts = [p for p in str(stamp).strip().split(":") if p != ""]
    try:
        nums = [float(p) for p in parts]
    except ValueError:
        return 0.0
    if len(nums) == 3:
        return nums[0] * 3600 + nums[1] * 60 + nums[2]
    if len(nums) == 2:
        return nums[0] * 60 + nums[1]
    return nums[0] if nums else 0.0


def sentence_start_indices(words: list[dict]) -> list[int]:
    """Indices of words that begin a sentence (first word, or preceded by .!?)."""
    starts = [0] if words else []
    for i in range(1, len(words)):
        if SENTENCE_END.search(words[i - 1]["word"]):
            starts.append(i)
    return starts


def snap_to_sentences(
    start_hint: float, end_hint: float, words: list[dict], min_s: float, max_s: float
) -> tuple[float, float] | None:
    """Snap a rough [start, end] window to sentence boundaries.

    Start snaps to the closest sentence start at or before the hint; end
    extends forward to the first sentence end at or after the hint. If the
    result is too long, the START advances to later sentence starts until it
    fits (head-trim, never tail-trim). Returns None if no valid window exists.
    """
    if not words or end_hint <= start_hint:
        return None
    starts = sentence_start_indices(words)

    start_idx = starts[0]
    for idx in starts:
        if words[idx]["start"] <= start_hint + 0.5:
            start_idx = idx
        else:
            break

    end_idx = None
    for i, w in enumerate(words):
        if w["end"] >= end_hint - 0.5 and SENTENCE_END.search(w["word"]):
            end_idx = i
            break
    if end_idx is None:
        for i in range(len(words) - 1, -1, -1):
            if SENTENCE_END.search(words[i]["word"]):
                end_idx = i
                break
    if end_idx is None or end_idx <= start_idx:
        return None

    def duration(si: int) -> float:
        return words[end_idx]["end"] - words[si]["start"]

    while duration(start_idx) > max_s:
        later = [idx for idx in starts if idx > start_idx and idx < end_idx]
        if not later:
            return None
        start_idx = later[0]

    if duration(start_idx) < min_s:
        return None
    return round(words[start_idx]["start"], 2), round(words[end_idx]["end"], 2)


def clip_words(words: list[dict], start: float, end: float) -> list[dict]:
    """Words inside [start, end], re-based to clip-relative time."""
    out = []
    for w in words:
        if w["start"] >= start - 0.05 and w["end"] <= end + 0.05:
            out.append(
                {
                    "start": round(max(0.0, w["start"] - start), 2),
                    "end": round(min(end - start, w["end"] - start), 2),
                    "word": w["word"],
                }
            )
    return out
