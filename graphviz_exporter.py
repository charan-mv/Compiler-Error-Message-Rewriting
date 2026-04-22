"""
graphviz_exporter.py
--------------------
Converts the visualization IR (produced by ast_ir.build_ir) into a
Graphviz DOT file.

Styling rules
-------------
Normal node  : white background, navy border, dark text (light mode)
Error node   : pale red background, vivid red border, dark red text
"""

from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Styling constants  (light-mode palette)
# ---------------------------------------------------------------------------

# Normal node: clean white fill, indigo border, dark charcoal text
_NORMAL_ATTRS = (
    'shape=box, fontname="Courier", fontsize=11, '
    'color="#3b5bdb", fillcolor="#ffffff", fontcolor="#1a1a2e", '
    'style="filled,rounded"'
)

# Error node: pale red fill, bold crimson border, dark red text
_ERROR_ATTRS = (
    'shape=box, fontname="Courier", fontsize=11, '
    'color="#c0392b", fillcolor="#fdf0f0", fontcolor="#7b0000", '
    'style="filled,rounded", penwidth=2.5'
)

_GRAPH_HEADER = """\
digraph AST {
    graph [
        rankdir=TB,
        splines=ortho,
        nodesep=0.6,
        ranksep=0.9,
        bgcolor="#ffffff",
        fontname="Courier",
        fontcolor="#1a1a2e",
        pad=0.5,
        dpi=150
    ];
    node  [margin="0.2,0.14", fontcolor="#1a1a2e", color="#3b5bdb", fillcolor="#ffffff", style="filled,rounded"];
    edge  [arrowsize=0.7, color="#4a5568", arrowhead=open];
"""

_GRAPH_FOOTER = "}\n"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _escape_label(text: str) -> str:
    """
    Escape special characters inside a Graphviz double-quoted label.
    """
    text = text.replace("\\", "\\\\")
    text = text.replace('"', '\\"')
    text = text.replace("\n", "\\n")
    # Escape angle brackets that would be interpreted as HTML
    text = text.replace("<", "\\<")
    text = text.replace(">", "\\>")
    return text


def _node_line(node: dict[str, Any]) -> str:
    """
    Render a single DOT node declaration:
        n3 [label="...", shape=box, ...];
    """
    nid: int = node["id"]
    label: str = _escape_label(node["label"])
    attrs: str = _ERROR_ATTRS if node["is_error"] else _NORMAL_ATTRS
    return f'    n{nid} [{attrs}, label="{label}"];'


def _edge_lines(nodes: dict[int, dict[str, Any]]) -> list[str]:
    """
    Generate one DOT edge per parent->child relationship.
    """
    lines: list[str] = []
    for node in nodes.values():
        parent_id: int = node["id"]
        for child_id in node["children"]:
            lines.append(f"    n{parent_id} -> n{child_id};")
    return lines


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def ir_to_dot(ir: dict[str, Any]) -> str:
    """
    Convert the visualization IR into a DOT format string.

    Parameters
    ----------
    ir : dict
        The IR dictionary returned by ast_ir.build_ir():
            {"nodes": dict[int, node], "roots": list[int], "error_lines": set[int]}

    Returns
    -------
    str
        Complete DOT source string ready to be written to a .dot file.
    """
    nodes: dict[int, dict[str, Any]] = ir["nodes"]

    dot_parts: list[str] = [_GRAPH_HEADER]

    # Node declarations
    for node in nodes.values():
        dot_parts.append(_node_line(node))

    dot_parts.append("")  # blank separator

    # Edge declarations
    dot_parts.extend(_edge_lines(nodes))

    dot_parts.append(_GRAPH_FOOTER)
    return "\n".join(dot_parts)


def save_dot_file(dot_source: str, dot_path: str) -> None:
    """
    Write DOT source to a file.

    Parameters
    ----------
    dot_source : str
        The DOT string produced by ir_to_dot().
    dot_path : str
        Destination file path (e.g. "ast_output.dot").
    """
    with open(dot_path, "w", encoding="utf-8") as fh:
        fh.write(dot_source)