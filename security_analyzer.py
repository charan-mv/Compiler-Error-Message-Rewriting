"""
security_analyzer.py
--------------------
Week 10 – Security Scoring & Static Analysis

Implements static analysis rules to evaluate the security of C++ source
code and produces a ranked scoring report (SafeScore™).

Two-layer analysis
------------------
1. Pattern scanner  – regex checks for known unsafe patterns
   (buffer overflows, format-string bugs, use-after-free, etc.).
2. Scoring engine   – aggregates findings into a 0-100 SafeScore and
   a letter grade (A–F).

Public API
----------
    from security_analyzer import analyze_security, SecurityReport

    report = analyze_security(source_code, errors=[])
    print(report.score, report.grade)
    for f in report.findings:
        print(f.rule_id, f.severity, f.description)

No existing module is modified.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Severity constants
# ---------------------------------------------------------------------------

CRITICAL = "Critical"
HIGH     = "High"
MEDIUM   = "Medium"
LOW      = "Low"
INFO     = "Info"

_SEVERITY_PENALTY: dict[str, int] = {
    CRITICAL: 30,
    HIGH:     18,
    MEDIUM:    9,
    LOW:       3,
    INFO:      0,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SecurityFinding:
    """A single static-analysis finding."""

    rule_id:        str
    """Short identifier, e.g. 'SEC001'."""

    severity:       str
    """CRITICAL / HIGH / MEDIUM / LOW / INFO."""

    line:           int
    """Source line number (0 if not determinable)."""

    description:    str
    """Human-readable risk explanation."""

    recommendation: str
    """Suggested safe alternative."""

    cwe:            str = ""
    """MITRE CWE reference, e.g. 'CWE-120'."""


@dataclass
class SecurityReport:
    """Aggregated security analysis result."""

    score:       int
    """0–100 SafeScore: 100 = perfectly safe."""

    grade:       str
    """A (90–100) · B (75–89) · C (60–74) · D (45–59) · F (< 45)."""

    findings:    list[SecurityFinding] = field(default_factory=list)

    summary:     str = ""
    """Short human-readable overall assessment."""

    penalized_by: int = 0
    """Total penalty deducted from 100."""


# ---------------------------------------------------------------------------
# Static-analysis rules
# (rule_id, severity, pattern, description, recommendation, cwe)
# ---------------------------------------------------------------------------

_RULES: list[tuple[str, str, re.Pattern, str, str, str]] = [

    (
        "SEC001", CRITICAL,
        re.compile(r"\bstrcpy\s*\(", re.MULTILINE),
        "'strcpy' copies without checking the destination buffer size, "
        "making buffer overflows trivial to trigger.",
        "Use 'strncpy(dst, src, sizeof(dst)-1)' and null-terminate, "
        "or use std::string for automatic memory management.",
        "CWE-120",
    ),
    (
        "SEC002", CRITICAL,
        re.compile(r"\bgets\s*\(", re.MULTILINE),
        "'gets' reads unlimited input and will always overflow the "
        "buffer if the input is longer than the buffer. It was "
        "removed from C11 and C++14.",
        "Replace with 'fgets(buf, sizeof(buf), stdin)'.",
        "CWE-242",
    ),
    (
        "SEC003", HIGH,
        re.compile(
            r"\b(printf|fprintf|sprintf|snprintf)\s*\(\s*[^\")\n]+\s*[,)]",
            re.MULTILINE,
        ),
        "A format-string function is called with a variable as the "
        "first argument. Attackers can use this to read from or write "
        "to arbitrary memory.",
        "Always pass a string literal as the format argument: "
        "'printf(\"%s\", var)' not 'printf(var)'.",
        "CWE-134",
    ),
    (
        "SEC004", HIGH,
        re.compile(
            r"\b(int|unsigned|short)\s+\w+\s*=\s*\w+\s*[\+\*]\s*\w+",
            re.MULTILINE,
        ),
        "An integer arithmetic operation stores the result in a "
        "fixed-width type that may silently wrap on overflow.",
        "Use 'long long' or 'uint64_t', or check bounds before the "
        "operation with std::numeric_limits<T>::max().",
        "CWE-190",
    ),
    (
        "SEC005", CRITICAL,
        re.compile(
            r"free\s*\(\s*(\w+)\s*\).*\1",
            re.MULTILINE | re.DOTALL,
        ),
        "A pointer is used after 'free()' has been called on it. "
        "Use-after-free is undefined behaviour and a common "
        "memory-corruption vector.",
        "Set the pointer to NULL immediately after freeing: "
        "'free(ptr); ptr = NULL;'. Prefer std::unique_ptr in C++.",
        "CWE-416",
    ),
    (
        "SEC006", MEDIUM,
        re.compile(r"\bnew\b(?!.*\bdelete\b)", re.MULTILINE | re.DOTALL),
        "'new' allocates heap memory that may never be released with "
        "'delete', causing a memory leak over time.",
        "Use smart pointers (std::unique_ptr, std::shared_ptr) to "
        "manage heap objects automatically.",
        "CWE-401",
    ),
    (
        "SEC007", HIGH,
        re.compile(r"\bsystem\s*\(", re.MULTILINE),
        "'system()' invokes a shell and is vulnerable to injection "
        "if any part of the command is user-controlled.",
        "Use 'execv()' / 'CreateProcess()' with explicit argument "
        "arrays to avoid shell interpretation.",
        "CWE-676",
    ),
    (
        "SEC008", CRITICAL,
        re.compile(
            r"\bsystem\s*\(.*\b(argv|cin|getenv|fgets|scanf)\b",
            re.MULTILINE,
        ),
        "User-controlled data is passed directly to 'system()', "
        "creating an OS command-injection vulnerability.",
        "Never pass user input to 'system()'. Validate all input "
        "and prefer exec* family functions with explicit arg arrays.",
        "CWE-78",
    ),
    (
        "SEC009", CRITICAL,
        re.compile(
            r"free\s*\(\s*(\w+)\s*\)[^;]*;\s*[^;]*free\s*\(\s*\1\s*\)",
            re.MULTILINE,
        ),
        "The same pointer is freed twice. Double-free corrupts the "
        "heap allocator and can lead to arbitrary-code execution.",
        "Set the pointer to NULL after the first free. "
        "'free(NULL)' is a safe no-op.",
        "CWE-415",
    ),
    (
        "SEC010", MEDIUM,
        re.compile(
            r"\(char\)\s*\w+|\(short\)\s*\w+|\(int\)\s*\w+long\b",
            re.MULTILINE,
        ),
        "A larger numeric type is cast to a smaller one, silently "
        "discarding the high bits and potentially producing wrong values.",
        "Verify the value fits in the target type before narrowing. "
        "Use std::numeric_limits<T>::max() for bounds checking.",
        "CWE-197",
    ),
    (
        "SEC011", MEDIUM,
        re.compile(r"\bstrlen\s*\(\s*(?!\")", re.MULTILINE),
        "Calling 'strlen' on a buffer that may not be null-terminated "
        "causes an over-read, potentially leaking memory contents.",
        "Ensure all buffers passed to 'strlen' are always "
        "null-terminated. Use 'strnlen(s, max_len)' defensively.",
        "CWE-126",
    ),
    (
        "SEC012", HIGH,
        re.compile(r"\w+\s*\[\s*-\s*\d+\s*\]", re.MULTILINE),
        "A negative array index writes or reads behind the start "
        "of the buffer (buffer underwrite).",
        "Validate all indices are non-negative and within bounds "
        "before use.",
        "CWE-124",
    ),
    (
        "SEC013", LOW,
        re.compile(
            r"\breturn\b.*\n\s*(?![\}\#])(?!\s*//)[^\n;{}]+;",
            re.MULTILINE,
        ),
        "Code appears after a 'return' statement and will never "
        "be executed. Dead code can hide logic errors.",
        "Remove the unreachable statements or restructure the "
        "control flow so they execute before the return.",
        "CWE-561",
    ),
    (
        "SEC014", MEDIUM,
        re.compile(r"\bINT_MAX\b|\bINT_MIN\b", re.MULTILINE),
        "Direct use of INT_MAX/INT_MIN in arithmetic may indicate "
        "signed-integer overflow, which is undefined behaviour in C++.",
        "Use std::numeric_limits<int>::max() and guard arithmetic "
        "with overflow checks before performing the operation.",
        "CWE-758",
    ),
    (
        "SEC015", MEDIUM,
        re.compile(
            r"\b(int|char|float|double|long|short)\s+(\w+)\s*;",
            re.MULTILINE,
        ),
        "A variable is declared without an initializer. Reading it "
        "before assignment produces undefined behaviour.",
        "Always initialize at declaration: 'int x = 0;' not 'int x;'.",
        "CWE-457",
    ),
]


# ---------------------------------------------------------------------------
# Scan engine
# ---------------------------------------------------------------------------

def _scan_source(source: str) -> list[SecurityFinding]:
    findings: list[SecurityFinding] = []
    for rule_id, severity, pattern, description, recommendation, cwe in _RULES:
        for m in pattern.finditer(source):
            line_no = source[: m.start()].count("\n") + 1
            findings.append(
                SecurityFinding(
                    rule_id=rule_id,
                    severity=severity,
                    line=line_no,
                    description=description,
                    recommendation=recommendation,
                    cwe=cwe,
                )
            )
            break   # one occurrence per rule to avoid noise
    return findings


# ---------------------------------------------------------------------------
# Scoring engine
# ---------------------------------------------------------------------------

def _compute_score(findings: list[SecurityFinding]) -> tuple[int, int]:
    penalty = sum(_SEVERITY_PENALTY.get(f.severity, 0) for f in findings)
    return max(0, 100 - penalty), penalty


def _grade(score: int) -> str:
    if score >= 90: return "A"
    if score >= 75: return "B"
    if score >= 60: return "C"
    if score >= 45: return "D"
    return "F"


def _build_summary(score: int, grade: str, findings: list[SecurityFinding]) -> str:
    if not findings:
        return (
            f"SafeScore: {score}/100 (Grade {grade}). "
            "No security issues detected — all static-analysis checks passed."
        )
    counts: dict[str, int] = {}
    for f in findings:
        counts[f.severity] = counts.get(f.severity, 0) + 1
    issues = ", ".join(f"{v} {k}" for k, v in counts.items())
    posture = {
        "A": "excellent", "B": "good", "C": "fair", "D": "poor", "F": "critical",
    }.get(grade, "unknown")
    return (
        f"SafeScore: {score}/100 (Grade {grade}) — {posture} security posture. "
        f"Found {len(findings)} issue(s): {issues}. "
        "Review findings below and apply the recommended fixes."
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def analyze_security(
    source: str,
    errors: list[dict[str, Any]] | None = None,
) -> SecurityReport:
    """
    Run static-analysis security checks on C++ source code.

    Parameters
    ----------
    source : str
        Raw C++ source code.
    errors : list[dict], optional
        Compiler diagnostics from compiler_engine.analyze()["errors"].

    Returns
    -------
    SecurityReport
    """
    findings = _scan_source(source)

    # De-duplicate: one finding per rule_id, keep first occurrence
    seen: dict[str, SecurityFinding] = {}
    for f in findings:
        if f.rule_id not in seen:
            seen[f.rule_id] = f

    severity_order = list(_SEVERITY_PENALTY.keys())
    unique = sorted(
        seen.values(),
        key=lambda f: severity_order.index(f.severity),
    )

    score, penalty = _compute_score(unique)
    grade = _grade(score)

    return SecurityReport(
        score=score,
        grade=grade,
        findings=unique,
        summary=_build_summary(score, grade, unique),
        penalized_by=penalty,
    )