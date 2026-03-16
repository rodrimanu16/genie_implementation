# Genie Chat

A Databricks App that wraps a [Genie Space](https://docs.databricks.com/en/genie/index.html) as a conversational chat interface with interactive charts.

![Genie Chat](https://img.shields.io/badge/Databricks-App-FF3621?logo=databricks&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.37+-FF4B4B?logo=streamlit&logoColor=white)

## Features

- **Natural language queries** — ask questions in plain English, Genie translates them to SQL
- **Interactive charts** — results are automatically visualized with Plotly (bar, line, scatter, pie, area)
- **Live chart controls** — change chart type, axes, color grouping, palette, and sort order without re-querying
- **View SQL** — see the query Genie generated for every answer
- **Suggested questions** — starter questions on the empty state, follow-up chips after each response

## Demo

Ask a question like *"What is the distribution of status values in production_snapshots?"* and get back:

- A natural language explanation
- The SQL Genie generated
- An interactive chart you can customize in real time
- A collapsible result table

## Stack

| Layer | Technology |
|---|---|
| UI | [Streamlit](https://streamlit.io) |
| Charts | [Plotly Express](https://plotly.com/python/plotly-express/) |
| Data | [pandas](https://pandas.pydata.org) |
| Databricks SDK | [databricks-sdk](https://github.com/databricks/databricks-sdk-py) |
| Hosting | [Databricks Apps](https://docs.databricks.com/en/dev-tools/databricks-apps/index.html) |

## Project Structure

```
genie-chat/
├── app.py            # Entire application
├── app.yaml          # Databricks App config
├── requirements.txt  # Python dependencies
├── ARCHITECTURE.md   # Detailed architecture documentation
└── README.md
```

## Quick Start

### Prerequisites

- Databricks CLI (`databricks` v0.229+) authenticated against your workspace
- A Genie Space already created in your workspace
- A Databricks App created with the Genie space attached as a resource

### 1. Configure the Genie Space ID

Edit `app.py` and set your Genie Space ID:

```python
GENIE_SPACE_ID = "your-genie-space-id-here"
```

### 2. Customize suggested questions

Also in `app.py`, update the starter and follow-up questions to match your dataset:

```python
STARTER_QUESTIONS = [
    "What is the distribution of status values?",
    ...
]

FOLLOWUP_QUESTIONS = [
    "Can you break this down by date?",
    ...
]
```

### 3. Deploy to Databricks

```bash
# Create the app (first time only)
databricks apps create genie-chat --description "Genie Chat App"

# Upload files
databricks workspace import-dir . /Workspace/Users/<you>/genie-chat

# Deploy
databricks apps deploy genie-chat \
  --source-code-path /Workspace/Users/<you>/genie-chat
```

### 4. Attach the Genie Space resource

In the Databricks UI go to **Compute → Apps → genie-chat → Edit**, add a **Genie** resource pointing to your space with `CAN_RUN` permission, then redeploy.

### Local Development

```bash
pip install -r requirements.txt
export DATABRICKS_PROFILE=your-profile
streamlit run app.py
```

## How It Works

See [ARCHITECTURE.md](ARCHITECTURE.md) for a full breakdown of the API call flow, chart rendering pipeline, and session state design.

The short version:

1. User submits a question
2. `w.genie.start_conversation_and_wait()` sends it to Genie and blocks until done
3. `w.genie.get_message()` returns attachments: a text explanation + a SQL query attachment
4. `w.statement_execution.get_statement_result_chunk_n()` fetches the actual row data (chunked)
5. Rows are loaded into a pandas DataFrame, column types are coerced
6. `detect_chart_type()` picks the best Plotly chart based on column types
7. Live Streamlit widgets let the user modify the chart without re-querying

## License

MIT
