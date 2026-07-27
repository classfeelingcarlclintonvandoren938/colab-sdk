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
        secrets={"HF_TOKEN": "abc"},
    )
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from colab._analyzer import Analyzer
from colab._exceptions import (
    AuthError,
    SessionDeadError,
    SessionError,
    SessionGpuMismatchError,
    ValidationError,
)
from colab._manifest import ExecutionManifest
from colab._packager import Artifact, Packager
from colab._protocol import ResultMessage, classify
from colab._session import ColabSession

__all__ = [
    "ExecutionEngine",
]

# Known GPU types for validation
_KNOWN_GPUS = frozenset({"T4", "L4", "A100", "H100"})

# Retry defaults
_MAX_TRANSIENT_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0


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
    ) -> Any:
        """Execute a function remotely on a Colab VM.

        The full pipeline::

            validate → analyze → package → ensure_session →
            ensure_requirements → upload → execute → parse → return

        Args:
            function_name: Name of the function to execute.
            source_file: Path to the ``.py`` file containing the function.
            args: Positional arguments for the remote function.
            kwargs: Keyword arguments for the remote function.
            secrets: Environment variables to inject on the VM.
            session_name: Name for the Colab VM session.
            gpu: GPU type (``\"T4\"``, ``\"L4\"``, ``\"A100\"``, ``\"H100\"``,
                or ``None`` for CPU).

        Returns:
            The deserialised return value of the remote function.

        Raises:
            ValidationError: If GPU type is invalid.
            AnalysisError: If static analysis fails.
            PackagingError: If artifact packaging fails.
            SessionError: If session or upload operations fail.
            RemoteExecutionError: If the remote function raises.
            ProtocolError: If the stdout protocol is malformed.
        """
        kwargs = kwargs or {}
        secrets = secrets or {}

        # Step 1: Validate
        self._validate(gpu)

        # Step 2: Analyse
        manifest = self._analyzer.analyze(function_name, source_file)

        # Step 3: Package
        artifact = self._packager.build(manifest, args, kwargs, secrets)

        # Steps 4-6: Session management (with retry for transient failures)
        for attempt in range(_MAX_TRANSIENT_RETRIES):
            try:
                self._prepare_session(
                    session_name=session_name,
                    gpu=gpu,
                    manifest=manifest,
                    artifact=artifact,
                )
                break  # Success — exit retry loop
            except (SessionError, OSError) as exc:
                # Non-retriable errors: configuration or auth failures
                if isinstance(exc, (SessionGpuMismatchError, AuthError)):
                    raise
                if attempt == _MAX_TRANSIENT_RETRIES - 1:
                    raise
                delay = _RETRY_DELAY_SECONDS * (2**attempt)
                time.sleep(delay)

        # Step 7-8: Execute and parse result (with session-dead retry)
        return self._execute_with_retry(
            session_name=session_name,
            artifact=artifact,
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
        artifact: Artifact,
    ) -> None:
        """Ensure the session is alive and the artifact is uploaded.

        Steps 4-6 in the pipeline.
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

        # Step 6: Upload the artifact
        remote_path = f"/content/.colab-client/artifacts/{artifact.hash}/artifact.tar.gz"
        self._session.upload(session_name, str(artifact.path), remote_path)

    def _execute_with_retry(
        self,
        session_name: str,
        artifact: Artifact,
    ) -> Any:
        """Execute the artifact on the VM and parse the result.

        Retries once if the session is dead (creates a fresh session).

        Args:
            session_name: Colab VM session name.
            artifact: The packaged artifact.

        Returns:
            The deserialised return value.

        Raises:
            RemoteExecutionError: If the remote function raises.
            ProtocolError: If the output protocol is malformed.
        """
        # Construct the remote runner path
        runner_path = (
            f"/content/.colab-client/artifacts/{artifact.hash}/runner.py"
        )

        for attempt in range(2):  # At most one retry for session death
            try:
                return self._execute_and_parse(session_name, runner_path)
            except SessionDeadError:
                if attempt == 1:
                    raise
                # Session died — recreate and retry once
                self._session.start(session_name)

        # Shouldn't be reached, but satisfies the return type
        raise RuntimeError("Unexpected: execution retry loop exhausted")  # pragma: no cover

    def _execute_and_parse(
        self,
        session_name: str,
        runner_path: str,
    ) -> Any:
        """Execute the runner on the VM and parse the stream.

        Args:
            session_name: Colab VM session name.
            runner_path: Path to ``runner.py`` on the VM.

        Returns:
            The deserialised return value.

        Raises:
            RemoteExecutionError: If the remote function raised.
            ProtocolError: If the output protocol is malformed.
            SessionDeadError: If the session is dead.
        """
        stream = self._session.execute(session_name, runner_path)
        gen = classify(stream)

        try:
            while True:
                next(gen)
                # LogMessage and ProgressMessage are yielded in real-time.
                # Forwarding to callbacks will be added in v0.2.
        except StopIteration as exc:
            result_msg: ResultMessage = exc.value
            return result_msg.value
        except SessionError as exc:
            # SessionError during execution → session might be dead
            if "dead" in str(exc).lower() or "not found" in str(exc).lower():
                raise SessionDeadError(str(exc)) from exc
            raise
