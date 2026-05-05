FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir torch==2.10.0 torchvision --index-url https://download.pytorch.org/whl/cu128 \
    && git clone https://github.com/facebookresearch/sam3.git /opt/sam3 \
    && pip install --no-cache-dir -e /opt/sam3 \
    && pip install --no-cache-dir -r /app/requirements.txt \
    && python -c "import av, einops, ftfy, iopath, pycocotools, regex, timm; from sam3 import build_sam3_image_model; from sam3.model.sam3_image_processor import Sam3Processor"

COPY multiSegment.py pixel_count.py /app/
COPY entrypoint.sh /app/entrypoint.sh
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

ENTRYPOINT ["/bin/sh", "/app/entrypoint.sh"]
