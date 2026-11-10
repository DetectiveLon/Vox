"""Download the pinned VoxLock model files into models/.

The model weights are not stored in git. This script downloads the exact
revision Vox was built and tested against, verifies every file by SHA-256, and
writes the license notice next to the models.

  python tools/fetch_models.py
  python tools/fetch_models.py --dest models --force
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "arbazsiddiqui/voxlock"
REVISION = "2413b292bc2c337bfc19a9802aaf3e011e68e9c4"
HF = f"https://huggingface.co/{REPO}/resolve/{REVISION}"

# local name -> (remote path, sha256, size)
FILES: dict[str, tuple[str, str, int]] = {
    "enroll.onnx": (
        "onnx/v2/enroll.onnx",
        "81f305c9b7a32f13d1401f53bb4c6301826a607c9e807e60912f36ef1b9fae29",
        21_023_799,
    ),
    "enroll_fp16.onnx": (
        "onnx/v2/enroll_fp16.onnx",
        "96515a725cf0466450a41c565887a07e8c0fb0c89f6bbfbc01214433029a2f6c",
        10_893_975,
    ),
    "chunk_int8.onnx": (
        "onnx/v2/chunk_int8.onnx",
        "c50ffdc8d723fd4f91cb08889f3d0143491f95967b705f35c444a0b4afe88172",
        56_560_589,
    ),
    "chunk_fp16.onnx": (
        "onnx/v2/chunk_fp16.onnx",
        "c4850d3bff7cacfed360ef4708a448ced1b6bf0eb43aff06e764099c9db02e3b",
        38_947_947,
    ),
    "config.yaml": (
        "config.yaml",
        "786230c34b7f40f4a23eb1dd791d917010e74443a7e8125eee7e9f14fae0224b",
        2_431,
    ),
    "LICENSE": (
        "LICENSE",
        "cfc7749b96f63bd31c3c42b5c471bf756814053e847c10f3eb003417bc523d30",
        11_358,
    ),
}

# VoxLock's NOTICE is not published on Hugging Face, so this repository keeps a
# verbatim copy and writes it next to the models. It ships with the app.
NOTICE = Path(__file__).resolve().parent.parent / "third_party" / "voxlock-NOTICE.txt"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def download(url: str, target: Path) -> None:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "vox-model-fetch/1.0",
            "Accept": "application/octet-stream",
        },
    )
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            with partial.open("wb") as handle:
                while True:
                    block = response.read(1 << 20)
                    if not block:
                        break
                    handle.write(block)
                    done += len(block)
                    if total:
                        percent = done * 100 // total
                        print(f"\r  {target.name}: {percent:3d}%", end="", flush=True)
        print()
        partial.replace(target)
    except (urllib.error.URLError, OSError) as exc:
        partial.unlink(missing_ok=True)
        raise SystemExit(f"Could not download {url}\n{exc}") from exc


def fetch(dest: Path, force: bool) -> int:
    dest.mkdir(parents=True, exist_ok=True)
    failed = 0
    for name, (remote, expected, size) in FILES.items():
        target = dest / name
        if target.is_file() and not force:
            actual = sha256(target)
            if actual == expected:
                print(f"ok   {name}")
                continue
            print(f"bad  {name} (hash mismatch, downloading again)")
        print(f"get  {name}")
        download(f"{HF}/{remote}", target)
        actual = sha256(target)
        if actual != expected or target.stat().st_size != size:
            print(
                f"     verification failed: expected {expected} / {size} bytes, "
                f"got {actual} / {target.stat().st_size} bytes",
                file=sys.stderr,
            )
            target.unlink(missing_ok=True)
            failed += 1
        else:
            print(f"ok   {name} ({size / 1e6:.1f} MB)")

    notice_target = dest / "NOTICE"
    if NOTICE.is_file():
        text = NOTICE.read_bytes()
        notice_target.write_bytes(text)
        print(f"ok   NOTICE ({len(text)} bytes)")
    else:
        print(f"warning: {NOTICE} is missing, so NOTICE was not written", file=sys.stderr)

    if failed:
        print(f"{failed} file(s) failed verification.", file=sys.stderr)
        return 1
    print(f"\nModels ready in {dest.resolve()}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "models",
        help="target folder (default: models/ next to this script)",
    )
    parser.add_argument(
        "--force", action="store_true", help="download even when a file already matches"
    )
    args = parser.parse_args()
    return fetch(args.dest, args.force)


if __name__ == "__main__":
    os.environ.setdefault("PYTHONIOENCODING", "utf-8")
    raise SystemExit(main())
