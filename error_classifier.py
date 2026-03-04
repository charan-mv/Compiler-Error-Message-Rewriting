"""Error classification: Token Error, Missing Symbol, Misplaced Token."""


def classify_error(message: str) -> str:
    """Classify error message into Token Error, Missing Symbol, or Misplaced Token."""
    msg_lower =message.lower()
    if "extraneous" in msg_lower or "redeclaration" in msg_lower or "redefinition" in msg_lower:
        return "Misplaced Token"
    if "missing" in msg_lower or "expected" in msg_lower:
        return "Missing Symbol"
    if "invalid" in msg_lower or "token" in msg_lower or "stray" in msg_lower or "unexpected" in msg_lower:
        return "Token Error"
    return "Misplaced Token"
