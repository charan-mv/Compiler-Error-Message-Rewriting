"""
explanation_engine.py
---------------------
Week 9 – Explanation Engine Integration

Transforms raw libclang diagnostic messages into clear, student-friendly
natural-language explanations. Acts as the communication layer between
the C++ compiler frontend (compiler_engine.py) and the explanation backend.

Two backends
------------
1. Rule-based  – always available, zero dependencies, zero latency.
2. Llama 3     – calls a local Ollama server (http://localhost:11434).
                 Falls back to rule-based silently if Ollama is not running.

Public API
----------
    from explanation_engine import explain_errors, ExplainedError

    result    = analyze(source_code)          # from compiler_engine
    explained = explain_errors(
        errors  = result["errors"],
        source  = source_code,
        use_llm = True,                       # attempt Llama 3 via Ollama
    )
    for e in explained:
        print(e.natural_language)
        print(e.suggestion)
        print(e.difficulty)
        print(e.explanation_source)           # "rule-based" | "llama3"

No existing module is modified.
"""

from __future__ import annotations

import re
import json
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Any


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class ExplainedError:
    """One fully-explained compiler diagnostic."""

    # ── pass-through from compiler_engine ──────────────────────────────────
    raw_message:    str
    line:           int
    column:         int
    error_line:     str
    context_before: list
    context_after:  list
    ast_node:       str
    category:       str           # from error_classifier

    # ── Week 9 additions ───────────────────────────────────────────────────
    natural_language:   str = ""
    """Plain-English explanation of what went wrong."""

    suggestion:         str = ""
    """Concrete fix guidance for a student."""

    difficulty:         str = "Beginner"
    """Beginner / Intermediate / Advanced."""

    explanation_source: str = "rule-based"
    """'rule-based'  or  'llama3'."""


# ---------------------------------------------------------------------------
# Rule-based backend  (15 patterns, always available)
# ---------------------------------------------------------------------------

# (compiled_pattern, natural_language_template, suggestion_template, difficulty)
# {token} is replaced with the named capture group when present.
_RULES: list[tuple] = [
    (
        re.compile(r"expected\s*[';']", re.IGNORECASE),
        "A semicolon is missing at the end of a statement. "
        "Every C++ statement must be terminated with ';'.",
        "Add ';' at the end of the statement on the indicated line.",
        "Beginner",
    ),
    (
        re.compile(r"expected\s+(?:an?\s+)?expression", re.IGNORECASE),
        "The compiler expected a value or expression here but found "
        "something it could not parse. This often happens after an "
        "operator or opening parenthesis that is missing its value.",
        "Check that every operator has both operands and every '(' "
        "has a matching ')'.",
        "Beginner",
    ),
    (
        re.compile(
            r"use of undeclared identifier\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        "The name '{token}' is used but has never been declared in "
        "this scope. C++ requires variables and functions to be "
        "declared before use.",
        "Declare '{token}' before first use. Check for typos — "
        "identifiers are case-sensitive.",
        "Beginner",
    ),
    (
        re.compile(
            r"undefined reference to\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        "The linker cannot find an implementation for '{token}'. "
        "The declaration exists but the definition (body) is "
        "missing or not linked in.",
        "Make sure '{token}' is defined — not just declared — and "
        "that all required source files are compiled and linked.",
        "Intermediate",
    ),
    (
        re.compile(
            r"(cannot convert|incompatible type|no viable conversion|"
            r"invalid conversion|type mismatch)",
            re.IGNORECASE,
        ),
        "There is a type mismatch: a value whose type does not "
        "match what is expected is being assigned or passed here.",
        "Check the types on both sides of the assignment or call. "
        "Use 'static_cast<TargetType>(value)' for intentional casts.",
        "Intermediate",
    ),
    (
        re.compile(
            r"(redeclaration|redefinition)\s+of\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        "'{token}' has been declared or defined more than once in "
        "the same scope. Each name must be unique within a scope.",
        "Remove the duplicate declaration of '{token}', or rename one.",
        "Beginner",
    ),
    (
        re.compile(
            r"(non-void function|control reaches end of non-void)",
            re.IGNORECASE,
        ),
        "A non-void function ends without a 'return' statement. "
        "All code paths through a non-void function must return a value.",
        "Add 'return <value>;' at the end, or ensure every branch "
        "returns an appropriate value.",
        "Beginner",
    ),
    (
        re.compile(
            r"(stray|unexpected token|extraneous input)",
            re.IGNORECASE,
        ),
        "An unexpected character or token appeared where the "
        "compiler did not expect one — often a stray punctuation mark.",
        "Check the flagged line for extra characters like '@' or "
        "duplicate operators and remove them.",
        "Beginner",
    ),
    (
        re.compile(r"expected\s+'?['})]'?", re.IGNORECASE),
        "A closing brace '}' or parenthesis ')' is missing. "
        "Every opening delimiter must have a matching closing one.",
        "Count your opening and closing braces. Consistent "
        "indentation makes mismatches much easier to spot.",
        "Beginner",
    ),
    (
        re.compile(r"\b(gets|strcpy|sprintf)\s*\(", re.IGNORECASE),
        "An unsafe function that does not check buffer size was "
        "detected. This is a common source of security vulnerabilities.",
        "Replace 'gets' with 'fgets', 'strcpy' with 'strncpy', "
        "and 'sprintf' with 'snprintf'. Prefer std::string.",
        "Advanced",
    ),
    (
        re.compile(
            r"no matching function for call to\s+'?(?P<token>[^'(\s]+)",
            re.IGNORECASE,
        ),
        "No overload of '{token}' accepts the argument types supplied.",
        "Check the signature of '{token}': verify argument count "
        "and types match the declaration.",
        "Intermediate",
    ),
    (
        re.compile(
            r"(printf|fprintf|sprintf|snprintf)\s*\(\s*[^\")\n]+\s*[,)]",
            re.MULTILINE,
        ),
        "A format-string function was called with a variable as "
        "the first argument instead of a string literal. This can "
        "allow reading or writing arbitrary memory.",
        "Always use a literal format: 'printf(\"%s\", var)' — "
        "never 'printf(var)'.",
        "Advanced",
    ),
    (
        re.compile(r"division by zero", re.IGNORECASE),
        "A compile-time division by zero was detected. Dividing "
        "by zero is undefined behaviour and will crash at runtime.",
        "Guard the division: 'if (divisor != 0) { ... }'.",
        "Beginner",
    ),
    (
        re.compile(r"(overflow|INT_MAX|INT_MIN)", re.IGNORECASE),
        "An integer arithmetic expression may overflow the "
        "fixed-width type, silently wrapping to an incorrect value.",
        "Use 'long long', or check bounds with "
        "std::numeric_limits<T>::max() before the operation.",
        "Intermediate",
    ),
    (
        re.compile(
            r"(array index|out.of.bound|index .* is past)",
            re.IGNORECASE,
        ),
        "An array is being accessed with an index outside its "
        "valid range. C++ arrays are zero-indexed; the last valid "
        "index is size - 1.",
        "Keep indices within [0, size-1]. Use '.at()' on "
        "std::vector for automatic bounds-checking.",
        "Intermediate",
    ),
]

_DEFAULT = (
    "The compiler reported an error at this location. Review the "
    "flagged line for incorrect syntax, missing punctuation, or "
    "a misspelled identifier.",
    "Read the raw message above and compare it with the code on "
    "the indicated line. Look for missing semicolons, mismatched "
    "brackets, or undeclared names.",
    "Beginner",
)


def _rule_based_explain(message: str) -> tuple[str, str, str]:
    """Return (natural_language, suggestion, difficulty) via regex matching."""
    for pattern, nl_tpl, sug_tpl, difficulty in _RULES:
        m = pattern.search(message)
        if m:
            token = m.groupdict().get("token", "")
            return (
                nl_tpl.replace("{token}", token),
                sug_tpl.replace("{token}", token),
                difficulty,
            )
    return _DEFAULT


# ---------------------------------------------------------------------------
# Llama 3 backend  (Ollama — http://localhost:11434)
# ---------------------------------------------------------------------------

_OLLAMA_URL   = "http://localhost:11434/api/generate"
_LLAMA3_MODEL = "llama3"

_PROMPT_TEMPLATE = """\
You are an expert C++ tutor helping a first-year student understand a compiler error.

Compiler error:
{message}

Code context:
{context}

Respond ONLY with a valid JSON object — absolutely no markdown fences, no extra text — with exactly these three keys:
  "natural_language": 2-3 plain-English sentences explaining what went wrong (no jargon).
  "suggestion": 1-2 sentences with a concrete fix the student can apply right now.
  "difficulty": exactly one of "Beginner", "Intermediate", or "Advanced".
"""


def _build_context(error_line: str, before: list, after: list) -> str:
    lines = []
    for ln, txt in (before or []):
        lines.append(f"  {ln:3d} | {txt}")
    if error_line:
        lines.append(f"  >>> {error_line}   ← ERROR HERE")
    for ln, txt in (after or []):
        lines.append(f"  {ln:3d} | {txt}")
    return "\n".join(lines) or "(no context available)"


def _llama3_explain(
    message: str,
    error_line: str,
    context_before: list,
    context_after: list,
) -> tuple[str, str, str] | None:
    """
    POST to Ollama's local /api/generate endpoint with the llama3 model.

    Returns (natural_language, suggestion, difficulty) on success, or None
    if Ollama is unreachable, times out, or returns unparseable output.
    """
    prompt = _PROMPT_TEMPLATE.format(
        message=message,
        context=_build_context(error_line, context_before, context_after),
    )

    payload = json.dumps({
        "model":  _LLAMA3_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.2,
            "num_predict": 400,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError):
        # Ollama not running — silent fallback to rule-based
        return None
    except Exception:
        return None

    raw = data.get("response", "").strip()
    if not raw:
        return None

    # Strip any accidental markdown fences the model may emit
    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()

    # Extract the first JSON object in the response
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if not m:
        return None

    try:
        parsed = json.loads(m.group())
    except json.JSONDecodeError:
        return None

    nl  = parsed.get("natural_language", "").strip()
    sug = parsed.get("suggestion", "").strip()
    dif = parsed.get("difficulty", "Beginner").strip()

    if dif not in ("Beginner", "Intermediate", "Advanced"):
        dif = "Beginner"

    return (nl, sug, dif) if nl else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_errors(
    errors: list[dict[str, Any]],
    source: str = "",
    use_llm: bool = False,
) -> list[ExplainedError]:
    """
    Transform a list of raw compiler diagnostics into ExplainedError objects.

    Parameters
    ----------
    errors : list[dict]
        From compiler_engine.analyze()["errors"].
        Each dict requires at least {"message", "line", "column"}.

    source : str
        Original C++ source string (reserved for future enrichment).

    use_llm : bool
        If True, attempt Llama 3 via Ollama (http://localhost:11434).
        Automatically falls back to rule-based if Ollama is unavailable.

    Returns
    -------
    list[ExplainedError]
    """
    from error_classifier import classify_error

    results: list[ExplainedError] = []

    for err in errors:
        msg        = err.get("message", "")
        line       = err.get("line", 0)
        col        = err.get("column", 0)
        error_line = err.get("error_line", "")
        ctx_before = err.get("context_before", [])
        ctx_after  = err.get("context_after", [])
        ast_node   = err.get("ast_node", "")
        category   = classify_error(msg)

        # Rule-based is always computed first (guaranteed fallback)
        nl, suggestion, difficulty = _rule_based_explain(msg)
        src = "rule-based"

        if use_llm:
            llm_result = _llama3_explain(msg, error_line, ctx_before, ctx_after)
            if llm_result:
                nl, suggestion, difficulty = llm_result
                src = "llama3"

        results.append(
            ExplainedError(
                raw_message=msg,
                line=line,
                column=col,
                error_line=error_line,
                context_before=ctx_before,
                context_after=ctx_after,
                ast_node=ast_node,
                category=category,
                natural_language=nl,
                suggestion=suggestion,
                difficulty=difficulty,
                explanation_source=src,
            )
        )

    return results