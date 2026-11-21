"""Write reproducible CSVs and manifests without publishing a partial build."""

import json
from pathlib import Path
from tempfile import TemporaryDirectory

from .loaders import sha256
from .pipeline import BuildResult


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")


def write_build(result: BuildResult, destination: Path):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=destination.parent) as temporary:
        stage = Path(temporary) / "build"
        stage.mkdir()
        outputs = {}
        for name, frame in result.tables.items():
            path = stage / f"{name}.csv"
            frame.to_csv(path, index=False, date_format="%Y-%m-%d", lineterminator="\n")
            outputs[name] = {"path": path.name, "sha256": sha256(path)}
        write_json(stage / "source_manifest.json", result.source_manifest)
        write_json(stage / "reconciliation.json", result.reconciliation)
        write_json(stage / "transformation_manifest.json", {**result.transformation_manifest, "outputs": outputs})
        try:
            stage.rename(destination)
        except OSError:
            if not destination.is_dir():
                raise
            staged = {path.name: sha256(path) for path in stage.iterdir()}
            existing = {path.name: sha256(path) for path in destination.iterdir() if path.is_file()}
            if staged != existing or any(path.is_dir() for path in destination.iterdir()):
                raise ValueError(f"{destination} already contains a different build; choose a new output directory")
