"""Optional face tracking for smart 9:16 crops.

Uses OpenCV Zoo's YuNet detector (and optionally SFace recognition against a
target-person embedding built by scripts/build_face_embedding.py) to answer
three questions per candidate clip:

  1. Where is the speaker horizontally? (median face center -> crop x)
  2. How often is the speaker actually on screen? (gate input)
  3. Is this a multi-speaker moment? (if yes: render the full frame,
     never a single-face crop — cutting participants out of a conversation
     reads as rude and gets clips rejected)

Frames are extracted with ffmpeg single-shot seeks, NOT cv2.VideoCapture:
VideoCapture silently fails on AV1 sources and returns garbage instead of
erroring (docs/lessons.md).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import FaceConfig


@dataclass
class FaceReport:
    sampled: int
    face_pct: float  # frames with >= 1 face (or the target person when identity is on)
    multi_pct: float  # frames with >= 2 faces
    median_cx: float | None  # median face center x in source pixels
    identity_used: bool


def _extract_frame(video: Path, t: float, out: Path) -> bool:
    result = subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-loglevel",
            "error",
            "-ss",
            f"{t:.2f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-q:v",
            "3",
            str(out),
        ],
        capture_output=True,
    )
    return result.returncode == 0 and out.exists()


def track(video: Path, start: float, end: float, cfg: FaceConfig, out_path: Path) -> FaceReport:
    import cv2
    import numpy as np

    yunet = cfg.models_dir / "yunet.onnx"
    if not yunet.exists():
        raise FileNotFoundError(
            f"{yunet} missing; run scripts/download_models.py or disable face tracking"
        )
    det = cv2.FaceDetectorYN_create(str(yunet), "", (1920, 1080), 0.6, 0.3, 5000)

    rec = None
    ensemble = None
    if cfg.embedding is not None:
        sface = cfg.models_dir / "sface.onnx"
        if not sface.exists():
            raise FileNotFoundError(f"{sface} missing; run scripts/download_models.py")
        rec = cv2.FaceRecognizerSF_create(str(sface), "")
        ensemble = np.load(cfg.embedding)
        if ensemble.ndim == 1:
            ensemble = ensemble[None, :]
        ensemble = ensemble / np.linalg.norm(ensemble, axis=1, keepdims=True)

    rows: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        frame_path = Path(tmp) / "frame.jpg"
        t = start
        while t < end:
            if not _extract_frame(video, t, frame_path):
                t += cfg.sample_step_seconds
                continue
            frame = cv2.imread(str(frame_path))
            if frame is None:
                t += cfg.sample_step_seconds
                continue
            det.setInputSize((frame.shape[1], frame.shape[0]))
            _, faces = det.detect(frame)
            row = {"t": round(t, 1), "n_faces": 0, "cx": None, "sim": None}
            if faces is not None and len(faces):
                row["n_faces"] = int(len(faces))
                best_cx, best_sim = None, None
                for f in faces:
                    cx = float(f[0] + f[2] / 2)
                    if rec is not None and ensemble is not None:
                        try:
                            feat = rec.feature(rec.alignCrop(frame, f)).flatten()
                            feat = feat / (np.linalg.norm(feat) + 1e-9)
                            sim = float(np.max(ensemble @ feat))
                        except cv2.error:
                            continue
                        if best_sim is None or sim > best_sim:
                            best_sim, best_cx = sim, cx
                    else:
                        # no identity model: track the largest face
                        if best_cx is None or f[2] > 0:
                            best_cx = cx
                row["cx"] = best_cx
                row["sim"] = round(best_sim, 3) if best_sim is not None else None
            rows.append(row)
            t += cfg.sample_step_seconds

    identity_used = rec is not None
    if identity_used:
        hits = [r for r in rows if r["sim"] is not None and r["sim"] >= cfg.identity_threshold]
    else:
        hits = [r for r in rows if r["n_faces"] > 0]
    cxs = sorted(r["cx"] for r in hits if r["cx"] is not None)

    report = FaceReport(
        sampled=len(rows),
        face_pct=round(len(hits) / max(1, len(rows)), 3),
        multi_pct=round(sum(1 for r in rows if r["n_faces"] >= 2) / max(1, len(rows)), 3),
        median_cx=cxs[len(cxs) // 2] if cxs else None,
        identity_used=identity_used,
    )
    out_path.write_text(json.dumps({"report": asdict(report), "rows": rows}))
    return report


def pick_mode(report: FaceReport | None, configured: str) -> tuple[str, float | None]:
    """Choose the render mode for a clip.

    Multi-speaker moments always get the full frame: if other people are part
    of the conversation, everyone stays on screen.
    """
    if configured != "auto":
        cx = report.median_cx if report else None
        return configured, cx
    if report is None:
        return "panorama", None
    if report.multi_pct > 0.3:
        return "panorama", None
    if report.face_pct >= 0.5 and report.median_cx is not None:
        return "face", report.median_cx
    return "panorama", None
