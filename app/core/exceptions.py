class DomainError(Exception):
    """Base class for expected, user-facing errors."""

    status_code = 400

    def __init__(self, message: str, errors: list[dict] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors


class NotFoundError(DomainError):
    status_code = 404


class ConflictError(DomainError):
    status_code = 409


class PayloadTooLargeError(DomainError):
    status_code = 413


class FileValidationError(DomainError):
    status_code = 422