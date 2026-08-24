from pathlib import Path

from reelhawk.config import GateConfig
from reelhawk.gate import gate_clip
from reelhawk.mine import Candidate


def make_candidate(words: list[dict], start: float = 0.0, end: float = 30.0) -> Candidate:
    return Candidate(
        cid="c00",
        start=start,
        end=end,
        hook="h",
        why="w",
        score=8.0,
        title="t",
        caption="c",
        words=words,
    )


def dense_words(until: float) -> list[dict]:
    words = []
    t = 0.0
    while t < until - 0.5:
        words.append({"start": round(t, 2), "end": round(t + 0.45, 2), "word": "word"})
        t += 0.5
    if words:
        words[-1]["word"] = "done."
    return words


def cfg_no_llm() -> GateConfig:
    return GateConfig(llm_review=False)


def test_pass(tmp_path: Path):
    cand = make_candidate(dense_words(30.0))
    result = gate_clip(tmp_path, cand, None, cfg_no_llm(), 15.0, 75.0, model="unused")
    assert result.verdict == "PASS"
    assert (tmp_path / "gate-c00.json").exists()


def test_duration_bounds(tmp_path: Path):
    cand = make_candidate(dense_words(8.0), end=8.0)
    result = gate_clip(tmp_path, cand, None, cfg_no_llm(), 15.0, 75.0, model="unused")
    assert result.verdict == "FAIL"
    assert any(f.startswith("DURATION_OUT_OF_BOUNDS") for f in result.failures)


def test_truncated_ending_fails(tmp_path: Path):
    words = dense_words(30.0)
    words[-1]["word"] = "and"  # ends mid-thought
    cand = make_candidate(words)
    result = gate_clip(tmp_path, cand, None, cfg_no_llm(), 15.0, 75.0, model="unused")
    assert result.verdict == "FAIL"
    assert any(f.startswith("ENDING_TRUNCATED") for f in result.failures)


def test_sparse_captions_fail(tmp_path: Path):
    words = [
        {"start": 0.0, "end": 0.45, "word": "hello."},
        {"start": 28.0, "end": 28.45, "word": "bye."},
    ]
    cand = make_candidate(words)
    result = gate_clip(tmp_path, cand, None, cfg_no_llm(), 15.0, 75.0, model="unused")
    assert result.verdict == "FAIL"
    assert any(f.startswith("CAPTION_COVERAGE_LOW") for f in result.failures)
