# The measurement container: every tool the corpus uses lives here, never on a developer's machine.
#   docker build -t krizaka-forensics -f Dockerfile .
#   docker run --rm -v "$PWD/../..:/pack" -w /pack/worker krizaka-forensics python forensics/measure.py --write
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ghostscript qpdf \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt
