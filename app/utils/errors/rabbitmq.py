class NonRetryableIngestError(Exception):
    """Permanent failure; reject without requeue so the message goes to the DLQ immediately."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(f"{message}")
