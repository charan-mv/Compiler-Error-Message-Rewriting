"""
ast_ir.py
---------
Internal Representation (IR) for AST visualization.

Converts the existing libclang AST JSON tree (produced by _build_ast_node)
into a flat, visualization-ready IR structure. Each IR node carries:
  - a unique integer id
  - a human-readable label  (shows actual variable names, values, types)
  - an is_error flag  (only set on the deepest node per error line)
  - a list of child IR node ids (for edge generation)

Key design: a node is only marked is_error=True if it is the deepest
(leaf-closest) node on that error line AND no child of it shares the
same line. This prevents every ancestor on the same line from turning red.
"""

from __future__ import annotations
from typing import Any


# ---------------------------------------------------------------------------
# Kind → friendly display name mapping
# ---------------------------------------------------------------------------

# Maps verbose libclang kind names to short, readable display names.
_KIND_DISPLAY: dict[str, str] = {
    # Declarations
    "TranslationUnitDecl":          "TranslationUnit",
    "FunctionDecl":                 "FunctionDecl",
    "ParmDecl":                     "Param",
    "VarDecl":                      "VarDecl",
    "FieldDecl":                    "Field",
    "TypedefDecl":                  "Typedef",
    "RecordDecl":                   "Record",
    "StructDecl":                   "Struct",
    "ClassDecl":                    "Class",
    "EnumDecl":                     "Enum",
    "EnumConstantDecl":             "EnumConst",
    "NamespaceDecl":                "Namespace",
    "UsingDirectiveDecl":           "UsingDirective",
    # Statements
    "CompoundStmt":                 "Block {}",
    "ReturnStmt":                   "Return",
    "IfStmt":                       "If",
    "ForStmt":                      "ForLoop",
    "WhileStmt":                    "WhileLoop",
    "DoStmt":                       "DoWhile",
    "SwitchStmt":                   "Switch",
    "CaseStmt":                     "Case",
    "DefaultStmt":                  "Default",
    "BreakStmt":                    "Break",
    "ContinueStmt":                 "Continue",
    "NullStmt":                     "NullStmt",
    "DeclStmt":                     "DeclStmt",
    "GotoStmt":                     "Goto",
    # Expressions
    "CallExpr":                     "CallExpr",
    "DeclRefExpr":                  "VarRef",
    "MemberRefExpr":                "MemberRef",
    "BinaryOperator":               "BinaryOp",
    "UnaryOperator":                "UnaryOp",
    "CompoundAssignOperator":       "CompoundAssign",
    "ConditionalOperator":          "TernaryOp",
    "CXXMemberCallExpr":            "MethodCall",
    "CXXOperatorCallExpr":          "OperatorCall",
    "CXXConstructExpr":             "ConstructExpr",
    "CXXDeleteExpr":                "DeleteExpr",
    "CXXNewExpr":                   "NewExpr",
    "CXXThisExpr":                  "this",
    "CXXStaticCastExpr":            "static_cast",
    "CXXReinterpretCastExpr":       "reinterpret_cast",
    "CXXDynamicCastExpr":           "dynamic_cast",
    "CXXConstCastExpr":             "const_cast",
    "ImplicitCastExpr":             "ImplicitCast",
    "CStyleCastExpr":               "CStyleCast",
    "ArraySubscriptExpr":           "ArrayIndex",
    "InitListExpr":                 "InitList",
    "ParenExpr":                    "Paren ()",
    "UnaryExprOrTypeTraitExpr":     "sizeof/alignof",
    "LambdaExpr":                   "Lambda []",
    # Literals
    "IntegerLiteral":               "IntLiteral",
    "FloatingLiteral":              "FloatLiteral",
    "StringLiteral":                "StringLiteral",
    "CharacterLiteral":             "CharLiteral",
    "CXXBoolLiteralExpr":           "BoolLiteral",
    "CXXNullPtrLiteralExpr":        "nullptr",
    # Types / misc
    "TypeRef":                      "TypeRef",
    "TemplateRef":                  "TemplateRef",
    "NamespaceRef":                 "NamespaceRef",
    "OverloadedDeclRef":            "OverloadedRef",
    "NoDeclFound":                  "NoDeclFound",
}

# Kinds whose spelling is the most important thing to show prominently
_SPELLING_PRIMARY_KINDS = {
    "FunctionDecl", "ParmDecl", "VarDecl", "FieldDecl", "TypedefDecl",
    "EnumConstantDecl", "RecordDecl", "StructDecl", "ClassDecl", "EnumDecl",
    "NamespaceDecl", "DeclRefExpr", "MemberRefExpr", "TypeRef",
    "TemplateRef", "NamespaceRef", "CallExpr", "CXXMemberCallExpr",
}

# Kinds that carry a meaningful operator / value in their spelling
_OPERATOR_KINDS = {
    "BinaryOperator", "UnaryOperator", "CompoundAssignOperator",
}

# Kinds that are literal values — show the raw value prominently
_LITERAL_KINDS = {
    "IntegerLiteral", "FloatingLiteral", "StringLiteral",
    "CharacterLiteral", "CXXBoolLiteralExpr",
}


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
        Build a rich, informative label for a Graphviz node box.

        Strategy:
          - Use a friendly short name (from _KIND_DISPLAY) for the kind.
          - For declarations / refs: show the actual identifier name prominently.
          - For literals: show the actual value prominently.
          - For operators: show the operator symbol.
          - Always append the source location as a small footer.

        Format (varies by kind):
            <FriendlyKind>
            name: <identifier>         ← for decls / refs
          OR
            <FriendlyKind>
            = <value>                  ← for literals
          OR
            <FriendlyKind>
            op: <symbol>               ← for operators
            line:<n>
        """
        raw_kind: str = ast_node.get("kind", "?")
        spelling: str = ast_node.get("spelling", "").strip()
        line: int = ast_node.get("line", 0)

        # Friendly display name for the kind
        display_kind = _KIND_DISPLAY.get(raw_kind, raw_kind)

        parts: list[str] = [display_kind]

        if raw_kind in _LITERAL_KINDS:
            # Show the literal value
            if spelling:
                val = spelling if len(spelling) <= 20 else spelling[:17] + "..."
                parts.append(f"= {val}")

        elif raw_kind in _OPERATOR_KINDS:
            # Show the operator symbol
            if spelling:
                parts.append(f"op: {spelling}")

        elif raw_kind in _SPELLING_PRIMARY_KINDS:
            # Show the identifier / function name
            if spelling:
                name = spelling if len(spelling) <= 22 else spelling[:19] + "..."
                parts.append(f"name: {name}")

        else:
            # Generic fallback: show spelling if present and short
            if spelling and len(spelling) <= 28:
                parts.append(spelling)
            elif spelling:
                parts.append(spelling[:25] + "...")

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