#!/usr/bin/env python3
"""Download the face models (optional feature) from OpenCV Zoo.

Both models are Apache-2.0 licensed. Whisper models are handled separately:
faster-whisper downloads them automatically on first run.

Usage: python scripts/download_models.py [models_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

ZOO = "https://github.com/opencv/opencv_zoo/raw/main/models"
MODELS = {
    "yunet.onnx": f"{ZOO}/face_detection_yunet/face_detection_yunet_2023mar.onnx",
    "sface.onnx": f"{ZOO}/face_recognition_sface/face_recognition_sface_2021dec.onnx",
}


def main() -> int:
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("models")
    dest.mkdir(parents=True, exist_ok=True)
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for name, url in MODELS.items():
            out = dest / name
            if out.exists():
                print(f"{name}: already present")
                continue
            print(f"{name}: downloading from {url}")
            response = client.get(url)
            response.raise_for_status()
            out.write_bytes(response.content)
            print(f"{name}: {len(response.content) // 1024} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
