import unittest

from ai_chat import AiChatClient


class FakeResponses:
    def __init__(self):
        self.requests = []

    def create(self, **request):
        self.requests.append(request)
        return type("Response", (), {"id": "response-1", "output_text": "H:0,0,0,0,0,0"})()


class AiChatTests(unittest.TestCase):
    def test_sends_compact_system_prompt(self):
        chat = AiChatClient()
        responses = FakeResponses()
        chat._client = type("Client", (), {"responses": responses})()
        chat.api_key = "test"

        self.assertEqual(chat.ask("張開手"), "H:0,0,0,0,0,0")
        request = responses.requests[0]
        self.assertIn("只輸出 1～20 行 DSL", request["instructions"])
        self.assertIn("P 可用名稱：open,fist,1,2,3,4,5,6", request["instructions"])
        self.assertEqual(request["reasoning"], {"effort": "low"})
        self.assertEqual(request["max_output_tokens"], 256)
        self.assertEqual(request["text"], {"verbosity": "low"})


if __name__ == "__main__":
    unittest.main()
