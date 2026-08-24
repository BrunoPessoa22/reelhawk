from reelhawk.mine import (
    _extract_json_array,
    _ts,
    clip_words,
    sentence_start_indices,
    snap_to_sentences,
)


def make_words(sentences: list[tuple[str, float]]) -> list[dict]:
    """Build a word list from (sentence, start_time) pairs, 0.5s per word."""
    words = []
    for text, t0 in sentences:
        t = t0
        for token in text.split():
            words.append({"start": round(t, 2), "end": round(t + 0.45, 2), "word": token})
            t += 0.5
    return words


WORDS = make_words(
    [
        ("The market shifted three times in five years.", 0.0),
        ("Nobody noticed until it was over.", 10.0),
        ("Here is what actually happened.", 20.0),
        ("Everyone was looking at the wrong metric.", 30.0),
    ]
)


def test_sentence_starts():
    starts = sentence_start_indices(WORDS)
    assert starts[0] == 0
    assert len(starts) == 4
    assert all(WORDS[i - 1]["word"].endswith(".") for i in starts[1:])


def test_snap_extends_end_to_sentence_boundary():
    window = snap_to_sentences(0.0, 12.0, WORDS, min_s=5.0, max_s=60.0)
    assert window is not None
    start, end = window
    assert start == 0.0
    # end lands on the end of "over.", not mid-sentence
    assert end == next(w["end"] for w in WORDS if w["word"] == "over.")


def test_snap_head_trims_never_tail_trims():
    # window covering all 4 sentences but max 20s: the START must advance,
    # the end (the payoff) must stay
    window = snap_to_sentences(0.0, 33.0, WORDS, min_s=5.0, max_s=20.0)
    assert window is not None
    start, end = window
    assert end == WORDS[-1]["end"]  # payoff kept
    assert start > 0.0  # head trimmed


def test_snap_rejects_impossible_windows():
    assert snap_to_sentences(0.0, 2.0, WORDS, min_s=50.0, max_s=60.0) is None
    assert snap_to_sentences(5.0, 5.0, WORDS, min_s=1.0, max_s=60.0) is None
    assert snap_to_sentences(0.0, 10.0, [], min_s=1.0, max_s=60.0) is None


def test_clip_words_rebased():
    words = clip_words(WORDS, 10.0, 15.0)
    assert words
    assert words[0]["start"] == 0.0
    assert all(w["end"] <= 5.0 for w in words)


def test_ts_parsing():
    assert _ts("1:30") == 90.0
    assert _ts("01:02:03") == 3723.0
    assert _ts("45") == 45.0
    assert _ts("junk") == 0.0


def test_extract_json_array_tolerates_fences():
    text = '```json\n[{"start": "0:10"}]\n```'
    assert _extract_json_array(text) == [{"start": "0:10"}]


def test_extract_json_array_tolerates_prose():
    text = 'Here are the segments:\n[{"a": 1}, {"b": 2}]\nHope this helps.'
    assert _extract_json_array(text) == [{"a": 1}, {"b": 2}]
