import pandas as pd
import plotly.express as px
import streamlit as st
from databricks.sdk import WorkspaceClient

GENIE_SPACE_ID = "01f118a5dc961552bb5fc970d430a5c2"

STARTER_QUESTIONS = [
    "What is the distribution of status values in production_snapshots?",
    "What are the different mirror types and their counts?",
    "Show me the top 10 tables by row count",
    "What is the trend of snapshots over time?",
    "How many records have a 'high' status in the last 7 days?",
    "What are the most recent production snapshots?",
]

FOLLOWUP_QUESTIONS = [
    "Can you break this down by date?",
    "Show me the same data as a table",
    "What are the outliers in this result?",
    "Compare this to the previous period",
    "Filter this to only show 'optimal' status",
    "What is the percentage distribution?",
]

st.set_page_config(page_title="Genie Chat", page_icon="🧞", layout="wide")
st.title("Genie Chat")
st.caption("Ask questions about your data using natural language.")


@st.cache_resource
def get_client():
    return WorkspaceClient()


def fetch_genie_response(question: str) -> dict:
    """Returns dict with: texts (list[str]), sql (str|None), df (DataFrame|None)"""
    w = get_client()
    result = w.genie.start_conversation_and_wait(
        space_id=GENIE_SPACE_ID,
        content=question,
    )
    conversation_id = result.conversation_id
    message_id = result.id

    texts, sql, df, debug_lines = [], None, None, []

    full_msg = w.genie.get_message(
        space_id=GENIE_SPACE_ID,
        conversation_id=conversation_id,
        message_id=message_id,
    )

    if hasattr(full_msg, "attachments") and full_msg.attachments:
        for att in full_msg.attachments:
            if hasattr(att, "text") and att.text:
                content = getattr(att.text, "content", None) or str(att.text)
                if content:
                    texts.append(content)

            if hasattr(att, "query") and att.query:
                q = att.query
                if getattr(q, "description", None):
                    texts.append(q.description)
                if getattr(q, "query", None):
                    sql = q.query

                try:
                    attachment_id = getattr(att, "attachment_id", None) or getattr(att, "id", None)
                    if attachment_id:
                        qr = w.genie.get_message_attachment_query_result(
                            space_id=GENIE_SPACE_ID,
                            conversation_id=conversation_id,
                            message_id=message_id,
                            attachment_id=attachment_id,
                        )
                    else:
                        qr = w.genie.get_message_query_result(
                            space_id=GENIE_SPACE_ID,
                            conversation_id=conversation_id,
                            message_id=message_id,
                        )
                    sr = getattr(qr, "statement_response", None)
                    if sr:
                        manifest = getattr(sr, "manifest", None)
                        schema_cols = getattr(getattr(manifest, "schema", None), "columns", []) or []

                        # data_array is None when results are chunked — fetch each chunk explicitly
                        all_rows = []
                        chunks = getattr(manifest, "chunks", []) or []
                        statement_id = getattr(sr, "statement_id", None)
                        if statement_id and chunks:
                            for chunk in chunks:
                                chunk_idx = getattr(chunk, "chunk_index", 0)
                                chunk_data = w.statement_execution.get_statement_result_chunk_n(
                                    statement_id=statement_id,
                                    chunk_index=chunk_idx,
                                )
                                rows = getattr(chunk_data, "data_array", []) or []
                                all_rows.extend(rows)
                        else:
                            # fallback: try inline data_array
                            result_obj = getattr(sr, "result", None)
                            all_rows = getattr(result_obj, "data_array", []) or []

                        if schema_cols and all_rows:
                            col_names = [getattr(c, "name", str(c)) for c in schema_cols]
                            col_types = [str(getattr(c, "type_text", "STRING")).upper() for c in schema_cols]
                            df = pd.DataFrame(all_rows, columns=col_names)
                            for col, typ in zip(col_names, col_types):
                                if any(t in typ for t in ["INT", "FLOAT", "DOUBLE", "DECIMAL", "LONG", "BIGINT", "NUMERIC"]):
                                    df[col] = pd.to_numeric(df[col], errors="coerce")
                except Exception as ex:
                    debug_lines.append(f"DEBUG fetch error: {ex}")
                    debug_lines.append(f"DEBUG att attrs: {[a for a in dir(att) if not a.startswith('_')]}")
                    debug_lines.append(f"DEBUG att.query attrs: {[a for a in dir(att.query) if not a.startswith('_')]}")

    return {"texts": texts, "sql": sql, "df": df, "debug": debug_lines}


def detect_chart_type(df: pd.DataFrame) -> str:
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    other_cols = [c for c in df.columns if c not in numeric_cols]

    if len(df.columns) < 2:
        return "table"
    if any(kw in c.lower() for c in other_cols for kw in ["date", "time", "month", "year", "week", "day"]):
        return "line"
    if other_cols and numeric_cols:
        return "bar"
    if len(numeric_cols) >= 2:
        return "scatter"
    return "table"


CHART_TYPES = ["bar", "line", "scatter", "pie", "area", "table"]
PALETTES = ["Bold", "Vivid", "Safe", "Plotly", "D3", "Pastel"]


def render_chart(df: pd.DataFrame, idx: int):
    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    all_cols = df.columns.tolist()
    other_cols = [c for c in all_cols if c not in numeric_cols]

    default_chart = detect_chart_type(df)
    default_x = other_cols[0] if other_cols else all_cols[0]
    default_y = numeric_cols[0] if numeric_cols else (all_cols[1] if len(all_cols) > 1 else all_cols[0])

    with st.expander("Chart controls", expanded=True):
        c1, c2, c3, c4, c5, c6 = st.columns(6)

        chart_type = c1.selectbox(
            "Type", CHART_TYPES,
            index=CHART_TYPES.index(default_chart) if default_chart in CHART_TYPES else 0,
            key=f"chart_type_{idx}",
        )
        x_col = c2.selectbox("X axis", all_cols, index=all_cols.index(default_x), key=f"x_{idx}")
        y_col = c3.selectbox("Y axis", all_cols, index=all_cols.index(default_y), key=f"y_{idx}")
        color_opt = c4.selectbox("Color by", ["None"] + all_cols, key=f"color_{idx}")
        color_col = None if color_opt == "None" else color_opt
        palette = c5.selectbox("Palette", PALETTES, key=f"palette_{idx}")
        colors = getattr(px.colors.qualitative, palette)

        sort_by = None
        if chart_type in ("bar", "line"):
            sort_by = c6.selectbox(
                "Sort", ["value ↓", "value ↑", "label ↓", "label ↑", "none"],
                key=f"sort_{idx}",
            )

    if chart_type == "table":
        st.dataframe(df, use_container_width=True)
        return

    # Apply sort
    plot_df = df.copy()
    if sort_by and sort_by != "none":
        asc = "↑" in sort_by
        by = x_col if "label" in sort_by else y_col
        plot_df = plot_df.sort_values(by=by, ascending=asc)

    try:
        if chart_type == "bar":
            fig = px.bar(plot_df, x=x_col, y=y_col, color=color_col, color_discrete_sequence=colors)
        elif chart_type == "line":
            fig = px.line(plot_df, x=x_col, y=y_col, color=color_col, markers=True,
                          color_discrete_sequence=colors)
        elif chart_type == "scatter":
            fig = px.scatter(plot_df, x=x_col, y=y_col, color=color_col,
                             color_discrete_sequence=colors)
        elif chart_type == "pie":
            fig = px.pie(plot_df, names=x_col, values=y_col, color=color_col,
                         color_discrete_sequence=colors)
        elif chart_type == "area":
            fig = px.area(plot_df, x=x_col, y=y_col, color=color_col,
                          color_discrete_sequence=colors)

        fig.update_layout(
            plot_bgcolor="white",
            paper_bgcolor="white",
            font=dict(family="Inter, sans-serif", size=13),
            margin=dict(t=30, b=40, l=40, r=20),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        fig.update_xaxes(showgrid=False)
        fig.update_yaxes(gridcolor="#f0f0f0")

        st.plotly_chart(fig, use_container_width=True)

        with st.expander(f"Result table ({len(plot_df)} rows)"):
            st.dataframe(plot_df, use_container_width=True)

    except Exception as e:
        st.warning(f"Could not render chart: {e}")
        st.dataframe(df, use_container_width=True)


def render_assistant_message(msg: dict, idx: int):
    with st.chat_message("assistant"):
        data = msg.get("data")
        if not data:
            st.markdown(msg["content"])
            return
        for text in data.get("texts", []):
            st.markdown(text)
        if data.get("sql"):
            with st.expander("View SQL"):
                st.code(data["sql"], language="sql")
        df = data.get("df")
        if df is not None and not df.empty:
            render_chart(df, idx)


# ── Session state ──────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []
if "pending_question" not in st.session_state:
    st.session_state.pending_question = None

# ── Empty state: starter questions ────────────────────────────────────────────
if not st.session_state.messages:
    st.markdown("##### Suggested questions")
    cols = st.columns(3)
    for i, q in enumerate(STARTER_QUESTIONS):
        if cols[i % 3].button(q, key=f"starter_{i}", use_container_width=True):
            st.session_state.pending_question = q
            st.rerun()

# ── Render history ─────────────────────────────────────────────────────────────
for i, msg in enumerate(st.session_state.messages):
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        render_assistant_message(msg, i)
        # Follow-up chips after each assistant message (only for the last one)
        if i == len(st.session_state.messages) - 1:
            st.markdown("**Suggested follow-ups:**")
            chip_cols = st.columns(3)
            for j, fq in enumerate(FOLLOWUP_QUESTIONS[:3]):
                if chip_cols[j].button(fq, key=f"followup_{i}_{j}", use_container_width=True):
                    st.session_state.pending_question = fq
                    st.rerun()

# ── Chat input ─────────────────────────────────────────────────────────────────
# Consume any pending question from a suggestion click
typed_prompt = st.chat_input("Ask a question about your data...")
if st.session_state.pending_question:
    prompt = st.session_state.pending_question
    st.session_state.pending_question = None
elif typed_prompt:
    prompt = typed_prompt
else:
    prompt = None

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                data = fetch_genie_response(prompt)

                for text in data.get("texts", []):
                    st.markdown(text)
                if data.get("sql"):
                    with st.expander("View SQL"):
                        st.code(data["sql"], language="sql")
                df = data.get("df")
                idx = len(st.session_state.messages)
                if df is not None and not df.empty:
                    render_chart(df, idx)

                st.session_state.messages.append({
                    "role": "assistant",
                    "content": " ".join(data.get("texts", [])),
                    "data": data,
                })
            except Exception as e:
                error_msg = f"Error: {str(e)}"
                st.error(error_msg)
                st.session_state.messages.append({"role": "assistant", "content": error_msg})
