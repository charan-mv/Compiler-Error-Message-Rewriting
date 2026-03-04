"""Compiler engine: tokens, AST, diagnostics via libclang."""

import os
from typing import Optional

from utils import find_libclang, get_lines_context


def _ensure_libclang():
    if not find_libclang():
        raise RuntimeError("Could not find libclang. Install clang or set library path.")


def parse_source(source: str, filename: str = "input.cpp") -> "tuple":
    """Parse C++ source and return (tu, diag_list)."""
    _ensure_libclang()
    from clang.cindex import Index, TranslationUnit
    
    args = ["-std=c++17", "-fsyntax-only", "-Wno-everything"]
    if os.name == "nt":
        args.extend(["-fno-ms-compatibility", "-fms-compatibility-version=19"])
    
    index = Index.create()
    tu = index.parse(filename, args=args, unsaved_files=[(filename, source)])
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
    kind =str(cursor.kind).replace("CursorKind.", "")
    spelling= cursor.spelling or cursor.displayname or ""
    loc = cursor.location
    line =loc.line if loc else 0
    col =loc.column if loc else 0
    
    node ={
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
    root =tu.cursor
    return [_build_ast_node(root)]


def ast_to_display_string(nodes: list, indent: str = "") -> str:
    """Convert AST nodes to clean tree display string."""
    lines= []
    for node in nodes:
        kind =node.get("kind","?")
        spelling =node.get("spelling","")
        line= node.get("line",0)
        col= node.get("column",0)
        part= f"{kind}"
        if spelling:
            part+= f' "{spelling}"'
        if line > 0:
            part += f" [L{line}:{col}]"
        lines.append(indent + part)
        if node.get("children"):
            lines.append(ast_to_display_string(node["children"],indent+"  "))
    return "\n".join(lines)


def _nearest_ast_node(nodes: list,target_line: int,target_col: int,best: Optional[dict]= None) -> Optional[dict]:
    def score(n):
        nl, nc = n.get("line", 0), n.get("column",0)
        if nl<=0:
            return float("inf")
        line_dist= abs(nl - target_line)
        col_dist =abs(nc - target_col) if nl == target_line else 999
        return (line_dist, col_dist)
    
    for node in nodes:
        if node.get("line",0) > 0:
            if best is None or score(node) < score(best):
                best =node
        best= _nearest_ast_node(node.get("children",[]),target_line, target_col, best) or best
    return best


def analyze(source: str) -> dict:
    """Full analysis: tokens, AST, diagnostics, error context."""
    result = {
        "tokens":[],
        "token_rows":[],
        "ast": [],
        "ast_display":"",
        "errors": [],
        "success":False,
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
        
        for diag in diagnostics:
            if diag.severity >= 3:
                loc =diag.location
                line =loc.line if loc else 0
                col= loc.column if loc else 0
                msg= str(diag.spelling)
                
                before,err_line, after = get_lines_context(source, line)
                
                nearest =_nearest_ast_node(ast_nodes, line, col)
                ast_info = ""
                if nearest:
                    ast_info =f"{nearest.get('kind', '?')}"
                    if nearest.get("spelling"):
                        ast_info += f' "{nearest.get('spelling', '')}"'
                
                result["errors"].append({
                    "message": msg,
                    "line": line,
                    "column": col,
                    "context_before": before,
                    "error_line": err_line,
                    "context_after": after,
                    "ast_node": ast_info,
                })
        
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
        }]
    
    return result
