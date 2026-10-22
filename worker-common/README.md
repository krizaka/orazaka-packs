# worker-common

Code every pack worker shares, so it exists once (org rule: no copy-pasted code).

- `worker_broker.py` — how a worker reaches the RabbitMQ broker: host, credentials and, when the deployment asks, TLS.

A worker imports it through a three-line `broker.py` beside its code (`from worker_broker import *`) that puts this folder on
`sys.path`; its tests and its `worker.yaml` are unchanged. The folder travels with the repository: a deployment that copies a
single pack directory must copy `worker-common/` beside it.
