# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

"""Check whether the local machine is ready to run the Kova Hand desktop app."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from download_hand_model import MODEL_PATH, model_is_valid


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = {
    "bleak": "Bluetooth Low Energy",
    "cv2": "camera capture (installed by MediaPipe)",
    "dotenv": "environment configuration",
    "mediapipe": "hand tracking",
    "openai": "AI motion commands",
    "PIL": "image support",
    "PySide6": "desktop interface",
}


def main() -> int:
    problems: list[str] = []

    print(f"Python: {sys.version.split()[0]}")
    if sys.version_info[:2] != (3, 11):
        problems.append("Python 3.11 is required for the documented setup.")

    missing = [
        f"{module} ({purpose})"
        for module, purpose in REQUIRED_MODULES.items()
        if importlib.util.find_spec(module) is None
    ]
    if missing:
        problems.append(
            "Missing Python modules: "
            + ", ".join(missing)
            + ". Run: python -m pip install -r requirements.txt"
        )

    if not model_is_valid():
        problems.append(
            f"MediaPipe model is missing or invalid at {MODEL_PATH}. "
            "Run: python scripts/download_hand_model.py"
        )

    if problems:
        print("\nInstallation check failed:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1

    print(f"MediaPipe model: OK ({MODEL_PATH.relative_to(REPOSITORY_ROOT)})")
    print("Python dependencies: OK")
    print("Kova Hand desktop prerequisites are ready.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
