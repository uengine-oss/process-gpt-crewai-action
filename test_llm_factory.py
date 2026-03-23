import os
import unittest
from unittest.mock import patch

import llm


class TestLLM(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["LLM_PROXY_URL"] = "http://litellm-proxy:4000"
        os.environ["LLM_PROXY_API_KEY"] = "sk-test-key"
        os.environ["LLM_MODEL"] = "gpt-4o"

    @patch("langchain_openai.ChatOpenAI")
    def test_create_llm_uses_proxy_settings(self, mock_chat_openai):
        mock_chat_openai.return_value = object()

        llm.create_llm(
            model="gpt-4o-mini",
            temperature=0.25,
        )

        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args.kwargs
        self.assertEqual(called_kwargs["base_url"], "http://litellm-proxy:4000")
        self.assertEqual(called_kwargs["api_key"], "sk-test-key")
        self.assertEqual(called_kwargs["model"], "gpt-4o-mini")
        self.assertEqual(called_kwargs["temperature"], 0.25)
        self.assertFalse(called_kwargs["streaming"])
        self.assertTrue(called_kwargs["disable_streaming"])

    @patch("langchain_openai.ChatOpenAI")
    def test_default_model_from_env(self, mock_chat_openai):
        mock_chat_openai.return_value = object()

        llm.create_llm()

        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args.kwargs
        self.assertEqual(called_kwargs["model"], "gpt-4o")
        self.assertEqual(called_kwargs["temperature"], 0.0)

    @patch("langchain_openai.ChatOpenAI")
    def test_fallback_to_openai_api_key(self, mock_chat_openai):
        os.environ.pop("LLM_PROXY_API_KEY", None)
        os.environ["OPENAI_API_KEY"] = "openai-fallback-key"
        mock_chat_openai.return_value = object()

        llm.create_llm(model="gpt-4o-mini")
        mock_chat_openai.assert_called_once()
        called_kwargs = mock_chat_openai.call_args.kwargs
        self.assertEqual(called_kwargs["api_key"], "openai-fallback-key")


if __name__ == "__main__":
    unittest.main()

