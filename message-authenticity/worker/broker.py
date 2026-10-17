"""How the validation worker reaches the broker — host, credentials and, when the deployment asks, TLS.

The worker used to dial ``amqp://`` only. The dev broker of Orazaka (``broker-dev.orazaka.com``) is
TLS only (5671, a certificate signed by the dev CA), so a worker that cannot speak TLS never runs in
dev — and the Studios that need it (compliance-check, document-authenticity) stay locked behind a
queue nobody drains.

Names: the ``RABBITMQ_*`` family settled by ADR-053 §8 for host, port, user and password; TLS is
switched on by ``RABBITMQ_SSL_ENABLED`` or, as the Java services of the same container read it,
``SPRING_RABBITMQ_SSL_ENABLED`` — one environment describes the broker for every process. The private
CA is trusted when ``RABBITMQ_SSL_CA_FILE`` (or ``SPRING_RABBITMQ_SSL_CA_FILE``) names it; the name
checked against the certificate is ``RABBITMQ_SSL_SERVER_NAME``, else the host. The context always
verifies the certificate and the host name — there is no "insecure" switch.
"""
from __future__ import annotations

import os
import ssl
from typing import Mapping, Optional

import pika

#: Long enough for a quiet queue, short enough that a dead link is noticed.
DEFAULT_HEARTBEAT_SECONDS = 60


def _first(source: Mapping[str, str], *names: str) -> Optional[str]:
    for name in names:
        value = source.get(name)
        if value:
            return value
    return None


def tls_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the deployment asked for TLS."""
    source = os.environ if env is None else env
    return (_first(source, "RABBITMQ_SSL_ENABLED", "SPRING_RABBITMQ_SSL_ENABLED") or "false").lower() == "true"


def connection_parameters(
    credentials: "pika.PlainCredentials", env: Optional[Mapping[str, str]] = None
) -> "pika.ConnectionParameters":
    """The broker this worker talks to, as the deployment declared it.

    Args:
        credentials: the user and password (``_broker_credentials`` of the worker).
        env: the environment to read (tests pass a dict); ``os.environ`` by default.

    Returns:
        Parameters for ``pika.BlockingConnection``: host, port (5671 by default under TLS, 5672
        otherwise), credentials, heartbeat, and TLS with certificate and host-name verification
        when it is enabled.
    """
    source = os.environ if env is None else env
    host = _first(source, "RABBITMQ_HOST") or "localhost"
    secure = tls_enabled(source)
    try:
        port = int(_first(source, "RABBITMQ_PORT") or ("5671" if secure else "5672"))
    except ValueError:
        port = 5671 if secure else 5672
    options = {
        "host": host,
        "port": port,
        "credentials": credentials,
        "heartbeat": DEFAULT_HEARTBEAT_SECONDS,
        "blocked_connection_timeout": 300,
    }
    if secure:
        cafile = _first(source, "RABBITMQ_SSL_CA_FILE", "SPRING_RABBITMQ_SSL_CA_FILE")
        context = ssl.create_default_context(cafile=cafile)
        # Python 3.13+ adds VERIFY_X509_STRICT by default, which refuses a CA certificate without an Authority Key
        # Identifier — the dev CA has none. The chain and the host name are still verified (CERT_REQUIRED, check_hostname).
        context.verify_flags &= ~getattr(ssl, "VERIFY_X509_STRICT", 0)
        server_name = _first(source, "RABBITMQ_SSL_SERVER_NAME") or host
        options["ssl_options"] = pika.SSLOptions(context, server_hostname=server_name)
    return pika.ConnectionParameters(**options)


def describe(params: "pika.ConnectionParameters") -> str:
    """A log line for the connection — scheme, user, host and port, never the password."""
    user = getattr(params.credentials, "username", "?")
    scheme = "amqps" if params.ssl_options else "amqp"
    return f"{scheme}://{user}@{params.host}:{params.port}"
