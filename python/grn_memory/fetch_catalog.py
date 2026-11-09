"""Download the unchanged SBML files listed in supplementary Table S1.

Existing files are preserved and checked against the recorded hash. Newly
downloaded files must parse as SBML before entering the collection. No model
equations, events, annotations, or initial conditions are rewritten.
"""

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tempfile

import libsbml

ROOT = Path(__file__).resolve().parents[1]


def fetch(entry, destination, existing):
    identifier = entry["biomodel_id"]
    path = destination / f"{identifier}.xml"
    url = (f"https://www.ebi.ac.uk/biomodels/model/download/{identifier}"
           f"?filename={identifier}_url.xml")
    if path.exists():
        if path.name not in existing:
            raise ValueError(f"Existing file has no provenance record: {path}")
        record = existing[path.name]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != record["sha256"]:
            raise ValueError(f"Hash mismatch for {path}")
        return record
    with tempfile.TemporaryDirectory(prefix="grn-sbml-") as temporary:
        downloaded = Path(temporary) / path.name
        subprocess.run(["curl", "--fail", "--location", "--silent", "--show-error",
                        "--max-time", "90", "--retry", "2", url,
                        "--output", str(downloaded)], check=True)
        doc = libsbml.readSBML(str(downloaded))
        model = doc.getModel()
        if model is None or doc.getNumErrors(libsbml.LIBSBML_SEV_ERROR):
            raise ValueError(f"Invalid SBML for {identifier}: {doc.getErrorLog().toString()}")
        data = downloaded.read_bytes()
        record = {
            "file": path.name, "sha256": hashlib.sha256(data).hexdigest(),
            "network": entry["network"], "name": model.getName(), "url": url,
            "retrieved": datetime.now(timezone.utc).date().isoformat(),
            "record_url": f"https://www.ebi.ac.uk/biomodels/{identifier}",
            "species_order": [s.getId() for s in model.getListOfSpecies()],
            "compartments": {c.getId(): c.getSize() for c in model.getListOfCompartments()},
            "source_notes_preserved": True,
            "sbml_level": doc.getLevel(), "sbml_version": doc.getVersion(),
            "reaction_count": model.getNumReactions(),
            "license": "CC0-1.0", "license_policy_url": "https://biomodels.org/termsofuse",
        }
        path.write_bytes(data)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, default=ROOT / "models")
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.workers < 1:
        parser.error("--workers must be positive")
    args.destination.mkdir(parents=True, exist_ok=True)
    manifest = args.destination / "manifest.json"
    records = json.loads(manifest.read_text()) if manifest.exists() else []
    existing = {record["file"]: record for record in records}
    catalog = json.loads((ROOT / "models/catalog.json").read_text())["models"]
    failures = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [(entry, pool.submit(fetch, entry, args.destination, existing))
                   for entry in catalog]
        for entry, future in futures:
            try:
                record = future.result()
                existing[record["file"]] = record
                # Persist every completed entry so partial downloads can resume.
                temporary = manifest.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(sorted(existing.values(), key=lambda r: r["network"]),
                                                indent=2, allow_nan=False) + "\n")
                temporary.replace(manifest)
                print(f'{entry["network"]:02d} {entry["biomodel_id"]}: verified', flush=True)
            except Exception as exc:
                failures.append(entry["biomodel_id"])
                print(f'{entry["biomodel_id"]}: {exc}', flush=True)
    if failures:
        raise SystemExit(f"Download failed for {len(failures)} models: {failures}")


if __name__ == "__main__":
    main()
