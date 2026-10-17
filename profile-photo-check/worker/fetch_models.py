#!/usr/bin/env python3
"""Downloads the two face models into ``models/`` and checks their SHA-256 against ``models.lock.json``.

YuNet (MIT) and SFace (Apache-2.0) from the OpenCV Zoo. The lock is the pin: a file that does not match is deleted and
the run fails — a model that changed under us is not a model we tested.
"""

import hashlib
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))


def sha256(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    lock = json.load(open(os.path.join(HERE, "models.lock.json"), encoding="utf-8"))
    target = os.environ.get("PHOTO_MODELS_DIR") or os.path.join(HERE, "models")
    os.makedirs(target, exist_ok=True)
    for name, entry in lock["models"].items():
        path = os.path.join(target, name)
        if os.path.isfile(path) and sha256(path) == entry["sha256"]:
            print(f"ok      {name}")
            continue
        print(f"fetch   {name}")
        urllib.request.urlretrieve(entry["url"], path)
        if sha256(path) != entry["sha256"]:
            os.remove(path)
            print(f"MISMATCH {name}: the file is not the pinned one; removed", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
