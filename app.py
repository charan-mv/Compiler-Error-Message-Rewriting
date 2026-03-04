"""AI Tutor for Compiler Error Rewriting - Streamlit UI."""

import streamlit as st
from compiler_engine import analyze
from error_classifier import classify_error

st.set_page_config(
    page_title="Compiler Error Tutor",
    page_icon="  ",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header { font-size: 1.8rem; font-weight: 600; margin-bottom: 1.5rem; color: #1a1a2e; }
    .sidebar .sidebar-content { background: #f8f9fa; }
    .stTextArea textarea { font-family: 'Consolas', 'Monaco', monospace; font-size: 14px; }
    .error-panel { 
        background: #fff5f5; 
        border-left: 4px solid #e53e3e; 
        padding: 1rem; 
        margin: 0.5rem 0; 
        border-radius: 4px; 
    }
    .context-block { 
        font-family: 'Consolas', monospace; 
        background: #f7fafc; 
        padding: 0.75rem; 
        border-radius: 4px; 
        margin: 0.25rem 0;
        font-size: 13px;
    }
    .error-line { background: #fed7d7; padding: 2px 4px; border-radius: 2px; }
    .badge-token { background: #e53e3e; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .badge-missing { background: #dd6b20; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .badge-misplaced { background: #805ad5; color: white; padding: 2px 8px; border-radius: 4px; font-size: 12px; }
    .section-title { font-size: 1rem; font-weight: 600; margin: 1rem 0 0.5rem 0; color: #2d3748; }
</style>
""", unsafe_allow_html=True)

st.sidebar.markdown("##  Compiler Error Tutor")
st.sidebar.markdown("---")
st.sidebar.markdown("Enter C++ code and click **Analyze** to see tokens, AST, and error analysis.")

with st.sidebar:
    st.markdown("---")
    st.markdown("### Code Input")

default_code = '''int main() {
    int x = 10
    int y = x + 1
    return 0;
}'''

code = st.sidebar.text_area(
    "C++ Source",
    value=default_code,
    height=270,
    label_visibility="collapsed",
)

analyze_clicked = st.sidebar.button("Analyze", type="primary",use_container_width=True)

st.markdown('<p class="main-header">Compiler Error Analysis</p>',unsafe_allow_html=True)

if analyze_clicked and code.strip():
    with st.spinner("Analyzing..."):
        result = analyze(code.strip())
    
    if not result["success"]:
        st.error("Analysis failed. Check that libclang is installed.")
        if result.get("errors"):
            st.code(result["errors"][0]["message"])
    else:
        col1, col2 = st.columns([1, 1])
        
        with col1:
            st.markdown('<p class="section-title">Tokens</p>', unsafe_allow_html=True)
            if result["token_rows"]:
                st.dataframe(
                    result["token_rows"],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "Token": st.column_config.TextColumn("Token",width="medium"),
                        "Kind": st.column_config.TextColumn("Kind", width="small"),
                        "Class": st.column_config.TextColumn("Class",width="medium"),
                        "Line": st.column_config.NumberColumn("Line",width="small"),
                        "Column": st.column_config.NumberColumn("Col",width="small"),
                    },
                )
            else:
                st.info("No tokens extracted.")
        
        with col2:
            st.markdown('<p class="section-title">AST</p>',unsafe_allow_html=True)
            if result["ast_display"]:
                st.code(result["ast_display"],language="text")
            else:
                st.info("No AST available.")
        
        st.markdown("---")
        st.markdown('<p class="section-title">Errors</p>', unsafe_allow_html=True)
        
        if result["errors"]:
            for i, err in enumerate(result["errors"]):
                category =classify_error(err["message"])
                badge_class= "badge-token" if category=="Token Error" else "badge-missing" if category =="Missing Symbol" else "badge-misplaced"
                
                with st.container():
                    st.markdown(f"**Error {i+1}** — Line {err['line']}, Column {err['column']}")
                    st.markdown(f'<span class="{badge_class}">{category}</span>', unsafe_allow_html=True)
                    st.markdown(f"**Message:** {err['message']}")
                    
                    if err.get("ast_node"):
                        st.markdown(f"**Nearest AST node:** `{err['ast_node']}`")
                    
                    before= err.get("context_before",[])
                    err_line =err.get("error_line","")
                    after = err.get("context_after",[])
                    
                    if before or err_line or after:
                        st.markdown("**Context:**")
                        ctx_lines = []
                        for ln, txt in before:
                            ctx_lines.append(f"  {ln} | {txt}")
                        if err_line:
                            ln =err["line"]
                            ctx_lines.append(f"  {ln} | {err_line}  ← error")
                        for ln,txt in after:
                            ctx_lines.append(f"  {ln} | {txt}")
                        st.code("\n".join(ctx_lines),language="cpp")
                    st.markdown("---")
        else:
            st.success("No errors detected.")

elif analyze_clicked and not code.strip():
    st.warning("Please enter some C++ code.")

else:
    st.info("Enter C++ code in the sidebar and click **Analyze** to start.")
