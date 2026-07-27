"""Colab session management via ``google-colab-cli``.

Thin wrapper around the official Google Colab CLI. This is the **only**
component that communicates with Google.
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

    Usage::

        session = ColabSession()
        session.start("my-session", gpu="T4")
        for line in session.execute("my-session", "runner.py"):
            print(line)
        session.stop("my-session")
    """

    def __init__(self) -> None:
        """Verify that ``google-colab-cli`` is available (fail-fast).

        Loads ``.env`` from the current directory if present, so users
        can set ``COLAB_BIN_DIR`` for non-standard install locations
        (e.g. ``/home/user/.local/bin`` inside WSL).
        """
        if sys.platform == "win32":
            raise SessionError(
                "google-colab-cli does not run on native Windows. "
                "Use WSL2: https://learn.microsoft.com/en-us/windows/wsl/install"
            )

        load_dotenv()
        colab_bin_dir = os.environ.get("COLAB_BIN_DIR")

        # Build a subprocess environment with the extra PATH if configured
        self._env: dict[str, str] | None = None
        if colab_bin_dir:
            self._env = os.environ.copy()
            self._env["PATH"] = f"{colab_bin_dir}:{self._env['PATH']}"

        # Check CLI availability — use custom PATH if set
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
    # Session lifecycle
    # ------------------------------------------------------------------

    def start(self, name: str, gpu: str | None = None) -> None:
        """Create a new Colab VM session.

        Args:
            name: Session name (used in subsequent commands).
            gpu: GPU type (``\"T4\"``, ``\"L4\"``, ``\"A100\"``, ``\"H100"\"``,
                or ``None`` for CPU).

        Raises:
            SessionError: If the CLI command fails.
        """
        cmd = ["colab", "new", "-s", name]
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
        self._run(["colab", "stop", "-s", name])

    def status(self, name: str) -> SessionStatus:
        """Check if a session is alive and return its metadata.

        Args:
            name: Session name.

        Returns:
            A ``SessionStatus`` with the current session state.
        """
        result = subprocess.run(
            ["colab", "status", "-s", name],
            capture_output=True,
            text=True,
            timeout=30,
            env=self._env,
        )

        if result.returncode != 0:
            # Session is dead or doesn't exist
            return SessionStatus(alive=False, name=name, gpu="")

        # Exit code 0, but check the output text for dead-session indicators.
        # The CLI may cache stale state locally and report exit 0 even when
        # the backend session was stopped or never created.
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
        alive by calling ``status()`` again. This catches cases where
        ``colab new`` exits 0 but the session is not fully initialised
        or a stale name conflicts with previous state.

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
            return  # Session is alive and GPU matches — no-op

        self.start(name, gpu)

        # Verify the session is actually alive after creation
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

        Checks for a marker file at ``~/.colab-client/hashes/<hash>`` on the
        VM. If absent, runs ``colab install`` and writes the marker.

        Args:
            name: Session name.
            requirements_hash: SHA256 hex digest of the sorted requirements.
            packages: Package names to install (e.g. ``[\"torch\", \"numpy\"]``).

        Raises:
            SessionError: If the probe or install command fails.
        """
        if not packages:
            return

        marker_path = f"/content/.colab-client/hashes/{requirements_hash}"

        # Probe whether the marker file already exists on the VM.
        # colab exec only supports -f (file), so write the probe to a
        # temporary local file first.
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

            probe_result = subprocess.run(
                ["colab", "exec", "-s", name, "-f", tmp_probe.name],
                capture_output=True,
                text=True,
                timeout=60,
                env=self._env,
            )

            if probe_result.returncode == 0:
                # Hash is already cached — skip installation
                return
        finally:
            os.unlink(tmp_probe.name)

        # Install packages
        self.install(name, *packages)

        # Persist the hash marker
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
            remote_path: Destination on the VM. Defaults to
                ``/content/<filename>``.

        Raises:
            SessionError: If the upload fails.
        """
        cmd = ["colab", "upload", "-s", name, str(local_path)]
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
            local_path: Destination path locally. Defaults to
                ``./<filename>``.

        Returns:
            The local path the file was downloaded to.

        Raises:
            SessionError: If the download fails.
        """
        dest = Path(local_path or Path(remote_path).name)
        cmd = ["colab", "download", "-s", name, remote_path, str(dest)]
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
        cmd = ["colab", "install", "-s", name, *packages]
        self._run(cmd)

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def execute(self, name: str, local_file: str | Path) -> Generator[str, None, None]:
        """Execute a local Python file on the Colab VM.

        Yields stdout lines **in real-time** as they arrive from the VM.
        Stderr is forwarded separately.

        Args:
            name: Session name.
            local_file: Path to a local ``.py`` file to execute remotely.

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: If execution fails or the session is dead.
        """
        cmd = ["colab", "exec", "-s", name, "-f", str(local_file)]
        yield from self._exec(cmd)

    def run_code(self, name: str, code: str) -> Generator[str, None, None]:
        """Execute Python *code* directly on the Colab VM via stdin.

        Unlike ``execute()`` (which reads a local file via ``-f``),
        this method pipes *code* through stdin to ``colab exec``.
        Useful for setup steps (e.g. extracting archives) or for
        wrapping the target function call.

        Args:
            name: Session name.
            code: Python source code to execute.

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: If execution fails or the session is dead.
        """
        cmd = ["colab", "exec", "-s", name]
        yield from self._exec(cmd, stdin_data=code)

    def _exec(
        self,
        cmd: list[str],
        stdin_data: str | None = None,
    ) -> Generator[str, None, None]:
        """Shared subprocess helper for remote execution.

        Args:
            cmd: The ``colab exec`` command list.
            stdin_data: Optional code to send via stdin.

        Yields:
            Lines of stdout from the remote execution.

        Raises:
            SessionError: On failure or missing CLI.
        """
        try:
            with subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE if stdin_data is not None else None,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                env=self._env,
            ) as proc:
                # Send stdin data if provided
                if stdin_data is not None and proc.stdin:
                    proc.stdin.write(stdin_data)
                    proc.stdin.close()

                # Yield stdout lines in real-time
                if proc.stdout:
                    for line in proc.stdout:
                        yield line.rstrip("\n")

                # Wait for process to finish
                returncode = proc.wait()

                # Collect stderr (may contain __LAZY_ERROR__)
                stderr_output = ""
                if proc.stderr:
                    stderr_output = proc.stderr.read()

                if returncode != 0:
                    raise SessionError(
                        f"Execution failed (exit code {returncode}):\n{stderr_output}"
                    )
        except FileNotFoundError:
            raise SessionError(
                "google-colab-cli is not installed. "
                "Run: pip install google-colab-cli"
            ) from None

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
        """Run a CLI command and raise on failure."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
                env=self._env,
            )
        except FileNotFoundError:
            raise SessionError(
                "google-colab-cli is not installed. "
                "Run: pip install google-colab-cli"
            ) from None
        except subprocess.TimeoutExpired:
            raise SessionError(f"Command timed out: {' '.join(cmd)}") from None

        if result.returncode != 0:
            error_msg = result.stderr.strip() or f"exit code {result.returncode}"
            raise SessionError(
                f"Command failed: {' '.join(cmd)}\n{error_msg}"
            )

        return result
