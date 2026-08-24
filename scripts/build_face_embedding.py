#!/usr/bin/env python3
"""Build a target-person face embedding from a folder of reference photos.

Point it at 10-50 photos of ONE person (varied angles, lighting, distance).
Each photo is scanned with YuNet; the largest detected face is embedded with
SFace. The output .npy is an ensemble of embeddings that reelhawk matches
against with max-cosine-similarity, which is far more robust across lighting
and angle than a single averaged vector.

Usage: python scripts/build_face_embedding.py photos_dir out.npy [models_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    photos_dir = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    models_dir = Path(sys.argv[3]) if len(sys.argv) > 3 else Path("models")

    det = cv2.FaceDetectorYN_create(
        str(models_dir / "yunet.onnx"), "", (1920, 1080), 0.6, 0.3, 5000
    )
    rec = cv2.FaceRecognizerSF_create(str(models_dir / "sface.onnx"), "")

    embeddings: list[np.ndarray] = []
    photos = sorted(
        p for p in photos_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    for photo in photos:
        frame = cv2.imread(str(photo))
        if frame is None:
            print(f"skip {photo.name}: unreadable")
            continue
        det.setInputSize((frame.shape[1], frame.shape[0]))
        _, faces = det.detect(frame)
        if faces is None or not len(faces):
            print(f"skip {photo.name}: no face found")
            continue
        largest = max(faces, key=lambda f: f[2] * f[3])
        try:
            feat = rec.feature(rec.alignCrop(frame, largest)).flatten()
        except cv2.error as exc:
            print(f"skip {photo.name}: {exc}")
            continue
        feat = feat / (np.linalg.norm(feat) + 1e-9)
        embeddings.append(feat)
        print(f"ok   {photo.name}")

    if len(embeddings) < 5:
        print(f"only {len(embeddings)} usable faces; need at least 5 for a stable ensemble")
        return 1
    np.save(out_path, np.stack(embeddings))
    print(f"wrote {out_path}: {len(embeddings)} embeddings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
