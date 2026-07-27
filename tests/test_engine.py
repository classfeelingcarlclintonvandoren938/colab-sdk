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
def mock_packager() -> MagicMock:
    """Mock ``Packager`` returning a canned artifact."""
    mock = MagicMock()
    artifact = MagicMock()
    artifact.path = Path("/tmp/cached/abc.tar.gz")
    artifact.hash = "def456"
    artifact.size = 1024
    mock.build.return_value = artifact
    return mock


@pytest.fixture
def mock_session() -> MagicMock:
    """Mock ``ColabSession`` with no-op methods."""
    mock = MagicMock()
    # execute() returns a generator that yields nothing and completes
    mock.execute.return_value = iter([])
    return mock


@pytest.fixture
def engine(
    mock_analyzer: MagicMock,
    mock_packager: MagicMock,
    mock_session: MagicMock,
) -> ExecutionEngine:
    """Create an ``ExecutionEngine`` with all mocked components."""
    return ExecutionEngine(
        analyzer=mock_analyzer,
        packager=mock_packager,
        session=mock_session,
    )


class TestConstruction:
    """Engine creation with dependency injection."""

    def test_creates_with_components(
        self,
        mock_analyzer: MagicMock,
        mock_packager: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Engine stores injected components."""
        eng = ExecutionEngine(mock_analyzer, mock_packager, mock_session)
        assert eng._analyzer is mock_analyzer
        assert eng._packager is mock_packager
        assert eng._session is mock_session


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


class TestPrepareSession:
    """The ``_prepare_session`` internal helper."""

    def test_calls_ensure_session(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """``_prepare_session`` calls ``session.ensure_session``."""
        manifest = MagicMock()
        manifest.requirements = ["torch"]
        manifest.requirements_hash = "abc"
        artifact = MagicMock()
        artifact.hash = "def"
        artifact.path = Path("/tmp/a.tar.gz")

        engine._prepare_session("s", "T4", manifest, artifact)
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
        artifact = MagicMock()
        artifact.hash = "def"
        artifact.path = Path("/tmp/a.tar.gz")

        engine._prepare_session("s", None, manifest, artifact)
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
        artifact = MagicMock()
        artifact.hash = "def"
        artifact.path = Path("/tmp/a.tar.gz")

        engine._prepare_session("s", None, manifest, artifact)
        mock_session.ensure_requirements.assert_not_called()

    def test_calls_upload(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """``_prepare_session`` uploads the artifact."""
        manifest = MagicMock()
        manifest.requirements = []
        artifact = MagicMock()
        artifact.hash = "myhash"
        artifact.path = Path("/local/artifact.tar.gz")

        engine._prepare_session("s", None, manifest, artifact)
        expected_remote = "/content/.colab-client/artifacts/myhash/artifact.tar.gz"
        # Normalize paths for cross-platform comparison
        mock_session.upload.assert_called_once()
        call_args = mock_session.upload.call_args[0]
        assert call_args[0] == "s"
        assert Path(call_args[1]) == artifact.path
        assert call_args[2] == expected_remote


class TestExecuteAndParse:
    """The ``_execute_and_parse`` internal helper."""

    def test_returns_result_value(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Valid execution returns the remote function's return value."""
        # Build a proper result stream
        import json

        payload = json.dumps({"status": "ok", "value": 42})
        mock_session.execute.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]

        result = engine._execute_and_parse("s", "/runner.py")
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
            "traceback": ["  File \"runner.py\", line 1\n"],
        })
        mock_session.execute.return_value = [
            f"__LAZY_ERROR__:{payload}",
        ]

        with pytest.raises(RemoteExecutionError, match="ValueError: bad things"):
            engine._execute_and_parse("s", "/runner.py")

    def test_protocol_error_propagates(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Malformed protocol raises ``ProtocolError``."""
        mock_session.execute.return_value = [
            "__LAZY_RESULT__:{bad json}",
        ]

        with pytest.raises(ProtocolError):
            engine._execute_and_parse("s", "/runner.py")

    def test_session_dead_retried(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """Session dead during execute triggers retry (creates new session)."""
        import json

        payload = json.dumps({"status": "ok", "value": "recovered"})
        mock_session.execute.side_effect = [
            SessionDeadError("session is dead"),
            [f"__LAZY_RESULT__:{payload}"],
        ]

        result = engine._execute_with_retry("s", MagicMock(hash="h"))
        assert result == "recovered"
        mock_session.start.assert_called_once_with("s")


class TestExecuteWithRetry:
    """Session-dead retry logic."""

    def test_first_attempt_succeeds(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """If the first execute attempt succeeds, no retry."""
        import json

        payload = json.dumps({"status": "ok", "value": "success"})
        mock_session.execute.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]

        result = engine._execute_with_retry("s", MagicMock(hash="h"))
        assert result == "success"

    def test_retries_on_session_dead(
        self,
        engine: ExecutionEngine,
        mock_session: MagicMock,
    ) -> None:
        """On ``SessionDeadError``, engine restarts session and retries."""
        import json

        payload = json.dumps({"status": "ok", "value": "recovered"})

        # First call raises SessionDeadError, second succeeds
        mock_session.execute.side_effect = [
            SessionDeadError("session gone"),
            [f"__LAZY_RESULT__:{payload}"],
        ]

        result = engine._execute_with_retry("s", MagicMock(hash="h"))
        assert result == "recovered"
        mock_session.start.assert_called_once_with("s")


class TestExecute:
    """The full ``execute()`` pipeline."""

    def test_full_success(
        self,
        engine: ExecutionEngine,
        mock_analyzer: MagicMock,
        mock_packager: MagicMock,
        mock_session: MagicMock,
    ) -> None:
        """Full pipeline succeeds with valid inputs."""
        import json

        payload = json.dumps({"status": "ok", "value": "done"})
        mock_session.execute.return_value = [
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
        mock_packager.build.assert_called_once()
        mock_session.ensure_session.assert_called_once_with("my-session", "T4")
        mock_session.execute.assert_called_once()

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
        mock_session.execute.return_value = [
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
        mock_session.execute.return_value = [
            f"__LAZY_RESULT__:{payload}",
        ]
        mock_session.ensure_session.side_effect = AuthError("authentication failed")

        with pytest.raises(AuthError, match="authentication"):
            engine.execute(
                function_name="train",
                source_file=Path("app.py"),
                gpu="T4",
            )
