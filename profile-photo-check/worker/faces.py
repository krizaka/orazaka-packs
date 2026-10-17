"""Faces in a photo: how many, which one is the subject, and whether two photos show the same person.

Two small open models, both commercially usable — YuNet (MIT) finds faces, SFace (Apache-2.0) turns a face into a
128-number vector — run by OpenCV. Nothing else is involved: no cloud, no third-party service.

**The vectors never leave this module's callers' memory.** They exist for the length of one job, to be compared with
each other, and are dropped. :func:`inspect_photos` returns counts and codes — never a vector, never a face box —
and the worker logs nothing but job ids. A vector is a biometric template; the only thing this pack does with it is
the question « could these two photos be of different people? », and it keeps nothing that would answer another.

The engine is injectable (:class:`FaceEngine`) so the rules around it are tested without a model; the real one is
:class:`OpenCvEngine`, tested on a public-domain photograph when the model files are present.
"""

from __future__ import annotations

import base64
import binascii
import os
from dataclasses import dataclass
from typing import Optional, Protocol, Sequence

FACE = "FACE"  # one face dominates the frame: this is a photo OF someone
GROUP = "GROUP"  # several faces of similar size: nobody in particular is the subject
NO_FACE = "NO_FACE"  # no face worth the name (too small, hidden, turned away, none)

#: Anything bigger is refused before decoding: a thumbnail is a few tens of kilobytes (the caller sends 512 px JPEGs).
MAX_IMAGE_BYTES = 1_500_000


class UnreadableImage(ValueError):
    """The bytes are not an image this worker can read — a checked, positive finding about the input."""


@dataclass(frozen=True)
class Face:
    """A detected face. ``height_ratio`` is its height over the image's; ``area`` orders faces by size."""

    score: float
    height_ratio: float
    area: float
    handle: object  # whatever the engine needs to embed it (never serialised)


class FaceEngine(Protocol):
    def detect(self, image: object) -> Sequence[Face]: ...

    def embed(self, image: object, face: Face) -> Sequence[float]: ...

    def decode(self, data: bytes) -> object: ...


@dataclass(frozen=True)
class PhotoFacts:
    """What is kept of one photo: its kind and its face count. The vector is held apart, in memory, for comparison."""

    index: int
    kind: str
    face_count: int


def classify(faces: Sequence[Face], detector: dict) -> tuple[str, Optional[Face]]:
    """FACE / GROUP / NO_FACE from the faces a photo holds, and the subject's face when there is one.

    A face counts when it is sure enough (``scoreThreshold``) and big enough (``minFaceHeightRatio`` of the frame: a
    passer-by far behind the subject is not a second person in the photo). The subject is the largest face when it is at
    least ``dominanceRatio`` times the area of the next one; otherwise the photo is a group.
    """
    counted = sorted(
        (f for f in faces if f.score >= detector["scoreThreshold"] and f.height_ratio >= detector["minFaceHeightRatio"]),
        key=lambda f: f.area,
        reverse=True,
    )
    if not counted:
        return NO_FACE, None
    if len(counted) == 1 or counted[0].area >= detector["dominanceRatio"] * counted[1].area:
        return FACE, counted[0]
    return GROUP, None


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)


def identity(vectors: dict[int, Sequence[float]], recognizer: dict) -> dict:
    """Whether the face photos could show different people.

    Photos are grouped by « clearly the same » (cosine >= ``sameCosine``, transitively). The largest group is the
    reference; a photo is a MISMATCH only when it is *clearly different* (cosine < ``mismatchCosine``) from every member
    of that group — the doubtful band between the two thresholds is never held against the person. Two groups of the
    same size cannot say which is the stranger: every photo outside the first one is then flagged, and the caller words
    it as « these photos may not show the same person ».
    """
    indexes = sorted(vectors)
    if len(indexes) < 2:
        return {"status": "NOT_COMPARABLE", "mismatch": [], "compared": len(indexes)}
    parent = {i: i for i in indexes}

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for pos, i in enumerate(indexes):
        for j in indexes[pos + 1 :]:
            if cosine(vectors[i], vectors[j]) >= recognizer["sameCosine"]:
                parent[find(j)] = find(i)
    groups: dict[int, list[int]] = {}
    for i in indexes:
        groups.setdefault(find(i), []).append(i)
    ordered = sorted(groups.values(), key=lambda g: (-len(g), g[0]))
    reference = ordered[0]
    mismatch = [
        i
        for g in ordered[1:]
        for i in g
        if all(cosine(vectors[i], vectors[r]) < recognizer["mismatchCosine"] for r in reference)
    ]
    return {"status": "MISMATCH" if mismatch else "CONSISTENT", "mismatch": sorted(mismatch), "compared": len(indexes)}


def decode_base64(encoded: object) -> bytes:
    if not isinstance(encoded, str) or not encoded:
        raise UnreadableImage("a photo is empty")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as bad:
        raise UnreadableImage("a photo is not valid base64") from bad
    if len(data) > MAX_IMAGE_BYTES:
        raise UnreadableImage("a photo is larger than a thumbnail should be")
    return data


def inspect_photos(photos_base64: Sequence[object], engine: FaceEngine, ruleset: dict) -> dict:
    """The facts of each photo and the identity verdict — counts and codes only."""
    detector, recognizer = ruleset["detector"], ruleset["recognizer"]
    facts: list[PhotoFacts] = []
    vectors: dict[int, Sequence[float]] = {}
    for index, encoded in enumerate(photos_base64):
        image = engine.decode(decode_base64(encoded))
        faces = engine.detect(image)
        kind, subject = classify(faces, detector)
        counted = sum(1 for f in faces if f.score >= detector["scoreThreshold"] and f.height_ratio >= detector["minFaceHeightRatio"])
        facts.append(PhotoFacts(index=index, kind=kind, face_count=counted))
        if subject is not None:
            vectors[index] = engine.embed(image, subject)
    verdict = identity(vectors, recognizer)
    vectors.clear()  # the templates end here
    return {
        "photos": [{"index": f.index, "kind": f.kind, "faceCount": f.face_count} for f in facts],
        "identity": verdict,
    }


class OpenCvEngine:
    """YuNet + SFace through OpenCV. Model files come from :func:`models_dir` (``fetch_models.py`` puts them there)."""

    def __init__(self, ruleset: dict, directory: Optional[str] = None) -> None:
        import cv2  # imported here: the rules and their tests need no OpenCV

        self._cv2 = cv2
        detector = ruleset["detector"]
        base = directory or models_dir()
        self._detector_config = detector
        self._yunet_path = os.path.join(base, "face_detection_yunet_2023mar.onnx")
        sface_path = os.path.join(base, "face_recognition_sface_2021dec.onnx")
        for path in (self._yunet_path, sface_path):
            if not os.path.isfile(path):
                raise FileNotFoundError(f"model file missing: {os.path.basename(path)} (run fetch_models.py)")
        self._sface = cv2.FaceRecognizerSF.create(sface_path, "")

    def decode(self, data: bytes) -> object:
        import numpy as np

        image = self._cv2.imdecode(np.frombuffer(data, dtype=np.uint8), self._cv2.IMREAD_COLOR)
        if image is None:
            raise UnreadableImage("a photo could not be decoded")
        edge = self._detector_config["maxEdge"]
        h, w = image.shape[:2]
        if max(h, w) > edge:
            scale = edge / max(h, w)
            image = self._cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=self._cv2.INTER_AREA)
        return image

    def detect(self, image: object) -> Sequence[Face]:
        cfg = self._detector_config
        h, w = image.shape[:2]  # type: ignore[attr-defined]
        detector = self._cv2.FaceDetectorYN.create(self._yunet_path, "", (w, h), cfg["scoreThreshold"] - 0.1, cfg["nmsThreshold"], cfg["topK"])
        _, rows = detector.detect(image)
        if rows is None:
            return []
        out = []
        for row in rows:
            fw, fh = float(row[2]), float(row[3])
            out.append(Face(score=float(row[14]), height_ratio=fh / h, area=fw * fh, handle=row))
        return out

    def embed(self, image: object, face: Face) -> Sequence[float]:
        aligned = self._sface.alignCrop(image, face.handle)
        return [float(x) for x in self._sface.feature(aligned)[0]]


def models_dir() -> str:
    return os.environ.get("PHOTO_MODELS_DIR") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
