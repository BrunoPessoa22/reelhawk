"""Source acquisition: local files pass through, URLs go through yt-dlp.

One production lesson is baked in here: datacenter IPs get bot-walled by the
big video platforms and no cookie file fixes that permanently. If you run
reelhawk on a server and downloads start failing, move the download step to a
residential connection (a laptop cron that drops files into the workdir is
enough) and feed reelhawk local files. See docs/lessons.md.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Source:
    video_id: str
    path: Path
    title: str


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", text).strip("-")
    return slug[:80] or "video"


def resolve(target: str, workdir: Path) -> Source:
    """Return a local Source for a file path or a URL (downloading if needed)."""
    local = Path(target)
    if local.exists():
        vid = _slug(local.stem)
        dest = workdir / vid
        dest.mkdir(parents=True, exist_ok=True)
        return Source(video_id=vid, path=local.resolve(), title=local.stem)
    if not target.startswith(("http://", "https://")):
        raise FileNotFoundError(f"{target} is neither a file nor a URL")
    return download(target, workdir)


def download(url: str, workdir: Path) -> Source:
    probe = subprocess.run(
        ["yt-dlp", "--no-download", "--print", "%(id)s\t%(title)s", url],
        capture_output=True,
        text=True,
        check=True,
    )
    raw_id, title = probe.stdout.strip().split("\t", 1)
    vid = _slug(raw_id)
    dest = workdir / vid
    dest.mkdir(parents=True, exist_ok=True)
    out = dest / "source.mp4"
    if not out.exists():
        subprocess.run(
            [
                "yt-dlp",
                # h264 preferred: AV1 sources break several downstream tools
                "-f",
                "bv*[vcodec^=avc1][height<=1080]+ba/bv*[height<=1080]+ba/b",
                "--merge-output-format",
                "mp4",
                "-o",
                str(out),
                url,
            ],
            check=True,
        )
    return Source(video_id=vid, path=out, title=title)


def list_channel(channel_url: str, limit: int = 50) -> list[dict]:
    """Flat-list a channel/playlist without downloading anything.

    Listing works from almost anywhere, including servers where the actual
    download is bot-walled, so this is safe to run in a cron.
    """
    result = subprocess.run(
        [
            "yt-dlp",
            "--flat-playlist",
            "--playlist-end",
            str(limit),
            "--print",
            "%(.{id,title,duration,url})j",
            channel_url,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    entries = []
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries
