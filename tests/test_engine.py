"""Tests for ``_engine.py`` — ``ExecutionEngine`` pipeline orchestrator.

All external components (Analyzer, Packager, ColabSession) are mocked.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from colab._engine import ExecutionEngine
from colab._exceptions import (
    AuthError,
    ProtocolError,
    RemoteExecutionError,
    SessionDeadError,
    SessionGpuMismatchError,
    ValidationError,
)


@pytest.fixture
def mock_analyzer() -> MagicMock:
    """Mock ``Analyzer`` returning a canned manifest."""
    mock = MagicMock()
    manifest = MagicMock()
    manifest.function_name = "train"
    manifest.requirements = ["torch", "numpy"]
    manifest.requirements_hash = "abc123"
    manifest.files = [Path("app.py"), Path("utils/helper.py")]
    mock.analyze.return_value = manifest
    return mock


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock ``ColabSession`` with no-op methods."""
    mock = MagicMock()
    mock.run_code.return_value = iter([])
    return mock


@pytest.fixture
def engine(
    mock_analyzer: MagicMock,
    mock_session: MagicMock,
) -> ExecutionEngine:
    """Create an ``ExecutionEngine`` with all mocked components."""
    return ExecutionEngine(
        analyzer=mock_analyzer,
        session=mock_session,
    )


# ======================================================================
# Construction
# ======================================================================


class TestConstruction:
    """Engine creation with dependency injection."""

    def test_creates_with_components(
        self,
        mock_analyzer: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Engine stores injected components."""
        eng = ExecutionEngine(mock_analyzer, mock_session)
        assert eng._analyzer is mock_analyzer
        assert eng._session is mock_session


# ======================================================================
# Validate
# ======================================================================


class TestValidate:
    """Static validation of configuration."""

    def test_valid_gpu(self) -> None:
        """Known GPU types pass validation."""
        for gpu in ["T4", "L4", "A100", "H100"]:
            ExecutionEngine._validate(gpu)  # no error

    def test_none_gpu(self) -> None:
        """``None`` GPU (CPU session) is valid."""
        ExecutionEngine._validate(None)  # no error

    def test_invalid_gpu(self) -> None:
        """Unknown GPU raises ``ValidationError``."""
        with pytest.raises(ValidationError, match="Unsupported GPU"):
            ExecutionEngine._validate("RTX_4090")


# ======================================================================
# PrepareSession
# ======================================================================


class TestPrepareSession:
    """The ``_prepare_session`` internal helper (no upload step)."""

    def test_calls_ensure_session(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """``_prepare_session`` calls ``session.ensure_session``."""
        manifest = MagicMock()
        manifest.requirements = ["torch"]
        manifest.requirements_hash = "abc"

        engine._prepare_session("s", "T4", manifest)
        mock_session.ensure_session.assert_called_once_with("s", "T4")

    def test_calls_ensure_requirements_with_packages(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """With non-empty requirements, ``ensure_requirements`` is called."""
        manifest = MagicMock()
        manifest.requirements = ["torch", "numpy"]
        manifest.requirements_hash = "abc123"

        engine._prepare_session("s", None, manifest)
        mock_session.ensure_requirements.assert_called_once_with(
            "s", "abc123", ["torch", "numpy"]
        )

    def test_skips_requirements_when_empty(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """With empty requirements, ``ensure_requirements`` is NOT called."""
        manifest = MagicMock()
        manifest.requirements = []

        engine._prepare_session("s", None, manifest)
        mock_session.ensure_requirements.assert_not_called()

    def test_no_upload_called(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """No upload happens during prepare (files are inlined in wrapper)."""
        manifest = MagicMock()
        manifest.requirements = []

        engine._prepare_session("s", None, manifest)
        mock_session.upload.assert_not_called()


# ======================================================================
# ExecuteAndParse
# ======================================================================


class TestExecuteAndParse:
    """The ``_execute_and_parse`` internal helper."""

    def test_returns_result_value(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Valid execution returns the remote function's return value."""
        import json

        payload = json.dumps({"status": "ok", "value": 42})
        mock_session.run_code.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]

        result = engine._execute_and_parse("s", "wrapper_code")
        assert result == 42

    def test_raises_on_error(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Error stream raises ``RemoteExecutionError``."""
        import json

        payload = json.dumps({
            "status": "error",
            "type": "ValueError",
            "message": "bad things",
            "traceback": ['  File "runner.py", line 1\n'],
        })
        mock_session.run_code.return_value = [
            f"__LAZY_ERROR__:{payload}",
        ]

        with pytest.raises(RemoteExecutionError, match="ValueError: bad things"):
            engine._execute_and_parse("s", "wrapper_code")

    def test_protocol_error_propagates(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Malformed protocol raises ``ProtocolError``."""
        mock_session.run_code.return_value = [
            "__LAZY_RESULT__:{bad json}",
        ]

        with pytest.raises(ProtocolError):
            engine._execute_and_parse("s", "wrapper_code")


# ======================================================================
# ExecuteWithRetry
# ======================================================================


class TestExecuteWithRetry:
    """Session-dead retry logic."""

    def test_first_attempt_succeeds(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """If the first execute attempt succeeds, no retry."""
        import json

        manifest = MagicMock()
        manifest.entry_point = Path("app.py")
        manifest.function_name = "train"
        manifest.files = [Path("app.py")]
        payload = json.dumps({"status": "ok", "value": "success"})
        mock_session.run_code.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]

        result = engine._execute_with_retry(
            session_name="s",
            manifest=manifest,
            secrets={},
            args=(),
            kwargs={},
        )
        assert result == "success"

    def test_retries_on_session_dead(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """On ``SessionDeadError``, engine restarts session and retries."""
        import json

        manifest = MagicMock()
        manifest.entry_point = Path("app.py")
        manifest.function_name = "train"
        manifest.files = [Path("app.py")]
        payload = json.dumps({"status": "ok", "value": "recovered"})

        mock_session.run_code.side_effect = [
            SessionDeadError("session gone"),
            [f"__LAZY_RESULT__:{payload}"],
        ]

        result = engine._execute_with_retry(
            session_name="s",
            manifest=manifest,
            secrets={},
            args=(),
            kwargs={},
        )
        assert result == "recovered"
        mock_session.start.assert_called_once_with("s")


# ======================================================================
# Execute (full pipeline)
# ======================================================================


class TestExecute:
    """The full ``execute()`` pipeline."""

    def test_full_success(
        self,
        engine: ExecutionEngine,
        mock_analyzer: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Full pipeline succeeds with valid inputs."""
        import json

        payload = json.dumps({"status": "ok", "value": "done"})
        mock_session.run_code.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]

        result = engine.execute(
            function_name="train",
            source_file=Path("app.py"),
            args=(10,),
            kwargs={"lr": 0.001},
            secrets={"TOKEN": "abc"},
            session_name="my-session",
            gpu="T4",
        )

        assert result == "done"

        # Verify each step was called
        mock_analyzer.analyze.assert_called_once_with("train", Path("app.py"))
        mock_session.ensure_session.assert_called_once_with("my-session", "T4")
        mock_session.run_code.assert_called_once()
        # No upload should happen
        mock_session.upload.assert_not_called()

    def test_validate_before_analyze(
        self,
        engine: ExecutionEngine,
        mock_analyzer: MagicMock,
    ) -> None:
        """Invalid GPU raises before any analysis happens."""
        with pytest.raises(ValidationError, match="Unsupported GPU"):
            engine.execute(
                function_name="train",
                source_file=Path("app.py"),
                gpu="INVALID_GPU",
            )
        mock_analyzer.analyze.assert_not_called()

    def test_gpu_mismatch_not_retried(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """``SessionGpuMismatchError`` raises immediately, no retry."""
        import json

        payload = json.dumps({"status": "ok", "value": "done"})
        mock_session.run_code.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]
        mock_session.ensure_session.side_effect = SessionGpuMismatchError(
            "GPU mismatch: T4 vs A100"
        )

        with pytest.raises(SessionGpuMismatchError, match="GPU mismatch"):
            engine.execute(
                function_name="train",
                source_file=Path("app.py"),
                gpu="T4",
            )

    def test_auth_error_not_retried(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """``AuthError`` raises immediately, no retry."""
        import json

        payload = json.dumps({"status": "ok", "value": "done"})
        mock_session.run_code.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]
        mock_session.ensure_session.side_effect = AuthError("authentication failed")

        with pytest.raises(AuthError, match="authentication"):
            engine.execute(
                function_name="train",
                source_file=Path("app.py"),
                gpu="T4",
            )
