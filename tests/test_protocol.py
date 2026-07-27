"""Tests for ``_protocol.py`` — stdout protocol parser."""

import json

import pytest

from colab._exceptions import ProtocolError, RemoteExecutionError
from colab._protocol import (
    ErrorMessage,
    LogMessage,
    ProgressMessage,
    ResultMessage,
    classify,
    parse_line,
)


class TestParseLine:
    """``parse_line()`` single-line parsing."""

    def test_non_prefixed_line_returns_none(self) -> None:
        """A plain line without a ``__LAZY_*`` prefix returns ``None``."""
        assert parse_line("regular output line") is None
        assert parse_line("") is None
        assert parse_line("  ") is None

    def test_log_message(self) -> None:
        """``__LAZY_LOG__:text`` → ``LogMessage(text=...)``."""
        msg = parse_line("__LAZY_LOG__:Hello world")
        assert isinstance(msg, LogMessage)
        assert msg.text == "Hello world"

    def test_log_message_empty(self) -> None:
        """``__LAZY_LOG__:`` with empty payload."""
        msg = parse_line("__LAZY_LOG__:")
        assert isinstance(msg, LogMessage)
        assert msg.text == ""

    def test_progress_message(self) -> None:
        """``__LAZY_PROGRESS__:50`` → ``ProgressMessage(value=50.0)``."""
        msg = parse_line("__LAZY_PROGRESS__:50")
        assert isinstance(msg, ProgressMessage)
        assert msg.value == 50.0

    def test_progress_message_clamps_above_100(self) -> None:
        """Values > 100 are clamped to 100."""
        msg = parse_line("__LAZY_PROGRESS__:150")
        assert isinstance(msg, ProgressMessage)
        assert msg.value == 100.0

    def test_progress_message_clamps_below_0(self) -> None:
        """Values < 0 are clamped to 0."""
        msg = parse_line("__LAZY_PROGRESS__:-10")
        assert isinstance(msg, ProgressMessage)
        assert msg.value == 0.0

    def test_progress_message_float(self) -> None:
        """Float progress values are accepted."""
        msg = parse_line("__LAZY_PROGRESS__:33.3")
        assert isinstance(msg, ProgressMessage)
        assert abs(msg.value - 33.3) < 0.01

    def test_progress_message_invalid_raises(self) -> None:
        """Non-numeric progress raises ``ProtocolError``."""
        with pytest.raises(ProtocolError, match="Invalid progress"):
            parse_line("__LAZY_PROGRESS__:abc")

    def test_result_message(self) -> None:
        """``__LAZY_RESULT__:{\"status\":\"ok\",\"value\":42}`` → ``ResultMessage(value=42)``."""
        payload = json.dumps({"status": "ok", "value": 42})
        msg = parse_line(f"__LAZY_RESULT__:{payload}")
        assert isinstance(msg, ResultMessage)
        assert msg.value == 42

    def test_result_message_none_value(self) -> None:
        """Result with ``null`` value."""
        payload = json.dumps({"status": "ok", "value": None})
        msg = parse_line(f"__LAZY_RESULT__:{payload}")
        assert isinstance(msg, ResultMessage)
        assert msg.value is None

    def test_result_message_dict_value(self) -> None:
        """Result with a dict value."""
        payload = json.dumps({"status": "ok", "value": {"accuracy": 0.95}})
        msg = parse_line(f"__LAZY_RESULT__:{payload}")
        assert isinstance(msg, ResultMessage)
        assert msg.value == {"accuracy": 0.95}

    def test_result_message_invalid_json_raises(self) -> None:
        """Malformed JSON in result raises ``ProtocolError``."""
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            parse_line("__LAZY_RESULT__:{bad json}")

    def test_result_message_wrong_status_raises(self) -> None:
        """Result with status != \"ok\" raises ``ProtocolError``."""
        payload = json.dumps({"status": "error"})
        with pytest.raises(ProtocolError, match="unexpected status"):
            parse_line(f"__LAZY_RESULT__:{payload}")

    def test_error_message(self) -> None:
        """``__LAZY_ERROR__:...`` → ``ErrorMessage``."""
        payload = json.dumps({
            "status": "error",
            "type": "ValueError",
            "message": "bad value",
            "traceback": ["line1\n", "line2\n"],
        })
        msg = parse_line(f"__LAZY_ERROR__:{payload}")
        assert isinstance(msg, ErrorMessage)
        assert msg.type == "ValueError"
        assert msg.message == "bad value"
        assert msg.traceback == ["line1\n", "line2\n"]

    def test_error_message_minimal(self) -> None:
        """Error with only required fields."""
        payload = json.dumps({"status": "error"})
        msg = parse_line(f"__LAZY_ERROR__:{payload}")
        assert isinstance(msg, ErrorMessage)
        assert msg.type == "Exception"  # default
        assert msg.message == ""

    def test_error_message_invalid_json_raises(self) -> None:
        """Malformed JSON in error raises ``ProtocolError``."""
        with pytest.raises(ProtocolError, match="Invalid JSON"):
            parse_line("__LAZY_ERROR__:{bad}")

    def test_error_message_wrong_status_raises(self) -> None:
        """Error with status != \"error\" raises ``ProtocolError``."""
        payload = json.dumps({"status": "ok"})
        with pytest.raises(ProtocolError, match="unexpected status"):
            parse_line(f"__LAZY_ERROR__:{payload}")

    def test_unrecognised_prefix(self) -> None:
        """Unrecognised ``__LAZY_*`` prefix logs a warning and returns None."""
        msg = parse_line("__LAZY_UNKNOWN__:foo")
        assert msg is None


class TestClassify:
    """``classify()`` streaming parser."""

    def test_single_result(self) -> None:
        """Stream with only a result returns ``ResultMessage``."""
        payload = json.dumps({"status": "ok", "value": 42})
        gen = classify([f"__LAZY_RESULT__:{payload}"])

        try:
            next(gen)
            assert False, "Expected StopIteration"
        except StopIteration as exc:
            result = exc.value
            assert isinstance(result, ResultMessage)
            assert result.value == 42

    def test_single_error_raises(self) -> None:
        """Stream with only an error raises ``RemoteExecutionError``."""
        payload = json.dumps({
            "status": "error",
            "type": "ValueError",
            "message": "bad",
            "traceback": [],
        })
        gen = classify([f"__LAZY_ERROR__:{payload}"])

        with pytest.raises(RemoteExecutionError, match="ValueError: bad"):
            next(gen)

    def test_logs_yielded_before_result(self) -> None:
        """Log lines are yielded before the terminal result."""
        payload = json.dumps({"status": "ok", "value": "done"})
        lines = [
            "__LAZY_LOG__:Starting",
            "pass-through line",
            "__LAZY_LOG__:Progressing",
            f"__LAZY_RESULT__:{payload}",
        ]
        gen = classify(lines)

        # Collect yielded messages
        yielded: list[LogMessage | ProgressMessage] = []
        try:
            while True:
                yielded.append(next(gen))
        except StopIteration as exc:
            result = exc.value

        assert len(yielded) == 3
        assert isinstance(yielded[0], LogMessage)
        assert yielded[0].text == "Starting"
        assert isinstance(yielded[1], LogMessage)
        assert yielded[1].text == "pass-through line"
        assert isinstance(yielded[2], LogMessage)
        assert yielded[2].text == "Progressing"
        assert isinstance(result, ResultMessage)
        assert result.value == "done"

    def test_progress_yielded(self) -> None:
        """Progress messages are yielded before the result."""
        payload = json.dumps({"status": "ok", "value": None})
        lines = [
            "__LAZY_PROGRESS__:25",
            "__LAZY_PROGRESS__:50",
            "__LAZY_PROGRESS__:100",
            f"__LAZY_RESULT__:{payload}",
        ]
        gen = classify(lines)

        yielded: list[LogMessage | ProgressMessage] = []
        try:
            while True:
                yielded.append(next(gen))
        except StopIteration as exc:
            result_msg = exc.value

        assert len(yielded) == 3
        for y in yielded:
            assert isinstance(y, ProgressMessage)
        assert isinstance(result_msg, ResultMessage)

    def test_empty_stream_raises(self) -> None:
        """An empty stream (no RESULT/ERROR) raises ``ProtocolError``."""
        gen = classify([])
        with pytest.raises(ProtocolError, match="without"):
            try:
                next(gen)
            except StopIteration:
                pass  # Empty generator without return → StopIteration with None value

    def test_stream_with_only_logs_raises(self) -> None:
        """A stream with only log lines (no RESULT/ERROR) raises ``ProtocolError``."""
        gen = classify(["__LAZY_LOG__:hello", "__LAZY_LOG__:world"])

        # Collect all yielded messages, then expect ProtocolError
        with pytest.raises(ProtocolError, match="without"):
            try:
                while True:
                    next(gen)
            except StopIteration:
                pass

    def test_generator_return_value_pattern(self) -> None:
        """Verifies the ``StopIteration.value`` pattern used by ``Engine._execute_and_parse``."""
        payload = json.dumps({"status": "ok", "value": {"epochs": 10}})
        gen = classify([f"__LAZY_RESULT__:{payload}"])

        try:
            while True:
                next(gen)
        except StopIteration as exc:
            result: ResultMessage = exc.value
            assert result.value == {"epochs": 10}
