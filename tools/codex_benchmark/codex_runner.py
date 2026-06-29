"""Subprocess wrapper around `codex exec`."""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .checkpoint import utc_now
from .config import BenchmarkConfig


@dataclass
class CodexResult:
    success: bool
    started_at: str
    ended_at: str
    latency_ms: float
    timeout: bool
    return_code: int | None
    stdout: str
    stderr: str
    last_message: str | None
    command: list[str]
    stdout_path: str
    stderr_path: str
    last_message_path: str
    error_kind: str | None = None
    error_message: str | None = None
    rate_limited: bool = False
    usage_exhausted: bool = False


class CodexRunner:
    def __init__(self, config: BenchmarkConfig, run_id: str, dry_run: bool = False):
        self.config = config
        self.run_id = run_id
        self.dry_run = dry_run
        self.artifact_root = Path(config.paths.artifacts_dir) / run_id
        self.artifact_root.mkdir(parents=True, exist_ok=True)

    def version(self) -> str:
        if self.dry_run:
            return "dry-run"
        try:
            completed = subprocess.run(
                [self.config.codex.executable, "--version"],
                text=True,
                capture_output=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            return f"unavailable: {exc}"
        text = (completed.stdout or completed.stderr).strip()
        return text or f"returncode={completed.returncode}"

    def run(
        self,
        *,
        prompt: str,
        module: str,
        scenario: str,
        call_index: int,
        schema_path: str | None = None,
        image_paths: list[str] | None = None,
        sandbox: str | None = None,
        timeout_seconds: int | None = None,
    ) -> CodexResult:
        call_dir = self.artifact_root / module / scenario / f"{call_index:06d}"
        call_dir.mkdir(parents=True, exist_ok=True)
        stdout_path = call_dir / "stdout.txt"
        stderr_path = call_dir / "stderr.txt"
        last_message_path = call_dir / "last_message.txt"

        command = self._build_command(
            schema_path=schema_path,
            image_paths=image_paths or [],
            sandbox=sandbox,
            last_message_path=str(last_message_path),
        )

        started_at = utc_now()
        start = time.perf_counter()
        if self.dry_run:
            last_message = self._dry_run_message(prompt, schema_path)
            self._maybe_write_dry_run_image(prompt)
            stdout = json.dumps({"dry_run": True, "module": module, "call_index": call_index})
            stderr = ""
            return_code = 0
            timeout = False
            error_kind = None
            error_message = None
            success = True
        else:
            try:
                completed = subprocess.run(
                    command,
                    input=prompt,
                    text=True,
                    capture_output=True,
                    timeout=timeout_seconds or self.config.codex.timeout_seconds,
                    cwd=self.config.codex.cwd,
                    env=self._environment(),
                )
                stdout = completed.stdout or ""
                stderr = completed.stderr or ""
                return_code = completed.returncode
                timeout = False
                last_message = (
                    last_message_path.read_text(encoding="utf-8")
                    if last_message_path.exists()
                    else None
                )
                error_kind, error_message = classify_failure(
                    stdout=stdout,
                    stderr=stderr,
                    return_code=return_code,
                    timeout=False,
                )
                success = return_code == 0
            except subprocess.TimeoutExpired as exc:
                stdout = _safe_process_text(exc.stdout)
                stderr = _safe_process_text(exc.stderr)
                return_code = None
                timeout = True
                last_message = None
                error_kind, error_message = classify_failure(
                    stdout=stdout,
                    stderr=stderr,
                    return_code=None,
                    timeout=True,
                )
                success = False
            except OSError as exc:
                stdout = ""
                stderr = str(exc)
                return_code = None
                timeout = False
                last_message = None
                error_kind = "cli_unavailable"
                error_message = str(exc)
                success = False

        latency_ms = (time.perf_counter() - start) * 1000
        ended_at = utc_now()
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        if last_message is not None:
            last_message_path.write_text(last_message, encoding="utf-8")

        combined = f"{stdout}\n{stderr}\n{last_message or ''}"
        return CodexResult(
            success=success,
            started_at=started_at,
            ended_at=ended_at,
            latency_ms=latency_ms,
            timeout=timeout,
            return_code=return_code,
            stdout=stdout,
            stderr=stderr,
            last_message=last_message,
            command=command,
            stdout_path=str(stdout_path),
            stderr_path=str(stderr_path),
            last_message_path=str(last_message_path),
            error_kind=error_kind,
            error_message=error_message,
            rate_limited=(not success) and is_rate_limited(combined),
            usage_exhausted=(not success) and is_usage_exhausted(combined),
        )

    def _build_command(
        self,
        *,
        schema_path: str | None,
        image_paths: list[str],
        sandbox: str | None,
        last_message_path: str,
    ) -> list[str]:
        codex = self.config.codex
        command = [
            codex.executable,
            "-C",
            codex.cwd,
            "-a",
            codex.approval_policy,
            "-s",
            sandbox or codex.sandbox,
        ]
        if codex.model:
            command.extend(["--model", codex.model])
        if codex.profile:
            command.extend(["--profile", codex.profile])
        command.extend(
            [
                "exec",
                "--color",
                "never",
                "--output-last-message",
                last_message_path,
            ]
        )
        if codex.skip_git_repo_check:
            command.append("--skip-git-repo-check")
        if codex.ignore_user_config:
            command.append("--ignore-user-config")
        if codex.ignore_rules:
            command.append("--ignore-rules")
        if codex.json_events:
            command.append("--json")
        for image_path in image_paths:
            command.extend(["--image", image_path])
        if schema_path:
            command.extend(["--output-schema", schema_path])
        command.extend(codex.extra_args)
        command.append("-")
        return command

    def _environment(self) -> dict[str, str]:
        env = os.environ.copy()
        env.update(self.config.codex.env)
        return env

    def _dry_run_message(self, prompt: str, schema_path: str | None) -> str:
        if schema_path:
            schema = json.loads(Path(schema_path).read_text(encoding="utf-8"))
            sample = sample_from_schema(schema)
            output_path = _extract_marker(prompt, "BENCHMARK_IMAGE_OUTPUT_PATH")
            if output_path and isinstance(sample, dict):
                sample["output_path"] = output_path
                sample["format"] = Path(output_path).suffix.lstrip(".") or "svg"
                sample["file_bytes"] = max(sample.get("file_bytes", 0), 256)
            return json.dumps(sample, sort_keys=True)
        return "CODEX_BENCHMARK_OK dry_run=true"

    def _maybe_write_dry_run_image(self, prompt: str) -> None:
        output_path = _extract_marker(prompt, "BENCHMARK_IMAGE_OUTPUT_PATH")
        if not output_path:
            return
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            """<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256">
<rect width="256" height="256" fill="#f7f7f2"/>
<rect x="36" y="80" width="184" height="116" fill="#2f80ed"/>
<circle cx="86" cy="128" r="24" fill="#27ae60"/>
<path d="M150 96 L204 176 L96 176 Z" fill="#f2994a"/>
<text x="128" y="226" text-anchor="middle" font-size="16">dry-run</text>
</svg>
""",
            encoding="utf-8",
        )


def sample_from_schema(schema: dict[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), schema_type[0])

    if schema_type == "object" or "properties" in schema:
        properties = schema.get("properties", {})
        required = schema.get("required", list(properties))
        return {
            key: sample_from_schema(properties.get(key, {"type": "string"}))
            for key in required
        }
    if schema_type == "array":
        return [sample_from_schema(schema.get("items", {"type": "string"}))]
    if schema_type == "integer":
        return int(schema.get("minimum", 1))
    if schema_type == "number":
        return float(schema.get("minimum", 1.0))
    if schema_type == "boolean":
        return True
    if schema_type == "null":
        return None
    return "dry-run"


def classify_failure(
    *, stdout: str, stderr: str, return_code: int | None, timeout: bool
) -> tuple[str | None, str | None]:
    combined = f"{stdout}\n{stderr}".strip()
    if timeout:
        return "timeout", "codex exec exceeded benchmark timeout"
    if return_code == 0:
        return None, None
    if is_rate_limited(combined):
        return "rate_limited", _truncate(combined)
    if is_usage_exhausted(combined):
        return "usage_exhausted", _truncate(combined)
    if re.search(r"not logged in|authentication|unauthorized|api key", combined, re.I):
        return "auth", _truncate(combined)
    return "codex_exec_failed", _truncate(combined)


def is_rate_limited(text: str) -> bool:
    return bool(
        re.search(
            r"\brate limit(?:ed|ing)?\b|http\s*429|\b429\b|too many requests|retry after",
            text,
            re.I,
        )
    )


def is_usage_exhausted(text: str) -> bool:
    return bool(
        re.search(
            r"usage limit|quota|insufficient_quota|out of credits|billing hard limit|exceeded",
            text,
            re.I,
        )
    )


def _safe_process_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _extract_marker(prompt: str, marker: str) -> str | None:
    match = re.search(rf"^{re.escape(marker)}=(.+)$", prompt, re.MULTILINE)
    if match:
        return match.group(1).strip()
    return None


def _truncate(text: str, limit: int = 2000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"
