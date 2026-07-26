"""Colab session management via ``google-colab-cli``.

Thin wrapper around the official Google Colab CLI. This is the **only**
component that communicates with Google.
"""

import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Generator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

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
        """Verify that ``google-colab-cli`` is installed (fail-fast)."""
        if shutil.which("colab") is None:
            raise SessionError(
                "google-colab-cli is not installed. "
                "Run: pip install google-colab-cli"
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
            ["colab", "status", "-s", name, "--json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode != 0:
            # Session is dead or doesn't exist
            return SessionStatus(alive=False, name=name, gpu="")

        # Try to parse JSON output for metadata
        try:
            data = json.loads(result.stdout)
            created: datetime | None = None
            if "created_at" in data and data["created_at"]:
                try:
                    created = datetime.fromisoformat(data["created_at"])
                except (ValueError, TypeError):
                    pass
            return SessionStatus(
                alive=True,
                name=name,
                gpu=data.get("gpu", ""),
                created_at=created,
            )
        except (json.JSONDecodeError, KeyError):
            # Fall back to basic alive status
            return SessionStatus(alive=True, name=name, gpu="")

    # ------------------------------------------------------------------
    # Composite operations (used by Engine)
    # ------------------------------------------------------------------

    def ensure_session(self, name: str, gpu: str | None = None) -> None:
        """Create a session if one does not exist or is dead.

        Args:
            name: Session name.
            gpu: GPU type for a new session.

        Raises:
            SessionError: If session creation fails.
            SessionDeadError: If the existing session has a different GPU type.
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

        # Probe whether the marker file already exists on the VM
        probe_script = (
            f"import os; "
            f"exit(0) if os.path.exists('{marker_path}') else exit(1)"
        )
        probe_cmd = [
            "colab", "exec", "-s", name,
            "-c", probe_script,
        ]
        probe_result = subprocess.run(
            probe_cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if probe_result.returncode == 0:
            # Hash is already cached — skip installation
            return

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

        try:
            with subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            ) as proc:
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

    @staticmethod
    def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
        """Run a CLI command and raise on failure."""
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300,
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
