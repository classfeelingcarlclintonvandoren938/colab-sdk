"""Tests for ``_exceptions.py`` — the custom exception hierarchy."""

from colab._exceptions import (
    AnalysisError,
    AuthError,
    ColabClientError,
    PackagingError,
    ProtocolError,
    RemoteExecutionError,
    SessionDeadError,
    SessionError,
    SessionGpuMismatchError,
    ValidationError,
)

_ALL_EXCEPTIONS = [
    AnalysisError,
    AuthError,
    ColabClientError,
    PackagingError,
    ProtocolError,
    RemoteExecutionError,
    SessionDeadError,
    SessionError,
    SessionGpuMismatchError,
    ValidationError,
]


class TestExceptionHierarchy:
    """Verify all exception types exist and inherit correctly."""

    def test_all_exceptions_are_exceptions(self) -> None:
        """Every custom exception inherits from Exception."""
        for exc_type in _ALL_EXCEPTIONS:
            assert issubclass(exc_type, Exception), f"{exc_type} is not an Exception"

    def test_all_inherit_base(self) -> None:
        """Every custom exception (except the base) inherits ColabClientError."""
        for exc_type in _ALL_EXCEPTIONS:
            if exc_type is ColabClientError:
                continue
            assert issubclass(exc_type, ColabClientError), (
                f"{exc_type} does not inherit ColabClientError"
            )

    def test_message_preserved(self) -> None:
        """The message passed to the constructor is stored in args[0]."""
        msg = "Something went wrong"
        for exc_type in _ALL_EXCEPTIONS:
            exc = exc_type(msg)
            assert str(exc) == msg, f"{exc_type} did not preserve message"

    def test_session_error_hierarchy(self) -> None:
        """SessionDeadError and SessionGpuMismatchError are SessionErrors."""
        assert issubclass(SessionDeadError, SessionError)
        assert issubclass(SessionGpuMismatchError, SessionError)

    def test_repr(self) -> None:
        """repr of exceptions includes the class name and message."""
        exc = ValidationError("invalid GPU")
        assert "ValidationError" in repr(exc)
        assert "invalid GPU" in repr(exc)
