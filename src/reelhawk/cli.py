"""reelhawk CLI.

    reelhawk run <url-or-file>     full pipeline: fetch, transcribe, mine,
                                   track, render, gate, then export/post
    reelhawk daily <channel-url>   cron mode: publish the next banked PASS,
                                   or mine the newest unseen video
    reelhawk mine <url-or-file>    stop after candidates.json (inspect first)

Every stage caches its artifact in the workdir, so re-running is cheap and a
crashed run resumes where it stopped.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

from . import facetrack, fetch, gate, mine, post, render, transcribe
from .config import Config
from .state import Ledger

FONTS_DIR = Path(__file__).resolve().parent.parent.parent / "fonts"


def _pipeline(target: str, cfg: Config, stop_after_mine: bool = False) -> list[dict]:
    cfg.workdir.mkdir(parents=True, exist_ok=True)
    source = fetch.resolve(target, cfg.workdir)
    workdir = cfg.workdir / source.video_id
    workdir.mkdir(parents=True, exist_ok=True)
    print(f"[reelhawk] source: {source.title} ({source.video_id})")

    words = transcribe.transcribe(source.path, workdir, cfg.whisper)
    print(f"[reelhawk] transcribed: {len(words)} words")

    candidates = mine.mine(
        workdir,
        words,
        model=cfg.model,
        n=cfg.clip.candidates,
        min_s=cfg.clip.min_seconds,
        max_s=cfg.clip.max_seconds,
    )
    print(f"[reelhawk] mined {len(candidates)} candidates")
    if stop_after_mine:
        for c in candidates:
            print(f"  {c.cid} score={c.score:.0f} {c.start:.0f}-{c.end:.0f}s {c.title}")
        return []

    results: list[dict] = []
    for cand in candidates:
        report = None
        if cfg.face.enabled:
            report = facetrack.track(
                source.path,
                cand.start,
                cand.end,
                cfg.face,
                workdir / f"facetrack-{cand.cid}.json",
            )
        mode, crop_cx = facetrack.pick_mode(report, cfg.render.mode)

        clip_path = workdir / f"clip-{cand.cid}.mp4"
        if not clip_path.exists():
            render.render_clip(
                source.path,
                workdir,
                cand.cid,
                cand.start,
                cand.end,
                mode,
                crop_cx,
                cfg.render,
                cfg.captions,
                cand.words,
                FONTS_DIR,
            )

        verdict = gate.gate_clip(
            workdir,
            cand,
            report,
            cfg.gate,
            cfg.clip.min_seconds,
            cfg.clip.max_seconds,
            cfg.model,
        )
        status = verdict.verdict
        if status == "FAIL":
            status += f" ({', '.join(verdict.failures)})"
        print(f"[reelhawk] {cand.cid} {mode} -> {status}")
        results.append(
            {
                **dataclasses.asdict(cand),
                "video_id": source.video_id,
                "clip": str(clip_path),
                "mode": mode,
                "verdict": verdict.verdict,
                "failures": verdict.failures,
            }
        )

    ledger = Ledger(cfg.workdir)
    ledger.record_mine(source.video_id, results)
    return results


def _deliver(item: dict, cfg: Config) -> str:
    clip = Path(item["clip"])
    caption = item.get("caption", "")
    if cfg.post.mode == "instagram":
        media_id = post.publish_instagram(clip, caption, cfg.post)
        print(f"[reelhawk] published to Instagram: {media_id}")
        return f"instagram:{media_id}"
    out = post.export(
        clip,
        caption,
        {k: item[k] for k in ("video_id", "title", "start", "end", "score") if k in item},
        cfg.workdir / "export",
        cfg.post,
    )
    print(f"[reelhawk] exported: {out}")
    return f"export:{out}"


def cmd_run(args: argparse.Namespace, cfg: Config) -> int:
    results = _pipeline(args.target, cfg)
    passes = [r for r in results if r["verdict"] == "PASS"]
    print(f"[reelhawk] {len(passes)}/{len(results)} clips passed the gate")
    ledger = Ledger(cfg.workdir)
    for item in passes:
        ref = _deliver(item, cfg)
        ledger.mark_published(item["video_id"], item["cid"], ref)
    return 0 if passes else 1


def cmd_mine(args: argparse.Namespace, cfg: Config) -> int:
    _pipeline(args.target, cfg, stop_after_mine=True)
    return 0


def cmd_daily(args: argparse.Namespace, cfg: Config) -> int:
    ledger = Ledger(cfg.workdir)

    banked = ledger.next_banked()
    if banked is not None:
        video_id, cid = banked
        workdir = cfg.workdir / video_id
        seg = ledger.video(video_id)["segments"][cid]
        candidates = json.loads((workdir / "candidates.json").read_text())
        cand = next((c for c in candidates if c["cid"] == cid), {})
        item = {
            "video_id": video_id,
            "cid": cid,
            "clip": str(workdir / f"clip-{cid}.mp4"),
            "caption": cand.get("caption", ""),
            "title": seg.get("title"),
            "start": seg["start"],
            "end": seg["end"],
            "score": seg.get("score"),
        }
        print(f"[reelhawk] daily: publishing banked PASS {video_id}/{cid} (zero pipeline cost)")
        ref = _deliver(item, cfg)
        ledger.mark_published(video_id, cid, ref)
        return 0

    print("[reelhawk] daily: nothing banked, scanning channel for unseen videos")
    entries = fetch.list_channel(args.channel, limit=args.scan_limit)
    fresh = [
        e
        for e in entries
        if e.get("id")
        and not ledger.is_mined(fetch._slug(e["id"]))
        and (e.get("duration") or 0) >= args.min_duration
    ]
    if not fresh:
        # honest dry signal, never silence: say exactly why nothing happened
        print(
            f"[reelhawk] daily: DRY - no unmined video >= {args.min_duration}s "
            f"in the newest {len(entries)} channel entries. Nothing published today."
        )
        return 1

    target = fresh[0].get("url") or f"https://www.youtube.com/watch?v={fresh[0]['id']}"
    print(f"[reelhawk] daily: mining {fresh[0].get('title', target)}")
    results = _pipeline(target, cfg)
    passes = sorted(
        (r for r in results if r["verdict"] == "PASS"),
        key=lambda r: r.get("score", 0),
        reverse=True,
    )
    if not passes:
        print("[reelhawk] daily: mined but no clip passed the gate. A day with no ")
        print("good clip is skipped, never padded with a bad one.")
        return 1
    item = passes[0]
    ref = _deliver(item, cfg)
    Ledger(cfg.workdir).mark_published(item["video_id"], item["cid"], ref)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="reelhawk", description=__doc__)
    parser.add_argument("--config", type=Path, default=None, help="path to reelhawk.yaml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_run = sub.add_parser("run", help="full pipeline on one video")
    p_run.add_argument("target", help="URL or local video file")

    p_mine = sub.add_parser("mine", help="transcribe + mine only, print candidates")
    p_mine.add_argument("target", help="URL or local video file")

    p_daily = sub.add_parser("daily", help="cron mode over a channel")
    p_daily.add_argument("channel", help="channel or playlist URL")
    p_daily.add_argument("--scan-limit", type=int, default=30)
    p_daily.add_argument("--min-duration", type=int, default=600)

    args = parser.parse_args()
    cfg = Config.load(args.config)

    commands = {"run": cmd_run, "mine": cmd_mine, "daily": cmd_daily}
    return commands[args.command](args, cfg)


if __name__ == "__main__":
    sys.exit(main())
