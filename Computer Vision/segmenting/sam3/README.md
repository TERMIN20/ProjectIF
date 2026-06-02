# SAM3 Raspberry Pi Share Pipeline

## Quick Start
If you are setting this up on the laptop(which i already set up), use this section first. The rest of this README is for brand new setup and reference details.

1. Fill In HF_TOKEN value by requesting access to sam3: https://huggingface.co/facebook/sam3 and then createing and copying the access token
2. Set the Pi SMB mount values in `.env`:
   - `PI_SHARE_HOST`
   - `PI_SHARE_USER`
   - `PI_SHARE_PASSWORD`
   - `PI_SHARE_VERS`
3. Set `MASK_OUTPUT_DIR_HOST` and `STATE_DIR_HOST` to local folders on the laptop.
4. Request access to the gated Meta SAM3 model repo on Hugging Face, then create a read token at `https://huggingface.co/settings/tokens` and set `HF_TOKEN` in `.env`.
5. From this directory run:
   ```bash
   docker compose up --build
   ```

The dashboard runs in the `sam3-dashboard` container and is exposed on port `8501` by default.

Open the dashboard at:
```text
http://localhost:8501
```

## What it does
- Mounts a Raspberry Pi SMB/CIFS share through Docker Compose.
- Watches the mounted input folder recursively for new or modified images.
- Waits for a newly discovered file to remain unchanged before processing it.
- Runs SAM3 text-prompt segmentation with prompt `"plant"` (configurable).
- Writes masked images where plant pixels keep original color and all other pixels are black.
- Runs a second script to count non-black pixels and logs the count.
- Persists per-image analytics to SQLite.
- Serves an interactive Streamlit dashboard with Plotly growth charts and image review.

## Files
- `multiSegment.py`: watcher + segmentation pipeline
- `analytics_store.py`: SQLite schema + analytics persistence helpers
- `dashboard.py`: Streamlit analytics dashboard
- `pixel_count.py`: standalone masked-image pixel counter
- `entrypoint.sh`: startup validation for mounted input/output paths
- `Dockerfile`: container image
- `docker-compose.yml`: single-service deployment with a Docker-managed Pi share mount
- `.env.example`: environment template

## Raspberry Pi setup
Run the Pi setup script once on the Raspberry Pi:
```bash
bash "Computer Vision/pi/setup_pi_capture_share.sh"
```

That script installs Samba, creates `/pic_shared`, installs a recurring capture script, and enables the systemd timer that writes timestamped image batches into the shared folder. The Pi capture path is Debian-friendly and grabs a still image from the Astra's V4L2 device using `ffmpeg` or `fswebcam`.

Pipeline logs include lines like:
```text
pixel_count: image=/data/output/example_1234abcd_plant_mask.png plant_pixels=12345
```

The dashboard includes KPI cards for current plant size and growth, interactive plant-pixel, growth-rate, and coverage-ratio charts, date/search filters, a processed image table, and side-by-side source/masked image review. Analytics are stored in `${STATE_DIR_HOST}/analytics.sqlite`.

The dashboard also includes a typed-confirm data management action. Typing `DELETE` enables deletion of analytics and masked output images. Original Raspberry Pi source captures are preserved and marked as already seen so the worker does not immediately reprocess old photos from the share.

## Raspberry Pi operations
Use these commands on the Raspberry Pi when you need to inspect or trigger the capture service:

- Check the timer status:
  ```bash
  systemctl status projectif-capture.timer
  ```
- Trigger an immediate capture:
  ```bash
  sudo systemctl start projectif-capture.service
  ```
- Check whether the USB camera is connected:
  ```bash
  v4l2-ctl --list-devices
  ```

You should see an `Orbbec` device in the output. If it is missing, replug the camera and run the command again.

## Environment variables
- `PI_SHARE_HOST`, `PI_SHARE_NAME`, `PI_SHARE_USER`, `PI_SHARE_PASSWORD`, `PI_SHARE_VERS`: Docker SMB/CIFS mount settings
- `MASK_OUTPUT_DIR_HOST`, `STATE_DIR_HOST`: local folders for masked outputs and pipeline state
- `HF_TOKEN`: Hugging Face read token for the gated SAM3 checkpoint repo
- `CHECK_INTERVAL_SECONDS`: polling interval for scanning the mounted share
- `FILE_STABLE_SECONDS`: how long a new file must remain unchanged before processing
- `PROMPT_TEXT`, `LOG_LEVEL`, `IMAGE_EXTENSIONS`, `DEVICE`: SAM3 pipeline options
- `MODEL_PRECISION`: `auto` by default. Uses CUDA `float16` autocast when available and CPU `float32`; set `float32`, `float16`, or `bfloat16` to override.
- `STATE_GC_INTERVAL_SECONDS`: how often retention cleanup runs, in seconds
- `RETENTION_DAYS`: delete analytics and masked outputs older than this many days; `0` disables cleanup
- `STATUS_FILE`: JSON heartbeat/status path shared by the pipeline and dashboard
- `DASHBOARD_PORT`: host port for the Streamlit dashboard, defaults to `8501`.

## Local run (optional)
Set env vars (`INPUT_DIR`, `MASK_OUTPUT_DIR`, `STATE_FILE`) and run:
```bash
python multiSegment.py
```

## Fallback if CIFS mounts are unavailable from Docker
The primary deployment is a Docker-managed SMB/CIFS volume. If the local Docker environment cannot mount the Pi share directly, mount the share on the host first and bind-mount that host path to `/data/input` as a local override.
