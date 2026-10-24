"""The external-check connectors this pack can use: **the mock only** (orazaka-ai-engine#73, #75).

``MockConnector`` answers from recorded fixtures chosen by the subject's last name, exactly like the engine's
``MockConnector`` (Tremblay matches, Gagnon does not, Roy is a provider error, Bouchard a timeout, anyone else has no
match). It makes no network call. Any other provider is refused: spending starts only when a pilot customer says go,
and then the engine's own ``ExternalCheckService`` (consent, key, audit, metering) replaces this module.

A connector returns an outcome and the provider's own reference, never record content. The reference is derived from
the opaque subject id, never from a name.
"""

import hashlib
from dataclasses import dataclass, field
from typing import Optional

MATCH, NO_MATCH, PROVIDER_ERROR, TIMEOUT, REFUSED = "MATCH", "NO_MATCH", "PROVIDER_ERROR", "TIMEOUT", "REFUSED"
OUTCOMES = (MATCH, NO_MATCH, PROVIDER_ERROR, TIMEOUT)


class ProviderNotEnabled(ValueError):
    """Only the mock runs here."""


@dataclass(frozen=True)
class Subject:
    """The person a check is about. Names are personal data: ``repr`` never prints them."""

    subject_id: str
    last_name: str
    first_name: str
    birth_date: Optional[str] = None

    def __repr__(self) -> str:
        return f"Subject(subject_id={self.subject_id!r}, names=redacted)"

    __str__ = __repr__


@dataclass(frozen=True)
class Answer:
    outcome: str
    provider_ref: Optional[str] = None


@dataclass
class MockConnector:
    """Recorded answers, no network. ``calls`` lists the purposes asked, so a test can prove a stage was never called."""

    fixtures: dict = field(default_factory=lambda: {"Tremblay": MATCH, "Gagnon": NO_MATCH, "Roy": PROVIDER_ERROR, "Bouchard": TIMEOUT})
    calls: list = field(default_factory=list)
    provider: str = "mock"

    def verify_court_records(self, subject: Subject) -> Answer:
        self.calls.append("COURT_RECORDS")
        return self._answer(subject)

    def verify_credit(self, subject: Subject) -> Answer:
        self.calls.append("CREDIT")
        return self._answer(subject)

    def _answer(self, subject: Subject) -> Answer:
        outcome = self.fixtures.get(subject.last_name, NO_MATCH)
        ref = "mock-" + hashlib.sha256(subject.subject_id.encode()).hexdigest()[:12] if outcome == MATCH else None
        return Answer(outcome, ref)


def connector_for(provider: str) -> MockConnector:
    if provider != "mock":
        raise ProviderNotEnabled(f"provider '{provider}' is not enabled: this pack runs on the mock until a pilot customer says go")
    return MockConnector()
