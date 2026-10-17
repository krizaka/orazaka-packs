"""The text classifier: a small open model (Apache-2.0), run on the machine of the worker. Nothing leaves it.

The score it computes is handed to :func:`rules.report` and goes no further — it is not returned, not logged, not stored.
Injectable (:class:`Classifier`) so the rules around it are tested without a model.
"""

from typing import Protocol


class Classifier(Protocol):
    def score(self, text: str) -> float: ...


class TransformersClassifier:
    """``roberta-base`` fine-tuned to tell human text from AI text, pinned by revision (``rules/…json`` → ``classifier``)."""

    def __init__(self, spec: dict) -> None:
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer

        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(spec["model"], revision=spec["revision"])
        self._model = AutoModelForSequenceClassification.from_pretrained(spec["model"], revision=spec["revision"]).eval()
        labels = {str(v).lower(): int(k) for k, v in self._model.config.id2label.items()}
        self._ai = labels[spec["aiLabel"].lower()]
        self._max = spec["maxTokens"]

    def score(self, text: str) -> float:
        encoded = self._tokenizer(text, return_tensors="pt", truncation=True, max_length=self._max)
        with self._torch.no_grad():
            return float(self._torch.softmax(self._model(**encoded).logits, -1)[0, self._ai])
