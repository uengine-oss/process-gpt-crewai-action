import os
import unittest
from unittest.mock import MagicMock, patch

from llm_factory import factory


class TestLLMFactory(unittest.TestCase):
    def setUp(self) -> None:
        # 테스트 동안 필요한 최소 환경변수 설정
        os.environ["OPENAI_API_KEY"] = "dummy-key"

    @patch("llm_factory.factory.ChatOpenAI")
    def test_reasoning_kwargs_are_forwarded(self, mock_chat_openai):
        """추론 옵션과 기타 kwargs가 그대로 전달되는지 확인"""
        mock_chat_openai.return_value = object()

        factory.create_llm(
            provider="openai",
            model="gpt-5",
            temperature=0.25,
            reasoning={"effort": "medium"},
            max_output_tokens=2048,
        )

        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args.kwargs
        self.assertEqual(called_kwargs["model"], "gpt-5")
        self.assertEqual(called_kwargs["temperature"], 0.25)
        self.assertEqual(called_kwargs["reasoning"], {"effort": "medium"})
        self.assertEqual(called_kwargs["max_output_tokens"], 2048)
        self.assertTrue(called_kwargs["streaming"])

    @patch("llm_factory.factory.ChatOpenAI")
    def test_default_temperature_is_zero(self, mock_chat_openai):
        """temperature를 전달하지 않아도 기본 0.0으로 동작하는지 확인"""
        mock_chat_openai.return_value = object()

        factory.create_llm(
            provider="openai",
            model="gpt-5",
            reasoning={"effort": "low"},
        )

        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args.kwargs
        self.assertEqual(called_kwargs["temperature"], 0.0)
        self.assertEqual(called_kwargs["model"], "gpt-5")
        self.assertEqual(called_kwargs["reasoning"], {"effort": "low"})

    @patch("llm_factory.factory.ChatOpenAI")
    def test_invoke_call_happens(self, mock_chat_openai):
        """LLM을 생성하고 invoke까지 호출되는지 확인"""
        mock_instance = MagicMock()
        mock_instance.invoke.return_value = {"content": "pong"}
        mock_chat_openai.return_value = mock_instance

        llm = factory.create_llm(
            provider="openai",
            model="gpt-5",
            temperature=0.1,
            reasoning={"effort": "medium"},
        )

        result = llm.invoke("ping")

        mock_chat_openai.assert_called_once()
        mock_instance.invoke.assert_called_once_with("ping")
        self.assertEqual(result, {"content": "pong"})


if __name__ == "__main__":
    unittest.main()

