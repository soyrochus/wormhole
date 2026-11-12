"""Translation providers backed by locally installed agent CLIs.

These providers drive Claude Code, OpenAI Codex, or GitHub Copilot CLI in their
non-interactive modes. Each CLI authenticates with the login the user already
performed (Claude, ChatGPT, or GitHub Copilot subscription), so no API key has
to be configured in Wormhole.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
from typing import Any, ClassVar

from .errors import (
    TranslationProviderConfigurationError,
    TranslationProviderError,
)
from .providers import JsonPromptTranslationProvider

DEFAULT_TIMEOUT_SECONDS = 300

RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "translations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "translated": {"type": "string"},
                },
                "required": ["id", "translated"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["translations"],
    "additionalProperties": False,
}


class AgentCliTranslationProvider(JsonPromptTranslationProvider):
    """Base class for providers that shell out to an agent CLI.

    Every batch is a fresh, stateless CLI run in an empty temporary directory,
    so no project instructions are picked up and nothing is persisted. Prompt
    text only ever travels over stdin or temporary files, never as a command
    line argument.
    """

    name: ClassVar[str]
    display_name: ClassVar[str]
    binary: ClassVar[str]
    env_prefix: ClassVar[str]
    login_hint: ClassVar[str]
    # API-key variables removed from the child environment. When present they
    # make the CLI bill an API account instead of the user's subscription.
    scrubbed_env: ClassVar[tuple[str, ...]] = ()

    def __init__(self, *, debug: bool = False) -> None:
        self.debug = debug
        self._default_model = os.getenv(f"WORMHOLE_{self.env_prefix}_MODEL") or None
        self._executable = self._locate_executable()
        self._timeout = self._read_timeout()

    # -- configuration -----------------------------------------------------

    def _locate_executable(self) -> str:
        override_name = f"WORMHOLE_{self.env_prefix}_BIN"
        override = os.getenv(override_name)
        if override:
            resolved = shutil.which(os.path.expanduser(override))
            if not resolved:
                raise TranslationProviderConfigurationError(
                    f"{override_name} points to '{override}', which is not an "
                    "executable file."
                )
            return resolved

        resolved = shutil.which(self.binary)
        if not resolved:
            # GUI launches (Finder, desktop shortcuts) often get a minimal PATH.
            search_path = os.pathsep.join(str(d) for d in _common_bin_dirs())
            resolved = shutil.which(self.binary, path=search_path)
        if not resolved:
            raise TranslationProviderConfigurationError(
                f"{self.display_name} CLI ('{self.binary}') was not found. Install "
                f"it and sign in ({self.login_hint}), or set {override_name} to "
                "its full path."
            )
        return resolved

    @staticmethod
    def _read_timeout() -> int:
        raw = os.getenv("WORMHOLE_AGENT_TIMEOUT")
        if not raw:
            return DEFAULT_TIMEOUT_SECONDS
        try:
            value = int(raw)
        except ValueError as exc:
            raise TranslationProviderConfigurationError(
                "WORMHOLE_AGENT_TIMEOUT must be a whole number of seconds."
            ) from exc
        if value <= 0:
            raise TranslationProviderConfigurationError(
                "WORMHOLE_AGENT_TIMEOUT must be greater than zero."
            )
        return value

    def _child_env(self) -> dict[str, str]:
        env = {k: v for k, v in os.environ.items() if k not in self.scrubbed_env}
        # npm-installed CLIs are scripts that need `node` next to them on PATH.
        bin_dir = os.path.dirname(self._executable)
        env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
        return env

    # -- per-CLI hooks -----------------------------------------------------

    def _build_invocation(
        self,
        *,
        workdir: pathlib.Path,
        system_prompt: str,
        user_text: str,
        model: str | None,
    ) -> tuple[list[str], str]:
        """Return the CLI arguments (without the executable) and stdin text."""
        raise NotImplementedError

    def _read_reply(self, stdout: str, workdir: pathlib.Path) -> str:
        """Return the model's final message from a successful run."""
        return stdout

    # -- execution ---------------------------------------------------------

    def _invoke_model(
        self,
        *,
        system_prompt: str,
        user_payload: dict,
        model: str | None,
    ) -> list[dict[str, Any]]:
        user_text = json.dumps(user_payload, ensure_ascii=False)
        with tempfile.TemporaryDirectory(prefix="wormhole-agent-") as tmp:
            workdir = pathlib.Path(tmp)
            arguments, stdin_text = self._build_invocation(
                workdir=workdir,
                system_prompt=system_prompt,
                user_text=user_text,
                model=model,
            )
            command = [self._executable, *arguments]
            self._log_debug("provider.agent.command", " ".join(command))
            completed = self._run(command, stdin_text, workdir)
            self._log_debug("provider.agent.stdout", completed.stdout)
            self._log_debug("provider.agent.stderr", completed.stderr)
            if completed.returncode != 0:
                raise TranslationProviderError(self._failure_message(completed))
            reply = self._read_reply(completed.stdout, workdir)

        if not reply or not reply.strip():
            raise TranslationProviderError(
                f"{self.display_name} returned an empty response."
            )
        return self._normalise_translations(self._isolate_json(reply))

    def _run(
        self, command: list[str], stdin_text: str, workdir: pathlib.Path
    ) -> subprocess.CompletedProcess[str]:
        creationflags = 0
        if sys.platform == "win32":
            # Keep a console window from flashing up under the GUI.
            creationflags = subprocess.CREATE_NO_WINDOW
        try:
            return subprocess.run(
                command,
                input=stdin_text,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=workdir,
                env=self._child_env(),
                timeout=self._timeout,
                creationflags=creationflags,
            )
        except subprocess.TimeoutExpired as exc:
            raise TranslationProviderError(
                f"{self.display_name} did not answer within {self._timeout} "
                "seconds (raise WORMHOLE_AGENT_TIMEOUT or lower --batch-guidance)."
            ) from exc
        except OSError as exc:
            raise TranslationProviderConfigurationError(
                f"Could not start {self.display_name} CLI at "
                f"'{self._executable}': {exc}"
            ) from exc

    def _failure_message(self, completed: subprocess.CompletedProcess[str]) -> str:
        detail = self._failure_detail(completed)
        return (
            f"{self.display_name} CLI failed (exit code {completed.returncode})"
            + (f": {detail}" if detail else "")
            + f". If you are not signed in, {self.login_hint}."
        )

    def _failure_detail(self, completed: subprocess.CompletedProcess[str]) -> str:
        text = (completed.stderr or "").strip() or (completed.stdout or "").strip()
        return _tail(text)

    def _isolate_json(self, reply: str) -> str:
        """Cut surrounding prose or code fences away from the JSON object."""

        text = self._strip_code_fence(reply)
        if text.startswith(("{", "[")):
            return text
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            return text[start : end + 1]
        return text


class ClaudeCodeTranslationProvider(AgentCliTranslationProvider):
    """Uses `claude -p` (Claude Code) with the user's Claude subscription."""

    name = "claude-code"
    display_name = "Claude Code"
    binary = "claude"
    env_prefix = "CLAUDE"
    login_hint = "run `claude` and use /login"
    scrubbed_env = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

    def _build_invocation(self, *, workdir, system_prompt, user_text, model):
        prompt_file = workdir / "system-prompt.txt"
        prompt_file.write_text(system_prompt, encoding="utf-8")
        arguments = [
            "--print",
            "--output-format", "json",
            "--system-prompt-file", str(prompt_file),
            "--tools", "",
            "--setting-sources", "",
            "--strict-mcp-config",
            "--disable-slash-commands",
            "--no-session-persistence",
        ]
        if model:
            arguments += ["--model", model]
        return arguments, user_text

    def _read_reply(self, stdout: str, workdir: pathlib.Path) -> str:
        envelope = _parse_claude_envelope(stdout)
        if envelope is None:
            raise TranslationProviderError(
                "Claude Code returned output that could not be read: "
                + _tail(stdout.strip())
            )
        if envelope.get("is_error"):
            raise TranslationProviderError(
                "Claude Code reported an error: "
                + _tail(str(envelope.get("result") or envelope.get("subtype") or ""))
            )
        return str(envelope.get("result") or "")

    def _failure_detail(self, completed: subprocess.CompletedProcess[str]) -> str:
        # Errors such as "not logged in" arrive inside the JSON envelope.
        envelope = _parse_claude_envelope(completed.stdout or "")
        if envelope and envelope.get("result"):
            return _tail(str(envelope["result"]))
        return super()._failure_detail(completed)


class CodexTranslationProvider(AgentCliTranslationProvider):
    """Uses `codex exec` (OpenAI Codex CLI) with the user's ChatGPT plan."""

    name = "codex"
    display_name = "Codex"
    binary = "codex"
    env_prefix = "CODEX"
    login_hint = "run `codex login`"
    scrubbed_env = ("OPENAI_API_KEY", "CODEX_API_KEY")

    _REPLY_FILE = "reply.txt"

    def _build_invocation(self, *, workdir, system_prompt, user_text, model):
        schema_file = workdir / "schema.json"
        schema_file.write_text(json.dumps(RESPONSE_SCHEMA), encoding="utf-8")
        arguments = [
            "exec",
            "--skip-git-repo-check",
            "--ephemeral",
            "--ignore-user-config",
            "--ignore-rules",
            "--sandbox", "read-only",
            "--color", "never",
            "--output-schema", str(schema_file),
            "--output-last-message", str(workdir / self._REPLY_FILE),
        ]
        if model:
            arguments += ["--model", model]
        arguments.append("-")  # read the prompt from stdin
        return arguments, _merge_prompt(system_prompt, user_text)

    def _read_reply(self, stdout: str, workdir: pathlib.Path) -> str:
        reply_file = workdir / self._REPLY_FILE
        if reply_file.exists():
            return reply_file.read_text(encoding="utf-8")
        return stdout


class CopilotTranslationProvider(AgentCliTranslationProvider):
    """Uses GitHub Copilot CLI with the user's Copilot subscription."""

    name = "copilot"
    display_name = "GitHub Copilot"
    binary = "copilot"
    env_prefix = "COPILOT"
    login_hint = "run `copilot login`"

    def _build_invocation(self, *, workdir, system_prompt, user_text, model):
        # Prompt mode cannot ask for approval, so tool requests are denied.
        # The plain-text output is markdown-rendered (re-wrapped, escapes
        # stripped), which corrupts JSON; the JSONL events carry the raw reply.
        arguments = [
            "--output-format", "json",
            "--stream", "off",
            "--no-custom-instructions",
            "--disable-builtin-mcps",
            "--no-ask-user",
            "--no-color",
        ]
        if model:
            arguments += ["--model", model]
        return arguments, _merge_prompt(system_prompt, user_text)

    def _read_reply(self, stdout: str, workdir: pathlib.Path) -> str:
        reply = ""
        for line in stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or event.get("type") != "assistant.message":
                continue
            data = event.get("data")
            content = data.get("content") if isinstance(data, dict) else None
            if isinstance(content, str) and content.strip():
                reply = content  # keep the last non-empty assistant message
        return reply


AGENT_PROVIDERS: dict[str, type[AgentCliTranslationProvider]] = {
    alias: provider
    for provider, aliases in (
        (ClaudeCodeTranslationProvider, ("claude-code", "claude_code", "claude")),
        (CodexTranslationProvider, ("codex", "codex-cli", "codex_cli", "chatgpt")),
        (
            CopilotTranslationProvider,
            ("copilot", "copilot-cli", "copilot_cli", "github-copilot", "github_copilot"),
        ),
    )
    for alias in aliases
}


def _merge_prompt(system_prompt: str, user_text: str) -> str:
    """Combine instructions and payload for CLIs without a system prompt flag."""

    return f"{system_prompt}\n\nInput:\n{user_text}\n"


def _parse_claude_envelope(stdout: str) -> dict[str, Any] | None:
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _tail(text: str, limit: int = 400) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else "…" + text[-limit:]


def _common_bin_dirs() -> list[pathlib.Path]:
    home = pathlib.Path.home()
    candidates = [
        home / ".local" / "bin",
        home / ".claude" / "local",
        home / ".npm-global" / "bin",
        pathlib.Path("/opt/homebrew/bin"),
        pathlib.Path("/usr/local/bin"),
    ]
    candidates += sorted((home / ".nvm" / "versions" / "node").glob("*/bin"), reverse=True)
    appdata = os.getenv("APPDATA")
    if appdata:
        candidates.append(pathlib.Path(appdata) / "npm")
    return [directory for directory in candidates if directory.is_dir()]
