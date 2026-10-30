# The measurement container: every tool the corpus uses lives here, never on a developer's machine.
# requirements.txt is compiled with hashes from requirements.in (pip-compile --generate-hashes --strip-extras --allow-unsafe).
#   docker build -t krizaka-forensics -f Dockerfile .
#   docker run --rm --user "$(id -u):$(id -g)" -v "$PWD/../..:/pack" -w /pack/worker krizaka-forensics python forensics/measure.py --write
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ghostscript qpdf \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 forensics
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --require-hashes --only-binary :all: -r /tmp/requirements.txt
USER forensics
