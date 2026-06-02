import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


APP_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP_DIR))

from analytics_store import ImageAnalytics, connect, upsert_image_analytics


class AnalyticsStoreTest(unittest.TestCase):
    def test_schema_creation_and_upsert(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "analytics.sqlite"
            with connect(db_path) as conn:
                upsert_image_analytics(
                    conn,
                    ImageAnalytics(
                        source_path="/data/input/capture.jpg",
                        output_path="/data/output/capture_mask.png",
                        processed_at="2026-06-01T12:00:00+00:00",
                        foreground_pixels=100,
                        total_pixels=1000,
                        foreground_ratio=0.1,
                        mask_count=2,
                        source_mtime_ns=123,
                        source_size_bytes=456,
                    ),
                )
                upsert_image_analytics(
                    conn,
                    ImageAnalytics(
                        source_path="/data/input/capture.jpg",
                        output_path="/data/output/capture_mask_v2.png",
                        processed_at="2026-06-01T13:00:00+00:00",
                        foreground_pixels=200,
                        total_pixels=1000,
                        foreground_ratio=0.2,
                        mask_count=3,
                        source_mtime_ns=789,
                        source_size_bytes=456,
                    ),
                )
                rows = conn.execute("SELECT * FROM image_analytics").fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["foreground_pixels"], 200)
            self.assertEqual(rows[0]["output_path"], "/data/output/capture_mask_v2.png")


class DashboardLoaderTest(unittest.TestCase):
    def test_dashboard_load_analytics(self) -> None:
        if importlib.util.find_spec("streamlit") is None:
            self.skipTest("streamlit is not installed")
        if importlib.util.find_spec("pandas") is None:
            self.skipTest("pandas is not installed")
        if importlib.util.find_spec("plotly") is None:
            self.skipTest("plotly is not installed")

        import dashboard

        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "analytics.sqlite"
            with connect(db_path) as conn:
                upsert_image_analytics(
                    conn,
                    ImageAnalytics(
                        source_path="/data/input/capture.jpg",
                        output_path="/data/output/capture_mask.png",
                        processed_at="2026-06-01T12:00:00+00:00",
                        foreground_pixels=100,
                        total_pixels=1000,
                        foreground_ratio=0.1,
                        mask_count=2,
                        source_mtime_ns=123,
                        source_size_bytes=456,
                    ),
                )

            df = dashboard.load_analytics(str(db_path))

        self.assertEqual(len(df), 1)
        self.assertEqual(df.iloc[0]["filename"], "capture.jpg")
        self.assertAlmostEqual(df.iloc[0]["coverage_percent"], 10.0)


if __name__ == "__main__":
    unittest.main()
