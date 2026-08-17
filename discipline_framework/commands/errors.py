class CommandError(Exception):
    """Raised by a command handler for invalid input. The message is sent
    back to the user as-is, so keep it short and actionable (include the
    expected usage)."""
