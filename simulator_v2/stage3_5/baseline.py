"""Verify rebuilt seed-42 baselines and the published Stage 3 archive."""

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from ..stage1.__main__ import build as build_stage1
from ..stage1.provenance import canonical, sha256
from ..stage2.export import build as build_stage2
from ..stage3.export import build as build_stage3


def verify(root):
    v2 = Path(__file__).resolve().parents[1]
    report = {}
    for number, build in enumerate((build_stage1, build_stage2, build_stage3), 1):
        name = f"stage{number}"
        output = root / name
        evidence = v2 / name / "evidence"
        run_id = build(output, 42)
        expected = (evidence / "hashes.json").read_bytes()
        if (output / "hashes.json").read_bytes() != expected:
            raise ValueError(f"{name} index differs from the accepted baseline")
        files = json.loads(expected)["files"]
        for file, digest in files.items():
            if sha256((output / file).read_bytes()) != digest:
                raise ValueError(f"{name} rebuilt artifact differs: {file}")
            published = evidence / file
            if published.is_file() and sha256(published.read_bytes()) != digest:
                raise ValueError(f"{name} published artifact differs: {file}")
        if number == 3:
            with ZipFile(evidence / "fixture-seed42.zip") as archive:
                if archive.read("hashes.json") != expected:
                    raise ValueError("Stage 3 archive index differs")
                for file, digest in files.items():
                    if sha256(archive.read(file)) != digest:
                        raise ValueError(f"Stage 3 archive member differs: {file}")
                manifest = json.loads(archive.read("run_manifest.json"))
                if manifest["hashes_sha256"] != sha256(expected):
                    raise ValueError("Stage 3 archive manifest digest differs")
        report[name] = {"run_id": run_id, "index_sha256": sha256(expected), "verified_files": len(files)}
    return {"seed": 42, "status": "passed", "baselines": report}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scratch", type=Path, default=None, help="existing directory for temporary rebuilds")
    args = parser.parse_args()
    with TemporaryDirectory(prefix="stage35-baselines-", dir=args.scratch) as temp:
        print(canonical(verify(Path(temp))).decode(), end="")


if __name__ == "__main__":
    main()
