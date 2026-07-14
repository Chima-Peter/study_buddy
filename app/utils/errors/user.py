class UserCreateError(Exception):
    """Failed to create user."""


class DuplicateEmailError(UserCreateError):
    """Email already exists in the database."""

    def __init__(self, email: str | None = None):
        self.email = email
        message = f"An account with email '{email}' already exists" if email else "Email already exists"
        super().__init__(message)
