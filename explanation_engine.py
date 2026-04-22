"""
explanation_engine.py
---------------------
Week 9 – Explanation Engine Integration (Enhanced)

Transforms raw libclang diagnostic messages into clear, student-friendly
natural-language explanations. Acts as the communication layer between
the C++ compiler frontend (compiler_engine.py) and the Streamlit UI.

Two backends
------------
1. Rule-based  – always available, zero dependencies, zero latency.
                 Enhanced with header-awareness and security context.
2. Llama 3     – calls a local Ollama server (http://localhost:11434).
                 Falls back to rule-based silently if Ollama is not running.

Key improvements over original
-------------------------------
- Header-aware rules: knows which header each stdlib function needs.
- Security-aware rules: gets/strcpy/printf(var) flagged with High severity
  and safe-alternative suggestions.
- Multi-line explanations: every rule has >= 2 substantive explanation lines.
- Missing semicolon: correctly detected even when clang says "expected ';'".
- Format-string injection rule: matches printf(var) pattern specifically.
- Severity tagging: each ExplainedError carries a severity field.
"""

from __future__ import annotations

import re
import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any


# ---------------------------------------------------------------------------
# Data structure
# ---------------------------------------------------------------------------

@dataclass
class ExplainedError:
    """One fully-explained compiler diagnostic."""

    raw_message:    str
    line:           int
    column:         int
    error_line:     str
    context_before: list
    context_after:  list
    ast_node:       str
    category:       str

    natural_language:   str = ""
    suggestion:         str = ""
    difficulty:         str = "Beginner"
    severity:           str = "Medium"
    explanation_source: str = "rule-based"


# ---------------------------------------------------------------------------
# Header map (mirrors error_classifier.UNSAFE_HEADER_MAP)
# ---------------------------------------------------------------------------

_HEADER_MAP: dict[str, str] = {
    "printf": "<stdio.h>", "fprintf": "<stdio.h>", "sprintf": "<stdio.h>",
    "snprintf": "<stdio.h>", "scanf": "<stdio.h>", "fscanf": "<stdio.h>",
    "gets": "<stdio.h>", "fgets": "<stdio.h>", "puts": "<stdio.h>",
    "fopen": "<stdio.h>", "fclose": "<stdio.h>", "perror": "<stdio.h>",
    "strcpy": "<string.h>", "strncpy": "<string.h>", "strcat": "<string.h>",
    "strncat": "<string.h>", "strcmp": "<string.h>", "strncmp": "<string.h>",
    "strlen": "<string.h>", "strstr": "<string.h>", "strchr": "<string.h>",
    "memcpy": "<string.h>", "memset": "<string.h>", "memmove": "<string.h>",
    "malloc": "<stdlib.h>", "calloc": "<stdlib.h>", "realloc": "<stdlib.h>",
    "free": "<stdlib.h>", "exit": "<stdlib.h>", "atoi": "<stdlib.h>",
    "atof": "<stdlib.h>", "system": "<stdlib.h>", "rand": "<stdlib.h>",
    "abs": "<stdlib.h>", "sqrt": "<math.h>", "pow": "<math.h>",
    "fabs": "<math.h>", "ceil": "<math.h>", "floor": "<math.h>",
    "sin": "<math.h>", "cos": "<math.h>", "tan": "<math.h>",
    "isalpha": "<ctype.h>", "isdigit": "<ctype.h>", "isspace": "<ctype.h>",
    "toupper": "<ctype.h>", "tolower": "<ctype.h>",
    "time": "<time.h>", "clock": "<time.h>",
}

# Unsafe functions with known safe replacements
_SAFE_ALTERNATIVES: dict[str, str] = {
    "gets":   "fgets(buf, sizeof(buf), stdin)",
    "strcpy": "strncpy(dst, src, sizeof(dst) - 1) then null-terminate",
    "strcat": "strncat(dst, src, sizeof(dst) - strlen(dst) - 1)",
    "sprintf": "snprintf(buf, sizeof(buf), fmt, ...)",
    "scanf":  "use fgets + sscanf, or limit input with scanf(\"%Ns\", buf)",
    "system": "execv() / CreateProcess() with explicit argument arrays",
    "strlen": "strnlen(s, max_len) when buffer may be unterminated",
}


# ---------------------------------------------------------------------------
# Rule-based backend
# Each rule: (pattern, natural_language, suggestion, difficulty, severity)
# ---------------------------------------------------------------------------

_RULES: list[tuple] = [

    # ── Missing semicolons ───────────────────────────────────────────────
    (
        re.compile(r"expected\s*[';']", re.IGNORECASE),
        (
            "A semicolon is missing at the end of a statement. "
            "In C and C++, every statement must be terminated with a semicolon (';') "
            "so the compiler knows where one instruction ends and the next begins. "
            "Without it, the compiler tries to merge two separate lines into one "
            "expression and fails to parse either correctly."
        ),
        (
            "Add ';' at the end of the highlighted statement. "
            "Example: change  'int x = 10'  to  'int x = 10;'."
        ),
        "Beginner", "Medium",
    ),

    # ── Expected expression ──────────────────────────────────────────────
    (
        re.compile(r"expected\s+(?:an?\s+)?expression", re.IGNORECASE),
        (
            "The compiler expected a value, variable, or expression at this point "
            "but encountered something it could not parse — often an operator "
            "missing one of its operands, or a statement that starts with a keyword "
            "where a value is required. "
            "This can also be caused by a missing semicolon on the previous line "
            "that makes the parser read two lines as one broken expression."
        ),
        (
            "Check that every operator (+, -, *, /, =) has both a left and right operand. "
            "Also verify that the previous line ends with a semicolon."
        ),
        "Beginner", "Medium",
    ),

    # ── gets() — missing header + unsafe ────────────────────────────────
    (
        re.compile(r"\bgets\s*\(", re.IGNORECASE),
        (
            "The function 'gets()' reads from stdin into a buffer with absolutely "
            "no bounds checking. If the user types more characters than the buffer "
            "can hold, gets() will overwrite memory beyond the array — a classic "
            "stack buffer overflow. This vulnerability is so dangerous that 'gets()' "
            "was removed from the C11 standard and C++14 entirely. "
            "Additionally, if <stdio.h> is not included, the compiler has no "
            "declaration for 'gets' and will raise an implicit-declaration error."
        ),
        (
            "Replace gets(buf) with fgets(buf, sizeof(buf), stdin). "
            "fgets() takes the buffer size as an argument and never writes past it. "
            "Also ensure '#include <stdio.h>' is at the top of your file."
        ),
        "Advanced", "High",
    ),

    # ── strcpy() — missing header + buffer overflow ──────────────────────
    (
        re.compile(r"\bstrcpy\s*\(", re.IGNORECASE),
        (
            "The function 'strcpy()' copies a source string into a destination buffer "
            "without checking whether the destination is large enough. "
            "If the source string is longer than the destination buffer, strcpy() "
            "overwrites memory past the end of the array — causing a buffer overflow "
            "that can crash the program or be exploited by an attacker. "
            "This is classified as CWE-120 (Buffer Copy Without Checking Size of Input). "
            "If <string.h> is missing, the compiler also has no declaration for strcpy."
        ),
        (
            "Replace strcpy(dst, src) with strncpy(dst, src, sizeof(dst) - 1), "
            "then manually null-terminate: dst[sizeof(dst) - 1] = '\\0'; "
            "Also add '#include <string.h>' if it is missing."
        ),
        "Advanced", "High",
    ),

    # ── printf(variable) — format-string injection ───────────────────────
    (
        re.compile(
            r"\b(printf|fprintf|sprintf|snprintf)\s*\(\s*(?!\")",
            re.IGNORECASE,
        ),
        (
            "A printf-family function is being called with a variable as the "
            "first (format) argument instead of a string literal. "
            "This is a format-string vulnerability (CWE-134): if the variable "
            "contains format specifiers like %s or %n, an attacker can read "
            "from or write to arbitrary memory addresses. "
            "For example, 'printf(buf)' is dangerous if 'buf' contains user input; "
            "use 'printf(\"%s\", buf)' instead so no format processing occurs on buf."
        ),
        (
            "Always pass a string literal as the format argument: "
            "printf(\"%s\", buf)  not  printf(buf). "
            "If <stdio.h> is missing, also add '#include <stdio.h>' at the top."
        ),
        "Advanced", "High",
    ),

    # ── Undeclared identifier ────────────────────────────────────────────
    (
        re.compile(
            r"use of undeclared identifier\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        (
            "The name '{token}' is used in the code but has never been declared "
            "in the current scope. C++ requires all variables, functions, and types "
            "to be declared before they are referenced. "
            "This is often caused by a typo in the name, forgetting to declare "
            "a variable, or missing the required '#include' header that provides "
            "the declaration for a standard library function."
        ),
        (
            "Declare '{token}' before its first use. "
            "If it is a standard library function, check the header table and add "
            "the correct #include. Verify spelling — identifiers are case-sensitive."
        ),
        "Beginner", "High",
    ),

    # ── Implicit declaration of function ────────────────────────────────
    (
        re.compile(
            r"implicit declaration of function\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        (
            "The function '{token}' is called without a prior declaration. "
            "In C, calling an undeclared function used to be a warning; in C99 and "
            "all C++ standards it is an error. The most common cause is a missing "
            "#include for the standard header that declares '{token}'. "
            "The compiler cannot verify argument types or return type without "
            "the declaration, which can lead to silent runtime errors."
        ),
        (
            "Add the correct #include at the top of your file. "
            "For example: gets/printf/scanf → #include <stdio.h>, "
            "strcpy/strlen → #include <string.h>, malloc/free → #include <stdlib.h>."
        ),
        "Beginner", "High",
    ),

    # ── Missing header (synthetic message from compiler_engine) ─────────
    (
        re.compile(
            r"missing required header\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        (
            "The function '{token}' is used but the header file that declares it "
            "has not been included. Without the #include directive, the compiler "
            "has no knowledge of '{token}': it does not know the function's "
            "parameter types, return type, or whether it exists at all. "
            "This causes an implicit-declaration error and can lead to incorrect "
            "code generation because the compiler must guess the calling convention."
        ),
        (
            "Add '#include {header}' at the very top of your source file, "
            "before any function definitions. "
            "Then recompile — the error should disappear."
        ),
        "Beginner", "High",
    ),

    # ── Undefined reference (linker) ────────────────────────────────────
    (
        re.compile(
            r"undefined reference to\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        (
            "The linker cannot find an implementation (definition) for '{token}'. "
            "A declaration tells the compiler a function exists; a definition "
            "provides the actual body with code. "
            "If a function is declared in a header but its source file is not "
            "compiled and linked, the linker raises this error. "
            "For math functions, you may also need to link with -lm."
        ),
        (
            "Make sure '{token}' is defined — not just declared — and that all "
            "source files containing definitions are included in the build. "
            "For math functions add '-lm' to your compiler command."
        ),
        "Intermediate", "High",
    ),

    # ── Type mismatch ────────────────────────────────────────────────────
    (
        re.compile(
            r"(cannot convert|incompatible type|no viable conversion|"
            r"invalid conversion|type mismatch|narrowing conversion)",
            re.IGNORECASE,
        ),
        (
            "There is a type mismatch: a value of one type is being assigned to, "
            "returned from, or passed into a context that expects a different type. "
            "C++ is strongly typed — you cannot silently convert, say, a pointer to "
            "an integer or a double to a char without an explicit cast. "
            "A narrowing conversion (e.g. double → int) silently truncates the value "
            "and is banned in brace-initialisation in C++11 and later."
        ),
        (
            "Check the declared type on both sides of the assignment or call. "
            "If the conversion is intentional, use 'static_cast<TargetType>(value)'. "
            "Avoid C-style casts like '(int)x' — they bypass type-safety checks."
        ),
        "Intermediate", "Medium",
    ),

    # ── Redeclaration / redefinition ────────────────────────────────────
    (
        re.compile(
            r"(redeclaration|redefinition)\s+of\s+'?(?P<token>[^';\s]+)'?",
            re.IGNORECASE,
        ),
        (
            "'{token}' has been declared or defined more than once in the same scope. "
            "Each name must be unique within a scope — duplicate declarations confuse "
            "the compiler about which version to use, and duplicate definitions "
            "violate the One Definition Rule (ODR) in C++. "
            "This often happens when a header is included multiple times without "
            "include guards, or when a variable is accidentally declared twice."
        ),
        (
            "Remove the duplicate declaration of '{token}'. "
            "If it appears in a header, protect the header with include guards: "
            "#ifndef MY_HEADER_H / #define MY_HEADER_H / ... / #endif."
        ),
        "Beginner", "Medium",
    ),

    # ── Non-void function missing return ─────────────────────────────────
    (
        re.compile(
            r"(non-void function|control reaches end of non-void)",
            re.IGNORECASE,
        ),
        (
            "A function declared to return a non-void type reaches the end of "
            "its body without executing a 'return' statement. "
            "In C++, reading the return value of such a function is undefined "
            "behaviour — the compiler may generate garbage values or the program "
            "may crash unpredictably. "
            "Every code path through a non-void function must end with a return."
        ),
        (
            "Add 'return <value>;' at the end of the function, ensuring the "
            "returned value matches the declared return type. "
            "Also check all branches (if/else, switch) — each branch that can "
            "reach the end of the function needs a return statement."
        ),
        "Beginner", "Medium",
    ),

    # ── Stray / unexpected token ─────────────────────────────────────────
    (
        re.compile(
            r"(stray|unexpected token|extraneous input)",
            re.IGNORECASE,
        ),
        (
            "An unexpected or illegal character appeared in the source code at a "
            "position where the compiler's parser did not expect it. "
            "Common causes include a stray '@', '#' outside a directive, a "
            "duplicate operator like '===' (not valid in C++), or a character "
            "that is not part of the C++ character set (e.g. a Unicode dash "
            "copied from a web page instead of a hyphen-minus)."
        ),
        (
            "Examine the flagged line for any character that should not be there. "
            "Make sure you are using plain ASCII for operators and punctuation — "
            "Unicode lookalikes (em-dash, curly quotes) are not valid C++ tokens."
        ),
        "Beginner", "Low",
    ),

    # ── Missing closing brace / paren ────────────────────────────────────
    (
        re.compile(r"expected\s+'?['})]'?", re.IGNORECASE),
        (
            "A closing delimiter — '}', ')', or ']' — is missing. "
            "In C++, every opening '{' must have a matching '}', every '(' a ')', "
            "and every '[' a ']'. When one is absent, the compiler reads code "
            "past the intended boundary and may report a cascade of confusing "
            "secondary errors far from the actual missing delimiter."
        ),
        (
            "Count your opening and closing braces carefully. "
            "Use consistent indentation (or your IDE's bracket-matching feature) "
            "to find where the match is missing. "
            "Adding the missing '}' or ')' at the correct location should resolve "
            "any cascade of follow-on errors as well."
        ),
        "Beginner", "Medium",
    ),

    # ── No matching function overload ────────────────────────────────────
    (
        re.compile(
            r"no matching function for call to\s+'?(?P<token>[^'(\s]+)",
            re.IGNORECASE,
        ),
        (
            "The compiler found a function named '{token}' but no overload "
            "of it accepts the combination of argument types that was supplied. "
            "C++ resolves function calls by matching the argument types exactly "
            "(after implicit conversions); if no overload fits, it is a compile error. "
            "This can also occur when calling a function with the wrong number of "
            "arguments or passing a pointer where a value is expected."
        ),
        (
            "Check the declaration of '{token}' and verify that the argument "
            "count and types match. "
            "Use explicit casts if you need to convert the argument type. "
            "If '{token}' is a constructor, ensure the correct constructor overload exists."
        ),
        "Intermediate", "Medium",
    ),

    # ── Division by zero ────────────────────────────────────────────────
    (
        re.compile(r"division by zero", re.IGNORECASE),
        (
            "A compile-time division by zero was detected. "
            "Dividing any number by zero is mathematically undefined and in C++ "
            "it is undefined behaviour — the program may crash, produce garbage, "
            "or (on some platforms) raise a hardware exception. "
            "Even if it seems harmless, the compiler is allowed to assume this "
            "never happens and may optimise away surrounding code in unexpected ways."
        ),
        (
            "Guard every division with a zero-check before performing it: "
            "'if (divisor != 0) { result = numerator / divisor; }'. "
            "For compile-time constants, simply fix the value."
        ),
        "Beginner", "High",
    ),

    # ── Integer overflow ────────────────────────────────────────────────
    (
        re.compile(r"(overflow|INT_MAX|INT_MIN)", re.IGNORECASE),
        (
            "An integer arithmetic expression may overflow the fixed-width type. "
            "Signed integer overflow in C++ is undefined behaviour — the result "
            "does not simply wrap around; the compiler is free to assume overflow "
            "never happens and may produce completely unexpected optimised code. "
            "Unsigned overflow wraps but can still produce logically incorrect values."
        ),
        (
            "Use 'long long' or 'uint64_t' for wider range, "
            "or check bounds before the operation with "
            "std::numeric_limits<T>::max(). "
            "For security-sensitive code, consider using a checked-arithmetic library."
        ),
        "Intermediate", "Medium",
    ),

    # ── Out-of-bounds array access ───────────────────────────────────────
    (
        re.compile(
            r"(array index|out.of.bound|index .* is past)",
            re.IGNORECASE,
        ),
        (
            "An array is being accessed with an index that is outside its valid "
            "range. C and C++ arrays are zero-indexed, so a declaration 'int a[N]' "
            "has valid indices 0 through N-1. Accessing a[N] or beyond is undefined "
            "behaviour: it may silently corrupt other variables, crash the program, "
            "or be exploited as a buffer overflow vulnerability."
        ),
        (
            "Keep all array indices within [0, size-1]. "
            "Add an explicit bounds check before every access: "
            "'if (i >= 0 && i < N) { a[i] = ...; }'. "
            "For C++ containers, use std::vector::at(i) which throws "
            "std::out_of_range automatically."
        ),
        "Intermediate", "High",
    ),
]

_DEFAULT = (
    (
        "The compiler reported an error at this location. "
        "This is often caused by incorrect syntax, a missing punctuation mark, "
        "or a misspelled identifier. "
        "Read the raw compiler message carefully — it usually names the exact "
        "token or keyword that caused the problem, which narrows the search "
        "to the highlighted line or the line immediately before it."
    ),
    (
        "Compare the highlighted line with the raw message above. "
        "Look for: missing semicolons, mismatched brackets, "
        "undeclared variable names, or missing #include directives."
    ),
    "Beginner", "Low",
)


# ---------------------------------------------------------------------------
# Header injection helper
# ---------------------------------------------------------------------------

def _inject_header_context(message: str, nl: str, sug: str) -> tuple[str, str]:
    """
    If the message mentions a known stdlib function without a header,
    enrich the natural_language and suggestion with the correct header.
    """
    for func, header in _HEADER_MAP.items():
        if re.search(rf"\b{func}\b", message, re.IGNORECASE):
            if header not in sug:
                sug = sug.replace(
                    "Add the correct #include",
                    f"Add '#include {header}'",
                )
                sug = sug.replace("{header}", header)
            # inject safe alternative if available
            safe = _SAFE_ALTERNATIVES.get(func, "")
            if safe and func in message.lower() and safe not in sug:
                sug += f" Safe alternative: {safe}."
            break
    return nl, sug


# ---------------------------------------------------------------------------
# Rule-based explain
# ---------------------------------------------------------------------------

def _rule_based_explain(message: str) -> tuple[str, str, str, str]:
    """
    Return (natural_language, suggestion, difficulty, severity).
    Tries every rule in order, picks the first match.
    """
    for pattern, nl_tpl, sug_tpl, difficulty, severity in _RULES:
        m = pattern.search(message)
        if m:
            token = m.groupdict().get("token", "")
            nl  = nl_tpl.replace("{token}", token)
            sug = sug_tpl.replace("{token}", token)

            # Fill {header} placeholder if present
            if "{header}" in sug and token:
                header = _HEADER_MAP.get(token.lower(), "<appropriate_header>")
                sug = sug.replace("{header}", header)

            nl, sug = _inject_header_context(message, nl, sug)
            return nl, sug, difficulty, severity

    nl, sug, difficulty, severity = _DEFAULT
    nl, sug = _inject_header_context(message, nl, sug)
    return nl, sug, difficulty, severity


# ---------------------------------------------------------------------------
# Llama 3 backend (Ollama)
# ---------------------------------------------------------------------------

_OLLAMA_URL   = "http://localhost:11434/api/generate"
_LLAMA3_MODEL = "llama3"

_PROMPT_TEMPLATE = """\
You are an expert C++ tutor helping a first-year student understand a compiler error. 

Compiler error (The Exact Error):
{message}

Code context:
{context}

Respond ONLY with a valid JSON object — absolutely no markdown fences, no extra text — \
with exactly these four keys:
  "natural_language": At least 2-4 sentences explaining what went wrong in a highly beginner-friendly tone. Explain WHY this is an error fundamentally.
  "suggestion": At least 2 sentences with a highly descriptive, concrete fix, including the exact corrected code snippet to replace the broken line.
  "difficulty": exactly one of "Beginner", "Intermediate", or "Advanced".
  "severity": exactly one of "High", "Medium", or "Low".
"""


def _build_context(error_line: str, before: list, after: list) -> str:
    lines = []
    for ln, txt in (before or []):
        lines.append(f"  {ln:3d} | {txt}")
    if error_line:
        lines.append(f"  >>> {error_line}   <- ERROR HERE")
    for ln, txt in (after or []):
        lines.append(f"  {ln:3d} | {txt}")
    return "\n".join(lines) or "(no context available)"


def _llama3_explain(
    message: str,
    error_line: str,
    context_before: list,
    context_after: list,
) -> tuple[str, str, str, str] | None:
    prompt = _PROMPT_TEMPLATE.format(
        message=message,
        context=_build_context(error_line, context_before, context_after),
    )

    payload = json.dumps({
        "model":  _LLAMA3_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 500},
    }).encode("utf-8")

    req = urllib.request.Request(
        _OLLAMA_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None

    raw = data.get("response", "").strip()
    if not raw:
        return None

    raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("`").strip()
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
    sev = parsed.get("severity", "Medium").strip()

    if dif not in ("Beginner", "Intermediate", "Advanced"):
        dif = "Beginner"
    if sev not in ("High", "Medium", "Low"):
        sev = "Medium"

    return (nl, sug, dif, sev) if nl else None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def explain_errors(
    errors: list[dict[str, Any]],
    source: str = "",
    use_llm: bool = False,
) -> list[ExplainedError]:
    """
    Transform raw compiler diagnostics into ExplainedError objects.

    Parameters
    ----------
    errors  : list[dict] from compiler_engine.analyze()["errors"]
    source  : original C++ source string
    use_llm : attempt Llama 3 via Ollama; falls back to rule-based if unavailable

    Returns
    -------
    list[ExplainedError]
    """
    from error_classifier import classify_error, classify_severity

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

        nl, suggestion, difficulty, severity = _rule_based_explain(msg)
        src = "rule-based"

        # Fall back to classify_severity if rule gave Low but message looks serious
        if severity == "Low":
            severity = classify_severity(msg)

        if use_llm:
            llm_result = _llama3_explain(msg, error_line, ctx_before, ctx_after)
            if llm_result:
                nl, suggestion, difficulty, severity = llm_result
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
                severity=severity,
                explanation_source=src,
            )
        )

    return results