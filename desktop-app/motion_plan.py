# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

"""Parse the compact hand-motion DSL returned by the language model."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence


MAX_STEPS = 20
JOINT_COUNT = 6
MIN_WAIT_MS = 100
MAX_WAIT_MS = 10_000
PRESET_PATH = Path(__file__).resolve().with_name("gesture_presets.json")


class MotionPlanError(ValueError):
    pass


@dataclass(frozen=True)
class PoseStep:
    values: tuple[int | None, ...]


@dataclass(frozen=True)
class AngleStep:
    values: tuple[int | None, ...]


@dataclass(frozen=True)
class WaitStep:
    milliseconds: int


MotionStep = PoseStep | AngleStep | WaitStep


def load_gesture_presets(path: Path = PRESET_PATH) -> dict[str, tuple[int, ...]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not raw:
        raise MotionPlanError("姿勢庫必須是非空物件")

    presets = {}
    for name, values in raw.items():
        if not isinstance(name, str) or not name.strip() or any(char in name for char in ":\r\n"):
            raise MotionPlanError("姿勢名稱不可為空或包含冒號、換行")
        if (
            not isinstance(values, list)
            or len(values) != JOINT_COUNT
            or any(type(value) is not int or not 0 <= value <= 100 for value in values)
        ):
            raise MotionPlanError(f"姿勢 {name} 必須包含六個 0～100 整數")
        presets[name] = tuple(values)
    return presets


def parse_motion_plan(
    text: str,
    presets: Mapping[str, tuple[int, ...]] | None = None,
    angle_ranges: Sequence[tuple[int, int]] | None = None,
) -> list[MotionStep]:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not 1 <= len(lines) <= MAX_STEPS:
        raise MotionPlanError("動作模組必須是 1～20 個")

    steps: list[MotionStep] = []
    for line in lines:
        if line.startswith("H:"):
            tokens = [token.strip() for token in line[2:].split(",")]
            if len(tokens) != JOINT_COUNT:
                raise MotionPlanError("H 必須包含六個關節值")
            values: list[int | None] = []
            for token in tokens:
                if token == "-":
                    values.append(None)
                    continue
                try:
                    value = int(token)
                except ValueError as error:
                    raise MotionPlanError(f"無效關節值：{token}") from error
                if not 0 <= value <= 100:
                    raise MotionPlanError("關節值必須介於 0～100")
                values.append(value)
            steps.append(PoseStep(tuple(values)))
        elif line.startswith("A:"):
            tokens = [token.strip() for token in line[2:].split(",")]
            if len(tokens) != JOINT_COUNT or not angle_ranges or len(angle_ranges) != JOINT_COUNT:
                raise MotionPlanError("A 必須包含六個有效馬達角度")
            values = []
            for channel, (token, (minimum, maximum)) in enumerate(zip(tokens, angle_ranges)):
                if token == "-":
                    values.append(None)
                    continue
                try:
                    value = int(token)
                except ValueError as error:
                    raise MotionPlanError(f"無效馬達角度：{token}") from error
                if not minimum <= value <= maximum:
                    raise MotionPlanError(f"馬達 {channel} 角度必須介於 {minimum}～{maximum}")
                values.append(value)
            steps.append(AngleStep(tuple(values)))
        elif line.startswith("P:"):
            name = line[2:].strip()
            if not presets or name not in presets:
                raise MotionPlanError(f"未知預設姿勢：{name}")
            steps.append(PoseStep(presets[name]))
        elif line.startswith("W:"):
            try:
                milliseconds = int(line[2:].strip())
            except ValueError as error:
                raise MotionPlanError("W 必須是整數毫秒") from error
            if not MIN_WAIT_MS <= milliseconds <= MAX_WAIT_MS:
                raise MotionPlanError("等待時間必須介於 100～10000 毫秒")
            steps.append(WaitStep(milliseconds))
        else:
            raise MotionPlanError(f"未知模組：{line}")

    action_types = (PoseStep, AngleStep)
    if not isinstance(steps[0], action_types) or not isinstance(steps[-1], action_types):
        raise MotionPlanError("動作序列的開頭與結尾必須是 H、P 或 A")
    if any(isinstance(a, WaitStep) and isinstance(b, WaitStep) for a, b in zip(steps, steps[1:])):
        raise MotionPlanError("W 不得連續")
    if not any(
        isinstance(step, action_types)
        and any(value is not None for value in step.values)
        for step in steps
    ):
        raise MotionPlanError("動作序列沒有任何可執行的關節值")
    return steps
