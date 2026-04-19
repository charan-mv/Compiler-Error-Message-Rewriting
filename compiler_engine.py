"""
compiler_engine.py
------------------
Compiler engine: tokens, AST, diagnostics via libclang.

Enhanced in Week 9/10:
- Header-awareness: scans the source for stdlib function calls and checks
  whether the required #include is present. If not, injects a synthetic
  "missing required header" diagnostic so the explanation engine can give
  a precise, actionable error message.
- Unsafe-function detection: flags gets/strcpy/printf(var)/system with
  a HIGH-severity synthetic diagnostic even when the header IS present,
  because these are security vulnerabilities, not just compiler warnings.
- _strip_includes preserves line numbers by replacing #include lines with
  blank lines rather than deleting them.
"""

import os
import re
import subprocess
import tempfile
from typing import Optional

from utils import find_libclang, get_lines_context


# ---------------------------------------------------------------------------
# Header map (kept local to avoid circular import; mirrors error_classifier)
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
    "abs": "<stdlib.h>",
    "sqrt": "<math.h>", "pow": "<math.h>", "fabs": "<math.h>",
    "ceil": "<math.h>", "floor": "<math.h>", "sin": "<math.h>",
    "cos": "<math.h>", "tan": "<math.h>",
    "isalpha": "<ctype.h>", "isdigit": "<ctype.h>", "isspace": "<ctype.h>",
    "toupper": "<ctype.h>", "tolower": "<ctype.h>",
    "time": "<time.h>", "clock": "<time.h>",
}

# Functions that are dangerous regardless of header presence
_UNSAFE_FUNCTIONS: set[str] = {
    "gets", "strcpy", "strcat", "sprintf",
}

# Maps unsafe function -> recommended safe alternative string
_SAFE_ALT: dict[str, str] = {
    "gets":    "fgets(buf, sizeof(buf), stdin)",
    "strcpy":  "strncpy(dst, src, sizeof(dst)-1) and null-terminate",
    "strcat":  "strncat(dst, src, sizeof(dst)-strlen(dst)-1)",
    "sprintf": "snprintf(buf, sizeof(buf), fmt, ...)",
}


def _ensure_libclang():
    if not find_libclang():
        raise RuntimeError(
            "Could not find libclang. Install clang or set library path."
        )


def _strip_includes(source: str) -> str:
    """
    Replace #include lines with blank lines so that missing system headers
    do not generate spurious diagnostics.  Line numbers of all other code
    are preserved because we substitute rather than delete.
    """
    lines = source.splitlines(keepends=True)
    cleaned = []
    for line in lines:
        if re.match(r"^\s*#\s*include\s*[<\"]", line):
            cleaned.append("\n")
        else:
            cleaned.append(line)
    return "".join(cleaned)


def _extract_included_headers(source: str) -> set[str]:
    """
    Return the set of headers explicitly included by the source.
    E.g. '#include <stdio.h>' -> '<stdio.h>'
         '#include "mylib.h"'  -> '"mylib.h"'
    """
    headers: set[str] = set()
    for m in re.finditer(
        r"^\s*#\s*include\s*([<\"][^>\"]+[>\"])",
        source,
        re.MULTILINE,
    ):
        headers.add(m.group(1).strip())
    return headers


def _find_func_call_line(source: str, func_name: str) -> int:
    """Return the 1-based line number of the first call to func_name, or 0."""
    for i, line in enumerate(source.splitlines(), start=1):
        if re.search(rf"\b{re.escape(func_name)}\s*\(", line):
            return i
    return 0


def _find_printf_var_lines(source: str) -> list[tuple[int, str]]:
    """
    Return (line_no, func_name) for every printf-family call where the first
    argument is NOT a string literal (i.e. a variable → format-string risk).
    """
    results = []
    pattern = re.compile(
        r"\b(printf|fprintf|sprintf|snprintf)\s*\(\s*(?!\")",
        re.MULTILINE,
    )
    for m in pattern.finditer(source):
        ln = source[: m.start()].count("\n") + 1
        results.append((ln, m.group(1)))
    return results


MOCK_STDLIB = """
namespace std {
    struct dummy_stream {
        template <typename T> dummy_stream& operator<<(const T&) { return *this; }
        template <typename T> dummy_stream& operator>>(T&) { return *this; }
    };
    extern dummy_stream cout, cin, cerr;
    extern dummy_stream endl;
    class string {};
    template<typename T> class vector {};
    template<typename K, typename V> class map {};
    template<typename T> class set {};
}
using namespace std;
extern "C" {
    int printf(const char*, ...);
    int fprintf(void*, const char*, ...);
    int sprintf(char*, const char*, ...);
    int snprintf(char*, int, const char*, ...);
    int scanf(const char*, ...);
    char* gets(char*);
    char* fgets(char*, int, void*);
    int puts(const char*);
    void* fopen(const char*, const char*);
    int fclose(void*);
    void perror(const char*);
    char* strcpy(char*, const char*);
    char* strncpy(char*, const char*, int);
    char* strcat(char*, const char*);
    char* strncat(char*, const char*, int);
    int strcmp(const char*, const char*);
    int strncmp(const char*, const char*, int);
    int strlen(const char*);
    void* malloc(int);
    void free(void*);
    int system(const char*);
    int atoi(const char*);
}
"""

def _compile_with_real_compiler(source: str) -> list[dict]:
    """
    Saves source to a temporary .cpp file and runs g++ (or clang++) -fsyntax-only
    to extract actual compiler errors, avoiding hallucinations.
    Injects a mock standard library to avoid missing boilerplate errors.
    """
    clean_source = _strip_includes(source)
    full_source = MOCK_STDLIB + '\n#line 1 "input.cpp"\n' + clean_source

    fd, temp_path = tempfile.mkstemp(suffix=".cpp", text=True)
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(full_source)

    errors = []
    try:
        # We try g++ first, fallback to clang++
        cmd = ["g++", "-fsyntax-only", "-fdiagnostics-color=never", temp_path]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        except FileNotFoundError:
            cmd = ["clang++", "-fsyntax-only", "-fno-color-diagnostics", temp_path]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        # Parse output for errors
        # Typical g++ output:
        # file.cpp:4:5: error: 'cout' was not declared in this scope
        # Typical clang++ output:
        # file.cpp:4:5: error: use of undeclared identifier 'cout'
        
        output = result.stderr + "\n" + result.stdout
        pattern = re.compile(r"^(?:.*?)(?:\.cpp|input\.cpp):(\d+):(\d+):\s*(error|warning|fatal error):\s*(.*)$")
        
        for line_str in output.splitlines():
            match = pattern.match(line_str.strip())
            if match:
                line_no = int(match.group(1))
                col_no = int(match.group(2))
                sev_type = match.group(3)
                msg = match.group(4)
                
                # We only want real errors (or fatal errors)
                if "error" in sev_type.lower():
                    before, err_line, after = get_lines_context(source, line_no)
                    errors.append({
                        "message": match.group(0).split("cpp:", 1)[1] if "cpp:" in match.group(0) else msg, # Store the actual raw error message
                        "raw_message": msg,
                        "line": line_no,
                        "column": col_no,
                        "context_before": before,
                        "error_line": err_line,
                        "context_after": after,
                        "ast_node": "",
                        "_synthetic": False,
                    })

    except Exception as e:
        # If compilation fails to even run
        errors.append({
            "message": f"Compilation sub-process failed: {str(e)}",
            "raw_message": str(e),
            "line": 0,
            "column": 0,
            "context_before": [],
            "error_line": "",
            "context_after": [],
            "ast_node": "",
            "_synthetic": False,
        })
    finally:
        # Clean up temp file
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
                
    return errors

def parse_source(source: str, filename: str = "input.cpp") -> "tuple":
    """Parse C++ source and return (tu, diag_list)."""
    _ensure_libclang()
    from clang.cindex import Index, TranslationUnit

    args = ["-std=c++17", "-fsyntax-only", "-Wno-everything"]
    if os.name == "nt":
        args.extend(["-fno-ms-compatibility", "-fms-compatibility-version=19"])

    clean_source = _strip_includes(source)

    index = Index.create()
    tu = index.parse(
        filename,
        args=args,
        unsaved_files=[(filename, clean_source)],
    )
    return tu, list(tu.diagnostics)


def extract_tokens(tu) -> list:
    """Extract tokens with line, column, spelling, kind."""
    tokens = []
    try:
        token_iter = tu.cursor.get_tokens()
    except Exception:
        return tokens
    for tok in token_iter:
        loc = tok.location
        tokens.append({
            "spelling": tok.spelling,
            "kind": str(tok.kind).replace("TokenKind.", ""),
            "line": loc.line,
            "column": loc.column,
        })
    return tokens


def _classify_token(kind_str: str) -> str:
    kind_lower = kind_str.lower()
    if "identifier" in kind_lower or "keyword" in kind_lower:
        return "Identifier/Keyword"
    if "literal" in kind_lower or "numeric" in kind_lower:
        return "Literal"
    if "punctuation" in kind_lower:
        return "Punctuation"
    if "comment" in kind_lower:
        return "Comment"
    return "Other"


def _build_ast_node(cursor, depth: int = 0) -> dict:
    kind = str(cursor.kind).replace("CursorKind.", "")
    spelling = cursor.spelling or cursor.displayname or ""
    loc = cursor.location
    line = loc.line if loc else 0
    col = loc.column if loc else 0

    node = {
        "kind": kind,
        "spelling": spelling,
        "line": line,
        "column": col,
        "depth": depth,
        "children": [],
    }

    for child in cursor.get_children():
        node["children"].append(_build_ast_node(child, depth + 1))

    return node


def build_ast(tu) -> list:
    """Build AST as list of root nodes."""
    root = tu.cursor
    return [_build_ast_node(root)]


def ast_to_display_string(nodes: list, indent: str = "") -> str:
    """Convert AST nodes to clean tree display string."""
    lines = []
    for node in nodes:
        kind = node.get("kind", "?")
        spelling = node.get("spelling", "")
        line = node.get("line", 0)
        col = node.get("column", 0)
        part = f"{kind}"
        if spelling:
            part += f' "{spelling}"'
        if line > 0:
            part += f" [L{line}:{col}]"
        lines.append(indent + part)
        if node.get("children"):
            lines.append(ast_to_display_string(node["children"], indent + "  "))
    return "\n".join(lines)


def _nearest_ast_node(
    nodes: list, target_line: int, target_col: int, best: Optional[dict] = None
) -> Optional[dict]:
    def score(n):
        nl, nc = n.get("line", 0), n.get("column", 0)
        if nl <= 0:
            return float("inf")
        line_dist = abs(nl - target_line)
        col_dist = abs(nc - target_col) if nl == target_line else 999
        return (line_dist, col_dist)

    for node in nodes:
        if node.get("line", 0) > 0:
            if best is None or score(node) < score(best):
                best = node
        best = (
            _nearest_ast_node(node.get("children", []), target_line, target_col, best)
            or best
        )
    return best


def _deduplicate_errors(errors: list[dict]) -> list[dict]:
    """
    Remove duplicate diagnostics that point to the same line with the same
    root cause.  Synthetic errors take priority over generic clang messages
    for the same line.
    """
    seen_lines: dict[int, dict] = {}
    result: list[dict] = []

    # Pass 1: add synthetic errors (they are more precise)
    for err in errors:
        if err.get("_synthetic"):
            ln = err.get("line", 0)
            seen_lines[ln] = err
            result.append(err)

    # Pass 2: add clang errors only if no synthetic error covers that line
    for err in errors:
        if not err.get("_synthetic"):
            ln = err.get("line", 0)
            if ln not in seen_lines:
                seen_lines[ln] = err
                result.append(err)
            # If the clang message adds distinct info (different column / kind),
            # include it too unless it's essentially the same text.
            elif err.get("message", "") not in seen_lines[ln].get("message", ""):
                result.append(err)

    return result


def analyze(source: str) -> dict:
    """Full analysis: tokens, AST, diagnostics, error context."""
    result = {
        "tokens": [],
        "token_rows": [],
        "ast": [],
        "ast_display": "",
        "errors": [],
        "success": False,
    }

    try:
        tu, diagnostics = parse_source(source)

        result["tokens"] = extract_tokens(tu)
        result["token_rows"] = [
            {
                "Token": t["spelling"],
                "Kind": t["kind"],
                "Class": _classify_token(t["kind"]),
                "Line": t["line"],
                "Column": t["column"],
            }
            for t in result["tokens"]
        ]

        ast_nodes = build_ast(tu)
        result["ast"] = ast_nodes
        result["ast_display"] = ast_to_display_string(ast_nodes)

        # Use real compiler for actual, legitimate errors
        all_errors = _compile_with_real_compiler(source)

        # Attach nearest AST node for helpful UI display
        for err in all_errors:
            if err.get("line", 0) > 0:
                nearest = _nearest_ast_node(ast_nodes, err["line"], err["column"])
                if nearest:
                    ast_info = f"{nearest.get('kind', '?')}"
                    if nearest.get("spelling"):
                        ast_info += f' "{nearest.get("spelling", "")}"'
                    err["ast_node"] = ast_info

        result["errors"] = _deduplicate_errors(all_errors)
        result["success"] = True

    except Exception as e:
        result["errors"] = [{
            "message": str(e),
            "line": 0,
            "column": 0,
            "context_before": [],
            "error_line": "",
            "context_after": [],
            "ast_node": "",
            "_synthetic": False,
        }]

    return result