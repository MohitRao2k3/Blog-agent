# ✍️ Blog Writing Agent

An AI-powered technical blog writer built with **Python, LangGraph, Google Gemini, Tavily Search, and Streamlit**.

The application accepts a topic, decides whether fresh research is needed, creates a structured outline, writes sections in parallel, and combines them into a downloadable Markdown article.

## Features

- AI routing into `closed_book`, `hybrid`, and `open_book` research modes.
- Optional web research using Tavily Search.
- Structured blog plans with audience, tone, goals, bullets, and target word counts.
- Parallel section generation with LangGraph.
- Evidence and source URLs supplied to writing workers.
- Markdown output saved to `generated_blogs/`.
- Dark-themed Streamlit interface with **Plan**, **Evidence**, and **Markdown Preview** tabs.
- Sidebar for creating blogs and reopening saved Markdown files.
- Download button for the completed article.

## How It Works

```text
Topic
  |
  v
Router
  |
  +---- Research needed? ---- Yes ----> Research
  |                                  |
  +--------------- No ----------------+
                   |
                   v
              Orchestrator
             (create plan)
                   |
                   v
        Parallel section workers
                   |
                   v
                Reducer
         (combine and save Markdown)
                   |
                   v
             Final blog post
```

| Graph node | Responsibility |
|---|---|
| `router` | Selects research mode and queries. |
| `research` | Searches with Tavily and normalizes evidence. |
| `orchestrator` | Creates a structured blog plan. |
| `worker` | Writes one section; multiple workers can run in parallel. |
| `reducer` | Orders sections and saves the final Markdown document. |

## Tech Stack

- Python 3.10+
- LangGraph
- LangChain Core
- Google Gemini
- Tavily Search
- Pydantic
- Streamlit
- python-dotenv

## Project Structure

```text
blog-writing-agent/
├── agent.py              # LangGraph backend
├── app.py                # Streamlit frontend
├── requirements.txt      # Python dependencies
├── .env.example          # Environment-variable template
├── .env                  # Your private API keys (create this)
└── generated_blogs/      # Generated Markdown files
```

The `generated_blogs/` folder is created automatically.

## Setup

### 1. Open the project folder

Extract the project ZIP and open the folder in VS Code or a terminal.

### 2. Create a virtual environment (recommended)

**Windows PowerShell**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

**macOS / Linux**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 4. Configure API keys

Copy `.env.example` to a file named `.env` in the project root and set your keys:

```env
GOOGLE_API_KEY=your_google_gemini_api_key
TAVILY_API_KEY=your_tavily_api_key

# Optional settings
GEMINI_MODEL=gemini-2.5-flash
BLOG_OUTPUT_DIR=generated_blogs
```

`GOOGLE_API_KEY` is required. `TAVILY_API_KEY` is required when the router chooses a research-enabled mode. Keep `.env` private and do not commit it to Git.

### 5. Run the app

```bash
streamlit run app.py
```

Streamlit will show a local URL in the terminal and usually open the app in your browser.

## Using the App

1. Enter a topic in the sidebar.
2. Choose an **As-of date**.
3. Click **Generate Blog**.
4. Review the outline and section requirements in **Plan**.
5. Inspect source URLs and snippets in **Evidence** when research was performed.
6. Read the generated article in **Markdown Preview**.
7. Download the Markdown file or reopen a saved blog from **Past blogs**.

## Research Modes

| Mode | Typical use | Behavior |
|---|---|---|
| `closed_book` | Evergreen concepts and fundamentals | Skips web research. |
| `hybrid` | Mostly evergreen topics needing current examples | Searches for recent supporting evidence. |
| `open_book` | News roundups and volatile topics | Uses a short recency window and plans a news roundup. |

For `open_book`, the backend filters evidence to sources with parseable dates in the configured time window. Evidence may therefore be empty if search results lack publication dates.

## Output

Generated articles are saved as Markdown files in `generated_blogs/`. The frontend also provides a download button for the current article.

## Notes and Limitations

- The frontend waits for the LangGraph workflow to finish; live node-by-node streaming is not implemented yet.
- Review factual claims and citations before publishing.
- Research-enabled topics require a valid Tavily API key.
- API usage may incur charges according to your provider accounts and plans.
- The project is intended as a starting point for local development. Secure API keys and add access controls before public deployment.
- If the default Gemini model is unavailable to your account, set `GEMINI_MODEL` to a supported model in `.env`.

## Troubleshooting

**Missing Google API key:** Check that `.env` exists in the project root and contains `GOOGLE_API_KEY=...`.

**Missing Tavily API key:** Add `TAVILY_API_KEY=...` if the router selects `hybrid` or `open_book`.

**Module not found:** Activate your virtual environment and run `pip install -r requirements.txt`.

**No evidence shown:** The router may have selected `closed_book`, or no usable evidence was returned. Check the mode and routing details in the Plan tab.

## Security

- Never commit `.env` or publish API keys.
- Use environment variables or deployment secrets for hosted deployments.
- Verify generated content and sources before publication.

## Possible Future Improvements

- Live LangGraph streaming and progress updates.
- Regenerate individual sections.
- Export to HTML or PDF.
- Checkpoint and resume interrupted runs.
- User-configurable audience, tone, and blog length.
- Automated tests and deployment configuration.

## License

No license has been specified. Add a `LICENSE` file if you plan to distribute the project and want to define usage terms.
