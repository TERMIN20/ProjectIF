#!/usr/bin/env python3
import argparse
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

import numpy as np
import torch
from dotenv import load_dotenv
from PIL import Image
from sam3 import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor


@dataclass(frozen=True)
class Config:
    input_dir: Path
    mask_output_dir: Path
    state_file: Path
    check_interval_seconds: int
    file_stable_seconds: int
    prompt_text: str
    log_level: str
    image_extensions: set[str]
    device: str
    precision: str


def load_config() -> Config:
    load_dotenv()

    input_dir = os.getenv("INPUT_DIR")
    output_dir = os.getenv("MASK_OUTPUT_DIR")
    state_file = os.getenv("STATE_FILE")
    if not input_dir or not output_dir or not state_file:
        raise ValueError("INPUT_DIR, MASK_OUTPUT_DIR, and STATE_FILE must be set.")

    interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "3600"))
    file_stable_seconds = int(os.getenv("FILE_STABLE_SECONDS", "30"))
    prompt = os.getenv("PROMPT_TEXT", "plant")
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    raw_ext = os.getenv("IMAGE_EXTENSIONS", ".jpg,.jpeg,.png,.bmp,.tif,.tiff")
    extensions = {e.strip().lower() for e in raw_ext.split(",") if e.strip()}
    device = os.getenv("DEVICE", "auto").strip().lower()
    precision = os.getenv("MODEL_PRECISION", "auto").strip().lower()

    return Config(
        input_dir=Path(input_dir),
        mask_output_dir=Path(output_dir),
        state_file=Path(state_file),
        check_interval_seconds=interval,
        file_stable_seconds=file_stable_seconds,
        prompt_text=prompt,
        log_level=log_level,
        image_extensions=extensions,
        device=device,
        precision=precision,
    )


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s %(levelname)s %(message)s",
        force=True,
    )


def validate_runtime(config: Config) -> None:
    if not config.input_dir.exists() or not config.input_dir.is_dir():
        raise ValueError(f"INPUT_DIR does not exist or is not a directory: {config.input_dir}")

    config.mask_output_dir.mkdir(parents=True, exist_ok=True)
    config.state_file.parent.mkdir(parents=True, exist_ok=True)

    if config.device in {"gpu-required", "cuda-required"} and not torch.cuda.is_available():
        raise RuntimeError("DEVICE is gpu-required, but CUDA is not available.")

    if config.precision not in {"auto", "float32", "fp32", "float16", "fp16", "bfloat16", "bf16"}:
        raise ValueError(
            "MODEL_PRECISION must be one of: auto, float32, fp32, float16, fp16, bfloat16, bf16."
        )

    if torch.cuda.is_available():
        torch.backends.cuda.matmul.allow_tf32 = True
        torch.backends.cudnn.allow_tf32 = True


def resolve_device(requested: str) -> torch.device:
    if requested in {"gpu-required", "cuda-required", "cuda", "gpu"}:
        return torch.device("cuda")
    if requested == "cpu":
        return torch.device("cpu")
    if torch.cuda.is_available():
        return torch.device("cuda")
    return torch.device("cpu")


def resolve_dtype(precision: str, device: torch.device) -> torch.dtype:
    if precision == "auto":
        return torch.float16 if device.type == "cuda" else torch.float32
    if precision in {"float16", "fp16"}:
        return torch.float16
    if precision in {"bfloat16", "bf16"}:
        return torch.bfloat16
    return torch.float32


def inference_context(device: torch.device, dtype: torch.dtype):
    if device.type == "cuda" and dtype in {torch.float16, torch.bfloat16}:
        return torch.autocast(device_type="cuda", dtype=dtype)
    return nullcontext()


def load_state(state_file: Path) -> Dict[str, Dict[str, Any]]:
    if not state_file.exists():
        return {}
    try:
        with state_file.open("r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        logging.warning("State file unreadable; starting fresh. file=%s error=%s", state_file, exc)
        return {}

    if not isinstance(data, dict):
        logging.warning("State file format invalid; starting fresh. file=%s", state_file)
        return {}
    return data


def atomic_write_json(path: Path, data: Dict[str, Dict[str, Any]]) -> None:
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    with tmp_path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)
    tmp_path.replace(path)


def file_signature(path: Path) -> Dict[str, Any]:
    st = path.stat()
    return {"mtime_ns": st.st_mtime_ns, "size_bytes": st.st_size}


def iter_input_images(input_dir: Path, extensions: set[str]) -> Iterable[Path]:
    for p in sorted(input_dir.rglob("*")):
        try:
            if p.is_file() and p.suffix.lower() in extensions:
                yield p
        except FileNotFoundError:
            logging.info("Skipping path that disappeared during scan path=%s", p)


def is_unseen(path: Path, state: Dict[str, Dict[str, Any]]) -> bool:
    key = str(path.resolve())
    sig = file_signature(path)
    prev = state.get(key)
    return not prev or prev.get("mtime_ns") != sig["mtime_ns"] or prev.get("size_bytes") != sig["size_bytes"]


def is_stable(path: Path, stable_seconds: int) -> bool:
    sig_before = file_signature(path)
    if stable_seconds <= 0:
        return True

    time.sleep(stable_seconds)
    try:
        sig_after = file_signature(path)
    except FileNotFoundError:
        logging.info("File disappeared before stability check completed image=%s", path)
        return False
    return sig_before == sig_after


def output_path_for(src: Path, output_dir: Path) -> Path:
    digest = hashlib.sha1(str(src.resolve()).encode("utf-8")).hexdigest()[:8]
    return output_dir / f"{src.stem}_{digest}_plant_mask.png"


def extract_union_mask(output: Dict[str, Any], height: int, width: int) -> tuple[np.ndarray, int]:
    raw_masks = output.get("masks")
    if raw_masks is None:
        raise RuntimeError("SAM3 output did not include a 'masks' field.")

    if torch.is_tensor(raw_masks):
        masks_arr = raw_masks.detach().cpu().numpy()
    else:
        masks_arr = np.asarray(raw_masks)

    if masks_arr.size == 0:
        return np.zeros((height, width), dtype=bool), 0

    masks_arr = np.squeeze(masks_arr)
    if masks_arr.ndim == 2:
        masks_arr = masks_arr[None, :, :]
    elif masks_arr.ndim == 4 and masks_arr.shape[1] == 1:
        masks_arr = masks_arr[:, 0, :, :]

    if masks_arr.ndim != 3 or masks_arr.shape[-2:] != (height, width):
        raise RuntimeError(
            "SAM3 masks have unexpected shape: "
            f"got={masks_arr.shape} expected=(*, {height}, {width})"
        )

    union_mask = np.zeros((height, width), dtype=bool)
    for mask in masks_arr:
        union_mask |= (mask > 0)
    return union_mask, int(masks_arr.shape[0])


def save_masked_image(src_image: np.ndarray, union_mask: np.ndarray, out_path: Path) -> None:
    masked = np.zeros_like(src_image)
    masked[union_mask] = src_image[union_mask]
    Image.fromarray(masked).save(out_path)


def run_pixel_counter(mask_path: Path) -> None:
    script_path = Path(__file__).resolve().parent / "pixel_count.py"
    result = subprocess.run(
        [sys.executable, str(script_path), "--image", str(mask_path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.stdout.strip():
        logging.info("pixel_count: %s", result.stdout.strip())
    if result.returncode != 0:
        stderr = result.stderr.strip() or "unknown error"
        raise RuntimeError(f"pixel_count failed for {mask_path}: {stderr}")


def process_one_image(
    image_path: Path,
    processor: Sam3Processor,
    prompt_text: str,
    output_dir: Path,
    device: torch.device,
    dtype: torch.dtype,
) -> tuple[Path, int, int, int]:
    with Image.open(image_path) as img:
        rgb = np.array(img.convert("RGB"))
        with torch.inference_mode(), inference_context(device, dtype):
            state = processor.set_image(img.convert("RGB"))
            processor.reset_all_prompts(state)
            output = processor.set_text_prompt(state=state, prompt=prompt_text)
        union_mask, mask_count = extract_union_mask(output, height=rgb.shape[0], width=rgb.shape[1])

    out_path = output_path_for(image_path, output_dir)
    save_masked_image(rgb, union_mask, out_path)
    foreground_pixels = int(union_mask.sum())
    total_pixels = int(union_mask.size)
    return out_path, foreground_pixels, total_pixels, mask_count


def run_loop(config: Config, run_once: bool = False) -> None:
    logging.info("Loading SAM3 model.")
    if not os.getenv("HF_TOKEN") and not os.getenv("HUGGING_FACE_HUB_TOKEN"):
        logging.warning(
            "HF_TOKEN is not set. SAM3 checkpoint downloads are gated; "
            "request access to the model repo on Hugging Face and set a read token "
            "in .env before first startup."
        )
    device = resolve_device(config.device)
    dtype = resolve_dtype(config.precision, device)
    model = build_sam3_image_model().to(device=device).float()
    processor = Sam3Processor(model, confidence_threshold=0.5)
    logging.info("SAM3 ready. device=%s precision=%s", device, dtype)

    while True:
        state = load_state(config.state_file)
        images = list(iter_input_images(config.input_dir, config.image_extensions))
        new_images = [p for p in images if is_unseen(p, state)]

        logging.info(
            "Scan complete. total_images=%d new_or_modified=%d",
            len(images),
            len(new_images),
        )

        for image_path in new_images:
            key = str(image_path.resolve())
            try:
                if not is_stable(image_path, config.file_stable_seconds):
                    logging.info(
                        "Skipping unstable image for now image=%s stable_seconds=%d",
                        image_path,
                        config.file_stable_seconds,
                    )
                    continue
                logging.info("Processing image=%s prompt=%s", image_path, config.prompt_text)
                out_path, foreground_pixels, total_pixels, mask_count = process_one_image(
                    image_path=image_path,
                    processor=processor,
                    prompt_text=config.prompt_text,
                    output_dir=config.mask_output_dir,
                    device=device,
                    dtype=dtype,
                )
                logging.info(
                    "Mask written output=%s mask_count=%d foreground_pixels=%d total_pixels=%d foreground_ratio=%.4f",
                    out_path,
                    mask_count,
                    foreground_pixels,
                    total_pixels,
                    foreground_pixels / total_pixels if total_pixels else 0,
                )
                run_pixel_counter(out_path)
                state[key] = {
                    **file_signature(image_path),
                    "output_path": str(out_path.resolve()),
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                }
                atomic_write_json(config.state_file, state)
            except Exception as exc:
                logging.exception("Failed processing image=%s error=%s", image_path, exc)

        if run_once:
            return
        logging.info("Sleeping for %d seconds", config.check_interval_seconds)
        time.sleep(config.check_interval_seconds)


def main() -> int:
    parser = argparse.ArgumentParser(description="Hourly SAM3 plant segmentation pipeline.")
    parser.add_argument("--run-once", action="store_true", help="Process once and exit.")
    args = parser.parse_args()

    try:
        config = load_config()
        configure_logging(config.log_level)
        validate_runtime(config)
    except Exception as exc:
        print(f"Startup validation failed: {exc}", file=sys.stderr)
        return 1

    logging.info(
        "Pipeline config input_dir=%s output_dir=%s state_file=%s interval=%d stable_seconds=%d prompt=%s device=%s precision=%s",
        config.input_dir,
        config.mask_output_dir,
        config.state_file,
        config.check_interval_seconds,
        config.file_stable_seconds,
        config.prompt_text,
        config.device,
        config.precision,
    )

    try:
        run_loop(config=config, run_once=args.run_once)
    except KeyboardInterrupt:
        logging.info("Interrupted; shutting down.")
    except Exception as exc:
        logging.exception("Pipeline crashed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
