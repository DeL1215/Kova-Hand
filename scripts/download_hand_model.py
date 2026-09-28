# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

"""Download and verify the MediaPipe Hand Landmarker model used by Kova Hand."""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.error
import urllib.request
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
MODEL_PATH = REPOSITORY_ROOT / "desktop-app" / "models" / "hand_landmarker.task"
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/"
    "hand_landmarker/float16/1/hand_landmarker.task"
)
MODEL_SHA256 = "fbc2a30080c3c557093b5ddfc334698132eb341044ccee322ccf8bcf3607cde1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def model_is_valid(path: Path = MODEL_PATH) -> bool:
    return path.is_file() and sha256(path) == MODEL_SHA256


def download_model(destination: Path = MODEL_PATH) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".download")

    try:
        print(f"Downloading MediaPipe model to {destination} ...")
        with urllib.request.urlopen(MODEL_URL, timeout=60) as response:
            with temporary.open("wb") as output:
                while chunk := response.read(1024 * 1024):
                    output.write(chunk)

        actual_hash = sha256(temporary)
        if actual_hash != MODEL_SHA256:
            raise RuntimeError(
                "Downloaded model failed checksum verification: "
                f"expected {MODEL_SHA256}, got {actual_hash}"
            )
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download and verify Kova Hand's MediaPipe model."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="only verify the existing model; do not download it",
    )
    args = parser.parse_args()

    if model_is_valid():
        print(f"MediaPipe model is ready: {MODEL_PATH}")
        return 0

    if args.check:
        print(
            f"MediaPipe model is missing or invalid: {MODEL_PATH}",
            file=sys.stderr,
        )
        return 1

    try:
        download_model()
    except (OSError, RuntimeError, urllib.error.URLError) as exc:
        print(f"Unable to download the MediaPipe model: {exc}", file=sys.stderr)
        return 1

    print(f"MediaPipe model is ready: {MODEL_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
