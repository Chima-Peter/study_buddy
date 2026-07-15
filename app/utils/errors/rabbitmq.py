class NonRetryableIngestError(Exception):
    """Permanent failure; ack the message instead of requeueing."""

    def __init__(self, message: str):
        self.message = message
        super().__init__(f"{message}")
