"""Verify a Stage 4 build and create a deterministic archive of its published files."""

import argparse
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from ..stage1.provenance import sha256


def package(build, output):
    hashes = (build / "hashes.json").read_bytes()
    index = json.loads(hashes)
    manifest = json.loads((build / "run_manifest.json").read_bytes())
    if manifest["hashes_sha256"] != sha256(hashes) or index["run_id"] != manifest["run_id"]:
        raise ValueError("invalid Stage 4 manifest or hash index")
    files = {}
    for name, digest in index["files"].items():
        source = build / name
        if not source.resolve().is_relative_to(build.resolve()):
            raise ValueError(f"file outside published build: {name}")
        data = source.read_bytes()
        if sha256(data) != digest:
            raise ValueError(f"invalid published file: {name}")
        files[name] = data
    files["hashes.json"] = hashes
    files["run_manifest.json"] = (build / "run_manifest.json").read_bytes()
    with TemporaryDirectory(prefix=".stage4-archive-", dir=output.parent) as temp:
        staged = Path(temp) / "fixture.zip"
        with ZipFile(staged, "w") as archive:
            for name, data in sorted(files.items()):
                entry = ZipInfo(name, date_time=(2024, 1, 1, 0, 0, 0))
                entry.external_attr = 0o100644 << 16
                archive.writestr(entry, data, compress_type=ZIP_DEFLATED, compresslevel=9)
        os.link(staged, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("build", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    package(args.build, args.output)


if __name__ == "__main__":
    main()
