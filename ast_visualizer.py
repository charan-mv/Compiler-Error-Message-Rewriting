"""
ast_visualizer.py  (Week 8 — updated)
--------------------------------------
Main interface for Week 8 – Visual AST Highlighting.

Public entry point
------------------
    visualize_ast(ast_tree, diagnostics, dot_path, png_path) -> VisualizationResult

This module:
  1. Builds the IR from the existing AST tree (via ast_ir.build_ir).
  2. Marks broken/error nodes (handled transparently inside the IR builder).
  3. Converts IR → DOT format (via graphviz_exporter.ir_to_dot).
  4. Saves the .dot file to disk.
  5. Calls the `dot` Graphviz binary to produce a PNG.

Integration with existing pipeline
-----------------------------------
    from compiler_engine import analyze
    from ast_visualizer import visualize_ast

    result = analyze(source_code)
    if result["success"]:
        vis = visualize_ast(result["ast"], result["errors"])
        print(vis.dot_path, vis.png_path, vis.graphviz_available)

No existing module (compiler_engine, utils, error_classifier, app) is modified.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any

# Ensure sibling modules are importable regardless of working directory
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from ast_ir import build_ir                             # noqa: E402
from graphviz_exporter import ir_to_dot, save_dot_file  # noqa: E402


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class VisualizationResult:
    """Holds the outcome of a visualize_ast() call."""

    dot_path: str
    """Absolute path to the written .dot file."""

    png_path: str
    """Absolute path to the generated PNG (empty string if Graphviz unavailable)."""

    graphviz_available: bool
    """True when the `dot` binary was found and PNG generation succeeded."""

    error_lines: set[int] = field(default_factory=set)
    """Set of source line numbers that were flagged as errors."""

    dot_source: str = ""
    """The raw DOT source string (useful for embedding in UI or tests)."""

    message: str = ""
    """Human-readable status or error message."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _find_dot_binary() -> str | None:
    """
    Return the path to the Graphviz `dot` executable, or None if not found.

    Searches PATH first, then a small list of common installation locations.
    """
    # shutil.which covers PATH automatically
    found = shutil.which("dot")
    if found:
        return found

    # Fallback: common locations on Linux / macOS / Windows
    candidates = [
        "/usr/bin/dot",
        "/usr/local/bin/dot",
        "/opt/homebrew/bin/dot",
        r"C:\Program Files\Graphviz\bin\dot.exe",
        r"C:\Program Files (x86)\Graphviz\bin\dot.exe",
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path

    return None


def _run_graphviz(dot_path: str, png_path: str, dot_binary: str) -> tuple[bool, str]:
    """
    Execute `dot -Tpng <dot_path> -o <png_path>`.

    Returns
    -------
    (success: bool, message: str)
    """
    cmd = [dot_binary, "-Tpng", dot_path, "-o", png_path]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if proc.returncode == 0:
            return True, f"PNG written to {png_path}"
        else:
            return False, f"Graphviz error (rc={proc.returncode}): {proc.stderr.strip()}"
    except FileNotFoundError:
        return False, f"Graphviz binary not found at {dot_binary}"
    except subprocess.TimeoutExpired:
        return False, "Graphviz timed out after 30 seconds"
    except Exception as exc:
        return False, f"Unexpected error running Graphviz: {exc}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def visualize_ast(
    ast_tree: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
    dot_path: str = "",
    png_path: str = "",
) -> VisualizationResult:
    """
    Build, export, and render a visual AST with error-node highlighting.

    Parameters
    ----------
    ast_tree : list[dict]
        Root-level AST nodes from analyze()["ast"].
        Each node follows the _build_ast_node() format:
            {"kind": str, "spelling": str, "line": int,
             "column": int, "depth": int, "children": list}

    diagnostics : list[dict]
        Error records from analyze()["errors"].
        Each record must contain at least {"line": int}.

    dot_path : str
        Where to write the .dot file. Defaults to system temp directory
        (cross-platform: works on Windows, Linux, macOS).

    png_path : str
        Where to write the PNG file. Defaults to system temp directory.

    Returns
    -------
    VisualizationResult
        Dataclass carrying paths, flags, and status messages.
    """
    import tempfile

    # Resolve cross-platform safe paths inside the system temp directory
    tmp_dir = tempfile.gettempdir()
    if not dot_path:
        dot_path = os.path.join(tmp_dir, "ast_output.dot")
    if not png_path:
        png_path = os.path.join(tmp_dir, "ast_output.png")

    # Ensure parent directory exists (handles custom paths too)
    os.makedirs(os.path.dirname(os.path.abspath(dot_path)), exist_ok=True)

    # --- Step 1: Build IR ---
    ir = build_ir(ast_tree, diagnostics)

    # --- Step 2: Generate DOT source ---
    dot_source = ir_to_dot(ir)

    # --- Step 3: Save .dot file ---
    save_dot_file(dot_source, dot_path)

    # --- Step 4: Run Graphviz ---
    dot_binary = _find_dot_binary()
    if dot_binary is None:
        return VisualizationResult(
            dot_path=dot_path,
            png_path="",
            graphviz_available=False,
            error_lines=ir["error_lines"],
            dot_source=dot_source,
            message=(
                "DOT file saved. Install Graphviz and ensure `dot` is on PATH to generate PNG. "
                "Or paste DOT source at https://dreampuf.github.io/GraphvizOnline/"
            ),
        )

    success, msg = _run_graphviz(dot_path, png_path, dot_binary)
    return VisualizationResult(
        dot_path=dot_path,
        png_path=png_path if success else "",
        graphviz_available=success,
        error_lines=ir["error_lines"],
        dot_source=dot_source,
        message=msg,
    )