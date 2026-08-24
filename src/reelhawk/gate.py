"""Quality gate: every rendered clip is checked before it can be posted, and
the gate fails closed — a clip with no PASS verdict never leaves the workdir.

Mechanical checks (always on):
  duration bounds, caption coverage, sentence-complete ending,
  speaker-on-screen percentage (when face tracking ran).

LLM review (optional): asks the model one question that mechanical checks
cannot answer — does the clip deliver the payoff it sets up?
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

import anthropic

from .config import GateConfig
from .facetrack import FaceReport
from .mine import Candidate
from .subtitles import caption_coverage

SENTENCE_END = re.compile(r"[.!?…][\"')\]]*$")

REVIEW_PROMPT = """You are quality-checking a short vertical clip cut from a longer video. \
Here is the clip's transcript:

{text}

Answer two questions:
1. complete: does this text deliver the payoff its opening sets up (true/false)? \
A clip that ends mid-thought or promises something it never says is false.
2. standalone: would this make sense to a viewer with zero outside context (true/false)?

Reply with ONLY a JSON object: {{"complete": bool, "standalone": bool, "note": "one sentence"}}"""


@dataclass
class GateResult:
    cid: str
    verdict: str  # PASS | FAIL
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def gate_clip(
    workdir: Path,
    cand: Candidate,
    face_report: FaceReport | None,
    cfg: GateConfig,
    min_seconds: float,
    max_seconds: float,
    model: str,
) -> GateResult:
    result = GateResult(cid=cand.cid, verdict="PASS")
    duration = cand.end - cand.start

    if not min_seconds <= duration <= max_seconds:
        result.failures.append(f"DURATION_OUT_OF_BOUNDS:{duration:.1f}s")

    coverage = caption_coverage(cand.words, duration)
    result.notes.append(f"caption_coverage={coverage:.2f}")
    if coverage < cfg.min_caption_coverage:
        result.failures.append(f"CAPTION_COVERAGE_LOW:{coverage:.2f}")

    if cfg.require_sentence_end and cand.words:
        last = cand.words[-1]["word"]
        if not SENTENCE_END.search(last):
            result.failures.append(f"ENDING_TRUNCATED:{last!r}")

    if face_report is not None and face_report.face_pct < cfg.min_face_pct:
        result.failures.append(f"FACE_ON_SCREEN_LOW:{face_report.face_pct:.2f}")

    if cfg.llm_review and not result.failures:
        review = _llm_review(cand, model)
        if review is not None:
            result.notes.append(f"llm_review={json.dumps(review, ensure_ascii=False)}")
            if not review.get("complete", False):
                result.failures.append("PAYOFF_NOT_DELIVERED")
            if not review.get("standalone", False):
                result.failures.append("NOT_STANDALONE")
        else:
            # fail closed: an unreviewable clip is not a publishable clip
            result.failures.append("LLM_REVIEW_UNAVAILABLE")

    if result.failures:
        result.verdict = "FAIL"
    (workdir / f"gate-{cand.cid}.json").write_text(
        json.dumps(asdict(result), ensure_ascii=False, indent=1)
    )
    return result


def _llm_review(cand: Candidate, model: str) -> dict | None:
    text = " ".join(w["word"] for w in cand.words)
    if not text.strip():
        return None
    client = anthropic.Anthropic()
    try:
        response = client.messages.create(
            model=model,
            max_tokens=1024,
            messages=[{"role": "user", "content": REVIEW_PROMPT.format(text=text)}],
        )
    except (anthropic.APIStatusError, anthropic.APIConnectionError):
        return None
    reply = next((b.text for b in response.content if b.type == "text"), "")
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
