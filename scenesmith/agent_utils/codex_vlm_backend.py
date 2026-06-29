"""Codex CLI backend for SceneSmith VLMService calls.

This backend preserves the VLMService string-in/string-out contract while routing
the actual model call through `codex exec` instead of the OpenAI API.
"""

from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
import uuid

from pathlib import Path
from typing import Any


class CodexVLMBackend:
    """Small subprocess wrapper around `codex exec` for structured VLM calls."""

    def __init__(
        self,
        *,
        executable: str | None = None,
        cwd: str | Path | None = None,
        sandbox: str | None = None,
        approval_policy: str | None = None,
        timeout_seconds: int | None = None,
        artifact_dir: str | Path | None = None,
    ) -> None:
        self.executable = executable or os.getenv(
            "SCENESMITH_CODEX_EXECUTABLE", "codex"
        )
        self.cwd = Path(cwd or os.getenv("SCENESMITH_CODEX_CWD", ".")).resolve()
        self.sandbox = sandbox or os.getenv("SCENESMITH_CODEX_SANDBOX", "read-only")
        self.approval_policy = approval_policy or os.getenv(
            "SCENESMITH_CODEX_APPROVAL_POLICY", "never"
        )
        self.timeout_seconds = timeout_seconds or int(
            os.getenv("SCENESMITH_CODEX_TIMEOUT_SECONDS", "180")
        )
        default_artifact_dir = self.cwd / "outputs" / "codex_vlm"
        self.artifact_dir = Path(
            artifact_dir
            or os.getenv("SCENESMITH_CODEX_ARTIFACT_DIR", default_artifact_dir)
        ).resolve()

    def create_completion(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        reasoning_effort: str,
        verbosity: str,
        response_format: dict[str, Any] | None = None,
        vision_detail: str = "auto",
    ) -> str:
        """Run `codex exec` and return the final message text."""

        run_dir = (
            self.artifact_dir
            / time.strftime("%Y%m%d_%H%M%S")
            / uuid.uuid4().hex[:8]
        )
        run_dir.mkdir(parents=True, exist_ok=True)

        image_paths = self._extract_image_paths(messages, run_dir)
        prompt = self._build_prompt(
            model=model,
            messages=messages,
            reasoning_effort=reasoning_effort,
            verbosity=verbosity,
            response_format=response_format,
            vision_detail=vision_detail,
        )
        schema_path = self._write_output_schema(response_format, run_dir)
        last_message_path = run_dir / "last_message.txt"
        stdout_path = run_dir / "stdout.txt"
        stderr_path = run_dir / "stderr.txt"

        command = [
            self.executable,
            "-C",
            self._path_for_codex(self.cwd),
            "-a",
            self.approval_policy,
            "-s",
            self.sandbox,
            "exec",
            "--color",
            "never",
            "--output-last-message",
            self._path_for_codex(last_message_path),
            "--skip-git-repo-check",
        ]
        for image_path in image_paths:
            command.extend(["--image", self._path_for_codex(image_path)])
        if schema_path is not None:
            command.extend(["--output-schema", self._path_for_codex(schema_path)])
        command.append("-")

        command_path = run_dir / "command.json"
        command_path.write_text(json.dumps(command, indent=2), encoding="utf-8")

        try:
            completed = subprocess.run(
                command,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout_seconds,
                cwd=str(self.cwd),
            )
        except subprocess.TimeoutExpired as exc:
            stdout_path.write_text(_safe_process_text(exc.stdout), encoding="utf-8")
            stderr_path.write_text(_safe_process_text(exc.stderr), encoding="utf-8")
            raise RuntimeError(
                "codex exec timed out after "
                f"{self.timeout_seconds}s; artifacts={run_dir}"
            ) from exc
        except OSError as exc:
            raise RuntimeError(
                f"Failed to launch codex executable '{self.executable}'"
            ) from exc

        stdout_path.write_text(completed.stdout or "", encoding="utf-8")
        stderr_path.write_text(completed.stderr or "", encoding="utf-8")

        if completed.returncode != 0:
            combined = f"{completed.stdout or ''}\n{completed.stderr or ''}".strip()
            raise RuntimeError(
                "codex exec failed "
                f"(returncode={completed.returncode}, artifacts={run_dir}): "
                f"{_truncate(combined)}"
            )

        if last_message_path.exists():
            output = last_message_path.read_text(encoding="utf-8").strip()
        else:
            output = (completed.stdout or "").strip()

        self._validate_response_format(output, response_format)
        return output

    def _build_prompt(
        self,
        *,
        model: str,
        messages: list[dict[str, Any]],
        reasoning_effort: str,
        verbosity: str,
        response_format: dict[str, Any] | None,
        vision_detail: str,
    ) -> str:
        lines = [
            "You are replacing a SceneSmith VLMService OpenAI call.",
            "Preserve the original task semantics and output contract.",
            f"Requested model: {model}",
            f"Requested reasoning_effort: {reasoning_effort}",
            f"Requested verbosity: {verbosity}",
            f"Requested vision_detail: {vision_detail}",
            "",
            "Messages:",
        ]
        for message in messages:
            role = message.get("role", "user")
            content = message.get("content", "")
            lines.append(f"\n[{role}]")
            lines.append(self._content_to_text(content))

        if response_format and response_format.get("type") == "json_object":
            lines.extend(
                [
                    "",
                    "Return only a valid JSON object.",
                    "Do not include markdown, code fences, comments, or extra text.",
                ]
            )
        return "\n".join(lines)

    def _content_to_text(self, content: Any) -> str:
        if isinstance(content, str):
            return content
        if not isinstance(content, list):
            return str(content)

        text_parts: list[str] = []
        image_count = 0
        for item in content:
            if not isinstance(item, dict):
                text_parts.append(str(item))
                continue
            if item.get("type") in {"text", "input_text"}:
                text_parts.append(str(item.get("text", "")))
            elif item.get("type") in {"image_url", "input_image"}:
                image_count += 1
                text_parts.append(f"[Image {image_count} attached via codex --image]")
            else:
                text_parts.append(json.dumps(item, sort_keys=True))
        return "\n".join(part for part in text_parts if part)

    def _extract_image_paths(
        self, messages: list[dict[str, Any]], run_dir: Path
    ) -> list[Path]:
        image_paths: list[Path] = []
        for message in messages:
            content = message.get("content")
            if not isinstance(content, list):
                continue
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") not in {"image_url", "input_image"}:
                    continue
                url = _extract_image_url(item)
                if not url:
                    continue
                image_paths.append(
                    self._materialize_image(url, run_dir, len(image_paths))
                )
        return image_paths

    def _materialize_image(self, image_url: str, run_dir: Path, index: int) -> Path:
        data_match = re.match(r"^data:image/([^;]+);base64,(.+)$", image_url, re.S)
        if data_match:
            ext = _safe_image_extension(data_match.group(1))
            image_path = run_dir / f"image_{index:03d}.{ext}"
            image_path.write_bytes(base64.b64decode(data_match.group(2)))
            return image_path

        if image_url.startswith("file://"):
            return Path(image_url[7:]).resolve()

        local_path = Path(image_url)
        if local_path.exists():
            return local_path.resolve()

        raise ValueError(
            "CodexVLMBackend only supports local image paths or data:image base64 URLs"
        )

    def _write_output_schema(
        self, response_format: dict[str, Any] | None, run_dir: Path
    ) -> Path | None:
        if not response_format or response_format.get("type") != "json_schema":
            return None
        json_schema = response_format.get("json_schema", {})
        schema = json_schema.get("schema", json_schema)
        schema_path = run_dir / "output_schema.json"
        schema_path.write_text(json.dumps(schema, indent=2), encoding="utf-8")
        return schema_path

    def _path_for_codex(self, path: Path) -> str:
        """Return a path string the selected Codex executable can read."""

        path_text = str(path)
        if os.name == "nt":
            return path_text
        if not self.executable.lower().endswith(".exe"):
            return path_text

        # WSL launching Windows codex.exe: convert /mnt/e/foo to E:\foo.
        posix_path = path.as_posix()
        match = re.match(r"^/mnt/([a-zA-Z])/(.*)$", posix_path)
        if not match:
            return path_text
        drive = match.group(1).upper()
        rest = match.group(2).replace("/", "\\")
        return f"{drive}:\\{rest}"

    def _validate_response_format(
        self, output: str, response_format: dict[str, Any] | None
    ) -> None:
        if not response_format:
            return
        if response_format.get("type") not in {"json_object", "json_schema"}:
            return
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Codex returned invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise RuntimeError("Codex returned JSON, but not a JSON object")


def _extract_image_url(item: dict[str, Any]) -> str | None:
    if item.get("type") == "input_image":
        return item.get("image_url")
    image_url = item.get("image_url")
    if isinstance(image_url, dict):
        return image_url.get("url")
    if isinstance(image_url, str):
        return image_url
    return None


def _safe_image_extension(mime_subtype: str) -> str:
    subtype = mime_subtype.lower().split("+", 1)[0]
    return {
        "jpeg": "jpg",
        "jpg": "jpg",
        "png": "png",
        "webp": "webp",
    }.get(subtype, "png")


def _safe_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _truncate(text: str, limit: int = 2000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"
