"""Prompt/schema/image cache for benchmark calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from .checkpoint import CheckpointStore
from .config import BenchmarkConfig


class CacheManager:
    def __init__(self, store: CheckpointStore, config: BenchmarkConfig):
        self.store = store
        self.config = config
        # Set by the suite once the live codex version is known so that a binary
        # upgrade invalidates cached results instead of replaying stale ones.
        self.codex_version: str | None = None

    def make_key(
        self,
        *,
        module: str,
        prompt: str,
        schema_path: str | None = None,
        image_paths: Iterable[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> tuple[str, str, str | None, str | None]:
        prompt_hash = sha256_text(prompt)
        schema_hash = sha256_file(schema_path) if schema_path else None
        image_hash = hash_files(image_paths or [])

        payload: dict[str, Any] = {
            "module": module,
            "prompt_hash": prompt_hash,
            "schema_hash": schema_hash,
            "image_hash": image_hash,
            "extra": extra or {},
        }
        if self.config.cache.include_codex_fingerprint:
            payload["codex"] = {
                "executable": self.config.codex.executable,
                "model": self.config.codex.model,
                "profile": self.config.codex.profile,
                "sandbox": self.config.codex.sandbox,
                "extra_args": self.config.codex.extra_args,
                "version": self.codex_version,
            }
        cache_key = sha256_text(json.dumps(payload, sort_keys=True, separators=(",", ":")))
        return cache_key, prompt_hash, schema_hash, image_hash

    def get(self, cache_key: str) -> dict[str, Any] | None:
        if not self.config.cache.enabled:
            return None
        row = self.store.cache_get(cache_key)
        if row is None:
            return None
        metadata = json.loads(row["metadata_json"] or "{}")
        return {
            "cache_key": row["cache_key"],
            "status": row["status"],
            "output_text": row["output_text"],
            "output_path": row["output_path"],
            "metadata": metadata,
        }

    def put(
        self,
        *,
        cache_key: str,
        prompt_hash: str,
        schema_hash: str | None,
        image_hash: str | None,
        module: str,
        status: str,
        output_text: str | None,
        output_path: str | None,
        metadata: dict[str, Any],
    ) -> None:
        if not self.config.cache.enabled:
            return
        self.store.cache_put(
            cache_key=cache_key,
            prompt_hash=prompt_hash,
            schema_hash=schema_hash,
            image_hash=image_hash,
            module=module,
            status=status,
            output_text=output_text,
            output_path=output_path,
            metadata=metadata,
        )


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: str | Path) -> str:
    file_path = Path(path)
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(paths: Iterable[str | Path]) -> str | None:
    digest = hashlib.sha256()
    count = 0
    for path in paths:
        file_path = Path(path)
        if not file_path.exists():
            digest.update(f"missing:{file_path}".encode("utf-8"))
        else:
            digest.update(str(file_path).encode("utf-8"))
            digest.update(sha256_file(file_path).encode("utf-8"))
        count += 1
    if count == 0:
        return None
    return digest.hexdigest()
