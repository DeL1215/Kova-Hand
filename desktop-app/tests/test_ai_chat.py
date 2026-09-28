# SPDX-FileCopyrightText: 2026 Kova Hand Project
# SPDX-License-Identifier: MIT

import unittest

from ai_chat import AiChatClient, LlmSettings, validate_llm_settings


class FakeCompletions:
    def __init__(self, error=None, contents=None):
        self.requests = []
        self.error = error
        self.contents = list(contents or ["H:0,0,0,0,0,0"])

    def create(self, **request):
        self.requests.append(request)
        if self.error:
            raise self.error
        message = type("Message", (), {"content": self.contents.pop(0)})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice]})()


class AiChatTests(unittest.TestCase):
    def setUp(self):
        self.settings = LlmSettings(
            provider="custom",
            api_key="",
            base_url="http://localhost:1234/v1",
            model="local-model",
        )

    def test_sends_provider_neutral_chat_completion(self):
        chat = AiChatClient(self.settings)
        completions = FakeCompletions()
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        self.assertEqual(chat.ask("張開手"), "H:0,0,0,0,0,0")
        request = completions.requests[0]
        self.assertEqual(request["model"], "local-model")
        self.assertEqual(request["max_tokens"], 512)
        self.assertEqual(request["messages"][-1], {"role": "user", "content": "張開手"})
        system_prompt = request["messages"][0]["content"]
        self.assertIn("只輸出 DSL", system_prompt)
        self.assertIn("P 可用名稱：open,fist,1,2,3,4,5,6,7,8", system_prompt)
        self.assertIn("自己設計或自由發揮時使用 H", system_prompt)
        self.assertIn("不可發明預設名稱", system_prompt)
        self.assertIn("A 角度範圍（馬達 0～5）：0..180,0..180", system_prompt)

    def test_custom_provider_allows_local_endpoint_without_key(self):
        validate_llm_settings(self.settings)

    def test_hosted_provider_requires_key(self):
        with self.assertRaisesRegex(ValueError, "API Key"):
            validate_llm_settings(
                LlmSettings(
                    provider="openrouter",
                    api_key="",
                    base_url="https://openrouter.ai/api/v1",
                    model="openrouter/auto",
                )
            )

    def test_openrouter_uses_only_selected_model(self):
        settings = LlmSettings(
            provider="openrouter",
            api_key="test",
            base_url="https://openrouter.ai/api/v1",
            model="qwen/qwen3.8-27b:free",
        )
        chat = AiChatClient(settings)
        completions = FakeCompletions()
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        chat.ask("握拳")
        request = completions.requests[0]
        self.assertEqual(request["model"], "qwen/qwen3.8-27b:free")
        self.assertEqual(
            request["extra_body"], {"reasoning": {"enabled": False}}
        )

    def test_requests_do_not_include_chat_history(self):
        chat = AiChatClient(self.settings)
        completions = FakeCompletions(contents=["H:0,0,0,0,0,0", "H:100,100,100,100,-,-"])
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        chat.ask("張開手")
        chat.ask("四指握拳")
        self.assertEqual(len(completions.requests), 2)
        self.assertEqual(len(completions.requests[1]["messages"]), 2)
        self.assertEqual(
            completions.requests[1]["messages"][-1],
            {"role": "user", "content": "四指握拳"},
        )

    def test_empty_reply_is_reported_without_switching_models(self):
        chat = AiChatClient(self.settings)
        completions = FakeCompletions(contents=[""])
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        with self.assertRaisesRegex(RuntimeError, "沒有回傳動作文字"):
            chat.ask("握拳")
        self.assertEqual(len(completions.requests), 1)

    def test_missing_choices_reports_readable_error(self):
        chat = AiChatClient(self.settings)
        class MalformedCompletions:
            def __init__(self):
                self.requests = []

            def create(inner_self, **request):
                inner_self.requests.append(request)
                return type("Response", (), {"choices": None})()

        completions = MalformedCompletions()
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        with self.assertRaisesRegex(RuntimeError, "沒有回傳動作文字"):
            chat.ask("張開手")
        self.assertEqual(len(completions.requests), 1)

    def test_rate_limit_error_is_readable(self):
        error = RuntimeError("raw provider response")
        error.status_code = 429
        chat = AiChatClient(self.settings)
        completions = FakeCompletions(error)
        chat._client = type(
            "Client",
            (),
            {"chat": type("Chat", (), {"completions": completions})()},
        )()

        with self.assertRaisesRegex(RuntimeError, "流量過高"):
            chat.ask("握拳")


if __name__ == "__main__":
    unittest.main()
