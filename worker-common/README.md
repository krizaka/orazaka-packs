# worker-common

Code every pack worker shares, so it exists once (org rule: no copy-pasted code).

- `worker_broker.py` — how a worker reaches the RabbitMQ broker: host, credentials and, when the deployment asks, TLS.
- `worker_loop.py` — the job loop: declare the queue and its dead-letter queue, consume, run the worker's handler, publish `done` or `error` (de-duplicated by message id). New workers bring a handler and a `worker.yaml`; older ones still carry their own copy.

A worker imports it through a three-line `broker.py` beside its code (`from worker_broker import *`) that puts this folder on
`sys.path`; its tests and its `worker.yaml` are unchanged. The folder travels with the repository: a deployment that copies a
single pack directory must copy `worker-common/` beside it.
