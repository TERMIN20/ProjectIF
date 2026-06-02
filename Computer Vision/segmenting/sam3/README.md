# SAM3 Raspberry Pi Share Pipeline

## What it does
- Mounts a Raspberry Pi SMB/CIFS share through Docker Compose.
- Watches the mounted input folder recursively for new or modified images.
- Waits for a newly discovered file to remain unchanged before processing it.
- Runs SAM3 text-prompt segmentation with prompt `"plant"` (configurable).
- Writes masked images where plant pixels keep original color and all other pixels are black.
- Runs a second script to count non-black pixels and logs the count.

## Files
- `multiSegment.py`: watcher + segmentation pipeline
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

## Run on the computer with Docker Compose
1. Copy `.env.example` to `.env`.
2. Set `PI_SHARE_HOST`, `PI_SHARE_USER`, and `PI_SHARE_PASSWORD` for the Raspberry Pi.
3. Request access to the gated Meta SAM3 model repo on Hugging Face, create a read token at `https://huggingface.co/settings/tokens`, and set `HF_TOKEN` in `.env`.
4. From this directory:
   ```bash
   docker compose up --build
   ```

Pipeline logs include lines like:
```text
pixel_count: image=/data/output/example_1234abcd_plant_mask.png plant_pixels=12345
```

## Environment variables
- `PI_SHARE_HOST`, `PI_SHARE_NAME`, `PI_SHARE_USER`, `PI_SHARE_PASSWORD`, `PI_SHARE_VERS`: Docker SMB/CIFS mount settings
- `MASK_OUTPUT_DIR_HOST`, `STATE_DIR_HOST`: local folders for masked outputs and pipeline state
- `HF_TOKEN`: Hugging Face read token for the gated SAM3 checkpoint repo
- `CHECK_INTERVAL_SECONDS`: polling interval for scanning the mounted share
- `FILE_STABLE_SECONDS`: how long a new file must remain unchanged before processing
- `PROMPT_TEXT`, `LOG_LEVEL`, `IMAGE_EXTENSIONS`, `DEVICE`: SAM3 pipeline options
- `MODEL_PRECISION`: `auto` by default. Uses CUDA `float16` autocast when available and CPU `float32`; set `float32`, `float16`, or `bfloat16` to override.

## Local run (optional)
Set env vars (`INPUT_DIR`, `MASK_OUTPUT_DIR`, `STATE_FILE`) and run:
```bash
python multiSegment.py
```

## Fallback if CIFS mounts are unavailable from Docker
The primary deployment is a Docker-managed SMB/CIFS volume. If the local Docker environment cannot mount the Pi share directly, mount the share on the host first and bind-mount that host path to `/data/input` as a local override.
