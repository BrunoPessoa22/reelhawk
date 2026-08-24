"""Segment-level ledger: which videos were mined, which clips passed, which
were already published.

The design point (learned in production): one deep mine of a long video banks
MANY days of clips. Most `daily` runs should publish the next banked PASS at
zero pipeline cost, and only mine when the bank is empty. A video is exhausted
only when its good moments are used up, never because it was visited once.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path


class Ledger:
    def __init__(self, workdir: Path) -> None:
        self.path = workdir / "ledger.json"
        self.data: dict = {"videos": {}}
        if self.path.exists():
            self.data = json.loads(self.path.read_text())

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, ensure_ascii=False, indent=1))

    def video(self, video_id: str) -> dict:
        return self.data["videos"].setdefault(video_id, {"mined_at": None, "segments": {}})

    def is_mined(self, video_id: str) -> bool:
        return self.data["videos"].get(video_id, {}).get("mined_at") is not None

    def record_mine(self, video_id: str, results: list[dict]) -> None:
        entry = self.video(video_id)
        entry["mined_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        for r in results:
            entry["segments"][r["cid"]] = {
                "start": r["start"],
                "end": r["end"],
                "verdict": r["verdict"],
                "score": r.get("score"),
                "title": r.get("title"),
                "published": False,
            }
        self.save()

    def next_banked(self) -> tuple[str, str] | None:
        """(video_id, cid) of the best unpublished PASS across all videos."""
        best: tuple[float, str, str] | None = None
        for vid, entry in self.data["videos"].items():
            for cid, seg in entry["segments"].items():
                if seg["verdict"] == "PASS" and not seg["published"]:
                    score = float(seg.get("score") or 0)
                    if best is None or score > best[0]:
                        best = (score, vid, cid)
        return (best[1], best[2]) if best else None

    def mark_published(self, video_id: str, cid: str, ref: str) -> None:
        seg = self.video(video_id)["segments"][cid]
        seg["published"] = True
        seg["published_ref"] = ref
        seg["published_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        self.save()
