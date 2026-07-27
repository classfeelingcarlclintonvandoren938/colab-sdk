"""Stdout protocol parser for Colab Client.

Parses ``__LAZY_*``-prefixed lines produced by ``runner.py`` on the Colab
VM and returns structured message objects.

Usage::

    msg = parse_line("__LAZY_RESULT__:{\\"status\\": \\"ok\\", \\"value\\": 42}")
    if isinstance(msg, ResultMessage):
        print(msg.value)  # 42
"""

from __future__ import annotations

import json
import sys
from collections.abc import Generator, Iterable
from dataclasses import dataclass
from typing import Any

from colab._exceptions import ProtocolError, RemoteExecutionError

__all__ = [
    "LogMessage",
    "ProgressMessage",
    "ResultMessage",
    "ErrorMessage",
    "parse_line",
    "classify",
]

# ---------------------------------------------------------------------------
# Message types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LogMessage:
    """A generic log line from the remote function.

    Attributes:
        text: The log message content.
    """

    text: str


@dataclass(frozen=True)
class ProgressMessage:
    """A progress indicator (0-100).

    Attributes:
        value: Numeric progress value, clamped to 0-100.
    """

    value: float


@dataclass(frozen=True)
class ResultMessage:
    """A successful execution result.

    Attributes:
        value: The deserialised return value of the remote function.
    """

    value: Any


@dataclass(frozen=True)
class ErrorMessage:
    """An error raised on the Colab VM.

    Attributes:
        type: The original exception type name (e.g. ``\"ValueError\"``).
        message: The original exception message.
        traceback: List of traceback lines from the VM.
    """

    type: str
    message: str
    traceback: list[str]


# ---------------------------------------------------------------------------
# Marker constants
# ---------------------------------------------------------------------------

_PREFIX_LOG = "__LAZY_LOG__:"
_PREFIX_PROGRESS = "__LAZY_PROGRESS__:"
_PREFIX_RESULT = "__LAZY_RESULT__:"
_PREFIX_ERROR = "__LAZY_ERROR__:"

# ---------------------------------------------------------------------------
# Single-line parser
# ---------------------------------------------------------------------------


def parse_line(line: str) -> LogMessage | ProgressMessage | ResultMessage | ErrorMessage | None:
    """Parse a single stdout line and return a structured message.

    Args:
        line: A line of stdout from the Colab VM.

    Returns:
        A ``LogMessage``, ``ProgressMessage``, ``ResultMessage``, or
        ``ErrorMessage``, or ``None`` if the line is a pass-through
        (non-prefixed) line.

    Raises:
        ProtocolError: If a ``__LAZY_*`` marker is recognised but its
            payload is malformed (invalid JSON, wrong structure, etc.).
    """
    # Fast reject — most lines are non-prefixed
    if not line.startswith("__LAZY_"):
        return None

    if line.startswith(_PREFIX_LOG):
        return LogMessage(text=line[len(_PREFIX_LOG):])

    if line.startswith(_PREFIX_PROGRESS):
        raw = line[len(_PREFIX_PROGRESS):]
        try:
            value = float(raw)
        except ValueError:
            raise ProtocolError(f"Invalid progress value: {raw!r}") from None
        return ProgressMessage(value=max(0.0, min(100.0, value)))

    if line.startswith(_PREFIX_RESULT):
        raw = line[len(_PREFIX_RESULT):]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON in result payload: {e}") from None
        if not isinstance(payload, dict):
            raise ProtocolError(f"Result payload is not a JSON object: {payload!r}")
        if payload.get("status") != "ok":
            raise ProtocolError(
                f"Result payload has unexpected status: {payload.get('status')!r}"
            )
        return ResultMessage(value=payload.get("value"))

    if line.startswith(_PREFIX_ERROR):
        raw = line[len(_PREFIX_ERROR):]
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as e:
            raise ProtocolError(f"Invalid JSON in error payload: {e}") from None
        if not isinstance(payload, dict):
            raise ProtocolError(f"Error payload is not a JSON object: {payload!r}")
        if payload.get("status") != "error":
            raise ProtocolError(
                f"Error payload has unexpected status: {payload.get('status')!r}"
            )
        return ErrorMessage(
            type=str(payload.get("type", "Exception")),
            message=str(payload.get("message", "")),
            traceback=list(payload.get("traceback", [])),
        )

    # Recognised prefix but unknown marker type
    marker_end = line.find(":")
    if marker_end != -1:
        marker = line[: marker_end + 1]
    else:
        marker = line
    # Only warn if it starts with __LAZY_ but isn't one of ours
    print(
        f"[colab-client] Warning: unrecognised protocol marker: {marker}",
        file=sys.stderr,
    )
    return None


# ---------------------------------------------------------------------------
# High-level streaming parser
# ---------------------------------------------------------------------------


def classify(
    lines: Iterable[str],
) -> Generator[
    LogMessage | ProgressMessage,
    None,
    ResultMessage | ErrorMessage,
]:
    """Iterate over an output stream, yielding log/progress messages,
    and return the final result or error.

    This is the primary entry point for the ``ExecutionEngine``.  It wraps
    the generator returned by ``ColabSession.execute()`` and:

    * Yields ``LogMessage`` objects for log lines and pass-through output.
    * Yields ``ProgressMessage`` objects for progress indicators.
    * Returns a ``ResultMessage`` or raises ``RemoteExecutionError`` when
      the terminal marker (``__LAZY_RESULT__`` / ``__LAZY_ERROR__``) is
      encountered.

    Usage::

        stream = session.execute("my-session", "runner.py")
        try:
            for msg in classify(stream):
                if isinstance(msg, LogMessage):
                    print(f"[LOG] {msg.text}")
                elif isinstance(msg, ProgressMessage):
                    print(f"[PROGRESS] {msg.value}%")
            # classify() returned normally → result
            print(f"Result: {result.value}")
        except RemoteExecutionError as e:
            print(f"Remote failed: {e}")

    Yields:
        ``LogMessage`` and ``ProgressMessage`` objects in real-time as
        lines arrive from the VM.

    Returns:
        The ``ResultMessage`` when ``__LAZY_RESULT__`` is received.

    Raises:
        RemoteExecutionError: When ``__LAZY_ERROR__`` is received.
        ProtocolError: If the stream ends without a RESULT or ERROR marker,
            or if markers are malformed.
    """
    terminal_received: LogMessage | ProgressMessage | ResultMessage | ErrorMessage | None = None

    for line in lines:
        msg = parse_line(line)

        if msg is None:
            # Pass-through line → treat as log
            yield LogMessage(text=line)
            continue

        if isinstance(msg, LogMessage) or isinstance(msg, ProgressMessage):
            yield msg
            continue

        # Terminal message: RESULT or ERROR
        if terminal_received is not None:
            # Protocol rule 1: first terminal marker wins
            print(
                f"[colab-client] Warning: duplicate terminal marker ignored: {line}",
                file=sys.stderr,
            )
            continue

        terminal_received = msg

        if isinstance(msg, ResultMessage):
            return msg

        if isinstance(msg, ErrorMessage):
            raise RemoteExecutionError(
                f"{msg.type}: {msg.message}\n"
                + "".join(msg.traceback)
            )

        continue

    raise ProtocolError(
        "Execution stream ended without __LAZY_RESULT__ or "
        "__LAZY_ERROR__ marker"
    )
