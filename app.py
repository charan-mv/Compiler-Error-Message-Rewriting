"""Compiler Error Analyzer — NITW · Streamlit UI"""

import os
import base64
import tempfile
import streamlit as st

from compiler_engine import analyze
from error_classifier import classify_error
from ast_visualizer import visualize_ast
from explanation_engine import explain_errors
from security_analyzer import analyze_security

# ── page config ────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Compiler Error Analyzer — NITW",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── global styles ──────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500;600&display=swap');

html, body, [class*="css"] { font-family: 'DM Sans', sans-serif; }

/* ── sidebar ── */
section[data-testid="stSidebar"] {
    background: #0a0a0f;
    border-right: 1px solid rgba(139,92,246,0.18);
}
section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
section[data-testid="stSidebar"] .stTextArea textarea {
    background: rgba(139,92,246,0.06) !important;
    border: 1px solid rgba(139,92,246,0.25) !important;
    color: #a5f3fc !important;
    font-family: 'JetBrains Mono', monospace !important;
    font-size: 12.5px !important;
    border-radius: 10px !important;
    line-height: 1.7 !important;
}
section[data-testid="stSidebar"] .stButton button {
    background: linear-gradient(135deg, #7c3aed 0%, #4f46e5 100%) !important;
    color: white !important;
    border: none !important;
    font-weight: 600 !important;
    font-family: 'Syne', sans-serif !important;
    letter-spacing: 0.5px !important;
    border-radius: 10px !important;
    padding: 0.55rem 1rem !important;
    transition: opacity 0.2s !important;
}
section[data-testid="stSidebar"] .stButton button:hover { opacity: 0.88 !important; }

/* ── main canvas ── */
.main .block-container { padding-top: 1.2rem; max-width: 1460px; }

/* ── page header ── */
.page-header {
    background: linear-gradient(135deg, #0a0a0f 0%, #12082a 45%, #0d0d1f 100%);
    border: 1px solid rgba(139,92,246,0.22);
    border-radius: 18px;
    padding: 1.6rem 2rem;
    margin-bottom: 1.4rem;
    display: flex;
    align-items: center;
    gap: 1.2rem;
    box-shadow: 0 8px 40px rgba(124,58,237,0.18), 0 2px 8px rgba(0,0,0,0.4);
}
.page-header h1 {
    font-family: 'Syne', sans-serif;
    font-size: 1.65rem;
    font-weight: 800;
    color: #fff;
    margin: 0;
    letter-spacing: -0.5px;
}
.page-header p { font-size: 0.82rem; color: #94a3b8; margin: 0.25rem 0 0; letter-spacing: 0.2px; }

/* ── stats ── */
.stats-row { display: flex; gap: 0.65rem; margin-bottom: 1.3rem; flex-wrap: wrap; }
.stat-chip {
    background: #ffffff;
    border: 1px solid #e8ecf4;
    border-radius: 50px;
    padding: 0.38rem 1rem;
    font-size: 0.79rem;
    color: #4a5568;
    display: flex;
    align-items: center;
    gap: 5px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.05);
    font-weight: 500;
}
.stat-chip strong { color: #1a202c; }

/* ── section cards ── */
.section-card {
    background: #ffffff;
    border: 1px solid #eaecf4;
    border-radius: 14px;
    padding: 1.15rem 1.35rem;
    margin-bottom: 1rem;
    box-shadow: 0 2px 12px rgba(0,0,0,0.04);
}
.section-title {
    font-family: 'Syne', sans-serif;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 1.4px;
    color: #8b5cf6;
    margin-bottom: 0.8rem;
}

/* ── AST tree ── */
.ast-tree-wrap {
    background: #0d1117;
    border-radius: 10px;
    padding: 1rem 1.2rem;
    overflow: auto;
    font-family: 'JetBrains Mono', monospace;
    font-size: 11.5px;
    line-height: 1.75;
    max-height: 440px;
    border: 1px solid rgba(255,255,255,0.06);
}
.ast-node  { display: block; white-space: pre; }
.ast-kind  { color: #79c0ff; font-weight: 600; }
.ast-spell { color: #ffa657; }
.ast-loc   { color: #484f58; font-size: 10.5px; }
.ast-error-node .ast-kind  { color: #ff7b72 !important; font-weight: 700 !important; }
.ast-error-node .ast-spell { color: #ffa198 !important; }
.ast-error-node .ast-loc   { color: #ff7b72 !important; }
.ast-err-badge {
    display: inline-block;
    background: #ff7b72; color: #0d1117;
    font-size: 8.5px; font-weight: 700;
    padding: 1px 5px; border-radius: 3px;
    margin-left: 5px; vertical-align: middle; letter-spacing: 0.5px;
}

/* ── graphviz ── */
.viz-wrap {
    background: #f7f9fc; border: 1px solid #e2e8f0;
    border-radius: 12px; padding: 1rem; text-align: center;
}
.viz-wrap img { max-width: 100%; border-radius: 8px; box-shadow: 0 4px 20px rgba(0,0,0,0.1); }
.viz-unavail {
    background: #fffbeb; border: 1px dashed #f59e0b;
    border-radius: 10px; padding: 1.2rem;
    font-size: 0.84rem; color: #78350f; text-align: center; line-height: 1.9;
}
.viz-unavail code { background: #fef3c7; padding: 1px 6px; border-radius: 4px; font-family: 'JetBrains Mono', monospace; }

/* ── error cards ── */
.err-card {
    background: #fffbfb;
    border: 1px solid #fcd0d0; border-left: 4px solid #e53e3e;
    border-radius: 10px; padding: 1rem 1.25rem; margin-bottom: 1rem;
}
.err-header { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.55rem; flex-wrap: wrap; }
.err-num {
    background: #e53e3e; color: white;
    font-size: 10.5px; font-weight: 700;
    padding: 2px 10px; border-radius: 20px;
    font-family: 'Syne', sans-serif; letter-spacing: 0.3px;
}
.err-loc  { font-size: 0.8rem; color: #718096; font-family: 'JetBrains Mono', monospace; }
.err-msg  {
    font-family: 'JetBrains Mono', monospace; font-size: 12px; color: #c53030;
    background: #fff0f0; border-radius: 7px; padding: 0.5rem 0.8rem;
    margin: 0.45rem 0; border: 1px solid #fed7d7; word-break: break-word; line-height: 1.6;
}
.err-ast {
    font-size: 11.5px; color: #553c9a; background: #faf5ff;
    border: 1px solid #e9d8fd; border-radius: 6px; padding: 3px 10px;
    display: inline-block; font-family: 'JetBrains Mono', monospace; margin: 0.25rem 0;
}

/* ── explanation cards ── */
.explanation-box {
    background: linear-gradient(135deg, #f0f9ff, #eff6ff);
    border: 1px solid #bfdbfe; border-left: 4px solid #3b82f6;
    border-radius: 10px; padding: 0.9rem 1.1rem; margin-top: 0.7rem;
}
.explanation-box .exp-label {
    font-family: 'Syne', sans-serif; font-size: 0.7rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.1px; color: #1d4ed8; margin-bottom: 0.35rem;
}
.explanation-box .exp-text { font-size: 0.875rem; color: #1e40af; line-height: 1.7; }

.suggestion-box {
    background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
    border: 1px solid #bbf7d0; border-left: 4px solid #22c55e;
    border-radius: 10px; padding: 0.9rem 1.1rem; margin-top: 0.55rem;
}
.suggestion-box .sug-label {
    font-family: 'Syne', sans-serif; font-size: 0.7rem; font-weight: 700;
    text-transform: uppercase; letter-spacing: 1.1px; color: #15803d; margin-bottom: 0.35rem;
}
.suggestion-box .sug-text { font-size: 0.875rem; color: #166534; line-height: 1.7; }

.difficulty-pill {
    display: inline-block; font-size: 10.5px; font-weight: 600;
    font-family: 'Syne', sans-serif; padding: 2px 10px; border-radius: 20px;
    letter-spacing: 0.3px; margin-left: 6px; vertical-align: middle;
}
.diff-beginner     { background: #dcfce7; color: #15803d; border: 1px solid #bbf7d0; }
.diff-intermediate { background: #fef9c3; color: #854d0e; border: 1px solid #fde68a; }
.diff-advanced     { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }

.exp-source-tag {
    display: inline-block; font-size: 9px; font-weight: 600;
    font-family: 'Syne', sans-serif; padding: 1px 7px; border-radius: 10px;
    margin-left: 5px; vertical-align: middle;
    text-transform: uppercase; letter-spacing: 0.5px;
}
.src-llama3    { background: #f0fdf4; color: #15803d; border: 1px solid #86efac; }
.src-rule      { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }

/* ── security panel ── */
.security-panel {
    background: #ffffff; border: 1px solid #eaecf4;
    border-radius: 16px; padding: 1.4rem 1.6rem;
    box-shadow: 0 2px 16px rgba(0,0,0,0.04);
}
.score-gauge-wrap { display: flex; align-items: center; gap: 2rem; margin-bottom: 1.2rem; flex-wrap: wrap; }
.score-circle {
    width: 80px; height: 80px; border-radius: 50%;
    display: flex; flex-direction: column; align-items: center; justify-content: center;
    font-family: 'Syne', sans-serif; font-weight: 800; flex-shrink: 0;
}
.score-circle .sc-num { font-size: 1.6rem; line-height: 1; }
.score-circle .sc-lbl { font-size: 0.6rem; text-transform: uppercase; letter-spacing: 1px; opacity: 0.7; }
.grade-A { background: #dcfce7; color: #15803d; border: 3px solid #4ade80; }
.grade-B { background: #dbeafe; color: #1d4ed8; border: 3px solid #60a5fa; }
.grade-C { background: #fef9c3; color: #854d0e; border: 3px solid #facc15; }
.grade-D { background: #ffedd5; color: #9a3412; border: 3px solid #fb923c; }
.grade-F { background: #fee2e2; color: #991b1b; border: 3px solid #f87171; }
.score-bar-wrap {
    background: #f1f5f9; border-radius: 20px;
    height: 10px; width: 280px; max-width: 100%; overflow: hidden; margin: 0.35rem 0;
}
.score-bar { height: 100%; border-radius: 20px; }
.bar-A { background: linear-gradient(90deg, #4ade80, #22c55e); }
.bar-B { background: linear-gradient(90deg, #60a5fa, #3b82f6); }
.bar-C { background: linear-gradient(90deg, #facc15, #eab308); }
.bar-D { background: linear-gradient(90deg, #fb923c, #f97316); }
.bar-F { background: linear-gradient(90deg, #f87171, #ef4444); }
.summary-text { font-size: 0.83rem; color: #4a5568; line-height: 1.65; max-width: 520px; }

.finding-card {
    background: #fff; border: 1px solid #e5e7eb;
    border-radius: 10px; padding: 0.85rem 1.1rem;
    margin-bottom: 0.7rem; display: flex; gap: 1rem; align-items: flex-start;
}
.finding-left  { flex-shrink: 0; }
.finding-sev   {
    font-family: 'Syne', sans-serif; font-size: 10px; font-weight: 700;
    text-transform: uppercase; letter-spacing: 0.5px;
    padding: 3px 10px; border-radius: 20px; white-space: nowrap;
}
.sev-Critical  { background: #fee2e2; color: #991b1b; border: 1px solid #fca5a5; }
.sev-High      { background: #ffedd5; color: #9a3412; border: 1px solid #fdba74; }
.sev-Medium    { background: #fef9c3; color: #854d0e; border: 1px solid #fde047; }
.sev-Low       { background: #dbeafe; color: #1e40af; border: 1px solid #93c5fd; }
.sev-Info      { background: #f1f5f9; color: #475569; border: 1px solid #cbd5e1; }
.finding-rule  { font-family: 'JetBrains Mono', monospace; font-size: 10.5px; color: #64748b; margin-top: 4px; }
.finding-cwe   { font-family: 'JetBrains Mono', monospace; font-size: 10px;   color: #94a3b8; margin-top: 2px; }
.finding-right { flex: 1; }
.finding-desc  { font-size: 0.845rem; color: #1e293b; line-height: 1.6; margin-bottom: 0.35rem; }
.finding-rec   {
    font-size: 0.82rem; color: #0f766e;
    background: #f0fdfa; border: 1px solid #99f6e4;
    border-radius: 7px; padding: 0.4rem 0.75rem; line-height: 1.55;
}
.finding-line  { font-size: 10.5px; color: #94a3b8; font-family: 'JetBrains Mono', monospace; margin-top: 3px; }
.no-issues-box {
    background: linear-gradient(135deg, #f0fdf4, #ecfdf5);
    border: 1px solid #86efac; border-radius: 12px;
    padding: 1.5rem; text-align: center;
    color: #15803d; font-family: 'Syne', sans-serif; font-weight: 600; font-size: 0.95rem;
}

/* ── badges ── */
.badge { display: inline-block; font-size: 10.5px; font-weight: 600; padding: 3px 10px; border-radius: 20px; font-family: 'Syne', sans-serif; letter-spacing: 0.2px; }
.badge-token     { background: #fff5f5; color: #c53030; border: 1px solid #fc8181; }
.badge-missing   { background: #fffaf0; color: #c05621; border: 1px solid #f6ad55; }
.badge-misplaced { background: #faf5ff; color: #553c9a; border: 1px solid #b794f4; }

/* ── divider ── */
.fancy-div { height: 2px; background: linear-gradient(90deg, transparent, rgba(139,92,246,0.3), transparent); margin: 1.5rem 0; border: none; }

/* ── welcome ── */
.welcome-card {
    background: linear-gradient(135deg, #0a0a0f, #12082a, #0d1117);
    border: 1px solid rgba(139,92,246,0.25); border-radius: 18px;
    padding: 3rem 2.5rem; text-align: center;
    box-shadow: 0 12px 48px rgba(124,58,237,0.15);
}
.welcome-card h2 {
    font-family: 'Syne', sans-serif; color: #fff;
    font-size: 1.7rem; font-weight: 800; margin-bottom: 0.5rem;
    background: linear-gradient(135deg, #a78bfa, #38bdf8);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.welcome-card p { color: #94a3b8; font-size: 0.9rem; line-height: 1.7; }
.feature-grid {
    display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 0.75rem; margin-top: 1.8rem;
}
.feature-item {
    background: rgba(255,255,255,0.04); border: 1px solid rgba(139,92,246,0.18);
    border-radius: 10px; padding: 0.85rem 1rem;
    font-size: 0.82rem; color: #c4b5fd; text-align: left; line-height: 1.5;
}
.feature-item strong {
    display: block; color: #a78bfa; font-family: 'Syne', sans-serif;
    margin-bottom: 2px; font-size: 0.77rem; text-transform: uppercase; letter-spacing: 0.5px;
}

/* ── ollama hint ── */
.ollama-hint {
    background: rgba(34,197,94,0.08); border: 1px solid rgba(34,197,94,0.25);
    border-radius: 8px; padding: 0.55rem 0.85rem;
    font-size: 0.74rem; color: #86efac; line-height: 1.6; margin-top: 0.4rem;
}
</style>
""", unsafe_allow_html=True)


# ── helpers ────────────────────────────────────────────────────────────────────

def _img_to_b64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()


def _render_ast_html(nodes: list, error_lines: set, indent: int = 0) -> str:
    html = ""
    for node in nodes:
        kind        = node.get("kind", "?")
        spelling    = node.get("spelling", "")
        line        = node.get("line", 0)
        col         = node.get("column", 0)
        children    = node.get("children", [])
        child_lines = {c.get("line", -1) for c in children}
        is_error    = (line > 0) and (line in error_lines) and (line not in child_lines)
        node_cls    = "ast-error-node" if is_error else ""
        prefix      = "&nbsp;&nbsp;" * indent
        connector   = "+-&nbsp;" if indent > 0 else ""
        spell_part  = f' <span class="ast-spell">&quot;{spelling}&quot;</span>' if spelling else ""
        loc_part    = f' <span class="ast-loc">[L{line}:{col}]</span>' if line > 0 else ""
        badge       = ' <span class="ast-err-badge">ERR</span>' if is_error else ""
        html += (
            f'<span class="ast-node {node_cls}">'
            f'{prefix}<span style="color:#3d4451">{connector}</span>'
            f'<span class="ast-kind">{kind}</span>'
            f'{spell_part}{loc_part}{badge}'
            f'</span>\n'
        )
        if children:
            html += _render_ast_html(children, error_lines, indent + 1)
    return html


def _difficulty_pill(d: str) -> str:
    cls = {
        "Beginner":     "diff-beginner",
        "Intermediate": "diff-intermediate",
        "Advanced":     "diff-advanced",
    }.get(d, "diff-beginner")
    return f'<span class="difficulty-pill {cls}">{d}</span>'


def _source_tag(src: str) -> str:
    if src == "llama3":
        return '<span class="exp-source-tag src-llama3">Llama 3</span>'
    return '<span class="exp-source-tag src-rule">Rule-based</span>'


# ── sidebar ────────────────────────────────────────────────────────────────────
with st.sidebar:
    st.markdown(
        "<div style='font-family:Syne,sans-serif;font-size:1.1rem;font-weight:800;"
        "color:#a78bfa;letter-spacing:-0.3px;margin-bottom:0.2rem;'>NITW — Compiler Analyzer</div>",
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:0.75rem;color:#64748b;margin-bottom:0.8rem;'>"
        "National Institute of Technology, Warangal<br>"
        "libclang · Graphviz · Llama 3 · Security Analysis</div>",
        unsafe_allow_html=True,
    )
    st.markdown("---")
    st.markdown("**C++ Source Code**")

    DEFAULT_CODE = """\
int main() {
    char buf[8];
    gets(buf);
    strcpy(buf, "overflow example");
    int x = 10
    int y = x + 1
    printf(buf);
    return 0;
}"""

    code = st.text_area(
        "C++ Source",
        value=DEFAULT_CODE,
        height=285,
        label_visibility="collapsed",
    )

    st.markdown("---")
    st.markdown("**Options**")

    use_llm = st.toggle(
        "Llama 3 Explanations",
        value=False,
        help=(
            "Uses Llama 3 running locally via Ollama "
            "(http://localhost:11434). Falls back to rule-based "
            "if Ollama is not running."
        ),
    )

    if use_llm:
        st.markdown(
            "<div class='ollama-hint'>"
            "Requires <b>Ollama</b> running locally with the "
            "<b>llama3</b> model pulled.<br>"
            "<code style='font-size:0.72rem;'>ollama pull llama3</code><br>"
            "<code style='font-size:0.72rem;'>ollama serve</code>"
            "</div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    analyze_clicked = st.button("Analyze", type="primary", use_container_width=True)

    st.markdown(
        "<div style='font-size:0.72rem;color:#475569;line-height:1.7;margin-top:0.6rem;'>"
        "Compiler Design Project — NITW<br>"
        "libclang · Graphviz · Llama 3 · Security Scorer"
        "</div>",
        unsafe_allow_html=True,
    )


# ── page header ────────────────────────────────────────────────────────────────
st.markdown("""
<div class="page-header">
  <div>
    <h1>Compiler Error Analyzer</h1>
    <p>National Institute of Technology, Warangal &nbsp;·&nbsp;
       Token Analysis &nbsp;·&nbsp; Visual AST &nbsp;·&nbsp;
       AI Explanations &nbsp;·&nbsp; Security Scoring</p>
  </div>
</div>
""", unsafe_allow_html=True)


# ── main logic ─────────────────────────────────────────────────────────────────
if analyze_clicked and code.strip():

    with st.spinner("Parsing and analyzing..."):
        result = analyze(code.strip())

    if not result["success"]:
        st.error("❌ Analysis failed — check that libclang is installed.")
        if result.get("errors"):
            st.code(result["errors"][0]["message"])
        st.stop()

    error_lines: set = {e["line"] for e in result["errors"] if e.get("line", 0) > 0}

    spinner_msg = (
        "Generating Llama 3 explanations..."
        if use_llm else
        "Generating rule-based explanations..."
    )
    with st.spinner(spinner_msg):
        explained = explain_errors(
            errors=result["errors"],
            source=code.strip(),
            use_llm=use_llm,
        )

    with st.spinner("Running security analysis..."):
        sec_report = analyze_security(code.strip(), result["errors"])

    # ── stats row ──────────────────────────────────────────────────────────
    n_tok   = len(result["token_rows"])
    n_err   = len(result["errors"])
    grade   = sec_report.grade
    g_colors = {"A": "#22c55e", "B": "#3b82f6", "C": "#eab308", "D": "#f97316", "F": "#ef4444"}
    g_color = g_colors.get(grade, "#94a3b8")
    llm_used = any(e.explanation_source == "llama3" for e in explained)

    err_color = "#e53e3e" if n_err else "#22c55e"
    err_icon  = "🔴" if n_err else "✅"

    st.markdown(
        f'<div class="stats-row">'
        f'<div class="stat-chip"><strong>{n_tok}</strong>&nbsp;tokens</div>'
        f'<div class="stat-chip">AST built</div>'
        f'<div class="stat-chip">{err_icon} '
        f'<strong style="color:{err_color}">{n_err}</strong>&nbsp;error{"s" if n_err != 1 else ""}</div>'
        f'<div class="stat-chip">{"Llama 3" if llm_used else "Rule-based"} explanations</div>'
        f'<div class="stat-chip">SafeScore: '
        f'<strong style="color:{g_color}">{sec_report.score}/100 (Grade {grade})</strong></div>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── tabs ───────────────────────────────────────────────────────────────
    tab1, tab2, tab3, tab4 = st.tabs([
        "Tokens & AST",
        "Visual Graph",
        "Diagnostics & Explanations",
        "Security Analysis",
    ])

    # ══════════════════════════════════════════════════════════════════════
    # TAB 1 — Tokens & AST
    # ══════════════════════════════════════════════════════════════════════
    with tab1:
        c1, c2 = st.columns([1, 1], gap="medium")

        with c1:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Token Stream</div>', unsafe_allow_html=True)
            if result["token_rows"]:
                st.dataframe(
                    result["token_rows"],
                    use_container_width=True,
                    hide_index=True,
                    height=430,
                    column_config={
                        "Token":  st.column_config.TextColumn("Token",  width="medium"),
                        "Kind":   st.column_config.TextColumn("Kind",   width="small"),
                        "Class":  st.column_config.TextColumn("Class",  width="medium"),
                        "Line":   st.column_config.NumberColumn("Line", width="small"),
                        "Column": st.column_config.NumberColumn("Col",  width="small"),
                    },
                )
            else:
                st.info("No tokens extracted.")
            st.markdown('</div>', unsafe_allow_html=True)

        with c2:
            st.markdown('<div class="section-card">', unsafe_allow_html=True)
            st.markdown('<div class="section-title">Abstract Syntax Tree</div>', unsafe_allow_html=True)
            if result["ast"]:
                ast_html = _render_ast_html(result["ast"], error_lines)
                st.markdown(
                    f'<div class="ast-tree-wrap">{ast_html}</div>',
                    unsafe_allow_html=True,
                )
                if error_lines:
                    st.markdown(
                        f"<div style='font-size:0.76rem;color:#e53e3e;margin-top:0.4rem;'>"
                        f"🔴 Error lines highlighted: {sorted(error_lines)}</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.info("No AST available.")
            st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 2 — Visual Graph
    # ══════════════════════════════════════════════════════════════════════
    with tab2:
        st.markdown('<div class="section-card">', unsafe_allow_html=True)
        st.markdown('<div class="section-title">Visual AST Graph — Graphviz</div>', unsafe_allow_html=True)

        _tmp = tempfile.gettempdir()
        _dot = os.path.join(_tmp, "ast_output.dot")
        _png = os.path.join(_tmp, "ast_output.png")

        with st.spinner("Rendering Graphviz visualization..."):
            vis = visualize_ast(result["ast"], result["errors"], _dot, _png)

        if vis.graphviz_available and os.path.isfile(vis.png_path):
            b64 = _img_to_b64(vis.png_path)
            st.markdown(
                f'<div class="viz-wrap">'
                f'<img src="data:image/png;base64,{b64}" alt="AST Visualization"/>'
                f'</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                f"<div style='font-size:0.76rem;color:#718096;margin-top:0.5rem;text-align:center;'>"
                f"🔴 Red node = error &nbsp;·&nbsp; Blue node = normal &nbsp;·&nbsp; "
                f"Error lines: {sorted(vis.error_lines) if vis.error_lines else 'none'}"
                f"</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="viz-unavail">'
                '⚠️ <strong>Graphviz not found.</strong> Install it to render the PNG.<br><br>'
                'Linux: <code>sudo apt install graphviz</code>&nbsp;&nbsp;'
                'macOS: <code>brew install graphviz</code>&nbsp;&nbsp;'
                '<a href="https://graphviz.org/download/" target="_blank">Windows</a>'
                '</div>',
                unsafe_allow_html=True,
            )
            if vis.dot_source:
                with st.expander("DOT source — paste at graphviz.online to view"):
                    st.code(vis.dot_source, language="dot")

        st.markdown('</div>', unsafe_allow_html=True)

    # ══════════════════════════════════════════════════════════════════════
    # TAB 3 — Diagnostics & Explanations
    # ══════════════════════════════════════════════════════════════════════
    with tab3:
        if explained:
            if llm_used:
                st.markdown(
                    "<div style='font-size:0.8rem;color:#15803d;background:#f0fdf4;"
                    "border:1px solid #86efac;border-radius:8px;"
                    "padding:0.5rem 0.9rem;margin-bottom:0.9rem;'>"
                    "Llama 3 explanations active via Ollama</div>",
                    unsafe_allow_html=True,
                )
            elif use_llm:
                st.markdown(
                    "<div style='font-size:0.8rem;color:#854d0e;background:#fef9c3;"
                    "border:1px solid #fde68a;border-radius:8px;"
                    "padding:0.5rem 0.9rem;margin-bottom:0.9rem;'>"
                    "⚠️ Ollama not reachable — showing rule-based explanations. "
                    "Run <code>ollama serve</code> and ensure <code>llama3</code> is pulled.</div>",
                    unsafe_allow_html=True,
                )

            for i, exp in enumerate(explained):
                badge_cls = (
                    "badge-token"     if exp.category == "Token Error"    else
                    "badge-missing"   if exp.category == "Missing Symbol" else
                    "badge-misplaced"
                )
                diff_pill = _difficulty_pill(exp.difficulty)
                src_tag   = _source_tag(exp.explanation_source)

                ctx_lines = []
                for ln, txt in exp.context_before:
                    ctx_lines.append(f"  {ln:3d} | {txt}")
                if exp.error_line:
                    ctx_lines.append(f"  {exp.line:3d} | {exp.error_line}  <- error here")
                for ln, txt in exp.context_after:
                    ctx_lines.append(f"  {ln:3d} | {txt}")

                ast_html = (
                    f'<div class="err-ast">Nearest AST: {exp.ast_node}</div>'
                    if exp.ast_node else ""
                )

                st.markdown(
                    f'<div class="err-card">'
                    f'  <div class="err-header">'
                    f'    <span class="err-num">Error {i + 1}</span>'
                    f'    <span class="err-loc">Line {exp.line}, Col {exp.column}</span>'
                    f'    <span class="badge {badge_cls}">{exp.category}</span>'
                    f'    {diff_pill}{src_tag}'
                    f'  </div>'
                    f'  <div class="err-msg">{exp.raw_message}</div>'
                    f'  {ast_html}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

                if ctx_lines:
                    st.code("\n".join(ctx_lines), language="cpp")

                if exp.natural_language:
                    st.markdown(
                        f'<div class="explanation-box">'
                        f'  <div class="exp-label">What went wrong</div>'
                        f'  <div class="exp-text">{exp.natural_language}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                if exp.suggestion:
                    st.markdown(
                        f'<div class="suggestion-box">'
                        f'  <div class="sug-label">How to fix it</div>'
                        f'  <div class="sug-text">{exp.suggestion}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                st.markdown("<hr class='fancy-div'>", unsafe_allow_html=True)

        else:
            st.success("✅ No compiler errors detected — code looks clean!")

    # ══════════════════════════════════════════════════════════════════════
    # TAB 4 — Security Analysis
    # ══════════════════════════════════════════════════════════════════════
    with tab4:
        score = sec_report.score
        grade = sec_report.grade

        st.markdown(
            f'<div class="security-panel">'
            f'  <div class="score-gauge-wrap">'
            f'    <div class="score-circle grade-{grade}">'
            f'      <span class="sc-num">{grade}</span>'
            f'      <span class="sc-lbl">Grade</span>'
            f'    </div>'
            f'    <div>'
            f'      <div style="font-family:Syne,sans-serif;font-weight:700;'
            f'font-size:1.05rem;color:#1e293b;margin-bottom:0.15rem;">'
            f'        SafeScore {score}'
            f'        <span style="font-size:0.8rem;color:#94a3b8;font-weight:400;">'
            f'/ 100</span>'
            f'      </div>'
            f'      <div class="score-bar-wrap">'
            f'        <div class="score-bar bar-{grade}" style="width:{score}%"></div>'
            f'      </div>'
            f'      <div class="summary-text">{sec_report.summary}</div>'
            f'    </div>'
            f'  </div>',
            unsafe_allow_html=True,
        )

        if sec_report.findings:
            st.markdown(
                f"<div style='font-family:Syne,sans-serif;font-size:0.72rem;"
                f"font-weight:700;text-transform:uppercase;letter-spacing:1.3px;"
                f"color:#8b5cf6;margin-bottom:0.8rem;'>"
                f"Findings ({len(sec_report.findings)})</div>",
                unsafe_allow_html=True,
            )
            for f_ in sec_report.findings:
                sev_cls   = f"sev-{f_.severity}"
                line_info = (
                    f"<div class='finding-line'>Line {f_.line}</div>"
                    if f_.line > 0 else ""
                )
                cwe_info = (
                    f"<div class='finding-cwe'>{f_.cwe}</div>"
                    if f_.cwe else ""
                )
                st.markdown(
                    f'<div class="finding-card">'
                    f'  <div class="finding-left">'
                    f'    <div class="finding-sev {sev_cls}">{f_.severity}</div>'
                    f'    <div class="finding-rule">{f_.rule_id}</div>'
                    f'    {cwe_info}{line_info}'
                    f'  </div>'
                    f'  <div class="finding-right">'
                    f'    <div class="finding-desc">{f_.description}</div>'
                    f'    <div class="finding-rec">Recommendation: {f_.recommendation}</div>'
                    f'  </div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
        else:
            st.markdown(
                '<div class="no-issues-box">'
                '✅ No security issues detected — all checks passed.'
                '</div>',
                unsafe_allow_html=True,
            )

        st.markdown("</div>", unsafe_allow_html=True)


# ── empty / idle state ─────────────────────────────────────────────────────────
elif analyze_clicked and not code.strip():
    st.warning("⚠️ Please enter some C++ code before clicking Analyze.")

else:
    st.markdown("""
    <div class="welcome-card">
      <h2>Compiler Error Analyzer — NITW</h2>
      <p>Paste C++ code in the sidebar and click <strong>Analyze</strong> for a full pipeline report.<br>
      Token analysis, highlighted AST, AI explanations, and security scoring — all in one place.</p>
      <div class="feature-grid">
        <div class="feature-item"><strong>Lexer</strong>Token stream extraction and classification</div>
        <div class="feature-item"><strong>Diagnostics</strong>Error mapping with code context</div>
        <div class="feature-item"><strong>Visual AST</strong>Graphviz graph with error node highlighting</div>
        <div class="feature-item"><strong>AI Explanations</strong>Llama 3 via Ollama (rule-based fallback)</div>
        <div class="feature-item"><strong>Security</strong>Static analysis and SafeScore rating</div>
        <div class="feature-item"><strong>Graphviz</strong>DOT export and PNG rendering</div>
      </div>
    </div>
    """, unsafe_allow_html=True)