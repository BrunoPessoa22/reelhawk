"""Publishing: export (default) or Instagram Reels via the Graph API.

reelhawk never auto-publishes silently. Export mode writes the final MP4 with
its caption and metadata next to it, ready for review. Instagram mode is
explicit opt-in, and even then only gate-PASS clips reach this module.

Instagram notes:
  The Reels container flow needs the video reachable at a public URL. Either
  pass one via post.upload_cmd (a shell template receiving {path} that must
  print a public URL) or host the file yourself and call publish_instagram
  with the URL directly. Credentials come from the environment only:
  IG_ACCESS_TOKEN and IG_USER_ID.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import time
from pathlib import Path

import httpx

from .config import PostConfig

GRAPH = "https://graph.facebook.com"


def compose_caption(caption: str, cfg: PostConfig) -> str:
    parts = [caption.strip()] if caption.strip() else []
    if cfg.disclosure:
        parts.append(cfg.disclosure.strip())
    if cfg.hashtags:
        parts.append(" ".join(cfg.hashtags))
    return "\n\n".join(parts)


def export(clip: Path, caption: str, metadata: dict, out_dir: Path, cfg: PostConfig) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / clip.name
    if clip.resolve() != dest.resolve():
        dest.write_bytes(clip.read_bytes())
    (out_dir / f"{clip.stem}.caption.txt").write_text(
        compose_caption(caption, cfg), encoding="utf-8"
    )
    (out_dir / f"{clip.stem}.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=1))
    return dest


def _public_url_for(clip: Path, cfg: PostConfig) -> str:
    if cfg.upload_cmd is None:
        raise RuntimeError(
            "instagram mode needs post.upload_cmd (a command that uploads the file "
            "and prints a public URL), because the Graph API fetches the video by URL"
        )
    cmd = cfg.upload_cmd.format(path=shlex.quote(str(clip)))
    result = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"upload_cmd failed: {result.stderr[-500:]}")
    url = result.stdout.strip().splitlines()[-1].strip()
    if not url.startswith("http"):
        raise RuntimeError(f"upload_cmd did not print a URL, got: {url[:200]}")
    return url


def publish_instagram(
    clip: Path, caption: str, cfg: PostConfig, video_url: str | None = None
) -> str:
    """Create a Reels container, wait for processing, publish. Returns media id."""
    token = os.environ.get("IG_ACCESS_TOKEN")
    user_id = os.environ.get("IG_USER_ID")
    if not token or not user_id:
        raise RuntimeError("IG_ACCESS_TOKEN and IG_USER_ID must be set for instagram mode")

    url = video_url or _public_url_for(clip, cfg)
    base = f"{GRAPH}/{cfg.ig_api_version}"

    with httpx.Client(timeout=60) as client:
        create = client.post(
            f"{base}/{user_id}/media",
            data={
                "media_type": "REELS",
                "video_url": url,
                "caption": compose_caption(caption, cfg),
                "access_token": token,
            },
        )
        create.raise_for_status()
        container = create.json()["id"]

        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            status = client.get(
                f"{base}/{container}",
                params={"fields": "status_code", "access_token": token},
            )
            status.raise_for_status()
            code = status.json().get("status_code")
            if code == "FINISHED":
                break
            if code == "ERROR":
                raise RuntimeError(f"Instagram rejected container {container}")
            time.sleep(10)
        else:
            raise TimeoutError(f"container {container} still processing after 10 minutes")

        publish = client.post(
            f"{base}/{user_id}/media_publish",
            data={"creation_id": container, "access_token": token},
        )
        publish.raise_for_status()
        return publish.json()["id"]
