"""Exception types for the resumable transfer library."""


class TransferError(Exception):
    """Base class for all transfer errors."""


class TaskNotFoundError(TransferError):
    """Raised when a task id is unknown to the store."""


class ManifestMismatchError(TransferError):
    """Raised when a supplied manifest does not match the registered one."""


class SourceUnavailableError(TransferError):
    """Raised when the source file is missing or unreadable."""


class SourceChangedError(TransferError):
    """Raised when the source content does not match the registered manifest."""
