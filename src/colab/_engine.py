"""Execution pipeline orchestrator for Colab Client.

Ties the ``Analyzer``, ``Packager``, ``ColabSession``, and protocol parser
together into a single ``execute()`` call.

Usage::

    engine = ExecutionEngine(analyzer, packager, session)
    result = engine.execute(
        function_name="train",
        source_file=Path("app.py"),
        args=(10,),
        kwargs={"lr": 0.001},
    )
"""

from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from typing import Any

from colab._analyzer import Analyzer
from colab._exceptions import (
    AuthError,
    RemoteExecutionError,
    SessionDeadError,
    SessionError,
    SessionGpuMismatchError,
    ValidationError,
)
from colab._manifest import ExecutionManifest
from colab._packager import Packager, _entry_point_to_module
from colab._protocol import LogMessage, ProgressMessage, ResultMessage, classify
from colab._session import ColabSession

__all__ = [
    "ExecutionEngine",
]

# Known GPU types for validation
_KNOWN_GPUS = frozenset({"T4", "L4", "A100", "H100"})

# Retry defaults
_MAX_TRANSIENT_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0


def _debug_print(msg: LogMessage | ProgressMessage) -> None:
    """Print a raw VM message to stderr for debugging."""
    if isinstance(msg, LogMessage):
        print(f"[colab-raw] {msg.text}", file=sys.stderr, flush=True)
    else:
        print(f"[colab-raw] {msg}", file=sys.stderr, flush=True)


class ExecutionEngine:
    """Orchestrates the full execution pipeline.

    Components are injected at construction time so callers can substitute
    mocks for testing or customise component configuration.

    Usage::

        engine = ExecutionEngine(analyzer, packager, session)
        result = engine.execute("train", Path("app.py"))
    """

    def __init__(
        self,
        analyzer: Analyzer,
        packager: Packager,
        session: ColabSession,
    ) -> None:
        """Initialise the engine with its three core components.

        Args:
            analyzer: Static dependency analyser.
            packager: Deterministic artifact packager.
            session: Colab CLI session wrapper.
        """
        self._analyzer = analyzer
        self._packager = packager
        self._session = session

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute(
        self,
        function_name: str,
        source_file: Path,
        args: tuple[object, ...] = (),
        kwargs: dict[str, object] | None = None,
        secrets: dict[str, str] | None = None,
        *,
        session_name: str = "default",
        gpu: str | None = None,
        debug: bool = False,
    ) -> Any:
        """Execute a function remotely on a Colab VM.

        The full pipeline::

            validate -> analyze -> package -> ensure_session ->
            ensure_requirements -> execute -> parse -> return

        Args:
            function_name: Name of the function to execute.
            source_file: Path to the ``.py`` file containing the function.
            args: Positional arguments for the remote function.
            kwargs: Keyword arguments for the remote function.
            secrets: Environment variables to inject on the VM.
            session_name: Name for the Colab VM session.
            gpu: GPU type (``\\\"T4\\\"``, ``\\\"L4\\\"``, ``\\\"A100\\\"``, ``\\\"H100\\\"``,
                or ``None`` for CPU).
            debug: If ``True``, print all raw VM output to stderr.

        Returns:
            The deserialised return value of the remote function.

        Raises:
            ValidationError: If GPU type is invalid.
            AnalysisError: If static analysis fails.
            SessionError: If session operations fail.
            RemoteExecutionError: If the remote function raises.
            ProtocolError: If the stdout protocol is malformed.
        """
        kwargs = kwargs or {}
        secrets = secrets or {}

        # Step 1: Validate
        self._validate(gpu)

        # Step 2: Analyse
        manifest = self._analyzer.analyze(function_name, source_file)

        # Step 3: Build artifact (for deterministic tracking, not uploaded)
        self._packager.build(manifest, args, kwargs, secrets)

        # Steps 4-5: Session management (with retry for transient failures)
        for attempt in range(_MAX_TRANSIENT_RETRIES):
            try:
                self._prepare_session(
                    session_name=session_name,
                    gpu=gpu,
                    manifest=manifest,
                )
                break
            except (SessionError, OSError) as exc:
                if isinstance(exc, (SessionGpuMismatchError, AuthError)):
                    raise
                if attempt == _MAX_TRANSIENT_RETRIES - 1:
                    raise
                delay = _RETRY_DELAY_SECONDS * (2**attempt)
                time.sleep(delay)

        # Step 6-7: Execute and parse result (with session-dead retry)
        return self._execute_with_retry(
            session_name=session_name,
            manifest=manifest,
            secrets=secrets,
            args=args,
            kwargs=kwargs,
            debug=debug,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate(gpu: str | None) -> None:
        """Validate configuration parameters (fail-fast).

        Args:
            gpu: GPU type to validate.

        Raises:
            ValidationError: If the GPU type is not recognised.
        """
        if gpu is not None and gpu not in _KNOWN_GPUS:
            raise ValidationError(
                f"Unsupported GPU type: {gpu!r}. "
                f"Known GPU types: {', '.join(sorted(_KNOWN_GPUS))}"
            )

    def _prepare_session(
        self,
        session_name: str,
        gpu: str | None,
        manifest: ExecutionManifest,
    ) -> None:
        """Ensure the session is alive and requirements are installed.

        Source files are delivered inline in the wrapper code, so
        no artifact upload is needed.
        """
        # Step 4: Ensure session exists
        self._session.ensure_session(session_name, gpu)

        # Step 5: Ensure requirements are installed
        if manifest.requirements:
            self._session.ensure_requirements(
                session_name,
                manifest.requirements_hash,
                manifest.requirements,
            )

    def _execute_with_retry(
        self,
        session_name: str,
        manifest: ExecutionManifest,
        secrets: dict[str, str],
        args: tuple[object, ...],
        kwargs: dict[str, object],
        *,
        debug: bool = False,
    ) -> Any:
        """Execute the function on the VM and parse the result.

        Retries once if the session is dead (creates a fresh session).

        The execution is done by sending a Python script via
        ``colab exec`` stdin that:
            1. Writes all source files to the VM filesystem (via base64)
            2. Injects secrets
            3. Imports and calls the target function
            4. Emits the result via the ``__LAZY_*`` protocol

        Args:
            session_name: Colab VM session name.
            manifest: The execution manifest.
            secrets: Environment variables to inject.
            args: Positional arguments for the remote function.
            kwargs: Keyword arguments for the remote function.
            debug: If ``True``, print raw VM output.

        Returns:
            The deserialised return value.
        """
        wrapper = self._build_wrapper(
            manifest=manifest,
            secrets=secrets,
            args=args,
            kwargs=kwargs,
        )

        for attempt in range(2):
            try:
                return self._execute_and_parse(session_name, wrapper, debug=debug)
            except SessionDeadError:
                if attempt == 1:
                    raise
                self._session.start(session_name)

        raise RuntimeError(  # pragma: no cover
            "Unexpected: execution retry loop exhausted"
        )

    def _execute_and_parse(
        self,
        session_name: str,
        wrapper_code: str,
        *,
        debug: bool = False,
    ) -> Any:
        """Send wrapper code to the VM and parse the streamed result.

        Args:
            session_name: Colab VM session name.
            wrapper_code: Python source code to execute on the VM.
            debug: If ``True``, print every raw line from the VM.

        Returns:
            The deserialised return value.
        """
        stream = self._session.run_code(session_name, wrapper_code)
        gen = classify(stream)

        try:
            while True:
                msg = next(gen)
                if debug:
                    _debug_print(msg)
        except StopIteration as exc:
            result_msg: ResultMessage = exc.value
            if debug:
                print(
                    f"[colab-raw] __LAZY_RESULT__: {result_msg.value!r}",
                    file=sys.stderr,
                    flush=True,
                )
            return result_msg.value
        except RemoteExecutionError:
            # Debug-print the raw error lines, then re-raise
            if debug:
                print(
                    "[colab-raw] <<< Remote function raised an error >>>",
                    file=sys.stderr,
                    flush=True,
                )
            raise
        except SessionError as exc:
            if "dead" in str(exc).lower() or "not found" in str(exc).lower():
                raise SessionDeadError(str(exc)) from exc
            raise

    # ------------------------------------------------------------------
    # Wrapper code generation
    # ------------------------------------------------------------------

    @staticmethod
    def _build_wrapper(
        manifest: ExecutionManifest,
        secrets: dict[str, str],
        args: tuple[object, ...],
        kwargs: dict[str, object],
    ) -> str:
        """Build a self-contained Python wrapper for the Colab VM.

        The wrapper:
        1. Creates directories and writes all source files (base64-encoded)
        2. Adds the source directory to ``sys.path``
        3. Injects secrets
        4. Imports and calls the target function
        5. Emits ``__LAZY_RESULT__`` or ``__LAZY_ERROR__``

        No ``colab upload`` is needed — everything is sent via stdin.
        """
        module_path = _entry_point_to_module(manifest.entry_point)

        # ---- Build file-writing preamble ---------------------------------
        write_lines: list[str] = []
        base_dir = "/content/colab-files"

        for file_path in sorted(manifest.files, key=str):
            resolved = (
                file_path.resolve()
                if not file_path.is_absolute()
                else file_path
            )
            if not resolved.exists():
                continue

            content = resolved.read_bytes()
            encoded = base64.b64encode(content).decode("ascii")

            # Destination path on the VM (preserve relative structure)
            dest = f"{base_dir}/{file_path.as_posix()}"
            parent = str(Path(dest).parent)

            write_lines.append(f'os.makedirs("{parent}", exist_ok=True)')
            write_lines.append(
                f'with open("{dest}", "wb") as _f: '
                f'_f.write(base64.b64decode("{encoded}"))'
            )

        file_preamble = "\n".join(write_lines)

        # ---- Secrets -----------------------------------------------------
        secret_lines = ""
        if secrets:
            secret_lines = "\n".join(
                f'os.environ["{k}"] = {json.dumps(v)}'
                for k, v in secrets.items()
            )
            secret_lines += "\n"

        # ---- Args / kwargs ----------------------------------------------
        args_json = json.dumps(list(args))
        kwargs_json = json.dumps(kwargs)

        # ---- Assemble wrapper -------------------------------------------
        return f"""import base64, json, os, sys, traceback

# ---------------------------------------------------------------------------
# 1. Write source files on the VM
# ---------------------------------------------------------------------------
{file_preamble}
sys.path.insert(0, "{base_dir}")

# ---------------------------------------------------------------------------
# 2. Stdout protocol helpers
# ---------------------------------------------------------------------------
def _emit_result(value):
    print(f"__LAZY_RESULT__:{{json.dumps({{'status': 'ok', 'value': value}})}}", flush=True)

def _emit_error(exc):
    tb = traceback.format_exc().splitlines(keepends=True)
    payload = json.dumps({{
        "status": "error",
        "type": type(exc).__name__,
        "message": str(exc),
        "traceback": tb,
    }})
    print(f"__LAZY_ERROR__:{{payload}}", file=sys.stderr, flush=True)

# ---------------------------------------------------------------------------
# 3. Secrets injection
# ---------------------------------------------------------------------------
{secret_lines}
# ---------------------------------------------------------------------------
# 4. Import and execute the target function
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
"""
