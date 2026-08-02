class NotificationNotFoundError(Exception):
    """One or more notifications were not found for the user."""

    def __init__(
        self,
        notification_ids: str | list[str] | None = None,
    ):
        if isinstance(notification_ids, str):
            ids = [notification_ids]
        elif notification_ids:
            ids = list(notification_ids)
        else:
            ids = []

        self.notification_ids = ids
        if len(ids) == 1:
            message = f"Notification not found: {ids[0]}"
        elif ids:
            message = f"Notifications not found: {', '.join(ids)}"
        else:
            message = "Notification not found"
        super().__init__(message)
