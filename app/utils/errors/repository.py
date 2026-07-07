class UserCreateError(Exception):
    """Failed to create user."""


class DuplicateEmailError(UserCreateError):
    """Email already exists in the database."""
