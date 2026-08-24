from reelhawk.config import CaptionConfig
from reelhawk.subtitles import (
    build_karaoke_line,
    caption_coverage,
    group_words_into_lines,
)

WORDS = [
    {"start": 0.0, "end": 0.4, "word": "The"},
    {"start": 0.4, "end": 0.9, "word": "market"},
    {"start": 0.9, "end": 1.3, "word": "shifted"},
    {"start": 1.3, "end": 1.8, "word": "three"},
    {"start": 1.8, "end": 2.4, "word": "times."},
    {"start": 3.1, "end": 3.6, "word": "Nobody"},
    {"start": 3.6, "end": 4.2, "word": "noticed."},
]


def test_lines_respect_word_cap():
    lines = group_words_into_lines(WORDS, duration=5.0, max_words_per_line=3)
    assert all(len(ln["words"]) <= 3 for ln in lines)
    total = sum(len(ln["words"]) for ln in lines)
    assert total == len(WORDS)


def test_lines_respect_char_cap():
    lines = group_words_into_lines(WORDS, duration=5.0, max_words_per_line=10, max_chars=12)
    for ln in lines:
        assert len(" ".join(w for _, _, w in ln["words"])) <= 12


def test_line_words_are_line_relative():
    lines = group_words_into_lines(WORDS, duration=5.0)
    for ln in lines:
        starts = [w_start for w_start, _, _ in ln["words"]]
        assert starts[0] == 0.0
        assert starts == sorted(starts)


def test_words_beyond_duration_are_dropped():
    lines = group_words_into_lines(WORDS, duration=3.0)
    assert all(ln["start"] < 3.0 for ln in lines)


def test_karaoke_line_contains_sweep_tags():
    lines = group_words_into_lines(WORDS, duration=5.0)
    text = build_karaoke_line(lines[0], base="FFFFFF", highlight="00D7FF")
    assert "\\kf" in text
    assert "{" not in text.replace("{\\", "")  # braces only open ASS tags


def test_karaoke_inserts_silent_gap():
    lines = group_words_into_lines(WORDS, duration=5.0, max_words_per_line=10, max_chars=99)
    # single line spanning the 0.7s silence between "times." and "Nobody"
    text = build_karaoke_line(lines[0], base="FFFFFF", highlight="00D7FF")
    assert "{\\k" in text  # plain \k tag used for the silent stretch


def test_caption_coverage():
    assert caption_coverage(WORDS, duration=4.2) > 0.7
    assert caption_coverage([], duration=10.0) == 0.0
    assert caption_coverage(WORDS, duration=0.0) == 0.0
