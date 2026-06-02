"""Inject the pdfium shared library into a built wheel and update its RECORD.

Maturin's `[tool.maturin] include` directive only bundles files that exist at
build time. Because libpdfium is produced as a side effect of compiling
pdfium-sys and copied in afterwards by CI, we have to splice it into the
finished wheel ourselves. Appending with `zipfile.ZipFile(..., 'a')` works for
the bytes, but leaves the `*.dist-info/RECORD` manifest out of sync — Poetry
and other strict installers warn about that. This script rewrites the wheel so
the dylib is present in both the archive and RECORD.
"""

from __future__ import annotations

import base64
import hashlib
import sys
import zipfile
from pathlib import Path


def _record_hash(data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    return "sha256=" + base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def inject(wheel_path: Path, dylib_path: Path, arcname: str) -> None:
    if not dylib_path.exists():
        print(f"Warning: {dylib_path} not found, skipping {wheel_path}")
        return

    dylib_bytes = dylib_path.read_bytes()
    dylib_hash = _record_hash(dylib_bytes)
    dylib_size = str(len(dylib_bytes))

    tmp_path = wheel_path.with_suffix(wheel_path.suffix + ".tmp")

    with zipfile.ZipFile(wheel_path, "r") as zin:
        record_name = next(
            (n for n in zin.namelist() if n.endswith(".dist-info/RECORD")), None
        )
        if record_name is None:
            raise RuntimeError(f"No RECORD file found in {wheel_path}")

        record_text = zin.read(record_name).decode("utf-8")
        record_lines = [ln for ln in record_text.splitlines() if ln.strip()]
        # Drop any pre-existing entries for this dylib or the RECORD itself
        # (RECORD's own line always carries empty hash/size).
        record_lines = [
            ln
            for ln in record_lines
            if not ln.startswith(arcname + ",")
            and not ln.startswith(record_name + ",")
        ]
        record_lines.append(f"{arcname},{dylib_hash},{dylib_size}")
        record_lines.append(f"{record_name},,")
        new_record = ("\n".join(record_lines) + "\n").encode("utf-8")

        with zipfile.ZipFile(
            tmp_path, "w", compression=zipfile.ZIP_DEFLATED
        ) as zout:
            for item in zin.infolist():
                if item.filename == record_name or item.filename == arcname:
                    continue
                zout.writestr(item, zin.read(item.filename))
            zout.writestr(arcname, dylib_bytes)
            zout.writestr(record_name, new_record)

    tmp_path.replace(wheel_path)
    print(f"Injected {arcname} ({dylib_size} bytes) into {wheel_path}")


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: inject_dylib.py <wheel> <dylib> <arcname>", file=sys.stderr)
        return 2
    inject(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
