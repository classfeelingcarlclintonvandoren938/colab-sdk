"""Custom exception hierarchy for Colab Client.

All SDK-specific exceptions inherit from ``ColabClientError`` so callers
can catch a single base type when needed.
"""


class ColabClientError(Exception):
    """Base exception for all Colab Client errors."""


class AnalysisError(ColabClientError):
    """Raised when static dependency analysis fails.

    Examples: circular imports, unresolvable local modules, malformed AST.
    """


class AuthError(ColabClientError):
    """Raised when Google Colab authentication fails or is missing."""


class PackagingError(ColabClientError):
    """Raised when artifact packaging fails.

    Examples: missing source files, compression failure.
    """


class ProtocolError(ColabClientError):
    """Raised when stdout protocol parsing fails.

    Examples: malformed ``__LAZY_*`` markers, missing required fields.
    """


class RemoteExecutionError(ColabClientError):
    """Raised when the remote function raises an exception on the Colab VM.

    Carries the original exception type, message, and traceback from the VM.
    """


class SessionError(ColabClientError):
    """Raised when a Colab session operation fails.

    Examples: session creation failure, CLI not found, unexpected errors.
    """


class SessionDeadError(SessionError):
    """Raised when the session is found to be dead or unreachable."""


class SessionGpuMismatchError(SessionError):
    """Raised when the requested GPU type differs from the active session.

    One session = one GPU type. The user must stop the current session
    and create a new one to change GPU types.
    """


class ValidationError(ColabClientError):
    """Raised when function metadata or configuration is invalid.

    Examples: invalid GPU type, missing function, bad timeout format.
    """
