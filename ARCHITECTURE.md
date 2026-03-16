# Genie Chat — Architecture

## Overview

A single-file Streamlit app (`app.py`) that wraps a Databricks Genie Space as a conversational chat interface with interactive charts. It uses the Databricks Python SDK for all API calls and Plotly for visualization.

```
User types question
       │
       ▼
 Databricks Genie API  ──► Natural language → SQL (done by Genie)
       │
       ▼
 Statement Execution API  ──► Fetch chunked row data
       │
       ▼
 pandas DataFrame  ──► Auto-detect chart type  ──► Plotly figure
       │
       ▼
 Streamlit UI (chat + chart + controls)
```

---

## Files

```
genie-chat/
├── app.py            # Entire application (single file)
├── app.yaml          # Databricks App config (Streamlit on port 8000)
└── requirements.txt  # databricks-sdk, streamlit, plotly, pandas
```

### `app.yaml`
Tells the Databricks Apps runtime to launch Streamlit and bind it to port 8000. The Genie space resource is attached here with `CAN_RUN` permission so the app's service principal is authorized to call the Genie API.

---

## Authentication

The app uses `WorkspaceClient()` from the Databricks SDK with no arguments. The SDK auto-detects credentials:

| Environment | Credential source |
|---|---|
| Deployed as Databricks App | Auto-injected service principal token via environment variables |
| Local development | `~/.databrickscfg` profile (set `DATABRICKS_PROFILE` env var) |

The client is created once and cached with `@st.cache_resource` so it is reused across all Streamlit reruns.

---

## API Call Flow

### Step 1 — Start a Genie conversation

```python
result = w.genie.start_conversation_and_wait(
    space_id=GENIE_SPACE_ID,
    content=question,
)
```

This is a **blocking** call. Under the hood it polls until Genie has finished generating the response. Returns a `GenieMessage` with:
- `result.conversation_id` — ID of the new conversation thread
- `result.id` — ID of the message within that conversation

> **Note:** The field is `.id`, not `.message_id`. This was a key discovery during development.

### Step 2 — Fetch the full message

```python
full_msg = w.genie.get_message(
    space_id=GENIE_SPACE_ID,
    conversation_id=conversation_id,
    message_id=message_id,
)
```

Returns a `GenieMessage` with an `attachments` list. Each attachment is one of:

| Attachment type | Content |
|---|---|
| `att.text` | Natural language answer (`att.text.content`) |
| `att.query` | SQL query (`att.query.query`) + description (`att.query.description`) |

A single response typically has **two attachments**: one text (the explanation) and one query (the SQL + data).

### Step 3 — Fetch query results

The query attachment has an `attachment_id`. We call:

```python
qr = w.genie.get_message_attachment_query_result(
    space_id=GENIE_SPACE_ID,
    conversation_id=conversation_id,
    message_id=message_id,
    attachment_id=attachment_id,
)
```

This returns a `GenieGetMessageQueryResultResponse` containing a `statement_response` of type `StatementResponse` — the same structure used by the Databricks Statement Execution API.

### Step 4 — Fetch chunked row data

**This is the critical non-obvious step.** The `statement_response.result.data_array` is always `None`. The actual rows are stored in chunks and must be fetched separately:

```python
manifest = sr.manifest           # ResultManifest
chunks   = manifest.chunks       # list of BaseChunkInfo
# Each chunk has: chunk_index, row_count, byte_count, row_offset

for chunk in chunks:
    chunk_data = w.statement_execution.get_statement_result_chunk_n(
        statement_id=sr.statement_id,
        chunk_index=chunk.chunk_index,
    )
    all_rows.extend(chunk_data.data_array)
```

Column schema comes from `manifest.schema.columns`, each with `.name` and `.type_text`.

### Step 5 — Build a DataFrame

```python
df = pd.DataFrame(all_rows, columns=col_names)
# Coerce numeric columns based on type_text (INT, FLOAT, DOUBLE, etc.)
for col, typ in zip(col_names, col_types):
    if any(t in typ for t in ["INT", "FLOAT", "DOUBLE", "DECIMAL", "LONG", "BIGINT", "NUMERIC"]):
        df[col] = pd.to_numeric(df[col], errors="coerce")
```

All values come back as strings from the API; the coercion step is necessary for charts to work.

---

## Chart Rendering

### Auto-detection (`detect_chart_type`)

Given a DataFrame, the function picks the most appropriate chart type by inspecting column types:

| Condition | Chart type |
|---|---|
| Only 1 column | `table` |
| Any non-numeric column name contains `date`, `time`, `month`, `year`, `week`, `day` | `line` |
| At least 1 categorical + 1 numeric column | `bar` |
| 2+ numeric columns | `scatter` |
| Fallback | `table` |

### Interactive controls (`render_chart`)

Each chart in the chat history gets its own set of Streamlit widgets, keyed by the message index (`idx`) so controls from different messages don't interfere:

| Control | Key | Effect |
|---|---|---|
| Type | `chart_type_{idx}` | Switches between bar / line / scatter / pie / area / table |
| X axis | `x_{idx}` | Any column as X |
| Y axis | `y_{idx}` | Any column as Y |
| Color by | `color_{idx}` | Groups/colors by a column |
| Palette | `palette_{idx}` | Plotly qualitative color scheme |
| Sort | `sort_{idx}` | value ↓↑ or label ↓↑ (bar and line only) |

Changing any control triggers a Streamlit rerun, which re-executes `render_chart` with the new widget values — the chart updates instantly without re-querying Genie.

### Plotly figures

All charts use `plotly.express` and are rendered with `st.plotly_chart(..., use_container_width=True)`. This gives built-in zoom, pan, hover tooltips, and PNG download for free.

---

## Suggested Questions

### Starter questions (empty state)
When `st.session_state.messages` is empty, a 3-column grid of buttons is shown. Clicking one sets `st.session_state.pending_question` and calls `st.rerun()`.

### Follow-up suggestions
After the last assistant message in the history, 3 follow-up chips are shown. Same mechanism: click → `pending_question` → rerun.

### Pending question consumption

At the bottom of the script, before `st.chat_input`:

```python
typed_prompt = st.chat_input("Ask a question about your data...")
if st.session_state.pending_question:
    prompt = st.session_state.pending_question
    st.session_state.pending_question = None
elif typed_prompt:
    prompt = typed_prompt
else:
    prompt = None
```

This merges the two input sources (button click vs typed) into a single `prompt` variable that drives the rest of the flow.

---

## Session State

| Key | Type | Purpose |
|---|---|---|
| `messages` | `list[dict]` | Full chat history. Each dict has `role`, `content`, and `data` (the raw API response including the DataFrame). |
| `pending_question` | `str \| None` | Question injected by a suggestion button click. Consumed once on the next rerun. |
| `chart_type_{idx}` | `str` | Streamlit widget state for chart type per message. |
| `x_{idx}`, `y_{idx}` | `str` | Axis column selections per message. |
| `color_{idx}` | `str` | Color-by column per message. |
| `palette_{idx}` | `str` | Color palette per message. |
| `sort_{idx}` | `str` | Sort order per message. |

The `data` dict stored in each message contains the original DataFrame, so charts can be re-rendered with live controls on every rerun without re-calling the Genie API.

---

## Deployment

```
databricks workspace import <path>/app.py --format RAW --overwrite
databricks apps deploy genie-chat --source-code-path <workspace-path>
```

The app runs at: `https://genie-chat-7474660582095786.aws.databricksapps.com`
