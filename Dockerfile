# Frame TV Dashboard — full stack: integrations (e.g. Keep), TV frame updates, Flask UI, mDNS.
# Entry point: main.py (not web.py).
#
# Build (default base image):
#   docker build -t frameware .
#
# Build with another Python base image:
#   docker build --build-arg BASE_IMAGE=python:3.11-slim-bookworm -t frameware .
#
# Run (map web.port from config, default 5000; mount config + writable data for Keep):
#   docker run --rm -p 5000:5000 \
#     -v /path/to/your/config.yaml:/app/config.yaml:ro \
#     -v /path/to/your/data:/app/data \
#     frameware
#
# Timezone (defaults to UTC): match the host’s local time with either of:
#   -e TZ=$TZ                    # if your shell already has TZ (e.g. America/Los_Angeles)
#   -v /etc/localtime:/etc/localtime:ro   # Linux: reuse host zone file (often simplest)
#   -e TZ=America/New_York       # set IANA zone explicitly (works everywhere, incl. Docker Desktop Mac)
#
# Custom config path:
#   docker run --rm ... frameware python main.py --config /app/config.yaml
#
# SSDP TV discovery and multicast often fail on the default bridge; on Linux use host networking:
#   docker run --rm --network host frameware
# (Use web.port in config; no -p with --network host.)

ARG BASE_IMAGE=python:3.12-slim-bookworm
FROM ${BASE_IMAGE}

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# TrueType fonts for PIL text rendering (get_font); without this, only the tiny
# bitmap default font loads and labels vanish at 4K scale.
# tzdata so TZ=… and /etc/localtime mounts resolve (datetime.now() uses container local time).
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && pip install -r requirements.txt

COPY . .

# Default config when none is bind-mounted (see .dockerignore: local config.yaml is not copied).
RUN cp config.example.yaml config.yaml

EXPOSE 5000

CMD ["python", "main.py"]
