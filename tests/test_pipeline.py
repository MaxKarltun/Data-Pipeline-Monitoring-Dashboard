import sqlite3
import unittest
from contextlib import closing
from functools import partial
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

import pipeline


class PipelineTest(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.db_path = Path(directory.name) / "pipeline.sqlite3"

    def test_dashboard_runs_sample_and_upload_and_keeps_history(self):
        app_path = Path(pipeline.__file__).with_name("app.py")
        with (
            patch.object(pipeline, "run_pipeline", partial(pipeline.run_pipeline, db_path=self.db_path)),
            patch.object(pipeline, "read_runs", partial(pipeline.read_runs, db_path=self.db_path)),
        ):
            app = AppTest.from_file(str(app_path), default_timeout=20).run()
            self.assertFalse(app.exception)
            self.assertTrue(app.button[0].disabled)
            app.button[1].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([metric.value for metric in app.metric], ["8", "3", "62.50%"])

            app.get("file_uploader")[0].upload(
                "orders.csv", b"\xef\xbb\xbfamount,product,order_id\n7.25,  Pens ,NEW-1\n1.00,Bag,\n",
                "text/csv",
            ).run()
            self.assertFalse(app.button[0].disabled)
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([metric.value for metric in app.metric], ["2", "1", "50.00%"])
            self.assertEqual(app.dataframe[0].value["Source"].tolist(), ["Upload", "Sample"])
            self.assertEqual(len(app.get("plotly_chart")), 1)

            bad_csv = b"wrong,header\n1,2\n"
            app.get("file_uploader")[0].upload("wrong.csv", bad_csv, "text/csv").run()
            app.button[0].click().run()
            self.assertFalse(app.exception)
            self.assertEqual([metric.value for metric in app.metric], ["N/A", "N/A", "N/A"])
            self.assertEqual(len(app.error), 1)
            app.selectbox[0].set_value(1).run()
            self.assertEqual([metric.value for metric in app.metric], ["8", "3", "62.50%"])

        with closing(sqlite3.connect(self.db_path)) as connection:
            orders = connection.execute(
                "SELECT order_id, product, amount_cents FROM orders WHERE run_id = 2"
            ).fetchall()
            self.assertEqual(orders, [("NEW-1", "Pens", 725)])
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 6)
            statuses = connection.execute(
                "SELECT extract_status, transform_status, load_status FROM pipeline_runs WHERE id = 3"
            ).fetchone()
            self.assertEqual(statuses, ("Failed", "Skipped", "Skipped"))

    def test_all_invalid_rows_skip_load(self):
        pipeline.run_pipeline(b"order_id,product,amount\n,Notebook,12.50\n", "Upload", self.db_path)
        run = pipeline.read_runs(self.db_path)[0]
        self.assertEqual((run["processed"], run["rejected"], run["loaded"]), (1, 1, 0))
        self.assertEqual(run["load_status"], "Skipped")

    def test_load_error_rolls_back_orders_and_logs_failed_status(self):
        with closing(sqlite3.connect(self.db_path)) as connection:
            connection.executescript(pipeline.SCHEMA)
            connection.execute(
                """CREATE TRIGGER reject_second_order BEFORE INSERT ON orders
                   WHEN NEW.order_id = 'SECOND'
                   BEGIN SELECT RAISE(ABORT, 'test load failure'); END"""
            )
        content = b"order_id,product,amount\nFIRST,Pen,1.00\nSECOND,Pad,2.00\n"
        with self.assertLogs("pipeline", level="ERROR"):
            pipeline.run_pipeline(content, "Upload", self.db_path)

        runs = pipeline.read_runs(self.db_path)
        self.assertEqual(len(runs), 1)
        self.assertEqual((runs[0]["load_status"], runs[0]["loaded"]), ("Failed", 0))
        with closing(sqlite3.connect(self.db_path)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM orders").fetchone()[0], 0)
