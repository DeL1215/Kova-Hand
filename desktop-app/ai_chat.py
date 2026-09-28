# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

"""Provider-neutral OpenAI-compatible client for the AI control panel."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import config
from dotenv import load_dotenv, set_key
from motion_plan import load_gesture_presets

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
PROMPT_PATH = Path(__file__).resolve().with_name("system_prompt.txt")
load_dotenv(ENV_PATH)

PROVIDERS = {
    "openrouter": {
        "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1",
        "model": "nvidia/nemotron-3-super-120b-a12b:free",
    },
    "openai": {
        "label": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4.1-mini",
    },
    "custom": {
        "label": "自訂相容服務",
        "base_url": "",
        "model": "",
    },
}


@dataclass(frozen=True)
class LlmSettings:
    provider: str
    api_key: str
    base_url: str
    model: str

    @property
    def provider_label(self) -> str:
        return PROVIDERS.get(self.provider, PROVIDERS["custom"])["label"]


def load_llm_settings() -> LlmSettings:
    legacy_key = os.getenv("OPENAI_API_KEY", "").strip()
    provider = os.getenv("LLM_PROVIDER", "").strip().lower()
    if provider not in PROVIDERS:
        provider = "openai" if legacy_key else "openrouter"
    preset = PROVIDERS[provider]
    return LlmSettings(
        provider=provider,
        api_key=os.getenv("LLM_API_KEY", legacy_key).strip(),
        base_url=os.getenv("LLM_BASE_URL", preset["base_url"]).strip().rstrip("/"),
        model=os.getenv(
            "LLM_MODEL",
            os.getenv("OPENAI_MODEL", "").strip() or preset["model"],
        ).strip(),
    )


def validate_llm_settings(settings: LlmSettings) -> None:
    if settings.provider not in PROVIDERS:
        raise ValueError("不支援的供應商。")
    if settings.provider != "custom" and not settings.api_key:
        raise ValueError(f"請輸入 {settings.provider_label} API Key。")
    parsed = urlparse(settings.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("Base URL 必須是完整的 http:// 或 https:// 網址。")
    if not settings.model:
        raise ValueError("請輸入模型 ID。")


def save_llm_settings(settings: LlmSettings) -> None:
    validate_llm_settings(settings)
    ENV_PATH.touch(exist_ok=True)
    for key, value in {
        "LLM_PROVIDER": settings.provider,
        "LLM_API_KEY": settings.api_key,
        "LLM_BASE_URL": settings.base_url.rstrip("/"),
        "LLM_MODEL": settings.model,
    }.items():
        set_key(str(ENV_PATH), key, value, quote_mode="always")


class AiChatClient:
    def __init__(self, settings: LlmSettings | None = None):
        self.gestures = load_gesture_presets()
        motors = sorted(config.MOTORS, key=lambda motor: motor["channel"])
        self.angle_ranges = tuple((motor["min"], motor["max"]) for motor in motors)
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
        ranges = ",".join(f"{minimum}..{maximum}" for minimum, maximum in self.angle_ranges)
        self.system_prompt = (
            f"{prompt}\nP 可用名稱：{','.join(self.gestures)}"
            f"\nA 角度範圍（馬達 0～5）：{ranges}"
        )
        self.configure(settings or load_llm_settings())

    def configure(self, settings: LlmSettings) -> None:
        self.settings = settings
        self.provider = settings.provider
        self.model = settings.model
        self.api_key = settings.api_key
        self._client = None

    def ask(self, message: str) -> str:
        if OpenAI is None:
            raise RuntimeError(
                "尚未安裝 openai 套件，請在專案根目錄執行 "
                "python -m pip install -r requirements.txt。"
            )
        validate_llm_settings(self.settings)
        if self._client is None:
            self._client = OpenAI(
                api_key=self.api_key or "not-required",
                base_url=self.settings.base_url,
            )

        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": message},
        ]
        request = {
            "model": self.model,
            "messages": messages,
            "max_tokens": 512,
        }
        if self.provider == "openrouter":
            request["extra_body"] = {"reasoning": {"enabled": False}}
        reply = self._extract_reply(self._create_completion(request))
        if not reply:
            raise RuntimeError(
                "模型完成請求但沒有回傳動作文字；請再試一次或更換模型。"
            )
        return reply

    @staticmethod
    def _extract_reply(response) -> str:
        choices = getattr(response, "choices", None)
        if not choices:
            return ""
        message = getattr(choices[0], "message", None)
        content = getattr(message, "content", None) if message is not None else None
        return content.strip() if isinstance(content, str) else ""

    def _create_completion(self, request: dict):
        try:
            return self._client.chat.completions.create(**request)
        except Exception as error:
            status = getattr(error, "status_code", None)
            if status == 429:
                raise RuntimeError(
                    "模型目前流量過高；請稍後重試或在模型設定更換模型。"
                ) from error
            if status == 401:
                raise RuntimeError("API Key 無效，請到模型設定重新確認。") from error
            if status == 404:
                raise RuntimeError("找不到指定模型或 API 端點，請檢查模型設定。") from error
            raise
