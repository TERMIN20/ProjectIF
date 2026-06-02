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
    @staticmethod
    def require_dashboard_deps() -> None:
        if importlib.util.find_spec("streamlit") is None:
            raise unittest.SkipTest("streamlit is not installed")
        if importlib.util.find_spec("pandas") is None:
            raise unittest.SkipTest("pandas is not installed")
        if importlib.util.find_spec("plotly") is None:
            raise unittest.SkipTest("plotly is not installed")

    def test_dashboard_load_analytics(self) -> None:
        self.require_dashboard_deps()

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

    def test_growth_metrics_increasing_and_decreasing(self) -> None:
        self.require_dashboard_deps()

        import pandas as pd
        import dashboard

        df = pd.DataFrame(
            {
                "processed_at": pd.to_datetime(
                    [
                        "2026-06-01T00:00:00+00:00",
                        "2026-06-02T00:00:00+00:00",
                        "2026-06-04T00:00:00+00:00",
                    ],
                    utc=True,
                ),
                "foreground_pixels": [100, 160, 130],
            }
        )

        result = dashboard.add_growth_metrics(df).sort_values("processed_at")

        self.assertTrue(pd.isna(result.iloc[0]["plant_pixels_delta"]))
        self.assertEqual(result.iloc[1]["plant_pixels_delta"], 60)
        self.assertEqual(result.iloc[1]["growth_pixels_per_day"], 60)
        self.assertAlmostEqual(result.iloc[1]["growth_percent"], 60)
        self.assertEqual(result.iloc[2]["plant_pixels_delta"], -30)
        self.assertEqual(result.iloc[2]["growth_pixels_per_day"], -15)
        self.assertAlmostEqual(result.iloc[2]["growth_percent"], -18.75)

    def test_growth_metrics_single_zero_interval_and_zero_baseline(self) -> None:
        self.require_dashboard_deps()

        import pandas as pd
        import dashboard

        single = pd.DataFrame(
            {
                "processed_at": pd.to_datetime(["2026-06-01T00:00:00+00:00"], utc=True),
                "foreground_pixels": [100],
            }
        )
        single_result = dashboard.add_growth_metrics(single)
        self.assertTrue(pd.isna(single_result.iloc[0]["growth_pixels_per_day"]))

        zero_interval = pd.DataFrame(
            {
                "processed_at": pd.to_datetime(
                    ["2026-06-01T00:00:00+00:00", "2026-06-01T00:00:00+00:00"],
                    utc=True,
                ),
                "foreground_pixels": [100, 125],
            }
        )
        zero_interval_result = dashboard.add_growth_metrics(zero_interval).sort_values(
            "foreground_pixels"
        )
        self.assertEqual(zero_interval_result.iloc[1]["plant_pixels_delta"], 25)
        self.assertTrue(pd.isna(zero_interval_result.iloc[1]["growth_pixels_per_day"]))

        zero_baseline = pd.DataFrame(
            {
                "processed_at": pd.to_datetime(
                    ["2026-06-01T00:00:00+00:00", "2026-06-02T00:00:00+00:00"],
                    utc=True,
                ),
                "foreground_pixels": [0, 50],
            }
        )
        zero_baseline_result = dashboard.add_growth_metrics(zero_baseline).sort_values(
            "processed_at"
        )
        self.assertTrue(pd.isna(zero_baseline_result.iloc[1]["growth_percent"]))
        delta, percent = dashboard.growth_since_start(zero_baseline_result)
        self.assertEqual(delta, 50)
        self.assertIsNone(percent)

    def test_delete_helper_preserves_source_paths(self) -> None:
        self.require_dashboard_deps()

        import dashboard

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / "state"
            output_dir = root / "masked"
            input_dir = root / "input"
            state_dir.mkdir()
            output_dir.mkdir()
            input_dir.mkdir()

            db_path = state_dir / "analytics.sqlite"
            state_file = state_dir / "processed_state.json"
            source_file = input_dir / "capture.jpg"
            masked_file = output_dir / "capture_mask.png"
            unrelated_file = root / "keep.txt"

            for path in [
                db_path,
                Path(str(db_path) + "-wal"),
                Path(str(db_path) + "-shm"),
                state_file,
                state_file.with_suffix(state_file.suffix + ".tmp"),
                source_file,
                masked_file,
                unrelated_file,
            ]:
                path.write_text("x", encoding="utf-8")

            deleted = dashboard.delete_analytics_and_masked_outputs(
                db_path=db_path,
                state_file=state_file,
                mask_output_dir=output_dir,
            )

            self.assertGreaterEqual(len(deleted), 5)
            self.assertFalse(db_path.exists())
            self.assertFalse(state_file.exists())
            self.assertFalse(masked_file.exists())
            self.assertTrue(source_file.exists())
            self.assertTrue(unrelated_file.exists())


if __name__ == "__main__":
    unittest.main()
