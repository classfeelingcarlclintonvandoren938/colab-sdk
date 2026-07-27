"""RemoteFunction — thin handle created by ``@app.function`` decorator.

A ``RemoteFunction`` holds metadata about a registered function and
delegates ``.remote()`` calls to the owning ``App``'s execution engine.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from colab._app import App

__all__ = [
    "RemoteFunction",
]


class RemoteFunction:
    """A handle that wraps a Python function for remote execution.

    Created by the ``@app.function`` decorator.  Stores function metadata
    and delegates ``.remote()`` to the owning ``App``.

    Usage::

        @app.function(gpu="T4")
        def train(epochs: int) -> dict:
            ...

        result = train.remote(epochs=10)
    """

    def __init__(
        self,
        fn: Callable[..., Any],
        app: App,
        gpu: str | None = None,
        timeout: int | None = None,
    ) -> None:
        """Initialise a RemoteFunction.

        Args:
            fn: The original Python function.
            app: The owning ``App`` instance.
            gpu: Optional GPU override for this specific function.
            timeout: Optional execution timeout in seconds.
        """
        self._fn = fn
        self._app = app
        self._gpu = gpu
        self._timeout = timeout
        self._name = fn.__name__
        self._source_file = Path(inspect.getfile(fn))

    # ------------------------------------------------------------------
    # Properties (read-only metadata access)
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        """The original function name."""
        return self._name

    @property
    def gpu(self) -> str | None:
        """GPU type override for this function, or ``None``."""
        return self._gpu

    @property
    def timeout(self) -> int | None:
        """Execution timeout in seconds, or ``None``."""
        return self._timeout

    @property
    def source_file(self) -> Path:
        """Path to the ``.py`` file containing the function."""
        return self._source_file

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def remote(
        self,
        *args: object,
        debug: bool = False,
        **kwargs: object,
    ) -> Any:
        """Execute the function remotely on a Colab VM.

        Args:
            *args: Positional arguments forwarded to the remote function.
            debug: If ``True``, print every raw line from the VM to stderr
                for debugging purposes.
            **kwargs: Keyword arguments forwarded to the remote function.

        Returns:
            The deserialised return value of the remote function.

        Raises:
            RemoteExecutionError: If the remote function raises.
            ValidationError: If configuration is invalid.
            AnalysisError: If dependency analysis fails.
            PackagingError: If artifact packaging fails.
            SessionError: If session operations fail.
            ProtocolError: If the stdout protocol is malformed.

        .. note::

            All ``args`` and ``kwargs`` must be JSON-serialisable.
            They are embedded into ``runner.py`` on the Colab VM.
        """
        return self._app._execute_remote(
            function=self,
            args=args,
            kwargs=kwargs,
            debug=debug,
        )
