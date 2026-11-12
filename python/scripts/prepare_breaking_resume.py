"""Prepare a new partition from a stopped partition's verified checkpoints."""

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from grn_memory.breaking_resume import prepare


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--network", type=int, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    args = parser.parse_args()
    result = prepare(args.source, args.output, args.network, args.shard_index, args.shard_count)
    print(json.dumps({k: result[k] for k in ("network", "shard_index", "shard_count", "copied_checkpoints")}))
