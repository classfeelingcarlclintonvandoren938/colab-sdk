"""Artifact packaging for Colab Client.

Consumes an ``ExecutionManifest`` and produces a deterministic ``.tar.gz``
artifact containing the source files, a generated ``runner.py`` entry point,
and metadata.
"""

import gzip
import hashlib
import io
import json
import tarfile
from dataclasses import dataclass
from pathlib import Path

from colab._manifest import ExecutionManifest

__all__ = [
    "Artifact",
    "Packager",
    "PackagingError",
]


class PackagingError(Exception):
    """Raised when artifact packaging fails."""


@dataclass(frozen=True)
class Artifact:
    """A packaged ``.tar.gz`` artifact ready for upload.

    Attributes:
        path: Absolute path to the ``.tar.gz`` file on disk.
        hash: Hex-encoded SHA256 digest of the **uncompressed** content.
        size: Size of the compressed ``.tar.gz`` file in bytes.
    """

    path: Path
    hash: str
    size: int


class Packager:
    """Builds deterministic ``.tar.gz`` artifacts from execution manifests.

    Usage::

        packager = Packager(cache_dir=Path.home() / ".colab-client" / "artifacts")
        artifact = packager.build(manifest, args=(), kwargs={})
    """

    _COLAB_VERSION = "0.1.0"

    def __init__(self, cache_dir: Path | None = None) -> None:
        """Initialize the packager with a cache directory.

        Args:
            cache_dir: Directory for storing built artifacts. Defaults to
                ``~/.colab-client/artifacts/``.
        """
        self._cache_dir = (cache_dir or Path.home() / ".colab-client" / "artifacts").resolve()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(
        self,
        manifest: ExecutionManifest,
        args: tuple[object, ...] = (),
        kwargs: dict[str, object] | None = None,
        secrets: dict[str, str] | None = None,
    ) -> Artifact:
        """Build a ``.tar.gz`` artifact from an execution manifest.

        Args:
            manifest: The manifest produced by the Analyzer.
            args: Positional arguments to pass to the remote function.
            kwargs: Keyword arguments to pass to the remote function.
            secrets: Environment variables to inject into ``runner.py``.

        Returns:
            An ``Artifact`` describing the built file.

        Raises:
            PackagingError: If source files are missing or compression fails.
        """
        kwargs = kwargs or {}
        secrets = secrets or {}

        # Generate runner.py content
        runner_source = _generate_runner(manifest, args, kwargs, secrets)

        # Generate metadata.json content
        metadata = _generate_metadata(manifest, args, kwargs)

        # Build the uncompressed tar in memory to compute the hash
        tar_bytes = self._build_tar(manifest, runner_source, metadata)
        artifact_hash = hashlib.sha256(tar_bytes).hexdigest()

        # Write compressed artifact to disk
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        artifact_path = self._cache_dir / f"{artifact_hash}.tar.gz"

        # Only write if not already cached (deterministic → same hash = same content)
        if not artifact_path.exists():
            _write_gzip(artifact_path, tar_bytes)

        return Artifact(
            path=artifact_path,
            hash=artifact_hash,
            size=artifact_path.stat().st_size,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tar(
        manifest: ExecutionManifest,
        runner_source: str,
        metadata: dict[str, object],
    ) -> bytes:
        """Build an uncompressed tar in memory and return the bytes."""
        buf = io.BytesIO()

        with tarfile.open(fileobj=buf, mode="w") as tar:
            # --- runner.py ---
            _add_bytes(tar, "runner.py", runner_source.encode("utf-8"))

            # --- metadata.json ---
            meta_bytes = (json.dumps(metadata, indent=2, default=str) + "\n").encode("utf-8")
            _add_bytes(tar, "metadata.json", meta_bytes)

            # --- files/ ---
            for file_path in sorted(manifest.files, key=str):
                resolved = file_path.resolve() if not file_path.is_absolute() else file_path
                if not resolved.exists():
                    raise PackagingError(f"Source file not found: {resolved}")
                arc_name = f"files/{file_path.as_posix()}"
                _add_bytes(tar, arc_name, resolved.read_bytes())

        return buf.getvalue()


# ======================================================================
# Module-level helpers
# ======================================================================


def _generate_runner(
    manifest: ExecutionManifest,
    args: tuple[object, ...],
    kwargs: dict[str, object],
    secrets: dict[str, str],
) -> str:
    """Generate the ``runner.py`` entry point script.

    The runner is the code that executes on the Colab VM. It:
    1. Sets up ``sys.path`` for the ``files/`` directory.
    2. Injects secret environment variables.
    3. Imports and calls the target function.
    4. Serialises the result via the ``__LAZY_*`` stdout protocol.
    """
    # Convert entry point path to a Python module path
    module_path = _entry_point_to_module(manifest.entry_point)

    # Build secret preamble
    secret_lines = ""
    if secrets:
        secret_lines = "\n".join(
            f'os.environ["{k}"] = {json.dumps(v)}'
            for k, v in secrets.items()
        )
        secret_lines += "\n"

    # Serialise args/kwargs
    args_json = json.dumps(args)
    kwargs_json = json.dumps(kwargs)

    return f'''#!/usr/bin/env python3
"""Auto-generated runner for function: {manifest.function_name}"""

import json
import os
import sys
import traceback
from pathlib import Path

# Add the files/ directory to sys.path so local modules are importable
FILES_DIR = Path(__file__).parent / "files"
sys.path.insert(0, str(FILES_DIR))

# ---------------------------------------------------------------------------
# Stdout protocol helpers
# ---------------------------------------------------------------------------

def _emit_result(value):
    payload = json.dumps({{"status": "ok", "value": value}})
    print(f"__LAZY_RESULT__:{{payload}}", flush=True)


def _emit_error(exc):
    tb = traceback.format_exc().splitlines(keepends=True)
    payload = json.dumps({{
        "status": "error",
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
    }})
    print(f"__LAZY_ERROR__:{{payload}}", file=sys.stderr, flush=True)


def _emit_log(msg):
    print(f"__LAZY_LOG__:{{msg}}", flush=True)


# ---------------------------------------------------------------------------
# Secrets injection
# ---------------------------------------------------------------------------
{secret_lines}
# ---------------------------------------------------------------------------
# Import and execute the target function
# ---------------------------------------------------------------------------
try:
    from {module_path} import {manifest.function_name}
except ImportError as e:
    _emit_error(e)
    sys.exit(1)

_args = {args_json}
_kwargs = {kwargs_json}

try:
    result = {manifest.function_name}(*_args, **_kwargs)
    _emit_result(result)
except Exception as e:
    _emit_error(e)
    sys.exit(1)
'''


def _generate_metadata(
    manifest: ExecutionManifest,
    args: tuple[object, ...],
    kwargs: dict[str, object],
) -> dict[str, object]:
    """Generate the ``metadata.json`` dictionary."""
    return {
        "function_name": manifest.function_name,
        "requirements_hash": manifest.requirements_hash,
        "requirements": manifest.requirements,
        "gpu": None,
        "args": list(args),
        "kwargs": kwargs,
        "colab_version": Packager._COLAB_VERSION,
    }


def _entry_point_to_module(entry_point: Path) -> str:
    """Convert a source file path to a Python module path.

    Examples::

        Path("app.py")               → "app"
        Path("training/trainer.py")  → "training.trainer"
        Path("training/__init__.py") → "training"
    """
    parts = entry_point.as_posix().split("/")
    # Remove .py extension from last part
    last = parts[-1]
    if last == "__init__.py":
        parts = parts[:-1]
    else:
        parts[-1] = last[:-3]  # strip ".py"
    return ".".join(parts)


def _add_bytes(tar: tarfile.TarFile, arcname: str, data: bytes) -> None:
    """Add a file to a tar archive with metadata stripped for determinism."""
    info = tarfile.TarInfo(name=arcname)
    info.size = len(data)
    info.mtime = 0
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    # Regular file mode (0o644), no executable bit
    info.mode = 0o644
    tar.addfile(info, io.BytesIO(data))


def _write_gzip(path: Path, uncompressed_data: bytes) -> None:
    """Write gzip-compressed data to *path*.

    Uses a deterministic gzip header (fixed mtime) so the compressed output
    is deterministic for identical inputs.
    """
    # mtime=0 ensures deterministic gzip output
    data = gzip.compress(uncompressed_data, mtime=0)
    path.write_bytes(data)
