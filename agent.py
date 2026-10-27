from __future__ import annotations
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_tavily import TavilySearch
from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

import operator
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Annotated, List, Literal, Optional, TypedDict

from dotenv import load_dotenv
from pydantic import BaseModel, Field


load_dotenv()

# ---------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------


llm = ChatGoogleGenerativeAI(model="gemini-3.6-flash")

OUTPUT_DIR = Path(os.getenv("BLOG_OUTPUT_DIR", "generated_blogs"))
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)



# ---------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------

class Task(BaseModel):
    id: int
    title: str
    goal: str = Field(
        ...,
        description="One sentence describing what the reader should be able to do or understand.",
    )
    bullets: List[str] = Field(
        ...,
        min_length=3,
        max_length=6,
        description="3-6 concrete, non-overlapping subpoints.",
    )
    target_words: int = Field(..., ge=120, le=550)
    tags: List[str] = Field(default_factory=list)
    requires_research: bool = False
    requires_citations: bool = False
    requires_code: bool = False


class Plan(BaseModel):
    blog_title: str
    audience: str
    tone: str
    blog_kind: Literal[
        "explainer", "tutorial", "news_roundup", "comparison", "system_design"
    ] = "explainer"
    constraints: List[str] = Field(default_factory=list)
    tasks: List[Task]


class EvidenceItem(BaseModel):
    title: str
    url: str
    published_at: Optional[str] = None
    snippet: Optional[str] = None
    source: Optional[str] = None


class RouterDecision(BaseModel):
    needs_research: bool
    mode: Literal["closed_book", "hybrid", "open_book"]
    reason: str
    queries: List[str] = Field(default_factory=list)
    max_results_per_query: int = Field(default=5, ge=3, le=8)


class EvidencePack(BaseModel):
    evidence: List[EvidenceItem] = Field(default_factory=list)


class State(TypedDict):
    topic: str
    mode: str
    needs_research: bool
    queries: List[str]
    evidence: List[EvidenceItem]
    plan: Optional[Plan]
    as_of: str
    recency_days: int
    sections: Annotated[List[tuple[int, str]], operator.add]
    final: str


# ---------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------

ROUTER_SYSTEM = """You are the routing module for a technical blog writing agent.
Decide whether web research is needed before planning.

Modes:
- closed_book: evergreen concepts whose correctness does not depend on recent facts.
- hybrid: mostly evergreen topics that benefit from current tools, examples, or model information.
- open_book: volatile topics such as weekly roundups, latest news, pricing, rankings, or policy changes.

If research is needed, return 3-10 specific, high-signal search queries.
For open_book, queries should target the seven days ending on the supplied as-of date.
Return only the structured schema requested.
"""


def router_node(state: State) -> dict:
    decision = llm.with_structured_output(RouterDecision).invoke(
        [
            SystemMessage(content=ROUTER_SYSTEM),
            HumanMessage(
                content=f"Topic: {state['topic']}\nAs-of date: {state['as_of']}"
            ),
        ]
    )

    if decision.mode == "open_book":
        recency_days = 7
    elif decision.mode == "hybrid":
        recency_days = 45
    else:
        recency_days = 3650

    # Keep the decision internally consistent.
    needs_research = decision.needs_research or decision.mode in {"hybrid", "open_book"}
    return {
        "needs_research": needs_research,
        "mode": decision.mode,
        "queries": decision.queries[:10] if needs_research else [],
        "recency_days": recency_days,
    }


def route_next(state: State) -> str:
    return "research" if state["needs_research"] else "orchestrator"


# ---------------------------------------------------------------------
# Research
# ---------------------------------------------------------------------

RESEARCH_SYSTEM = """You synthesize raw search results for technical writing.
Rules:
- Include only items with a non-empty URL.
- Prefer authoritative and relevant sources: official docs, company blogs, papers,
  and reputable publications.
- Normalize dates to YYYY-MM-DD only when reliably known; otherwise use null.
- Keep snippets concise and deduplicate URLs.
- Do not invent facts or URLs.
"""


def _iso_to_date(value: Optional[str]) -> Optional[date]:
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (TypeError, ValueError):
        return None


def _tavily_search(query: str, max_results: int = 5) -> List[dict]:
    """Run Tavily search and normalize common response shapes."""
    if not os.getenv("TAVILY_API_KEY"):
        raise RuntimeError(
            "This topic requires web research, but TAVILY_API_KEY is missing. "
            "Add it to your .env file or use a topic that does not require research."
        )

    tool = TavilySearch(max_results=max_results)
    result = tool.invoke({"query": query})

    # LangChain tool versions may return either a list or a dict wrapper.
    if isinstance(result, dict):
        result = result.get("results", result.get("content", []))
    if not isinstance(result, list):
        return []

    normalized = []
    for item in result:
        if not isinstance(item, dict):
            continue
        normalized.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
                "published_at": (
                    item.get("published_date")
                    or item.get("published_at")
                    or item.get("date")
                ),
                "source": item.get("source") or item.get("domain") or "",
            }
        )
    return normalized


def research_node(state: State) -> dict:
    raw_results: List[dict] = []
    for query in (state.get("queries") or [])[:10]:
        raw_results.extend(_tavily_search(query, max_results=5))

    if not raw_results:
        return {"evidence": []}

    # Deduplicate raw results before asking the model to normalize them.
    unique_raw = {}
    for item in raw_results:
        url = item.get("url")
        if url:
            unique_raw[url] = item

    extractor = llm.with_structured_output(EvidencePack)
    pack = extractor.invoke(
        [
            SystemMessage(content=RESEARCH_SYSTEM),
            HumanMessage(
                content=(
                    f"As-of date: {state['as_of']}\n"
                    f"Recency window: {state['recency_days']} days\n\n"
                    f"Raw search results:\n{list(unique_raw.values())[:50]}"
                )
            ),
        ]
    )

    evidence_by_url = {}
    for item in pack.evidence:
        if item.url:
            evidence_by_url[item.url] = item

    evidence = list(evidence_by_url.values())

    # For weekly roundups, only retain evidence with a known recent date.
    if state.get("mode") == "open_book":
        as_of = date.fromisoformat(state["as_of"])
        cutoff = as_of - timedelta(days=state["recency_days"])
        evidence = [
            item
            for item in evidence
            if (published := _iso_to_date(item.published_at)) is not None
            and cutoff <= published <= as_of
        ]

    return {"evidence": evidence}


# ---------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------

ORCH_SYSTEM = """You are a senior technical writer and developer advocate.
Create a highly actionable plan for a technical blog post.

Requirements:
- Create 5-9 sections.
- Each section needs a goal, 3-6 concrete non-overlapping bullets, and target_words
  between 120 and 550.
- Include at least two quality elements across the plan: a minimal code example,
  edge cases/failure modes, performance/cost, security/privacy, or debugging/
  observability. Set requires_code=True where code is needed.
- Keep the plan appropriate for a developer audience.
- closed_book: keep the plan evergreen.
- hybrid: use evidence only for up-to-date examples and mark relevant sections
  requires_research=True and requires_citations=True.
- open_book: blog_kind must be news_roundup. Focus on events and implications,
  not tutorials. If evidence is insufficient, say so transparently and do not
  invent events.
Return only the requested Plan schema.
"""


def orchestrator_node(state: State) -> dict:
    evidence = state.get("evidence", [])
    plan = llm.with_structured_output(Plan).invoke(
        [
            SystemMessage(content=ORCH_SYSTEM),
            HumanMessage(
                content=(
                    f"Topic: {state['topic']}\n"
                    f"Mode: {state.get('mode', 'closed_book')}\n"
                    f"As-of: {state['as_of']}\n"
                    f"Recency days: {state['recency_days']}\n"
                    f"Evidence (use only for fresh claims):\n"
                    f"{[item.model_dump() for item in evidence][:20]}\n"
                )
            ),
        ]
    )

    if state.get("mode") == "open_book":
        plan.blog_kind = "news_roundup"

    return {"plan": plan}


# ---------------------------------------------------------------------
# Parallel section writers
# ---------------------------------------------------------------------

def fanout(state: State):
    plan = state["plan"]
    if plan is None:
        raise ValueError("Cannot create section tasks without a plan.")

    return [
        Send(
            "worker",
            {
                "task": task.model_dump(),
                "topic": state["topic"],
                "mode": state["mode"],
                "as_of": state["as_of"],
                "recency_days": state["recency_days"],
                "plan": plan.model_dump(),
                "evidence": [
                    item.model_dump() for item in state.get("evidence", [])
                ],
            },
        )
        for task in plan.tasks
    ]


WORKER_SYSTEM = """You are a senior technical writer and developer advocate.
Write exactly ONE section of a technical blog in Markdown.

Requirements:
- Start with ## followed by the section title.
- Follow the goal and cover every supplied bullet in order.
- Aim for the target word count, within about 15%.
- Output only the section, with no blog-level H1 or commentary.
- If blog_kind is news_roundup, do not turn the section into a tutorial.
- For open_book claims about specific events, companies, models, funding, or
  policies, cite only URLs from the provided evidence list using Markdown links.
  If a claim is unsupported, say "Not found in provided sources."
- For requires_citations sections, cite evidence URLs for external factual claims.
- Do not invent URLs or citations.
- If requires_code is true, include at least one minimal correct code example.
- Use concise paragraphs, useful bullets, and code fences where appropriate.
"""


def worker_node(payload: dict) -> dict:
    task = Task(**payload["task"])
    plan = Plan(**payload["plan"])
    evidence = [EvidenceItem(**item) for item in payload.get("evidence", [])]

    evidence_text = "\n".join(
        f"- {item.title} | {item.url} | "
        f"{item.published_at or 'date unknown'} | {item.snippet or ''}"
        for item in evidence[:20]
    ) or "(No evidence supplied.)"

    bullets_text = "\n".join(f"- {bullet}" for bullet in task.bullets)
    response_chunks = []
    for chunk in llm.stream(
    [
        SystemMessage(content=WORKER_SYSTEM),
        HumanMessage(
            content=(
                    f"Blog title: {plan.blog_title}\n"
                    f"Audience: {plan.audience}\n"
                    f"Tone: {plan.tone}\n"
                    f"Blog kind: {plan.blog_kind}\n"
                    f"Constraints: {plan.constraints}\n"
                    f"Topic: {payload['topic']}\n"
                    f"Mode: {payload.get('mode', 'closed_book')}\n"
                    f"As-of date: {payload.get('as_of')}\n"
                    f"Recency days: {payload.get('recency_days')}\n\n"
                    f"Section title: {task.title}\n"
                    f"Goal: {task.goal}\n"
                    f"Target words: {task.target_words}\n"
                    f"Tags: {task.tags}\n"
                    f"requires_research: {task.requires_research}\n"
                    f"requires_citations: {task.requires_citations}\n"
                    f"requires_code: {task.requires_code}\n"
                    f"Bullets to cover in order:\n{bullets_text}\n\n"
                    f"Evidence URLs available for citations:\n{evidence_text}"
                )
            ),
    ]):
        # 🟢 CHANGE 2: Print each chunk immediately
        if isinstance(chunk.content, str):
            print(chunk.content, end="", flush=True)
            response_chunks.append(chunk.content)

    # 🟢 CHANGE 3: Combine all chunks into one response
    content = "".join(response_chunks)
    
    if isinstance(content, list):
        content = "\n".join(
            part.get("text", "") if isinstance(part, dict) else str(part)
            for part in content
        )

    section_markdown = str(content).strip()
    return {"sections": [(task.id, section_markdown)]}


# ---------------------------------------------------------------------
# Merge and save
# ---------------------------------------------------------------------

def _safe_filename(title: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*]', "", title).strip().rstrip(".")
    return cleaned or "generated_blog"


def reducer_node(state: State) -> dict:
    plan = state["plan"]
    if plan is None:
        raise ValueError("Reducer called without a plan.")

    ordered_sections = [
        markdown
        for _, markdown in sorted(state["sections"], key=lambda pair: pair[0])
    ]
    body = "\n\n".join(ordered_sections).strip()
    final_markdown = f"# {plan.blog_title}\n\n{body}\n"

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / f"{_safe_filename(plan.blog_title)}.md"
    output_path.write_text(final_markdown, encoding="utf-8")

    return {"final": final_markdown}


# ---------------------------------------------------------------------
# Build graph
# ---------------------------------------------------------------------

graph = StateGraph(State)
graph.add_node("router", router_node)
graph.add_node("research", research_node)
graph.add_node("orchestrator", orchestrator_node)
graph.add_node("worker", worker_node)
graph.add_node("reducer", reducer_node)

graph.add_edge(START, "router")
graph.add_conditional_edges(
    "router",
    route_next,
    {"research": "research", "orchestrator": "orchestrator"},
)
graph.add_edge("research", "orchestrator")
graph.add_conditional_edges("orchestrator", fanout, ["worker"])
graph.add_edge("worker", "reducer")
graph.add_edge("reducer", END)

app = graph.compile()


# ---------------------------------------------------------------------
# Public function imported by app.py
# ---------------------------------------------------------------------

def run(topic: str, as_of: Optional[str] = None) -> dict:
    """Run the complete graph and return the final LangGraph state."""
    if not topic or not topic.strip():
        raise ValueError("Topic cannot be empty.")

    if as_of is None:
        as_of = date.today().isoformat()

    # Validate date early for a friendlier error.
    date.fromisoformat(as_of)

    result = app.invoke(
        {
            "topic": topic.strip(),
            "mode": "",
            "needs_research": False,
            "queries": [],
            "evidence": [],
            "plan": None,
            "as_of": as_of,
            "recency_days": 7,
            "sections": [],
            "final": "",
        }
    )

    plan = result.get("plan")
    print("\n" + "=" * 72)
    print("BLOG WRITING AGENT")
    print("Topic:", topic)
    print("Mode:", result.get("mode"))
    print("Research required:", result.get("needs_research"))
    print("Evidence count:", len(result.get("evidence", [])))
    print("Sections:", len(plan.tasks) if plan else 0)
    print("Markdown characters:", len(result.get("final", "")))
    print("=" * 72 + "\n")

    return result


if __name__ == "__main__":
    generated = run("Write a blog on Self Attention")
    print(generated.get("final", ""))
