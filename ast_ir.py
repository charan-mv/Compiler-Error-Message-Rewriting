"""
ast_ir.py
---------
Internal Representation (IR) for AST visualization.

Converts the existing libclang AST JSON tree (produced by _build_ast_node)
into a flat, visualization-ready IR structure. Each IR node carries:
  - a unique integer id
  - a human-readable label
  - an is_error flag  (only set on the deepest node per error line)
  - a list of child IR node ids (for edge generation)

Key design: a node is only marked is_error=True if it is the deepest
(leaf-closest) node on that error line AND no child of it shares the
same line. This prevents every ancestor on the same line from turning red.
"""

from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# IR node structure
# ---------------------------------------------------------------------------

def make_ir_node(
    node_id: int,
    label: str,
    is_error: bool,
    children: list[int],
    line: int,
    column: int,
) -> dict[str, Any]:
    """Factory for a single IR node dict."""
    return {
        "id": node_id,
        "label": label,
        "is_error": is_error,
        "children": children,
        "line": line,
        "column": column,
    }


# ---------------------------------------------------------------------------
# IR builder
# ---------------------------------------------------------------------------

class _IRBuilder:
    """Stateful depth-first traversal; assigns unique IDs and marks error nodes."""

    def __init__(self, error_lines: set[int]) -> None:
        self._counter: int = 0
        self._error_lines: set[int] = error_lines
        self.nodes: dict[int, dict[str, Any]] = {}

    def _next_id(self) -> int:
        nid = self._counter
        self._counter += 1
        return nid

    def _build_label(self, ast_node: dict[str, Any]) -> str:
        """
        Label shown inside the Graphviz box:
            <kind>
            (<spelling>)   [only if non-empty]
            line:<n>
        """
        kind: str = ast_node.get("kind", "?")
        spelling: str = ast_node.get("spelling", "")
        line: int = ast_node.get("line", 0)
        parts = [kind]
        if spelling:
            # Truncate very long spellings so the node box stays readable
            s = spelling if len(spelling) <= 24 else spelling[:21] + "..."
            parts.append(f"({s})")
        if line > 0:
            parts.append(f"line:{line}")
        return "\n".join(parts)

    def visit(self, ast_node: dict[str, Any]) -> int:
        """
        Recursively visit an AST node and return its assigned IR id.

        A node is flagged is_error ONLY when:
          - its line is in error_lines, AND
          - none of its direct children share the same line
            (i.e. this is the deepest node on that error line).

        This prevents every ancestor with the same start-line from
        being coloured red — only the most specific node is highlighted.
        """
        nid = self._next_id()
        line = ast_node.get("line", 0)
        column = ast_node.get("column", 0)

        child_ast_nodes = ast_node.get("children", [])

        # Recurse into children first
        child_ids: list[int] = []
        for child_ast in child_ast_nodes:
            child_id = self.visit(child_ast)
            child_ids.append(child_id)

        # Collect the source lines covered by direct children
        child_lines: set[int] = {c.get("line", -1) for c in child_ast_nodes}

        # Flag this node as an error node if:
        #   1. The node's source line is a known error line
        #   2. No direct child also sits on that same line
        #      (so we mark only the deepest / most specific node)
        is_error = (
            line > 0
            and line in self._error_lines
            and line not in child_lines
        )

        ir_node = make_ir_node(
            node_id=nid,
            label=self._build_label(ast_node),
            is_error=is_error,
            children=child_ids,
            line=line,
            column=column,
        )
        self.nodes[nid] = ir_node
        return nid


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_ir(
    ast_tree: list[dict[str, Any]],
    diagnostics: list[dict[str, Any]],
) -> dict[str, Any]:
    """
    Convert the libclang AST tree and diagnostics list into the visualization IR.

    Parameters
    ----------
    ast_tree : list[dict]
        Root-level AST nodes from analyze()["ast"] / build_ast().
        Format: {"kind", "spelling", "line", "column", "depth", "children"}

    diagnostics : list[dict]
        Error list from analyze()["errors"].
        Must contain at least {"line": int} per entry.

    Returns
    -------
    dict:
        "nodes"       - flat {id: IR-node} registry
        "roots"       - list of top-level IR node IDs
        "error_lines" - set of flagged source lines
    """
    # Only collect error lines that are actually meaningful (line > 0)
    error_lines: set[int] = {
        d["line"] for d in diagnostics if d.get("line", 0) > 0
    }

    builder = _IRBuilder(error_lines)
    roots: list[int] = []
    for ast_node in ast_tree:
        roots.append(builder.visit(ast_node))

    return {
        "nodes": builder.nodes,
        "roots": roots,
        "error_lines": error_lines,
    }