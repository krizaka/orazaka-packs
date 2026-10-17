#!/usr/bin/env python3
"""Faces: classification and identity with a fake engine; the real models on a public-domain photograph when present.

Run: python3 -m pytest test_faces.py -q  (or: python3 test_faces.py)
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import faces  # noqa: E402
import rules  # noqa: E402

RULESET = rules.load_ruleset()
DET, REC = RULESET["detector"], RULESET["recognizer"]
HERE = os.path.dirname(os.path.abspath(__file__))


def face(height=0.4, score=0.95, area=None):
    return faces.Face(score=score, height_ratio=height, area=area if area is not None else height * height, handle=None)


class FakeEngine:
    """Decodes the 'image' (its bytes name a script), detects what the script says, embeds what it says."""

    def __init__(self, script):
        self.script = script  # name -> (faces, vector)

    def decode(self, data):
        return data.decode()

    def detect(self, image):
        return self.script[image][0]

    def embed(self, image, f):
        return self.script[image][1]


def b64(name):
    return base64.b64encode(name.encode()).decode()


def test_one_dominant_face_is_a_face_photo():
    assert faces.classify([face(0.5)], DET)[0] == faces.FACE


def test_two_similar_faces_are_a_group_and_a_small_second_face_is_not_counted():
    assert faces.classify([face(0.4), face(0.38)], DET)[0] == faces.GROUP
    assert faces.classify([face(0.5), face(0.05)], DET)[0] == faces.FACE  # a passer-by far behind


def test_a_doubtful_or_tiny_face_is_no_face():
    assert faces.classify([face(0.5, score=0.5)], DET)[0] == faces.NO_FACE
    assert faces.classify([face(0.04)], DET)[0] == faces.NO_FACE
    assert faces.classify([], DET)[0] == faces.NO_FACE


def test_identity_groups_the_same_person_and_flags_a_clear_stranger():
    a, b, stranger = [1.0, 0.0, 0.0], [0.95, 0.31, 0.0], [-0.2, 0.2, 0.96]
    verdict = faces.identity({0: a, 1: b, 2: a, 3: stranger}, REC)
    assert verdict["status"] == "MISMATCH" and verdict["mismatch"] == [3]


def test_the_doubtful_band_is_never_held_against_the_person():
    a = [1.0, 0.0]
    doubtful = [0.3, 0.954]  # cosine 0.3: between mismatchCosine and sameCosine
    verdict = faces.identity({0: a, 1: [0.99, 0.05], 2: doubtful}, REC)
    assert verdict["mismatch"] == [] and verdict["status"] == "CONSISTENT"


def test_two_photos_that_clearly_differ_cannot_say_who_is_the_stranger_so_the_second_is_flagged():
    verdict = faces.identity({0: [1.0, 0.0], 1: [0.0, 1.0]}, REC)
    assert verdict["status"] == "MISMATCH" and verdict["mismatch"] == [1]


def test_fewer_than_two_faces_cannot_be_compared():
    assert faces.identity({0: [1.0]}, REC)["status"] == "NOT_COMPARABLE"
    assert faces.identity({}, REC)["status"] == "NOT_COMPARABLE"


def test_inspect_returns_counts_and_codes_never_a_vector_or_a_box():
    engine = FakeEngine({"a": ([face(0.5)], [1.0, 0.0]), "b": ([face(0.5)], [0.9, 0.1]), "c": ([], [0.0, 0.0])})
    facts = faces.inspect_photos([b64("a"), b64("b"), b64("c")], engine, RULESET)
    assert [p["kind"] for p in facts["photos"]] == ["FACE", "FACE", "NO_FACE"]
    flat = repr(facts)
    assert "1.0" not in flat and "0.9" not in flat
    assert set(facts) == {"photos", "identity"} and set(facts["photos"][0]) == {"index", "kind", "faceCount"}


def test_without_the_consent_faces_are_counted_and_no_vector_is_ever_computed():
    class Spy(FakeEngine):
        embedded = 0

        def embed(self, image, f):
            Spy.embedded += 1
            return super().embed(image, f)

    engine = Spy({"a": ([face(0.5)], [1.0, 0.0]), "b": ([face(0.5)], [0.0, 1.0])})
    facts = faces.inspect_photos([b64("a"), b64("b")], engine, RULESET, compare=False)
    assert Spy.embedded == 0
    assert [p["kind"] for p in facts["photos"]] == ["FACE", "FACE"]
    assert facts["identity"] == {"status": "NOT_COMPARED", "mismatch": [], "compared": 0}


def test_unreadable_input_is_a_named_error():
    for bad in ["", "not base64!!", None, 12, base64.b64encode(b"x" * (faces.MAX_IMAGE_BYTES + 1)).decode()]:
        try:
            faces.decode_base64(bad)
        except faces.UnreadableImage:
            continue
        raise AssertionError(f"{bad!r} must be refused")


def _models_present():
    return all(os.path.isfile(os.path.join(faces.models_dir(), n)) for n in ("face_detection_yunet_2023mar.onnx", "face_recognition_sface_2021dec.onnx"))


def _real_engine():
    try:
        import cv2  # noqa: F401
    except ImportError:
        return None
    return faces.OpenCvEngine(RULESET) if _models_present() else None


def _file_b64(name):
    return base64.b64encode(open(os.path.join(HERE, "fixtures", name), "rb").read()).decode()


def test_real_models_find_the_face_and_the_same_person_in_a_mirrored_photo():
    engine = _real_engine()
    if engine is None:
        print("skip (models or OpenCV absent: run fetch_models.py)")
        return
    import cv2
    import numpy as np

    original = open(os.path.join(HERE, "fixtures", "astronaut.jpg"), "rb").read()
    mirrored = cv2.imencode(".jpg", cv2.flip(cv2.imdecode(np.frombuffer(original, np.uint8), 1), 1))[1].tobytes()
    facts = faces.inspect_photos([base64.b64encode(original).decode(), base64.b64encode(mirrored).decode(), _file_b64("gradient.jpg")], engine, RULESET)
    assert [p["kind"] for p in facts["photos"]] == ["FACE", "FACE", "NO_FACE"]
    assert facts["identity"]["status"] == "CONSISTENT" and facts["identity"]["compared"] == 2


if __name__ == "__main__":
    failed = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"ok   {name}")
            except Exception as error:  # noqa: BLE001
                failed += 1
                print(f"FAIL {name}: {error!r}")
    sys.exit(1 if failed else 0)
