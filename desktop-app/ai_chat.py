"""Small OpenAI Responses API client for the desktop chat panel."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from motion_plan import load_gesture_presets

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None


load_dotenv(Path(__file__).resolve().parent.parent / ".env")
PROMPT_PATH = Path(__file__).resolve().with_name("system_prompt.txt")


class AiChatClient:
    def __init__(self):
        self.model = os.getenv("OPENAI_MODEL", "gpt-5.6-luna").strip()
        self.api_key = os.getenv("OPENAI_API_KEY", "").strip()
        self.gestures = load_gesture_presets()
        prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
        self.system_prompt = f"{prompt}\nP 可用名稱：{','.join(self.gestures)}"
        self._client = None
        self._previous_response_id = None

    def ask(self, message: str) -> str:
        if OpenAI is None:
            raise RuntimeError("尚未安裝 openai 套件，請重新安裝 requirements.txt。")
        if not self.api_key:
            raise RuntimeError("請先在專案根目錄的 .env 填入 OPENAI_API_KEY。")
        if self._client is None:
            self._client = OpenAI(api_key=self.api_key)

        request = {
            "model": self.model,
            "instructions": self.system_prompt,
            "input": message,
            "reasoning": {"effort": "low"},
            "text": {"verbosity": "low"},
            "max_output_tokens": 256,
        }
        if self._previous_response_id:
            request["previous_response_id"] = self._previous_response_id
        response = self._client.responses.create(**request)
        self._previous_response_id = response.id
        return response.output_text.strip() or "模型沒有回傳文字。"
