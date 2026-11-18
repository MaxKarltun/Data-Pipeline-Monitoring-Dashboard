# Data Pipeline Monitoring Dashboard

A local ETL demo and monitoring dashboard built with Python, Streamlit, Pandas, Plotly, and SQLite. Run the bundled sample or upload an orders CSV. The dashboard reads real run results, not simulated metrics.

## Getting started

From the project directory in PowerShell:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Open the Local URL shown in your terminal. Select **Run sample orders** to see a run with **8 processed, 3 rejected, and 5 loaded**. To use your own data, select a CSV and click **Run uploaded CSV**.

## CSV format

Use a UTF-8 CSV up to 5 MB with exactly these columns (column order does not matter). See [sample_orders.csv](./sample_orders.csv) for a working example with both valid and invalid rows.

```csv
order_id,product,amount
ORD-2001,Notebook,12.50
ORD-2002,Desk Lamp,29.95
```

- **Extract:** Parse the CSV and validate its header. A malformed file fails extraction and skips the remaining stages.
- **Transform:** Trim whitespace. Reject rows with missing IDs or products, duplicate valid IDs in the same run (the first valid occurrence wins), an incorrect field count, or invalid amounts. Amounts must be nonnegative and have up to nine whole digits and two decimal places. They are stored as integer cents.
- **Load:** Write valid rows to the SQLite `orders` table. Rows are keyed by run and order ID, so a repeat run is a new snapshot. If all rows are rejected, Load is skipped.
- **Monitor:** Record each run's stage statuses, counts, elapsed time, and a short result message in `pipeline_runs`. The dashboard displays the latest 50 runs. Record success rate is loaded divided by processed; it is unavailable after a failed extraction or load.

SQLite creates `pipeline.sqlite3` next to the app on the first run. It persists across app restarts and is excluded from Git. Use only non-sensitive sample data if you share or deploy the app: this local demo does not isolate database records between users.

## Possible integrations

Airflow, Databricks, Snowflake, and Azure Data Factory are not required. A future adapter could read their run histories and map their stage statuses and logged row counts into the dashboard's monitoring format.

The dashboard now runs a real CSV-to-SQLite ETL pipeline. You can run the bundled sample or upload your own orders CSV. The dashboard uses an oversized title, large KPI cards, and a dark gray gradient with black trim and green chart bars.

Extract: Read a UTF-8 CSV with order_id, product, and amount.
Transform: Trim whitespace and reject rows with missing IDs, duplicate IDs, or invalid amounts.
Load: Save valid orders to a local SQLite database.
Monitor: Record each run’s stage statuses, record counts, and duration. Use Inspect a run to review previous runs and see why records were rejected.


run : .\.venv\Scripts\python.exe -m streamlit run app.py

 successful demo upload showed the other side: 6 processed, 0 rejected, and 6 loaded. That’s the practical value: you can verify the load before someone relies on the data for a report.

