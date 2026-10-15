#!/usr/bin/env python3
"""The worker's broker connection. Run: python3 -m pytest test_broker.py -q  (or: python3 test_broker.py)

The dev broker is TLS only: a worker that cannot verify it never drains a job, and one that skips
the verification would hand the job payloads — documents — to whoever answers on 5671.
"""

import os
import ssl
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pika  # noqa: E402

import broker  # noqa: E402

CREDS = pika.PlainCredentials("orazaka", "not-a-real-password")


def test_plain_amqp_by_default_on_5672():
    params = broker.connection_parameters(CREDS, {"RABBITMQ_HOST": "mq.local"})
    assert params.host == "mq.local"
    assert params.port == 5672
    assert params.ssl_options is None
    assert broker.describe(params) == "amqp://orazaka@mq.local:5672"


def test_tls_on_5671_verifies_the_certificate_and_the_host_name():
    params = broker.connection_parameters(CREDS, {"RABBITMQ_HOST": "broker-dev.orazaka.com", "SPRING_RABBITMQ_SSL_ENABLED": "true"})
    assert params.port == 5671
    context = params.ssl_options.context
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    assert params.ssl_options.server_hostname == "broker-dev.orazaka.com"
    assert broker.describe(params) == "amqps://orazaka@broker-dev.orazaka.com:5671"


def test_the_own_name_wins_over_springs_and_an_explicit_port_is_kept():
    env = {"RABBITMQ_HOST": "10.0.0.5", "RABBITMQ_PORT": "15671", "RABBITMQ_SSL_ENABLED": "true",
           "SPRING_RABBITMQ_SSL_ENABLED": "false", "RABBITMQ_SSL_SERVER_NAME": "broker-dev.orazaka.com"}
    params = broker.connection_parameters(CREDS, env)
    assert params.port == 15671
    assert params.ssl_options.server_hostname == "broker-dev.orazaka.com"


def test_a_private_ca_named_by_the_deployment_is_trusted():
    with tempfile.TemporaryDirectory() as tmp:
        key, ca = os.path.join(tmp, "ca.key"), os.path.join(tmp, "ca.pem")
        subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", key, "-out", ca,
                        "-days", "1", "-subj", "/CN=Orazaka Dev Test CA"], check=True, capture_output=True)
        params = broker.connection_parameters(CREDS, {"RABBITMQ_HOST": "broker-dev.orazaka.com", "SPRING_RABBITMQ_SSL_ENABLED": "true",
                                                      "SPRING_RABBITMQ_SSL_CA_FILE": ca})
        subjects = [dict(x[0] for x in cert["subject"]) for cert in params.ssl_options.context.get_ca_certs()]
        assert {"commonName": "Orazaka Dev Test CA"} in subjects


def test_the_password_never_reaches_the_log_line():
    params = broker.connection_parameters(CREDS, {"RABBITMQ_SSL_ENABLED": "true"})
    assert "not-a-real-password" not in broker.describe(params)


# The worker itself (it imports pika, hence here, after the CI installs it): a ruleset awaiting a lawyer says so.
def test_a_quebec_report_carries_its_review_status():
    import test_rules
    import validation_worker
    screened = validation_worker._screen({"document": test_rules.QC_DEFECTIVE, "jurisdiction": "QC", "asOf": "2026-10-15"})
    assert screened["reviewStatus"] == "TO_REVIEW_BY_LAWYER"
    report = validation_worker._assemble({"screened": screened["screenedJson"], "judgment": "[]"})["report"]
    assert report["reviewStatus"] == "TO_REVIEW_BY_LAWYER"


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as error:  # noqa: BLE001
                failures += 1
                print(f"FAIL {name}: {error!r}")
    sys.exit(1 if failures else 0)
