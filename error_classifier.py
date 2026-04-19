"""
error_classifier.py
--------------------
Classifies libclang diagnostic messages into one of three UI badge categories:
  - "Token Error"      -> unexpected/invalid token, stray char, bad syntax
  - "Missing Symbol"   -> undeclared identifier, missing header, expected semicolon/brace
  - "Misplaced Token"  -> redeclaration, extraneous input, wrong position

Also exposes UNSAFE_HEADER_MAP for compiler_engine's header-awareness layer,
and classify_severity() for High / Medium / Low tagging in the Diagnostics tab.
"""

import re


# ---------------------------------------------------------------------------
# Unsafe-function -> required header mapping
# ---------------------------------------------------------------------------

UNSAFE_HEADER_MAP: dict = {
    # <stdio.h>
    "printf":   "<stdio.h>",
    "fprintf":  "<stdio.h>",
    "sprintf":  "<stdio.h>",
    "snprintf": "<stdio.h>",
    "scanf":    "<stdio.h>",
    "fscanf":   "<stdio.h>",
    "gets":     "<stdio.h>",
    "fgets":    "<stdio.h>",
    "puts":     "<stdio.h>",
    "fopen":    "<stdio.h>",
    "fclose":   "<stdio.h>",
    "fread":    "<stdio.h>",
    "fwrite":   "<stdio.h>",
    "feof":     "<stdio.h>",
    "perror":   "<stdio.h>",
    # <string.h>
    "strcpy":   "<string.h>",
    "strncpy":  "<string.h>",
    "strcat":   "<string.h>",
    "strncat":  "<string.h>",
    "strcmp":   "<string.h>",
    "strncmp":  "<string.h>",
    "strlen":   "<string.h>",
    "strstr":   "<string.h>",
    "strchr":   "<string.h>",
    "memcpy":   "<string.h>",
    "memset":   "<string.h>",
    "memmove":  "<string.h>",
    # <stdlib.h>
    "malloc":   "<stdlib.h>",
    "calloc":   "<stdlib.h>",
    "realloc":  "<stdlib.h>",
    "free":     "<stdlib.h>",
    "exit":     "<stdlib.h>",
    "atoi":     "<stdlib.h>",
    "atof":     "<stdlib.h>",
    "atol":     "<stdlib.h>",
    "system":   "<stdlib.h>",
    "rand":     "<stdlib.h>",
    "srand":    "<stdlib.h>",
    "abs":      "<stdlib.h>",
    # <math.h>
    "sqrt":     "<math.h>",
    "pow":      "<math.h>",
    "fabs":     "<math.h>",
    "ceil":     "<math.h>",
    "floor":    "<math.h>",
    "log":      "<math.h>",
    "log10":    "<math.h>",
    "sin":      "<math.h>",
    "cos":      "<math.h>",
    "tan":      "<math.h>",
    # <ctype.h>
    "isalpha":  "<ctype.h>",
    "isdigit":  "<ctype.h>",
    "isspace":  "<ctype.h>",
    "toupper":  "<ctype.h>",
    "tolower":  "<ctype.h>",
    # <time.h>
    "time":     "<time.h>",
    "clock":    "<time.h>",
    "difftime": "<time.h>",
}

# Functions dangerous regardless of header
UNSAFE_FUNCTIONS: set = {
    "gets", "strcpy", "strcat", "sprintf", "scanf",
    "system", "strlen",
}


def classify_error(message: str) -> str:
    """
    Classify a raw clang diagnostic message into one of three UI badge types.
    Returns: "Token Error" | "Missing Symbol" | "Misplaced Token"
    """
    msg = message.lower()

    if any(kw in msg for kw in (
        "extraneous", "redeclaration", "redefinition",
        "cannot be redeclared", "already defined", "previous declaration",
    )):
        return "Misplaced Token"

    if any(kw in msg for kw in (
        "missing", "expected", "undeclared", "implicit declaration",
        "use of undeclared", "unknown type", "not declared",
        "no member named", "no such file", "file not found",
        "header", "undefined reference",
    )):
        return "Missing Symbol"

    if any(kw in msg for kw in (
        "invalid", "token", "stray", "unexpected",
        "illegal", "cannot", "incompatible", "does not name",
        "format string", "buffer", "overflow", "unsafe",
    )):
        return "Token Error"

    return "Misplaced Token"


def classify_severity(message: str, raw_message: str = "") -> str:
    """Returns 'High' | 'Medium' | 'Low' for a diagnostic message."""
    combined = (message + " " + raw_message).lower()

    high_patterns = [
        r"\bgets\b", r"\bstrcpy\b", r"\bsprintf\b",
        r"\bsystem\s*\(", r"buffer overflow", r"use.after.free",
        r"format.string", r"implicit declaration",
        r"undeclared identifier", r"undefined reference",
        r"missing.*header", r"no such file",
    ]
    medium_patterns = [
        r"expected\s*[';']", r"expected.*expression",
        r"redeclaration", r"redefinition",
        r"non-void.*return", r"control reaches end",
        r"integer overflow", r"narrowing conversion",
    ]

    for p in high_patterns:
        if re.search(p, combined, re.IGNORECASE):
            return "High"
    for p in medium_patterns:
        if re.search(p, combined, re.IGNORECASE):
            return "Medium"
    return "Low"