"""App — SDK entry point for Colab Client.

The ``App`` is the single top-level object users interact with.  It
owns the execution engine, session, and all configuration.  Usage::

    from colab import App

    app = App(gpu="T4")

    @app.function
    def hello() -> str:
        return "Hello from Colab!"

    print(hello.remote())
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, overload

from colab._analyzer import Analyzer
from colab._engine import ExecutionEngine
from colab._exceptions import ValidationError
from colab._session import ColabSession

if TYPE_CHECKING:
    from colab._function import RemoteFunction

__all__ = [
    "App",
]

# Known GPU types — matches the list in ``_engine._KNOWN_GPUS``.
_KNOWN_GPUS = frozenset({"T4", "L4", "A100", "H100"})

# Pattern for idle_timeout: digits followed by "m" (minutes) or "h" (hours).
_IDLE_TIMEOUT_PATTERN = re.compile(r"^(\d+)(m|h)$")


class App:
    """SDK entry point.  Holds configuration, engine, and session.

    Usage::

        app = App(gpu="T4")
    """

    def __init__(
        self,
        gpu: str | None = None,
        idle_timeout: str | None = "30m",
        session_name: str | None = None,
    ) -> None:
        """Initialise the App.

        Args:
            gpu: GPU type (``\\\"T4\\\"``, ``\\\"L4\\\"``, ``\\\"A100\\\"``,
                ``\\\"H100\\\"``, or ``None`` for CPU).
            idle_timeout: Session idle timeout before auto-shutdown.
                Format: ``\\\"30m\\\"``, ``\\\"1h\\\"``.  Currently a placeholder
                — keep-alive is managed by ``google-colab-cli``.
            session_name: Optional name for the Colab session.
                Auto-generated if omitted.

        Raises:
            ValidationError: If ``gpu`` is not recognised or
                ``idle_timeout`` has an invalid format.
        """
        # -- validate GPU --------------------------------------------------
        if gpu is not None and gpu not in _KNOWN_GPUS:
            raise ValidationError(
                f"Unsupported GPU type: {gpu!r}. "
                f"Known GPU types: {', '.join(sorted(_KNOWN_GPUS))}"
            )

        # -- validate idle_timeout -----------------------------------------
        if idle_timeout is not None:
            if not _IDLE_TIMEOUT_PATTERN.match(idle_timeout):
                raise ValidationError(
                    f"Invalid idle_timeout format: {idle_timeout!r}. "
                    "Expected format like '30m' or '1h'."
                )

        self._gpu = gpu
        self._idle_timeout = idle_timeout
        self._session_name = session_name or f"colab-session-{uuid.uuid4().hex[:8]}"
        self._secrets: dict[str, str] = {}

        # Create internal components (lazy — no VM created)
        project_root = Path.cwd().resolve()
        # Exclude the SDK itself so its internal imports (dotenv, etc.)
        # do not leak into the remote execution manifest.
        self._analyzer = Analyzer(
            project_root=project_root,
            exclude_packages=frozenset({"colab"}),
        )
        self._session = ColabSession()
        self._engine = ExecutionEngine(
            analyzer=self._analyzer,
            session=self._session,
        )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def engine(self) -> ExecutionEngine:
        """The ``ExecutionEngine`` instance used for all remote calls."""
        return self._engine

    @property
    def session_name(self) -> str:
        """The name of the Colab VM session."""
        return self._session_name

    @property
    def gpu(self) -> str | None:
        """The default GPU type for this App."""
        return self._gpu

    @property
    def secrets(self) -> dict[str, str]:
        """A read-only view of the stored secrets."""
        return dict(self._secrets)

    # ------------------------------------------------------------------
    # Decorator API
    # ------------------------------------------------------------------

    @overload
    def function(
        self,
        fn: Callable[..., Any],
        *,
        gpu: str | None = ...,
        timeout: int | None = ...,
    ) -> RemoteFunction: ...

    @overload
    def function(
        self,
        fn: None = ...,
        *,
        gpu: str | None = ...,
        timeout: int | None = ...,
    ) -> Callable[[Callable[..., Any]], RemoteFunction]: ...

    def function(
        self,
        fn: Callable[..., Any] | None = None,
        *,
        gpu: str | None = None,
        timeout: int | None = None,
    ) -> RemoteFunction | Callable[[Callable[..., Any]], RemoteFunction]:
        """Register a function for remote execution.

        Supports two forms::

            # Bare decorator (no arguments)
            @app.function
            def train():
                ...

            # Decorator with arguments
            @app.function(gpu="T4", timeout=300)
            def train():
                ...

        Args:
            fn: The decorated function.  ``None`` when called
                with keyword arguments (second form).
            gpu: Override the default GPU type for this function.
            timeout: Execution timeout in seconds.

        Returns:
            A ``RemoteFunction`` instance when called with a function,
            or a decorator function when called with keyword arguments.
        """
        from colab._function import RemoteFunction  # noqa: PLC0415 — late import avoids edge cases

        def decorator(f: Callable[..., Any]) -> RemoteFunction:
            return RemoteFunction(
                fn=f,
                app=self,
                gpu=gpu,
                timeout=timeout,
            )

        if fn is not None:
            # Used as ``@app.function`` (bare decorator)
            return decorator(fn)

        # Used as ``@app.function(gpu=..., timeout=...)``
        return decorator

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def login(self) -> None:
        """Trigger Google Colab authentication.

        Idempotent — safe to call multiple times.  If already
        authenticated, this is a no-op.  Auto-triggered before the
        first ``.remote()`` call if not already authenticated.

        Note:
            Currently this is a best-effort trigger.  The ``google-colab-cli``
            handles authentication automatically on the first command that
            requires it.
        """
        # Run a lightweight status check to trigger any pending auth flow.
        # The CLI will prompt for authentication if needed.
        try:
            self._session.status(self._session_name)
        except Exception:
            pass  # Swallow — real errors surface on .remote()

    def shutdown(self) -> None:
        """Explicitly terminate the Colab session.

        Idempotent — safe to call multiple times.  If no session
        exists, this is a no-op.  After shutdown, subsequent
        ``.remote()`` calls create a fresh session.
        """
        try:
            self._session.stop(self._session_name)
        except Exception:
            pass  # Idempotent: no session or already stopped

    # ------------------------------------------------------------------
    # File transfer (convenience wrappers)
    # ------------------------------------------------------------------

    def upload(
        self,
        local_path: str | Path,
        remote_path: str | None = None,
    ) -> None:
        """Upload a local file or directory to the Colab VM.

        Creates the session lazily if not already active.

        Args:
            local_path: Path to the local file or directory.
            remote_path: Destination path on the Colab VM.  Defaults
                to ``/content/<filename>``.

        Raises:
            FileNotFoundError: If the local file does not exist.
            SessionError: If upload fails.
        """
        self._session.ensure_session(self._session_name, self._gpu)
        self._session.upload(self._session_name, str(local_path), remote_path)

    def download(
        self,
        remote_path: str,
        local_path: str | Path | None = None,
    ) -> Path:
        """Download a file from the Colab VM to the local machine.

        Creates the session lazily if not already active.

        Args:
            remote_path: Path to the file on the Colab VM.
            local_path: Destination path locally.  Defaults to
                ``./<filename>``.

        Returns:
            The absolute local path the file was downloaded to.

        Raises:
            SessionError: If the download fails.
        """
        self._session.ensure_session(self._session_name, self._gpu)
        return self._session.download(self._session_name, remote_path, local_path)

    # ------------------------------------------------------------------
    # Secrets
    # ------------------------------------------------------------------

    def secret(self, name: str, value: str) -> None:
        """Store an environment variable for injection into remote execution.

        Secrets are embedded into ``runner.py`` before execution.  They are
        **not** sent to the VM until the next ``.remote()`` call.

        Args:
            name: Environment variable name.
            value: Environment variable value.

        Note:
            Secrets are not persisted across script restarts.
        """
        self._secrets[name] = value

    # ------------------------------------------------------------------
    # Internal: called by RemoteFunction.remote()
    # ------------------------------------------------------------------

    def _execute_remote(
        self,
        function: RemoteFunction,
        args: tuple[object, ...],
        kwargs: dict[str, object],
        *,
        debug: bool = False,
    ) -> Any:
        """Execute a ``RemoteFunction`` via the engine.

        Extracts metadata from the function and delegates to
        ``ExecutionEngine.execute()``.

        Args:
            function: The ``RemoteFunction`` to execute.
            args: Positional arguments for the remote function.
            kwargs: Keyword arguments for the remote function.
            debug: If ``True``, print raw VM output for debugging.

        Returns:
            The deserialised return value.
        """
        return self._engine.execute(
            function_name=function.name,
            source_file=function.source_file,
            args=args,
            kwargs=kwargs,
            secrets=self._secrets,
            session_name=self._session_name,
            gpu=function.gpu or self._gpu,
            debug=debug,
        )
