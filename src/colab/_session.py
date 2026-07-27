"""Colab session management via ``google-colab-cli``.

Thin wrapper around the official Google Colab CLI. This is the **only**
component that communicates with Google.

On Windows, the SDK automatically routes ``colab`` commands through WSL
(Windows Subsystem for Linux) so users can run everything from native
Windows Python — no separate WSL terminal needed.
"""

import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import ClassVar

from dotenv import load_dotenv

from colab._exceptions import SessionDeadError, SessionError

__all__ = [
    "ColabSession",
    "SessionStatus",
]


@dataclass
class SessionStatus:
    """Describes the current state of a Colab VM session."""

    alive: bool
    """Whether the session exists and is healthy."""

    name: str
    """The session name."""

    gpu: str
    """GPU type (or empty string for CPU sessions)."""

    created_at: datetime | None = None
    """When the session was created, if known."""


class ColabSession:
    """Wrapper around ``google-colab-cli`` commands.

    Every method shells out to ``colab <command>`` via ``subprocess``.
    The ``execute()`` method streams stdout line-by-line via a generator.

    On Windows, ``colab`` commands are automatically routed through WSL
    (``wsl.exe colab ...``) — users run everything from native Python.

    Usage::

        session = ColabSession()
        session.start("my-session", gpu="T4")
        for line in session.execute("my-session", "runner.py"):
            print(line)
        session.stop("my-session")
    """

    # Cache for wslpath results (avoids repeated subprocess calls for the
    # same Windows path during a single session).
    _wsl_path_cache: ClassVar[dict[str, str]] = {}

    def __init__(self) -> None:
        """Verify that ``google-colab-cli`` is available (fail-fast).

        On Linux/macOS, checks that ``colab`` is on ``PATH``.
        On Windows, checks that ``wsl.exe`` is available and that
        ``google-colab-cli`` is installed inside WSL.

        Loads ``.env`` from the current directory if present, so users
        can set ``COLAB_BIN_DIR`` for non-standard install locations
        (e.g. ``/home/user/.local/bin`` inside WSL).
        """
        self._use_wsl = sys.platform == "win32"
        self._env: dict[str, str] | None = None

        if self._use_wsl:
            # Windows: verify WSL is installed
            if shutil.which("wsl") is None:
                raise SessionError(
                    "WSL (Windows Subsystem for Linux) is required to run "
                    "google-colab-cli commands on Windows. "
                    "Install: wsl --install -d Ubuntu"
                )
            # Verify colab CLI exists inside WSL
            try:
                result = subprocess.run(
                    ["wsl", "which", "colab"],
                    capture_output=True, text=True, timeout=30,
                )
                if result.returncode != 0:
                    raise SessionError(
                        "google-colab-cli is not installed inside WSL. "
                        "Run inside WSL: pip install google-colab-cli"
                    )
            except FileNotFoundError:
                raise SessionError(
                    "WSL is not available. "
                    "Install: wsl --install -d Ubuntu"
                ) from None
        else:
            # Linux / macOS: verify colab is on PATH
            load_dotenv()
            colab_bin_dir = os.environ.get("COLAB_BIN_DIR")

            if colab_bin_dir:
                self._env = os.environ.copy()
                self._env["PATH"] = f"{colab_bin_dir}:{self._env['PATH']}"

            colab_path = shutil.which(
                "colab",
                path=self._env.get("PATH") if self._env else None,
            )
            if colab_path is None:
                hint = (
                    f" Try setting COLAB_BIN_DIR={colab_bin_dir} in your .env file."
                    if colab_bin_dir
                    else ""
                )
                raise SessionError(
                    "google-colab-cli is not installed. "
                    "Run: pip install google-colab-cli"
                    f"{hint}"
                )

    # ------------------------------------------------------------------
    # WSL helpers
    # ------------------------------------------------------------------

    def _build_cmd(self, args: list[str]) -> list[str]:
        """Prepend ``wsl`` on Windows so the CLI runs inside WSL.

        On Linux/macOS the command is returned as-is.
        """
        if self._use_wsl:
            return ["wsl", *args]
        return args

    def _to_wsl_path(self, win_path: str) -> str:
        """Convert a Windows path to a WSL path using ``wsl wslpath -u``.

        ``D:\\path\\file.py`` → ``/mnt/d/path/file.py``

        Results are cached per path to avoid repeated subprocess calls.
        """
        if not self._use_wsl:
            return win_path

        cached = self._wsl_path_cache.get(win_path)
        if cached is not None:
            return cached

        try:
            result = subprocess.run(
                ["wsl", "wslpath", "-u", win_path],
                capture_output=True, text=True, timeout=15, check=True,
            )
            wsl_path = result.stdout.strip()
            self._wsl_path_cache[win_path] = wsl_path
            return wsl_path
        except (subprocess.CalledProcessError, FileNotFoundError):
            # Fallback: manual translation for common patterns
            if len(win_path) > 1 and win_path[1] == ":":
                drive = win_path[0].lower()
                rest = win_path[2:].replace("\\", "/")
                wsl_path = f"/mnt/{drive}{rest}"
                self._wsl_path_cache[win_path] = wsl_path
                return wsl_path
            return win_path

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def start(self, name: str, gpu: str | None = None) -> None:
        """Create a new Colab VM session.

        Args:
            name: Session name (used in subsequent commands).
            gpu: GPU type (``\"T4\"``, ``\"L4\"``, ``\"A100\"``, ``\"H100\"``,
                or ``None`` for CPU).

        Raises:
            SessionError: If the CLI command fails.
        """
        cmd = self._build_cmd(["colab", "new", "-s", name])
        if gpu:
            cmd.extend(["--gpu", gpu])
        self._run(cmd)

    def stop(self, name: str) -> None:
        """Terminate a Colab VM session.

        Idempotent — safe to call on non-existent or already-stopped sessions.

        Args:
            name: Session name.

        Raises:
            SessionError: If the CLI command fails unexpectedly.
        """
        self._run(self._build_cmd(["colab", "stop", "-s", name]))

    def status(self, name: str) -> SessionStatus:
        """Check if a session is alive and return its metadata.

        Args:
            name: Session name.

        Returns:
            A ``SessionStatus`` with the current session state.
        """
        cmd = self._build_cmd(["colab", "status", "-s", name])
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=30,
                env=getattr(self, "_env", None),
            )
        except FileNotFoundError:
            return SessionStatus(alive=False, name=name, gpu="")

        if result.returncode != 0:
            return SessionStatus(alive=False, name=name, gpu="")

        # Exit code 0, but check the output text for dead-session indicators.
        output = (result.stdout + result.stderr).lower()
        if "not found" in output or "no such session" in output:
            return SessionStatus(alive=False, name=name, gpu="")

        return SessionStatus(alive=True, name=name, gpu="")

    # ------------------------------------------------------------------
    # Composite operations (used by Engine)
    # ------------------------------------------------------------------

    def ensure_session(self, name: str, gpu: str | None = None) -> None:
        """Create a session if one does not exist or is dead.

        After calling ``start()``, verifies the session is actually
        alive by calling ``status()`` again.

        Args:
            name: Session name.
            gpu: GPU type for a new session.

        Raises:
            SessionError: If session creation fails or the session
                is not alive after creation.
            SessionDeadError: If the existing session has a different
                GPU type.
        """
        current = self.status(name)
        if current.alive:
            if gpu and current.gpu and current.gpu != gpu:
                raise SessionDeadError(
                    f"Session '{name}' exists with GPU '{current.gpu}', "
                    f"but GPU '{gpu}' was requested. "
                    f"Stop the session and create a new one to change GPU type."
                )
            return

        self.start(name, gpu)

        post = self.status(name)
        if not post.alive:
            raise SessionError(
                f"Session '{name}' was created but is not responding. "
                "Try a different session name or check your Colab quota."
            )

    def ensure_requirements(
        self,
        name: str,
        requirements_hash: str,
        packages: list[str],
    ) -> None:
        """Install packages only if the hash is not cached on the VM.

        Args:
            name: Session name.
            requirements_hash: SHA256 hex digest of the sorted requirements.
            packages: Package names to install.

        Raises:
            SessionError: If the probe or install command fails.
        """
        if not packages:
            return

        marker_path = f"/content/.colab-client/hashes/{requirements_hash}"

        probe_script = (
            f"import os\n"
            f"exit(0) if os.path.exists('{marker_path}') else exit(1)\n"
        )
        tmp_probe = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        )
        try:
            tmp_probe.write(probe_script)
            tmp_probe.close()

            # Translate temp file path when running through WSL
            probe_path = self._to_wsl_path(tmp_probe.name)
            cmd = self._build_cmd(
                ["colab", "exec", "-s", name, "-f", probe_path]
            )

            probe_result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                env=getattr(self, "_env", None),
            )

            if probe_result.returncode == 0:
                return
        finally:
            os.unlink(tmp_probe.name)

        self.install(name, *packages)
        self.write_file(name, marker_path, requirements_hash)

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def upload(
        self,
        name: str,
        local_path: str | Path,
        remote_path: str | None = None,
    ) -> None:
        """Upload a local file or directory to the Colab VM.

        Args:
            name: Session name.
            local_path: Path to the local file or directory.
            remote_path: Destination on the VM.

        Raises:
            SessionError: If the upload fails.
        """
        wsl_path = self._to_wsl_path(str(local_path))
        cmd = self._build_cmd(["colab", "upload", "-s", name, wsl_path])
        if remote_path:
            cmd.append(remote_path)
        self._run(cmd)

    def download(
        self,
        name: str,
        remote_path: str,
        local_path: str | Path | None = None,
    ) -> Path:
        """Download a file from the Colab VM to the local machine.

        Args:
            name: Session name.
            remote_path: Path to the file on the VM.
            local_path: Destination path locally.

        Returns:
            The local path the file was downloaded to.

        Raises:
            SessionError: If the download fails.
        """
        dest = Path(local_path or Path(remote_path).name)
        wsl_dest = self._to_wsl_path(str(dest))
        cmd = self._build_cmd(
            ["colab", "download", "-s", name, remote_path, wsl_dest]
        )
        self._run(cmd)
        return dest.resolve()

    def install(self, name: str, *packages: str) -> None:
        """Install Python packages on the Colab VM.

        Args:
            name: Session name.
            packages: One or more package names to install.

        Raises:
            SessionError: If installation fails.
        """
        if not packages:
            return
        cmd = self._build_cmd(["colab", "install", "-s", name, *packages])
        self._run(cmd)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, name: str, local_file: str | Path) -> Generator[str, None, None]:
        """Execute a local Python file on the Colab VM.

        Yields stdout lines **in real-time** as they arrive from the VM.

        Args:
            name: Session name.
            local_file: Path to a local ``.py`` file to execute remotely.

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: If execution fails or the session is dead.
        """
        wsl_path = self._to_wsl_path(str(local_file))
        cmd = self._build_cmd(
            ["colab", "exec", "-s", name, "-f", wsl_path]
        )
        yield from self._exec(cmd)

    def run_code(self, name: str, code: str, *, timeout: int | None = None) -> Generator[str, None, None]:
        """Execute Python *code* directly on the Colab VM via stdin.

        Unlike ``execute()`` (which reads a local file via ``-f``),
        this method pipes *code* through stdin to ``colab exec``.

        Args:
            name: Session name.
            code: Python source code to execute.
            timeout: Maximum seconds to wait for execution.  ``None``
                means no timeout (the process may hang indefinitely).

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: If execution fails, the session is dead, or
                the timeout expires.
        """
        cmd = self._build_cmd(["colab", "exec", "-s", name])
        yield from self._exec(cmd, stdin_data=code, timeout=timeout)

    def _exec(
        self,
        cmd: list[str],
        stdin_data: str | None = None,
        timeout: int | None = None,
    ) -> Generator[str, None, None]:
        """Shared subprocess helper for remote execution.

        Args:
            cmd: The ``colab exec`` command list (already processed by
                ``_build_cmd`` on Windows).
            stdin_data: Optional code to send via stdin.
            timeout: Maximum seconds to wait for the process.
                ``None`` means no timeout (process may hang indefinitely).

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: On failure, missing CLI, or timeout expiry.
        """
        try:
            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=getattr(self, "_env", None),
            ) as proc:
                if stdin_data is not None and proc.stdin:
                    proc.stdin.write(stdin_data)
                    proc.stdin.close()

                if proc.stdout:
                    for line in proc.stdout:
                        yield line.rstrip("\n")

                returncode = proc.wait(timeout=timeout)

                stderr_output = ""
                if proc.stderr:
                    stderr_output = proc.stderr.read()

                if returncode != 0:
                    raise SessionError(
                        f"Execution failed (exit code {returncode}):\n{stderr_output}"
                    )
        except subprocess.TimeoutExpired:
            raise SessionError(
                f"Execution timed out after {timeout} seconds."
            ) from None
        except FileNotFoundError:
            msg = (
                "WSL is not available."
                if self._use_wsl
                else "google-colab-cli is not installed. Run: pip install google-colab-cli"
            )
            raise SessionError(msg) from None

    # ------------------------------------------------------------------
    # Utility
    # ------------------------------------------------------------------

    def write_file(
        self,
        name: str,
        remote_path: str,
        content: str,
    ) -> None:
        """Write a string to a file on the Colab VM.

        Creates a temporary local file, uploads it, then removes the temp file.

        Args:
            name: Session name.
            remote_path: Destination path on the VM.
            content: String content to write.

        Raises:
            SessionError: If the write or upload fails.
        """
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".tmp",
            delete=False,
        ) as f:
            f.write(content)
            tmp_path = f.name

        try:
            self.upload(name, tmp_path, remote_path)
        finally:
            os.unlink(tmp_path)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _run(self, cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a CLI command and raise on failure.

        Args:
            cmd: Command list (already processed by ``_build_cmd`` on Windows).

        Returns:
            The completed process result.

        Raises:
            SessionError: If the command fails or times out.
        """
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                env=getattr(self, "_env", None),
            )
        except FileNotFoundError:
            msg = (
                "WSL is not available."
                if self._use_wsl
                else "google-colab-cli is not installed. Run: pip install google-colab-cli"
            )
            raise SessionError(msg) from None
        except subprocess.TimeoutExpired:
            raise SessionError(f"Command timed out: {' '.join(cmd)}") from None

        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"exit code {result.returncode}"
            raise SessionError(
                f"Command failed: {' '.join(cmd)}\n{error_msg}"
            )

        return result
