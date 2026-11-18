import logging
import sqlite3

import pandas as pd
import plotly.express as px
import streamlit as st

from pipeline import SAMPLE_PATH, read_runs, run_pipeline

logger = logging.getLogger(__name__)

st.set_page_config(
    page_title="Data Pipeline Monitoring Dashboard",
    layout="wide",
)

st.html("""
<style>
.stApp { background: linear-gradient(135deg, #2a2a2a 0%, #3d3d3d 50%, #505050 100%); }
[data-testid="stHeader"] {
    background: #242424;
    border-bottom: 1px solid #080808;
}
.stApp main h1 {
    color: #fafafa;
    font-size: clamp(2.5rem, 5vw, 4.5rem);
    line-height: 1.1;
}
.stApp main h2 { color: #fafafa; font-size: 2rem; }
[data-testid="stCaptionContainer"] p {
    color: #d4d4d4;
    font-size: 1.125rem;
}
.stage-card, [data-testid="stMetric"] {
    background: #292929;
    border: 1px solid #080808;
    border-radius: 1rem;
    padding: 1.25rem;
}
.stage-card strong {
    display: block;
    color: #fafafa;
    font-size: 1.5rem;
}
.stage-card span { font-size: 1.25rem; }
.stage-card .succeeded { color: #86efac; }
.stage-card .failed { color: #fca5a5; }
.stage-card .skipped { color: #d4d4d4; }
[data-testid="stMetricLabel"] p { color: #fafafa; font-size: 1.25rem; }
[data-testid="stMetricValue"] {
    color: #fafafa;
    font-size: clamp(2rem, 4vw, 3.25rem);
}
[data-testid="stPlotlyChart"] {
    border: 1px solid #080808;
    border-radius: 1rem;
    overflow: hidden;
}
</style>
""")

st.title("Data Pipeline Monitoring Dashboard")
st.caption("ETL operations | CSV to SQLite | Local run history")

st.header("Run the Pipeline")
st.caption("Upload a UTF-8 CSV with order_id, product, and amount, or try the sample.")
upload_col, sample_col = st.columns([2, 1])
with upload_col:
    upload = st.file_uploader("Upload an orders CSV", type="csv")
    run_upload = st.button("Run uploaded CSV", type="primary", disabled=upload is None)
with sample_col:
    run_sample = st.button("Run sample orders")

try:
    if run_sample:
        st.session_state["selected_run"] = run_pipeline(SAMPLE_PATH.read_bytes(), "Sample")
    elif run_upload and upload is not None:
        st.session_state["selected_run"] = run_pipeline(upload.getvalue(), "Upload")
    runs = read_runs()
except sqlite3.Error:
    logger.exception("Could not access the local pipeline database")
    st.error("Could not access the local SQLite database. Check the Streamlit terminal for details.")
    st.stop()
except OSError:
    logger.exception("Could not read the sample orders file")
    st.error("Could not read the sample orders CSV. Check that it is next to the app.")
    st.stop()

if not runs:
    st.info("No pipeline runs yet. Run the sample or upload a CSV to get started.")
    st.stop()

runs_by_id = {run["id"]: run for run in runs}
if st.session_state.get("selected_run") not in runs_by_id:
    st.session_state["selected_run"] = runs[0]["id"]
selected_id = st.selectbox(
    "Inspect a run",
    list(runs_by_id),
    format_func=lambda run_id: f"Run {run_id} - {runs_by_id[run_id]['source']}",
    key="selected_run",
)
selected = runs_by_id[selected_id]

st.header("Pipeline Status")
for column, stage in zip(st.columns(3), ("Extract", "Transform", "Load")):
    status = selected[f"{stage.lower()}_status"]
    with column:
        st.html(
            f'<div class="stage-card"><strong>{stage}</strong>'
            f'<span class="{status.lower()}">{status}</span></div>'
        )

st.header("Run Summary")
processed, rejected, loaded = (selected[key] for key in ("processed", "rejected", "loaded"))
success_rate = (
    f"{loaded / processed:.2%}"
    if processed and loaded is not None and selected["load_status"] != "Failed"
    else "N/A"
)
volume, errors, rate = st.columns(3)
volume.metric("Records Processed", f"{processed:,}" if processed is not None else "N/A")
errors.metric("Rejected Records", f"{rejected:,}" if rejected is not None else "N/A")
rate.metric("Record Success Rate", success_rate, help="Records loaded divided by records processed.")
started = selected["started_at"].replace("T", " ").removesuffix("+00:00")
loaded_display = f"{loaded:,}" if loaded is not None else "N/A"
st.caption(f"{started} UTC | Records loaded: {loaded_display} | Duration: {selected['duration_ms']:,.1f} ms")
if "Failed" in (selected["extract_status"], selected["load_status"]):
    st.error(selected["detail"])
elif rejected:
    st.warning(selected["detail"])
else:
    st.success(selected["detail"])

st.header("Recent Run History")
st.caption("Up to 50 runs. Runs that failed during extraction have no record counts.")
history = pd.DataFrame.from_records(
    [{
        "Run": f"Run {run['id']}",
        "Source": run["source"],
        "Started (UTC)": run["started_at"],
        "Extract": run["extract_status"],
        "Transform": run["transform_status"],
        "Load": run["load_status"],
        "Records Processed": run["processed"],
        "Rejected Records": run["rejected"],
        "Records Loaded": run["loaded"],
        "Duration (ms)": run["duration_ms"],
    } for run in runs]
)
for field in ("Records Processed", "Rejected Records", "Records Loaded"):
    history[field] = history[field].astype("Int64")
chart_data = history.dropna(subset=["Rejected Records"]).iloc[::-1]
if not chart_data.empty:
    fig = px.bar(
        chart_data,
        x="Run",
        y="Rejected Records",
        text="Rejected Records",
        hover_data=["Records Processed", "Records Loaded"],
        color_discrete_sequence=["#4ade80"],
        template="plotly_dark",
    )
    fig.update_traces(textposition="outside", cliponaxis=False)
    fig.update_layout(
        paper_bgcolor="#292929",
        plot_bgcolor="#303030",
        font=dict(size=17, color="#fafafa"),
        yaxis=dict(rangemode="tozero", tickformat="d", gridcolor="#505050"),
        margin=dict(l=20, r=20, t=35, b=20),
        height=350,
    )
    st.plotly_chart(fig, theme=None, width="stretch")
st.dataframe(history, hide_index=True, width="stretch")