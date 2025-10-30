"""Translation provider abstractions."""

from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Dict, Sequence

from .errors import (
    ErrorCategory,
    TranslationProviderConfigurationError,
    TranslationProviderError,
)
from .structures import TextSegment


class TranslationProvider(ABC):
    """Abstract adapter for translation providers."""

    @abstractmethod
    def translate(
        self,
        segments: Sequence[TextSegment],
        *,
        source_language: str | None,
        target_language: str,
        model: str | None = None,
    ) -> Dict[str, str]:
        """Translate the provided segments and return a mapping by segment id."""


class EchoTranslationProvider(TranslationProvider):
    """A provider that returns the original text (useful for testing)."""

    def translate(
        self,
        segments: Sequence[TextSegment],
        *,
        source_language: str | None,
        target_language: str,
        model: str | None = None,
    ) -> Dict[str, str]:
        return {segment.segment_id: segment.text for segment in segments}


class OpenAITranslationProvider(TranslationProvider):
    """Translation provider that uses OpenAI chat models."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self) -> None:
        self._client = self._build_client()

    def _build_client(self):
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise TranslationProviderConfigurationError(
                "OpenAI configuration missing. Set OPENAI_API_KEY or choose a "
                "different provider."
            )

        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise TranslationProviderConfigurationError(
                "OpenAI Python SDK not installed. Install with `pip install openai`."
            ) from exc

        return OpenAI(api_key=api_key)

    def translate(
        self,
        segments: Sequence[TextSegment],
        *,
        source_language: str | None,
        target_language: str,
        model: str | None = None,
    ) -> Dict[str, str]:
        if not segments:
            return {}

        payload = [
            {"id": segment.segment_id, "text": segment.text}
            for segment in segments
        ]
        system_prompt = (
            "You are a professional translator. Return only JSON. "
            "Translate the provided text segments into the requested language. "
            "Preserve formatting, placeholders, numbers, and markup. "
            "Do not add commentary."
        )
        user_prompt = {
            "target_language": target_language,
            "source_language": source_language,
            "segments": payload,
        }

        response_text = self._invoke_model(
            system_prompt=system_prompt,
            user_payload=user_prompt,
            model=model or self.DEFAULT_MODEL,
        )

        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as exc:
            raise TranslationProviderError(
                f"Translation provider returned invalid JSON: {exc}"
            ) from exc

        if not isinstance(data, list):
            raise TranslationProviderError(
                "Translation provider response malformed: expected a list."
            )

        mapping: Dict[str, str] = {}
        for item in data:
            if not isinstance(item, dict):
                raise TranslationProviderError(
                    "Translation provider response malformed: expected objects."
                )
            segment_id = item.get("id")
            translated = item.get("translated")
            if not isinstance(segment_id, str) or not isinstance(translated, str):
                raise TranslationProviderError(
                    "Translation provider response malformed: missing fields."
                )
            mapping[segment_id] = translated

        return mapping

    def _invoke_model(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str,
    ) -> str:
        """Call the OpenAI Responses API and return the text output."""

        try:
            response = self._client.responses.create(
                model=model,
                input=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": json.dumps(user_payload, ensure_ascii=False),
                            }
                        ],
                    },
                ],
            )
        except Exception as exc:  # pragma: no cover - network call
            raise TranslationProviderError(
                f"Translation service temporarily unavailable — {exc}"
            ) from exc

        output_text = getattr(response, "output_text", None)
        if output_text:
            return output_text

        content = getattr(response, "output", None)
        if content:
            # Responses API structured content.
            for item in content:
                parts = getattr(item, "content", [])
                for part in parts:
                    part_type = getattr(part, "type", "")
                    if part_type in {"output_text", "text"}:
                        text_value = getattr(part, "text", None)
                        if text_value:
                            return text_value

        raise TranslationProviderError(
            "Translation provider response empty or unrecognised."
        )


def build_provider(name: str | None) -> TranslationProvider:
    """Factory to create providers by name."""

    normalized = (name or "openai").strip().lower()
    if normalized in {"openai", "gpt", "default"}:
        return OpenAITranslationProvider()
    if normalized in {"echo", "noop", "mock"}:
        return EchoTranslationProvider()
    raise TranslationProviderConfigurationError(
        f"Unknown translation provider '{name}'."
    )
