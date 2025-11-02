"""Prepper-backed configuration loader for Wormhole."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from dotenv import dotenv_values
from prepper import (
    ConfigNotFound,
    Field,
    IoError,
    SchemaError,
    SchemaModel,
    ValidationError,
    model_validator,
)
from prepper.config import ConfigInstance
from prepper.loaders import _parse_file, _path_to_source, discover_file_paths
from prepper.merge import merge_layer
from prepper.provenance import ProvenanceRecorder

from .errors import TranslationProviderConfigurationError

APP_NAME = "Wormhole"


class WormholeConfig(SchemaModel):
    """Schema describing all supported configuration options."""

    LLM_PROVIDER: Literal["azure_openai", "openai"] = Field(
        default="openai",
        description="Large language model provider selection.",
    )
    AZURE_OPENAI_API_KEY: str | None = Field(default=None, secret=True)
    AZURE_OPENAI_ENDPOINT: str | None = Field(default=None)
    AZURE_OPENAI_API_VERSION: str | None = Field(default=None)
    AZURE_OPENAI_DEPLOYMENT_NAME: str | None = Field(default=None)
    OPENAI_API_KEY: str | None = Field(default=None, secret=True)
    WORMHOLE_PROVIDER_DEBUG: bool = Field(default=False)
    WORMHOLE_DEBUG_PROVIDER: bool = Field(default=False)

    @model_validator(mode="before")
    def _normalise_provider(data: Any) -> Any:
        if isinstance(data, dict):
            raw_value = data.get("LLM_PROVIDER")
            if isinstance(raw_value, str):
                normalized = raw_value.strip().lower().replace("-", "_")
                synonyms = {
                    "azure_open_ai": "azure_openai",
                    "azureopenai": "azure_openai",
                }
                normalized = synonyms.get(normalized, normalized)
                if normalized not in {"openai", "azure_openai"}:
                    normalized = "openai"
                data["LLM_PROVIDER"] = normalized
        return data


@lru_cache(maxsize=1)
def _load_config_instance(app_dir: Path | None = None) -> ConfigInstance:
    """Load configuration layers once and cache the immutable instance."""

    base_dir = app_dir or Path.cwd()
    try:
        provenance = ProvenanceRecorder()
        combined = _load_discovered_yaml(app_dir=base_dir, provenance=provenance)
        _merge_env_sources(
            combined,
            provenance=provenance,
            app_dir=base_dir,
            schema=WormholeConfig,
        )

        if not combined:
            raise ConfigNotFound("No configuration sources were found.")

        model = WormholeConfig.validate(combined, provenance=provenance)
        _validate_provider_settings(model)

        instance = ConfigInstance(
            model=model,
            provenance=provenance,
            env_prefix=None,
            schema_cls=WormholeConfig,
        )
        return instance
    except ConfigNotFound as exc:
        raise TranslationProviderConfigurationError(
            "No configuration sources were found. Provide settings via a home YAML "
            "file, a local config.yaml, a .env file, or environment variables."
        ) from exc
    except IoError as exc:
        raise TranslationProviderConfigurationError(
            f"Configuration files could not be read: {exc}"
        ) from exc
    except SchemaError as exc:
        raise TranslationProviderConfigurationError(
            f"Configuration schema error: {exc}"
        ) from exc
    except ValidationError as exc:
        issues = _format_validation_errors(exc.to_dict())
        raise TranslationProviderConfigurationError(issues) from exc


def _load_discovered_yaml(
    *,
    app_dir: Path,
    provenance: ProvenanceRecorder,
) -> dict[str, Any]:
    """Load YAML configuration files using Prepper's discovery rules."""

    result: dict[str, Any] = {}
    discovered = discover_file_paths(
        APP_NAME,
        "yaml",
        app_dir=app_dir,
        extra_paths=None,
    )
    for path, label in discovered:
        parsed = _parse_file(path, "yaml")
        if not isinstance(parsed, Mapping):
            raise IoError(
                f"Invalid configuration file {path}: expected a mapping at the root."
            )
        source = _path_to_source(label, "yaml", path)
        merge_layer(result, parsed, provenance=provenance, source=source, layer="file")
    return result


def _merge_env_sources(
    target: dict[str, Any],
    *,
    provenance: ProvenanceRecorder,
    app_dir: Path,
    schema: type[SchemaModel],
) -> None:
    """Merge .env and process environment variables into the target mapping."""

    allowed = set(schema.__field_infos__.keys())

    def merge_values(values: Mapping[str, str], *, source_prefix: str) -> None:
        for key, value in sorted(values.items()):
            if value is None:
                continue
            if key not in allowed:
                continue
            merge_layer(
                target,
                {key: value},
                provenance=provenance,
                source=f"env:{source_prefix}:{key}",
                layer="env",
            )

    dotenv_path = app_dir / ".env"
    if dotenv_path.exists():
        dotenv_content = dotenv_values(dotenv_path)
        merge_values(
            {k: v for k, v in dotenv_content.items() if v is not None},
            source_prefix=".env",
        )

    merge_values(
        {k: v for k, v in os.environ.items() if isinstance(v, str)},
        source_prefix="process",
    )


def _validate_provider_settings(settings: WormholeConfig) -> None:
    provider = settings.LLM_PROVIDER
    errors: list[str] = []

    if provider == "openai":
        if not settings.OPENAI_API_KEY:
            errors.append(
                "OPENAI_API_KEY is required when LLM_PROVIDER is 'openai'."
            )
    elif provider == "azure_openai":
        missing = [
            name
            for name, value in {
                "AZURE_OPENAI_API_KEY": settings.AZURE_OPENAI_API_KEY,
                "AZURE_OPENAI_ENDPOINT": settings.AZURE_OPENAI_ENDPOINT,
                "AZURE_OPENAI_API_VERSION": settings.AZURE_OPENAI_API_VERSION,
                "AZURE_OPENAI_DEPLOYMENT_NAME": settings.AZURE_OPENAI_DEPLOYMENT_NAME,
            }.items()
            if not value
        ]
        if missing:
            errors.append(
                "The following Azure OpenAI settings must be provided when "
                f"LLM_PROVIDER is 'azure_openai': {', '.join(missing)}."
            )

    if errors:
        bullet_list = "\n".join(f"- {message}" for message in errors)
        raise TranslationProviderConfigurationError(
            "Configuration validation errors detected:\n" + bullet_list
        )


def _format_validation_errors(entries: Sequence[dict[str, Any]]) -> str:
    details: list[str] = []
    for entry in entries:
        path = entry.get("path") or []
        if isinstance(path, (list, tuple)):
            location = ".".join(str(part) for part in path if part not in {None, ""})
        else:
            location = str(path)
        message = str(entry.get("message") or entry.get("msg") or "Invalid value")
        source = entry.get("source")
        origin = f" (source: {source})" if source else ""
        prefix = f"{location}: " if location else ""
        details.append(f"- {prefix}{message}{origin}")
    return "Configuration validation errors detected:\n" + "\n".join(details)


def get_config(app_dir: Path | None = None) -> ConfigInstance:
    """Return the immutable configuration instance."""

    return _load_config_instance(app_dir=app_dir)


def get_settings(app_dir: Path | None = None) -> WormholeConfig:
    """Return the validated schema model for typed access."""

    return get_config(app_dir=app_dir).model()
