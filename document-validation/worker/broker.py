"""document-validation worker: the broker connection is the shared one (../../worker-common/worker_broker.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worker-common"))
from worker_broker import *  # noqa: E402,F401,F403  (re-exports the public names the worker and its tests use)
