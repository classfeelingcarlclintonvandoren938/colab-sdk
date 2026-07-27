"""Tests for ``_app.py`` and ``_function.py`` — ``App`` entry point and ``RemoteFunction``.

``ColabSession.__init__`` requires ``google-colab-cli`` on PATH and
non-Windows platform.  All external component classes are mocked so
``App`` can be constructed without the real CLI.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from colab._app import App
from colab._exceptions import ValidationError
from colab._function import RemoteFunction

# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture(autouse=True)
def _mock_app_components() -> Iterator[None]:
    """Mock all external component classes used by ``App.__init__``.

    This avoids needing ``google-colab-cli`` on PATH, and prevents
    ``ColabSession`` from checking ``sys.platform`` or calling real
    subprocesses.  Applied automatically to every test in this file.
    """
    with patch("colab._app.ColabSession") as mock_session_cls, \
         patch("colab._app.Analyzer"), \
         patch("colab._app.Packager"), \
         patch("colab._app.ExecutionEngine"):
        # Make ColabSession() return a MagicMock so app._session works
        mock_session_cls.return_value = MagicMock()
        yield


@pytest.fixture
def app() -> App:
    """Create an ``App`` with GPU set to ``\"T4\"``."""
    return App(gpu="T4")


@pytest.fixture
def mock_engine(app: App) -> Iterator[MagicMock]:
    """Return a patch on ``app.engine.execute``."""
    with patch.object(app.engine, "execute") as m:
        yield m


# ======================================================================
# Test: App construction
# ======================================================================


class TestAppConstruction:
    """App creation with various configurations."""

    def test_creates_with_defaults(self) -> None:
        """Default App is created without error."""
        app = App()
        assert app.gpu is None
        assert app._idle_timeout == "30m"
        assert app.session_name.startswith("colab-session-")

    def test_creates_with_gpu(self) -> None:
        """GPU type is stored."""
        app = App(gpu="A100")
        assert app.gpu == "A100"

    def test_creates_with_session_name(self) -> None:
        """Custom session name is stored."""
        app = App(session_name="my-training")
        assert app.session_name == "my-training"

    def test_invalid_gpu_raises(self) -> None:
        """Unknown GPU type raises ValidationError."""
        with pytest.raises(ValidationError, match="Unsupported GPU"):
            App(gpu="INVALID_GPU")

    def test_invalid_idle_timeout_raises(self) -> None:
        """Bad idle_timeout format raises ValidationError."""
        with pytest.raises(ValidationError, match="Invalid idle_timeout"):
            App(idle_timeout="abc")

    def test_valid_idle_timeout_formats(self) -> None:
        """Valid idle_timeout formats are accepted."""
        for timeout in ["30m", "1h", "120m", "24h"]:
            app = App(idle_timeout=timeout)
            assert app._idle_timeout == timeout

    def test_engine_created(self) -> None:
        """App creates an ExecutionEngine."""
        app = App(gpu="T4")
        assert app.engine is not None

    def test_secrets_empty(self) -> None:
        """Secrets dictionary starts empty."""
        app = App()
        assert app.secrets == {}


# ======================================================================
# Test: @app.function decorator
# ======================================================================


class TestAppFunctionDecorator:
    """The ``@app.function`` decorator in both forms."""

    def test_bare_decorator_returns_remote_function(self, app: App) -> None:
        """``@app.function`` (bare) returns a ``RemoteFunction``."""

        @app.function
        def my_func() -> str:
            return "hello"

        assert isinstance(my_func, RemoteFunction)
        assert my_func.name == "my_func"

    def test_decorator_with_gpu(self, app: App) -> None:
        """``@app.function(gpu=\"A100\")`` stores the GPU override."""

        @app.function(gpu="A100")
        def my_func() -> str:
            return "hello"

        assert isinstance(my_func, RemoteFunction)
        assert my_func.gpu == "A100"

    def test_decorator_with_timeout(self, app: App) -> None:
        """``@app.function(timeout=600)`` stores the timeout."""

        @app.function(timeout=600)
        def my_func() -> str:
            return "hello"

        assert isinstance(my_func, RemoteFunction)
        assert my_func.timeout == 600

    def test_decorator_inherits_app_gpu(self, app: App) -> None:
        """Without GPU override, function inherits the App default."""

        @app.function
        def my_func() -> str:
            return "hello"

        assert my_func.gpu is None  # None means "use app default"

    def test_source_file_is_set(self, app: App) -> None:
        """RemoteFunction stores the path to the source file."""

        @app.function
        def my_func() -> str:
            return "hello"

        assert my_func.source_file.suffix == ".py"
        assert my_func.source_file.exists()

    def test_multiple_functions(self, app: App) -> None:
        """Multiple functions can be registered on the same App."""

        @app.function
        def fn1() -> str:
            return "one"

        @app.function(gpu="L4", timeout=120)
        def fn2() -> str:
            return "two"

        assert fn1.name == "fn1"
        assert fn2.name == "fn2"
        assert fn2.gpu == "L4"
        assert fn2.timeout == 120


# ======================================================================
# Test: RemoteFunction.remote()
# ======================================================================


class TestRemoteFunctionRemote:
    """The ``remote()`` method delegates to the engine."""

    def test_remote_calls_engine_execute(self, app: App, mock_engine: MagicMock) -> None:
        """``remote()`` delegates to ``ExecutionEngine.execute()``."""

        @app.function(gpu="T4")
        def train(epochs: int) -> dict[str, object]:
            return {"done": True, "epochs": epochs}

        mock_engine.return_value = {"done": True}
        result = train.remote(epochs=10)

        assert result == {"done": True}
        mock_engine.assert_called_once()

        call_args = mock_engine.call_args[1]
        assert call_args["function_name"] == "train"
        assert call_args["args"] == ()
        assert call_args["kwargs"] == {"epochs": 10}
        assert call_args["secrets"] == {}
        assert call_args["session_name"] == app.session_name
        assert call_args["gpu"] == "T4"

    def test_remote_no_args(self, app: App, mock_engine: MagicMock) -> None:
        """``remote()`` with no arguments is valid."""

        @app.function
        def hello() -> str:
            return "world"

        mock_engine.return_value = "world"
        result = hello.remote()
        assert result == "world"

    def test_remote_passes_secrets(self, app: App, mock_engine: MagicMock) -> None:
        """Secrets stored on App are forwarded to the engine."""

        @app.function
        def train() -> str:
            return "done"

        app.secret("TOKEN", "abc123")
        train.remote()
        call_kwargs = mock_engine.call_args[1]
        assert call_kwargs["secrets"] == {"TOKEN": "abc123"}


# ======================================================================
# Test: App lifecycle (login, shutdown)
# ======================================================================


class TestAppLifecycle:
    """login() and shutdown() methods."""

    def test_login_calls_status(self) -> None:
        """``login()`` triggers a session status check."""
        app = App()
        with patch.object(app._session, "status") as mock_status:
            app.login()
            mock_status.assert_called_once()

    def test_login_swallows_errors(self) -> None:
        """``login()`` is resilient to status errors."""
        app = App()
        with patch.object(
            app._session, "status", side_effect=Exception("no CLI")
        ):
            app.login()  # Should not raise

    def test_shutdown_calls_stop(self) -> None:
        """``shutdown()`` calls ``session.stop()``."""
        app = App()
        with patch.object(app._session, "stop") as mock_stop:
            app.shutdown()
            mock_stop.assert_called_once_with(app.session_name)

    def test_shutdown_idempotent(self) -> None:
        """``shutdown()`` is safe to call multiple times."""
        app = App()
        with patch.object(app._session, "stop") as mock_stop:
            app.shutdown()
            app.shutdown()
            app.shutdown()
            assert mock_stop.call_count == 3  # No crash


# ======================================================================
# Test: App file transfer
# ======================================================================


class TestAppFileTransfer:
    """upload() and download() methods."""

    def test_upload_calls_ensure_session_and_upload(self) -> None:
        """``upload()`` ensures session then uploads."""
        app = App(gpu="T4")
        with patch.object(app._session, "ensure_session") as mock_ensure, \
             patch.object(app._session, "upload") as mock_upload:
            app.upload("model.pt", "/content/model.pt")

            mock_ensure.assert_called_once_with(app.session_name, "T4")
            mock_upload.assert_called_once_with(
                app.session_name, "model.pt", "/content/model.pt"
            )

    def test_download_calls_ensure_session_and_download(self) -> None:
        """``download()`` ensures session then downloads."""
        app = App(gpu="T4")
        expected_path = Path("./checkpoint.pt").resolve()
        with patch.object(app._session, "ensure_session") as mock_ensure, \
             patch.object(
                 app._session, "download", return_value=expected_path
             ):
            result = app.download("checkpoint.pt")

            mock_ensure.assert_called_once_with(app.session_name, "T4")
            assert result == expected_path


# ======================================================================
# Test: App secrets
# ======================================================================


class TestAppSecrets:
    """secret() method."""

    def test_stores_and_retrieves_secret(self) -> None:
        """A secret stored via ``secret()`` appears in ``secrets``."""
        app = App()
        app.secret("HF_TOKEN", "hf_abc123")
        assert app.secrets == {"HF_TOKEN": "hf_abc123"}

    def test_overwrites_existing_secret(self) -> None:
        """Calling ``secret()`` twice with the same key overwrites."""
        app = App()
        app.secret("KEY", "old_value")
        app.secret("KEY", "new_value")
        assert app.secrets == {"KEY": "new_value"}

    def test_multiple_secrets(self) -> None:
        """Multiple secrets are stored independently."""
        app = App()
        app.secret("A", "1")
        app.secret("B", "2")
        app.secret("C", "3")
        assert app.secrets == {"A": "1", "B": "2", "C": "3"}


# ======================================================================
# Test: RemoteFunction properties
# ======================================================================


class TestRemoteFunctionProperties:
    """RemoteFunction metadata access."""

    def test_name(self, app: App) -> None:
        """``name`` returns the function name."""

        @app.function
        def my_func() -> str:
            return "hello"

        assert my_func.name == "my_func"

    def test_source_file(self, app: App) -> None:
        """``source_file`` is an existing ``.py`` file."""

        @app.function
        def my_func() -> str:
            return "hello"

        assert isinstance(my_func.source_file, Path)
        assert my_func.source_file.name == "test_app.py"
