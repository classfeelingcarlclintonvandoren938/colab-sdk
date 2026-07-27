"""Tests for ``_session.py`` — ``ColabSession`` CLI wrapper.

All subprocess calls are mocked to avoid requiring the actual
``google-colab-cli`` tool.
"""

from collections.abc import Generator
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from colab._exceptions import SessionDeadError, SessionError
from colab._session import ColabSession, SessionStatus


@pytest.fixture(autouse=True)
def _mock_dotenv() -> Generator[None, None, None]:
    """Ensure dotenv.load_dotenv is a no-op in tests."""
    with patch("colab._session.load_dotenv"):
        yield


@pytest.fixture
def mock_cli() -> Generator[MagicMock, None, None]:
    """Mock ``shutil.which`` to pretend ``colab`` is on PATH."""
    with patch("colab._session.shutil.which", return_value="/usr/bin/colab") as m:
        yield m


@pytest.fixture
def session(mock_cli: MagicMock) -> ColabSession:
    """Create a fresh ColabSession with mocked CLI availability."""
    return ColabSession()


class TestColabSessionInit:
    """Session creation and CLI availability check."""

    def test_cli_found(self) -> None:
        """Session is created successfully when colab is on PATH."""
        with patch("colab._session.shutil.which", return_value="/usr/bin/colab"):
            s = ColabSession()
            assert s._env is None  # No custom PATH set

    def test_cli_not_found(self) -> None:
        """Session creation raises if colab is not installed."""
        with patch("colab._session.shutil.which", return_value=None):
            with pytest.raises(SessionError, match="not installed"):
                ColabSession()

    def test_custom_path_from_env(self) -> None:
        """``COLAB_BIN_DIR`` extends PATH for the subprocess env."""
        with patch("colab._session.shutil.which", return_value="/custom/colab"):
            with patch.dict(os.environ, {"COLAB_BIN_DIR": "/custom"}):
                s = ColabSession()
                assert s._env is not None
                assert "/custom" in s._env["PATH"]


class TestWSLInit:
    """WSL detection and initialization (Windows-only code paths)."""

    def test_wsl_found(self) -> None:
        """On Windows, session sets ``_use_wsl = True`` if WSL has colab."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                with patch(
                    "colab._session.subprocess.run",
                    return_value=MagicMock(returncode=0),
                ):
                    s = ColabSession()
                    assert s._use_wsl is True

    def test_wsl_not_installed(self) -> None:
        """On Windows without WSL, session creation raises."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value=None):
                with pytest.raises(SessionError, match="WSL"):
                    ColabSession()

    def test_wsl_no_colab_cli(self) -> None:
        """On Windows with WSL but no colab CLI inside it, session creation raises."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                with patch(
                    "colab._session.subprocess.run",
                    return_value=MagicMock(returncode=1),
                ):
                    with pytest.raises(SessionError, match="google-colab-cli"):
                        ColabSession()


class TestWSLBuildCmd:
    """``_build_cmd()`` prepends ``wsl`` on Windows."""

    def test_linux_no_prefix(self, session: ColabSession) -> None:
        """On Linux, commands are returned as-is."""
        assert session._build_cmd(["colab", "status", "-s", "s"]) == [
            "colab", "status", "-s", "s"
        ]

    def test_windows_prepends_wsl(self) -> None:
        """On Windows, ``wsl`` is prepended to the command."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                with patch(
                    "colab._session.subprocess.run",
                    return_value=MagicMock(returncode=0),
                ):
                    s = ColabSession()
                    cmd = s._build_cmd(["colab", "status", "-s", "s"])
                    assert cmd == ["wsl", "colab", "status", "-s", "s"]

    def test_wsl_caches_probe_result(self) -> None:
        """On Windows, WSL detection only runs once."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                with patch(
                    "colab._session.subprocess.run",
                    return_value=MagicMock(returncode=0),
                ) as mock_run:
                    s1 = ColabSession()
                    s2 = ColabSession()
                    # Subsequent sessions should also work
                    assert s1._use_wsl is True
                    assert s2._use_wsl is True


class TestWSLToWSLPath:
    """``_to_wsl_path()`` translates Windows paths to WSL paths."""

    def test_linux_returns_original(self, session: ColabSession) -> None:
        """On Linux, path is returned unchanged."""
        assert session._to_wsl_path("/home/user/file.py") == "/home/user/file.py"

    def test_windows_uses_wslpath(self) -> None:
        """On Windows, path is translated via ``wsl wslpath -u``."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                wsl_result = MagicMock()
                wsl_result.stdout = "/mnt/d/path/file.py"
                wsl_result.returncode = 0
                with patch(
                    "colab._session.subprocess.run",
                    side_effect=[
                        MagicMock(returncode=0),  # WSL colab which
                        wsl_result,  # wslpath result
                    ],
                ):
                    s = ColabSession()
                    result = s._to_wsl_path("D:\\path\\file.py")
                    assert result == "/mnt/d/path/file.py"

    def test_wslpath_fallback_manual(self) -> None:
        """On Windows, if ``wslpath`` fails, falls back to manual conversion."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                with patch(
                    "colab._session.subprocess.run",
                    side_effect=[
                        MagicMock(returncode=0),  # WSL colab which
                        FileNotFoundError,  # wslpath not found
                    ],
                ):
                    s = ColabSession()
                    result = s._to_wsl_path("D:\\path\\file.py")
                    assert result == "/mnt/d/path/file.py"

    def test_wslpath_cache(self) -> None:
        """On Windows, path translations are cached."""
        with patch("colab._session.sys.platform", "win32"):
            with patch("colab._session.shutil.which", return_value="/usr/bin/wsl.exe"):
                wsl_result = MagicMock()
                wsl_result.stdout = "/mnt/d/path/file.py"
                wsl_result.returncode = 0
                with patch(
                    "colab._session.subprocess.run",
                    side_effect=[
                        MagicMock(returncode=0),  # WSL colab which (init)
                        wsl_result,  # First wslpath call
                    ],
                ):
                    s = ColabSession()
                    result1 = s._to_wsl_path("D:\\path\\file.py")
                    result2 = s._to_wsl_path("D:\\path\\file.py")
                    assert result1 == result2
                    assert result1 == "/mnt/d/path/file.py"


class TestSessionLifecycle:
    """Session start, stop, status."""

    def test_start(self, session: ColabSession) -> None:
        """``start()`` calls ``colab new -s <name>``."""
        with patch.object(session, "_run") as mock_run:
            session.start("my-session", gpu="T4")
            mock_run.assert_called_once_with(
                ["colab", "new", "-s", "my-session", "--gpu", "T4"]
            )

    def test_start_no_gpu(self, session: ColabSession) -> None:
        """``start()`` without GPU omits the --gpu flag."""
        with patch.object(session, "_run") as mock_run:
            session.start("cpu-session")
            mock_run.assert_called_once_with(
                ["colab", "new", "-s", "cpu-session"]
            )

    def test_stop(self, session: ColabSession) -> None:
        """``stop()`` calls ``colab stop -s <name>``."""
        with patch.object(session, "_run") as mock_run:
            session.stop("my-session")
            mock_run.assert_called_once_with(
                ["colab", "stop", "-s", "my-session"]
            )

    def test_status_alive(self, session: ColabSession) -> None:
        """``status()`` returns ``SessionStatus(alive=True)`` on success."""
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("colab._session.subprocess.run", return_value=mock_result):
            status = session.status("my-session")
            assert status.alive is True
            assert status.name == "my-session"

    def test_status_dead(self, session: ColabSession) -> None:
        """``status()`` returns ``SessionStatus(alive=False)`` on failure."""
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("colab._session.subprocess.run", return_value=mock_result):
            status = session.status("dead-session")
            assert status.alive is False
            assert status.name == "dead-session"


class TestCompositeOperations:
    """ensure_session and ensure_requirements."""

    def test_ensure_session_alive(self, session: ColabSession) -> None:
        """If session is alive, ``ensure_session`` is a no-op."""
        with patch.object(session, "status") as mock_status:
            mock_status.return_value = SessionStatus(
                alive=True, name="s", gpu="T4"
            )
            with patch.object(session, "start") as mock_start:
                session.ensure_session("s", gpu="T4")
                mock_start.assert_not_called()

    def test_ensure_session_dead(self, session: ColabSession) -> None:
        """If session is dead, ``ensure_session`` calls ``start`` and then
        verifies the session is alive with a second status check."""
        with patch.object(session, "status") as mock_status:
            # First call (pre-start): dead
            # Second call (post-start): alive
            mock_status.side_effect = [
                SessionStatus(alive=False, name="s", gpu=""),
                SessionStatus(alive=True, name="s", gpu="T4"),
            ]
            with patch.object(session, "start") as mock_start:
                session.ensure_session("s", gpu="T4")
                mock_start.assert_called_once_with("s", "T4")

    def test_ensure_session_gpu_mismatch(self, session: ColabSession) -> None:
        """GPU mismatch raises ``SessionGpuMismatchError``."""
        with patch.object(session, "status") as mock_status:
            mock_status.return_value = SessionStatus(
                alive=True, name="s", gpu="T4"
            )
            with pytest.raises(SessionDeadError, match="GPU"):
                session.ensure_session("s", gpu="A100")

    def test_ensure_requirements_empty(self, session: ColabSession) -> None:
        """No requirements -> no-op."""
        with patch.object(session, "install") as mock_install:
            session.ensure_requirements("s", "hash123", [])
            mock_install.assert_not_called()


class TestFileOperations:
    """Upload, download, install, write_file."""

    def test_upload(self, session: ColabSession) -> None:
        """``upload()`` calls proper CLI command."""
        with patch.object(session, "_run") as mock_run:
            session.upload("s", "local.tar.gz", "/remote/path")
            mock_run.assert_called_once_with(
                ["colab", "upload", "-s", "s", "local.tar.gz", "/remote/path"]
            )

    def test_download(self, session: ColabSession) -> None:
        """``download()`` returns a Path."""
        with patch.object(session, "_run") as mock_run:
            result = session.download("s", "/remote/file.txt", "local.txt")
            assert isinstance(result, Path)

    def test_install(self, session: ColabSession) -> None:
        """``install()`` calls proper CLI command."""
        with patch.object(session, "_run") as mock_run:
            session.install("s", "torch", "numpy")
            mock_run.assert_called_once_with(
                ["colab", "install", "-s", "s", "torch", "numpy"]
            )

    def test_write_file(self, session: ColabSession) -> None:
        """``write_file()`` uploads a temp file then cleans it up."""
        with patch.object(session, "upload") as mock_upload:
            with patch("colab._session.tempfile.NamedTemporaryFile") as mock_tmp:
                mock_file = MagicMock()
                mock_file.name = "/tmp/test_content.tmp"
                mock_tmp.return_value.__enter__.return_value = mock_file

                with patch("colab._session.os.unlink") as mock_unlink:
                    session.write_file("s", "/remote/path", "hello world")
                    mock_upload.assert_called_once()
                    mock_unlink.assert_called_once_with("/tmp/test_content.tmp")


class TestExecute:
    """The streaming execute() generator."""

    def test_execute_yields_lines(self, session: ColabSession) -> None:
        """``execute()`` yields stdout lines from the subprocess."""
        mock_process = MagicMock()
        mock_process.stdout = ["line1\n", "line2\n", "line3\n"]
        mock_process.stderr = None
        mock_process.wait.return_value = 0

        with patch("colab._session.subprocess.Popen") as mock_popen:
            mock_popen.return_value.__enter__.return_value = mock_process

            lines = list(session.execute("s", "runner.py"))
            assert lines == ["line1", "line2", "line3"]

    def test_execute_non_zero_exit(self, session: ColabSession) -> None:
        """Non-zero exit code raises SessionError."""
        mock_process = MagicMock()
        mock_process.stdout = []
        mock_process.stderr = MagicMock()
        mock_process.stderr.read.return_value = "error details"
        mock_process.wait.return_value = 1

        with patch("colab._session.subprocess.Popen") as mock_popen:
            mock_popen.return_value.__enter__.return_value = mock_process

            with pytest.raises(SessionError, match="exit code 1"):
                list(session.execute("s", "runner.py"))

    def test_execute_file_not_found(self, session: ColabSession) -> None:
        """``FileNotFoundError`` is converted to a clear ``SessionError``."""
        with patch("colab._session.subprocess.Popen", side_effect=FileNotFoundError):
            with pytest.raises(SessionError, match="not installed"):
                list(session.execute("s", "runner.py"))


class TestRunInternal:
    """The internal ``_run()`` helper."""

    def test_run_success(self, session: ColabSession) -> None:
        """``_run()`` returns CompletedProcess on success."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 0
        mock_result.stdout = "ok"
        mock_result.stderr = ""

        with patch("colab._session.subprocess.run", return_value=mock_result):
            result = session._run(["colab", "status", "-s", "s"])
            assert result.stdout == "ok"

    def test_run_failure(self, session: ColabSession) -> None:
        """``_run()`` raises SessionError on non-zero exit."""
        mock_result = MagicMock(spec=subprocess.CompletedProcess)
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "error"

        with patch("colab._session.subprocess.run", return_value=mock_result):
            with pytest.raises(SessionError, match="error"):
                session._run(["colab", "fail"])
