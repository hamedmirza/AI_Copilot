class AICopilotError(Exception):
    """Base application error."""


class ConfigurationError(AICopilotError):
    pass


class ProviderError(AICopilotError):
    pass


class NotFoundError(AICopilotError):
    pass


class ValidationError(AICopilotError):
    pass


class PathTraversalError(AICopilotError):
    pass


class PatchGuardError(AICopilotError):
    def __init__(self, filename: str, reason: str) -> None:
        self.filename = filename
        self.reason = reason
        super().__init__(f"Patch blocked for {filename}: {reason}")


class CommandRejectedError(AICopilotError):
    pass
