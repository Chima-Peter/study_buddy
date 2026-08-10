class EmailAlreadyExistsError(Exception):
    """Email already registered."""


class UserNotFoundError(Exception):
    """User not found."""


class InvalidCredentialsError(Exception):
    """Invalid username or password."""


class InvalidResetCodeError(Exception):
    """Password reset code is invalid or expired."""
