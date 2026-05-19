#!/bin/bash
set -euo pipefail

CAPTURE_ROOT="${CAPTURE_ROOT:-/pic_shared/captures}"
IMAGE_BASENAME="${IMAGE_BASENAME:-capture}"
CAPTURE_COMMAND="${CAPTURE_COMMAND:-auto}"
VIDEO_DEVICE="${VIDEO_DEVICE:-auto}"
VIDEO_SIZE="${VIDEO_SIZE:-1280x720}"
VIDEO_INPUT_FORMAT="${VIDEO_INPUT_FORMAT:-mjpeg}"
FFMPEG_EXTRA_ARGS="${FFMPEG_EXTRA_ARGS:-}"

mkdir -p "$CAPTURE_ROOT"

TIMESTAMP="$(date +"%Y%m%d_%H%M%S")"
TARGET_DIR="$CAPTURE_ROOT/$TIMESTAMP"
mkdir -p "$TARGET_DIR"
IMAGE_PATH="$TARGET_DIR/${IMAGE_BASENAME}_${TIMESTAMP}.jpg"

resolve_video_device() {
  if [ "$VIDEO_DEVICE" != "auto" ]; then
    printf '%s\n' "$VIDEO_DEVICE"
    return
  fi

  if command -v v4l2-ctl >/dev/null 2>&1; then
    local detected_device
    detected_device="$(
      v4l2-ctl --list-devices 2>/dev/null \
        | awk '
            /^[^[:space:]].*:$/ { in_device = ($0 ~ /[Oo]rbbec|[Aa]stra|[Uu][Vv][Cc]/) }
            in_device && /\/dev\/video[0-9]+/ { print $1; exit }
          '
    )"

    if [ -n "$detected_device" ]; then
      printf '%s\n' "$detected_device"
      return
    fi
  fi

  for dev in /dev/video*; do
    if [ -e "$dev" ]; then
      printf '%s\n' "$dev"
      return
    fi
  done

  return 1
}

capture_with_ffmpeg() {
  local device="$1"
  local input_format_args=()
  local extra_args=()

  if [ -n "$VIDEO_INPUT_FORMAT" ]; then
    input_format_args=(-input_format "$VIDEO_INPUT_FORMAT")
  fi

  if [ -n "$FFMPEG_EXTRA_ARGS" ]; then
    # shellcheck disable=SC2206
    extra_args=($FFMPEG_EXTRA_ARGS)
  fi

  ffmpeg -hide_banner -loglevel error -y \
    -f video4linux2 \
    "${input_format_args[@]}" \
    -video_size "$VIDEO_SIZE" \
    -i "$device" \
    "${extra_args[@]}" \
    -frames:v 1 \
    "$IMAGE_PATH"
}

capture_with_fswebcam() {
  local device="$1"
  fswebcam -q -d "$device" -r "$VIDEO_SIZE" --no-banner "$IMAGE_PATH"
}

capture_with_rpicam() {
  local capture_tool="$1"
  local width="${VIDEO_SIZE%x*}"
  local height="${VIDEO_SIZE#*x}"

  "$capture_tool" --nopreview --timeout 1000 --width "$width" --height "$height" -o "$IMAGE_PATH"
}

rpicam_has_camera() {
  local capture_tool="$1"
  "$capture_tool" --list-cameras 2>/dev/null | grep -Eq '^[0-9]+ :'
}

resolve_rpicam_tool() {
  if command -v rpicam-still >/dev/null 2>&1; then
    printf '%s\n' "rpicam-still"
    return
  fi

  if command -v libcamera-still >/dev/null 2>&1; then
    printf '%s\n' "libcamera-still"
    return
  fi

  return 1
}

case "$CAPTURE_COMMAND" in
  auto)
    if [ "$VIDEO_DEVICE" = "auto" ] && RPICAM_TOOL="$(resolve_rpicam_tool)" && rpicam_has_camera "$RPICAM_TOOL"; then
      echo "[$(date --iso-8601=seconds)] Capturing image to $IMAGE_PATH with $RPICAM_TOOL"
      capture_with_rpicam "$RPICAM_TOOL"
    else
      DEVICE_PATH="$(resolve_video_device)" || {
        echo "No camera found. Check cable/power, then inspect with 'rpicam-still --list-cameras' or 'v4l2-ctl --list-devices'." >&2
        exit 1
      }

      echo "[$(date --iso-8601=seconds)] Capturing image to $IMAGE_PATH from $DEVICE_PATH"
      if command -v ffmpeg >/dev/null 2>&1; then
        capture_with_ffmpeg "$DEVICE_PATH"
      elif command -v fswebcam >/dev/null 2>&1; then
        capture_with_fswebcam "$DEVICE_PATH"
      else
        echo "No supported capture tool found. Install rpicam-apps, ffmpeg, or fswebcam." >&2
        exit 1
      fi
    fi
    ;;
  ffmpeg)
    DEVICE_PATH="$(resolve_video_device)" || {
      echo "No V4L2 video device found. Check cable/power and inspect with 'v4l2-ctl --list-devices'." >&2
      exit 1
    }
    echo "[$(date --iso-8601=seconds)] Capturing image to $IMAGE_PATH from $DEVICE_PATH"
    capture_with_ffmpeg "$DEVICE_PATH"
    ;;
  fswebcam)
    DEVICE_PATH="$(resolve_video_device)" || {
      echo "No V4L2 video device found. Check cable/power and inspect with 'v4l2-ctl --list-devices'." >&2
      exit 1
    }
    echo "[$(date --iso-8601=seconds)] Capturing image to $IMAGE_PATH from $DEVICE_PATH"
    capture_with_fswebcam "$DEVICE_PATH"
    ;;
  rpicam|libcamera)
    RPICAM_TOOL="$(resolve_rpicam_tool)" || {
      echo "No Raspberry Pi camera capture tool found. Install rpicam-apps or libcamera-apps." >&2
      exit 1
    }
    echo "[$(date --iso-8601=seconds)] Capturing image to $IMAGE_PATH with $RPICAM_TOOL"
    capture_with_rpicam "$RPICAM_TOOL"
    ;;
  *)
    echo "Unsupported CAPTURE_COMMAND: $CAPTURE_COMMAND. Use auto, ffmpeg, fswebcam, rpicam, or libcamera." >&2
    exit 1
    ;;
esac

if [ ! -s "$IMAGE_PATH" ]; then
  echo "Capture command completed but no image was written: $IMAGE_PATH" >&2
  exit 1
fi

echo "[$(date --iso-8601=seconds)] Capture complete: $IMAGE_PATH"
