from __future__ import annotations

import html
import re
from datetime import date
from pathlib import Path

import streamlit as st

from agent import run

# ---------------------------------------------------------------------
# Page configuration and theme
# ---------------------------------------------------------------------

st.set_page_config(
    page_title="Blog Writing Agent",
    page_icon="✍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

OUTPUT_DIR = Path("generated_blogs")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

st.markdown(
    """
    <style>
    .stApp {
        background: #0b0f19;
        color: #e5e7eb;
    }
    [data-testid="stSidebar"] {
        background: #24242f;
        border-right: 1px solid #343442;
    }
    [data-testid="stSidebar"] h2 {
        color: #f3f4f6;
        font-size: 1.12rem;
    }
    .main-title {
        color: #f9fafb;
        font-size: 2.35rem;
        line-height: 1.2;
        font-weight: 800;
        margin: 0 0 1.15rem 0;
    }
    .panel {
        background: #151923;
        border: 1px solid #303644;
        border-radius: 10px;
        padding: 16px 18px;
        min-height: 88px;
    }
    .metric-label {
        color: #9ca3af;
        font-size: 0.83rem;
        margin-bottom: 5px;
    }
    .metric-value {
        color: #f9fafb;
        font-size: 1.35rem;
        font-weight: 750;
        overflow-wrap: anywhere;
    }
    .stButton > button,
    .stFormSubmitButton > button {
        background: #ff525c;
        color: white;
        border: 0;
        border-radius: 7px;
        font-weight: 650;
        min-height: 42px;
    }
    .stButton > button:hover,
    .stFormSubmitButton > button:hover {
        background: #e9434d;
        color: white;
        border: 0;
    }
    .stTextArea textarea,
    .stTextInput input,
    .stDateInput input {
        background: #11141d;
        color: #f9fafb;
        border: 1px solid #303644;
        border-radius: 7px;
    }
    [data-testid="stExpander"] {
        background: #151923;
        border: 1px solid #303644;
        border-radius: 8px;
    }
    button[data-baseweb="tab"] {
        color: #d1d5db;
        font-weight: 650;
    }
    button[data-baseweb="tab"][aria-selected="true"] {
        color: #ff626b;
    }
    [data-testid="stMarkdownContainer"] {
        color: #e5e7eb;
    }
    #MainMenu, footer {
        visibility: hidden;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def plan_to_dict(result: dict):
    plan = result.get("plan")
    if plan is None:
        return None
    if hasattr(plan, "model_dump"):
        return plan.model_dump()
    return plan


def evidence_to_dicts(result: dict):
    values = result.get("evidence") or []
    return [
        item.model_dump() if hasattr(item, "model_dump") else item
        for item in values
    ]


def get_markdown(result: dict) -> str:
    return result.get("final") or ""


def safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", value).strip().rstrip(".")
    return cleaned or "generated_blog"


def list_blogs():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files = list(OUTPUT_DIR.glob("*.md"))
    return sorted(files, key=lambda item: item.stat().st_mtime, reverse=True)


def load_blog(path: Path):
    markdown = path.read_text(encoding="utf-8")
    st.session_state.result = {
        "final": markdown,
        "plan": None,
        "evidence": [],
        "mode": "saved",
        "needs_research": False,
        "queries": [],
        "as_of": "",
        "recency_days": None,
    }
    st.session_state.error = None
    st.session_state.status = "Loaded saved Markdown file."


# ---------------------------------------------------------------------
# Session state
# ---------------------------------------------------------------------

if "result" not in st.session_state:
    st.session_state.result = None
if "error" not in st.session_state:
    st.session_state.error = None
if "status" not in st.session_state:
    st.session_state.status = None


# ---------------------------------------------------------------------
# Sidebar: generate a blog and reopen past blogs
# ---------------------------------------------------------------------

with st.sidebar:
    st.markdown("## Generate New Blog")

    with st.form("generate_blog_form", clear_on_submit=False):
        topic = st.text_area(
            "Topic",
            value="Self Attention",
            height=100,
            placeholder="e.g. Building a RAG chatbot with LangGraph",
        )
        as_of = st.date_input("As-of date", value=date.today())
        generate = st.form_submit_button(
            "🚀 Generate Blog",
            use_container_width=True,
        )

    st.divider()
    st.markdown("## Past blogs")

    saved_blogs = list_blogs()
    if saved_blogs:
        for blog_path in saved_blogs:
            label = blog_path.stem.replace("_", " ")
            if st.button(
                f"📄 {label}",
                key=f"saved_{blog_path.name}",
                use_container_width=True,
                help=f"Open {blog_path.name}",
            ):
                try:
                    load_blog(blog_path)
                    st.rerun()
                except OSError as exc:
                    st.session_state.error = f"Could not open file: {exc}"
                    st.rerun()
    else:
        st.caption("Generated Markdown files will appear here.")

    st.divider()
    st.caption("LangGraph · Gemini · Tavily · Streamlit")


# ---------------------------------------------------------------------
# Generate action
# ---------------------------------------------------------------------

if generate:
    if not topic.strip():
        st.session_state.error = "Enter a topic before generating a blog."
        st.session_state.result = None
    else:
        st.session_state.error = None
        st.session_state.result = None
        st.session_state.status = None

        try:
            with st.spinner(
                "Running the agent: routing, research, planning, and writing..."
            ):
                result = run(topic=topic.strip(), as_of=as_of.isoformat())

            st.session_state.result = result
            markdown = get_markdown(result)
            plan = plan_to_dict(result)
            title = plan.get("blog_title", topic) if plan else topic

            if markdown:
                OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                output_path = OUTPUT_DIR / f"{safe_filename(title)}.md"
                output_path.write_text(markdown, encoding="utf-8")

            st.session_state.status = "Blog generated successfully."
        except Exception as exc:
            st.session_state.error = (
                f"{type(exc).__name__}: {exc}\n\n"
                "Check that your API keys are set in .env and that your "
                "installed packages match requirements.txt."
            )

    st.rerun()


# ---------------------------------------------------------------------
# Main content
# ---------------------------------------------------------------------

st.markdown(
    '<div class="main-title">Blog Writing Agent</div>',
    unsafe_allow_html=True,
)

if st.session_state.error:
    st.error(st.session_state.error)

if st.session_state.status:
    st.success(st.session_state.status)

result = st.session_state.result

if result is None:
    st.info(
        "Enter a topic in the sidebar and select **Generate Blog**. "
        "Your plan, research evidence, and finished Markdown will appear here."
    )
    st.markdown("### Workflow")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(
            '<div class="panel"><div class="metric-label">Step 1</div>'
            '<div class="metric-value">Route</div>'
            '<p>Decide whether the topic needs fresh research.</p></div>',
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="panel"><div class="metric-label">Step 2</div>'
            '<div class="metric-value">Research & plan</div>'
            '<p>Gather evidence when needed and build a structured outline.</p></div>',
            unsafe_allow_html=True,
        )
    with c3:
        st.markdown(
            '<div class="panel"><div class="metric-label">Step 3</div>'
            '<div class="metric-value">Write</div>'
            '<p>Generate sections in parallel and combine the final blog.</p></div>',
            unsafe_allow_html=True,
        )
    st.stop()

plan = plan_to_dict(result)
evidence = evidence_to_dicts(result)
markdown = get_markdown(result)

plan_tab, evidence_tab, preview_tab = st.tabs(
    ["📝 Plan", "🔎 Evidence", "📄 Markdown Preview"]
)

# ---------------------------------------------------------------------
# Plan tab
# ---------------------------------------------------------------------

with plan_tab:
    if plan:
        tasks = sorted(
            plan.get("tasks", []),
            key=lambda item: item.get("id", 0),
        )

        col1, col2, col3 = st.columns(3)
        with col1:
            st.markdown(
                f'<div class="panel"><div class="metric-label">Mode</div>'
                f'<div class="metric-value">{html.escape(str(result.get("mode", "N/A")))}</div></div>',
                unsafe_allow_html=True,
            )
        with col2:
            st.markdown(
                f'<div class="panel"><div class="metric-label">Sections</div>'
                f'<div class="metric-value">{len(tasks)}</div></div>',
                unsafe_allow_html=True,
            )
        with col3:
            st.markdown(
                f'<div class="panel"><div class="metric-label">Evidence sources</div>'
                f'<div class="metric-value">{len(evidence)}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("### Blog Details")
        st.markdown(f"**Title:** {plan.get('blog_title', 'Untitled')}")
        st.markdown(f"**Audience:** {plan.get('audience', 'N/A')}")
        st.markdown(f"**Tone:** {plan.get('tone', 'N/A')}")
        st.markdown(f"**Blog type:** {plan.get('blog_kind', 'N/A')}")

        constraints = plan.get("constraints", [])
        if constraints:
            st.markdown("### Writing Constraints")
            for constraint in constraints:
                st.markdown(f"- {constraint}")

        st.markdown("### Section Breakdown")
        for task in tasks:
            title = task.get("title", "Untitled section")
            with st.expander(
                f"{task.get('id', '?')}. {title}",
                expanded=False,
            ):
                st.markdown("**Goal**")
                st.write(task.get("goal", ""))
                st.markdown("**Key points**")
                for bullet in task.get("bullets", []):
                    st.markdown(f"- {bullet}")
                st.markdown(
                    f"**Target words:** {task.get('target_words', 'N/A')}"
                )
                tags = task.get("tags", [])
                if tags:
                    st.caption("Tags: " + ", ".join(tags))
                st.caption(
                    f"Research: {task.get('requires_research', False)} · "
                    f"Citations: {task.get('requires_citations', False)} · "
                    f"Code: {task.get('requires_code', False)}"
                )
    else:
        st.info(
            "This is a saved Markdown file. Generate a new blog to see its "
            "structured plan and evidence."
        )

    with st.expander("Research routing details"):
        st.write("Research required:", result.get("needs_research", False))
        st.write("Mode:", result.get("mode", "N/A"))
        st.write("As-of date:", result.get("as_of", "N/A"))
        st.write("Recency window:", result.get("recency_days", "N/A"), "days")
        queries = result.get("queries") or []
        if queries:
            st.markdown("**Search queries**")
            for query in queries:
                st.markdown(f"- {query}")
        else:
            st.caption("No search queries were used.")

# ---------------------------------------------------------------------
# Evidence tab
# ---------------------------------------------------------------------

with evidence_tab:
    st.markdown("### Research Evidence")
    st.caption("Sources returned by the backend research stage.")

    if evidence:
        for index, item in enumerate(evidence, start=1):
            with st.container(border=True):
                st.markdown(
                    f"**{index}. {item.get('title') or 'Untitled source'}**"
                )
                url = item.get("url", "")
                if url:
                    st.markdown(f"[Open source]({url})")
                if item.get("published_at"):
                    st.caption(f"Published: {item['published_at']}")
                if item.get("source"):
                    st.caption(f"Source: {item['source']}")
                if item.get("snippet"):
                    st.write(item["snippet"])
    else:
        st.info(
            "No evidence was returned. The topic may have been routed to "
            "closed-book mode, or no usable dated sources were found."
        )

# ---------------------------------------------------------------------
# Markdown preview tab
# ---------------------------------------------------------------------

with preview_tab:
    st.markdown("### Generated Blog")

    if markdown:
        st.download_button(
            "⬇️ Download Markdown",
            data=markdown,
            file_name="generated_blog.md",
            mime="text/markdown",
        )

        preview_mode = st.radio(
            "Preview mode",
            ["Rendered", "Markdown source"],
            horizontal=True,
        )

        if preview_mode == "Rendered":
            st.markdown(markdown)
        else:
            st.code(markdown, language="markdown")
    else:
        st.warning("No Markdown content is available for this result.")
