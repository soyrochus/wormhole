"""Translation provider abstractions."""

from __future__ import annotations

import json
import os
import sys
from abc import ABC, abstractmethod
from typing import Any, Dict, Sequence

from .errors import (
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

    DEFAULT_MODEL = "gpt-5-mini"  # "gpt-4o-mini"

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        provider_value = os.getenv("LLM_PROVIDER", "openai") or "openai"
        normalized = provider_value.strip().lower()
        if normalized in {"azure_open_ai", "azure-openai"}:
            normalized = "azure_openai"
        if normalized not in {"openai", "azure_openai"}:
            normalized = "openai"

        self.provider_kind = normalized
        self._client, self._default_model = self._build_client()

    def _build_client(self) -> tuple[Any, str]:
        if self.provider_kind == "azure_openai":
            return self._build_azure_client()

        return self._build_openai_client()

    def _build_openai_client(self) -> tuple[Any, str]:
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

        return OpenAI(api_key=api_key), self.DEFAULT_MODEL

    def _build_azure_client(self) -> tuple[Any, str]:
        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION")
        deployment_name = os.getenv("AZURE_OPENAI_DEPLOYMENT_NAME")

        missing = [
            name
            for name, value in {
                "AZURE_OPENAI_API_KEY": api_key,
                "AZURE_OPENAI_ENDPOINT": endpoint,
                "AZURE_OPENAI_API_VERSION": api_version,
                "AZURE_OPENAI_DEPLOYMENT_NAME": deployment_name,
            }.items()
            if not value
        ]
        if missing:
            raise TranslationProviderConfigurationError(
                "Azure OpenAI configuration incomplete. Please set: "
                + ", ".join(missing)
                + "."
            )

        try:
            from openai import AzureOpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - import guard
            raise TranslationProviderConfigurationError(
                "OpenAI Python SDK not installed. Install with `pip install openai`."
            ) from exc

        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        return client, deployment_name  # type: ignore[arg-type]

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
            "Respond strictly with an object shaped as "
            '{"translations": [{"id": "...", "translated": "..."}]}. '
            "Input may include tags such as <run id=\"…\">…</run>; keep tags and their "
            "attributes exactly as provided, translate only the inner text, and you may "
            "redistribute translated words across sequential runs as needed while "
            "preserving tag order. "
            "Do not add commentary. Do not wrap the JSON in markdown code fences."
        )
        user_prompt = {
            "target_language": target_language,
            "source_language": source_language,
            "segments": payload,
        }
        self._log_debug("provider.request.system_prompt", system_prompt)
        self._log_debug("provider.request.payload", user_prompt)

        response_items = self._invoke_model(
            system_prompt=system_prompt,
            user_payload=user_prompt,
            model=model or self._default_model,
        )
        self._log_debug("provider.response.items", response_items)

        mapping: Dict[str, str] = {}
        for item in response_items:
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

        self._log_debug("provider.response.mapping", mapping)
        return mapping

    def _invoke_model(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str,
    ) -> list[dict[str, Any]]:
        """Call the OpenAI Responses API and return structured JSON data."""

        try:
            response = self._client.responses.create(
                model=model,
                input=[
                    {
                        "role": "system",
                        "content": [
                            {"type": "input_text", "text": system_prompt},
                        ],
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "input_text",
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
        self._log_debug("provider.response.raw", self._safe_dump_response(response))
        return self._extract_translations(response)

    def _log_debug(self, label: str, payload: Any) -> None:
        """Emit structured debug information when enabled."""

        if not getattr(self, "debug", False):
            return
        try:
            if isinstance(payload, (dict, list)):
                message = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                message = str(payload)
        except Exception:
            message = repr(payload)
        print(f"[wormhole][provider-debug] {label}:\n{message}", file=sys.stderr)

    def _safe_dump_response(self, response: Any) -> Any:
        """Best-effort conversion of Responses API objects into JSON-friendly data."""

        for attr in ("model_dump_json", "model_dump"):
            candidate = getattr(response, attr, None)
            if candidate:
                try:
                    data = candidate()
                    if isinstance(data, str):
                        return json.loads(data)
                    return data
                except Exception:
                    continue
        if hasattr(response, "__dict__"):
            try:
                return json.loads(json.dumps(response.__dict__, default=str))
            except Exception:
                pass
        return str(response)

    def _strip_code_fence(self, text: str) -> str:
        """Remove leading/trailing markdown code fences if present."""

        stripped = text.strip()
        if not stripped.startswith("```"):
            return stripped

        # Drop opening fence and optional language hint.
        first_newline = stripped.find("\n")
        if first_newline == -1:
            return stripped
        body = stripped[first_newline + 1 :]
        closing_index = body.rfind("```")
        if closing_index != -1:
            body = body[:closing_index]
        return body.strip()

    def _extract_translations(self, response: Any) -> list[dict[str, Any]]:
        """Extract the structured translation list from a Responses API result."""

        content = getattr(response, "output", None)
        if content:
            for item in content:
                parts = getattr(item, "content", [])
                if parts is None:
                    continue
                for part in parts:
                    json_value = getattr(part, "json", None)
                    if hasattr(json_value, "value"):
                        json_value = json_value.value
                    if json_value is not None:
                        if isinstance(json_value, dict):
                            translations = json_value.get("translations")
                            if isinstance(translations, list):
                                return translations
                        if isinstance(json_value, list):
                            return json_value
                    text_value = getattr(part, "text", None)
                    if hasattr(text_value, "value"):
                        text_value = text_value.value
                    if text_value:
                        text_value = self._strip_code_fence(str(text_value))
                        try:
                            parsed = json.loads(text_value)
                        except json.JSONDecodeError:
                            continue
                        return self._normalise_translations(parsed)

        output_text = getattr(response, "output_text", None)
        if hasattr(output_text, "value"):
            output_text = output_text.value
        if output_text:
            output_text = self._strip_code_fence(str(output_text))
            return self._normalise_translations(output_text)

        raise TranslationProviderError(
            "Translation provider response empty or unrecognised."
        )

    def _normalise_translations(self, payload: Any) -> list[dict[str, Any]]:
        """Normalise raw payloads into a list of translation dictionaries."""

        if hasattr(payload, "value"):
            payload = payload.value

        if isinstance(payload, str):
            payload = self._strip_code_fence(payload)
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise TranslationProviderError(
                    f"Translation provider returned invalid JSON: {exc}"
                ) from exc

        if isinstance(payload, dict):
            translations = payload.get("translations")
            if isinstance(translations, list):
                return translations

        if isinstance(payload, list):
            return payload

        raise TranslationProviderError(
            "Translation provider response malformed: could not find translations list."
        )


class LegacyOpenAITranslationProvider(OpenAITranslationProvider):
    """Translation provider that uses the Chat Completions API for compatibility."""

    def _invoke_model(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str,
    ) -> list[dict[str, Any]]:
        """Call the Chat Completions API and return structured JSON data."""

        try:
            response = self._client.chat.completions.create(
                model=model,
                temperature=0,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(user_payload, ensure_ascii=False),
                    },
                ],
            )
        except Exception as exc:  # pragma: no cover - network call
            raise TranslationProviderError(
                f"Translation service temporarily unavailable — {exc}"
            ) from exc
        self._log_debug("provider.response.raw", self._safe_dump_response(response))

        content: str | None = None
        choices = getattr(response, "choices", None) or []
        for choice in choices:
            message = getattr(choice, "message", None)
            if message is None:
                continue
            message_content = getattr(message, "content", None)
            if hasattr(message_content, "value"):  # SDK helper attribute
                message_content = message_content.value
            if isinstance(message_content, list):
                parts: list[str] = []
                for part in message_content:
                    text_value = getattr(part, "text", None)
                    if hasattr(text_value, "value"):
                        text_value = text_value.value
                    if text_value is None and isinstance(part, dict):
                        text_value = part.get("text")
                    if text_value:
                        parts.append(str(text_value))
                if parts:
                    content = "\n".join(parts)
                    break
            elif message_content:
                content = str(message_content)
                break
            fallback_text = getattr(choice, "text", None)
            if fallback_text:
                content = str(fallback_text)
                break

        if content is None:
            raise TranslationProviderError(
                "Translation provider response empty or unrecognised."
            )

        content = self._strip_code_fence(content)
        translations = self._normalise_translations(content)
        return translations


def build_provider(name: str | None, *, debug: bool = False) -> TranslationProvider:
    """Factory to create providers by name."""

    normalized = (name or "openai").strip().lower()
    if normalized in {"openai", "gpt", "default"}:
        return OpenAITranslationProvider(debug=debug)
    if normalized in {"legacy-openai", "legacy_openai", "legacy", "openai-legacy"}:
        return LegacyOpenAITranslationProvider(debug=debug)
    if normalized in {"echo", "noop", "mock"}:
        return EchoTranslationProvider()
    raise TranslationProviderConfigurationError(
        f"Unknown translation provider '{name}'."
    )
