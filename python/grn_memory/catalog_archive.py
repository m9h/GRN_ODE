"""Bounded-memory checkpoints and sharded evidence archives for large screens."""

from collections import OrderedDict
import gzip
import hashlib
import json


class EvidenceStore:
    def __init__(self, output, model_id, signature, resume=False):
        self.output, self.model_id, self.signature = output, model_id, signature
        self.root = output/".evidence"/model_id/signature
        self.root.mkdir(parents=True, exist_ok=True)
        self.resume = resume
        self.used = {"branches": set(), "cases": set()}
        self.recent = OrderedDict()

    def _path(self, kind, key):
        if kind not in self.used or len(key) != 64 or any(c not in "0123456789abcdef" for c in key):
            raise ValueError("Unknown evidence kind or invalid SHA-256 key")
        return self.root/(kind+"-"+key+".json.gz")

    def get(self, kind, key, *, passed_only=True):
        path = self._path(kind, key)
        if not (self.resume or key in self.used[kind]) or not path.exists():
            return None
        cache_key = (kind, key)
        if cache_key in self.recent:
            record = self.recent.pop(cache_key)
            self.recent[cache_key] = record
        else:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                record = json.load(stream)
        if record.get("fingerprint") != self.signature or record.get("record_id") != key:
            raise ValueError("Evidence fingerprint or identifier mismatch")
        if passed_only and not record.get("passed"):
            return None
        self.used[kind].add(key)
        return record

    def put(self, kind, key, record):
        value = {**record, "record_id": key, "fingerprint": self.signature}
        path = self._path(kind, key)
        temporary = path.with_suffix(".tmp")
        with gzip.open(temporary, "wt", encoding="utf-8") as stream:
            json.dump(value, stream, allow_nan=False, separators=(",", ":"))
            stream.write("\n")
        temporary.replace(path)
        self.used[kind].add(key)
        self.recent[(kind,key)] = value
        while len(self.recent) > 8:
            self.recent.popitem(last=False)
        return value

    def publish(self, *, shard_records=100):
        """Publish only evidence used in this run, including failed records."""
        directory = self.output/"evidence"
        directory.mkdir(exist_ok=True)
        manifests = {}
        for kind, used in self.used.items():
            manifests[kind] = []
            ids = sorted(used)
            for index, start in enumerate(range(0,len(ids),shard_records)):
                subset = ids[start:start+shard_records]
                path = directory/f"{self.model_id}-{kind}-{index:05d}.jsonl.gz"
                temporary = path.with_suffix(".tmp")
                with temporary.open("wb") as raw:
                    with gzip.GzipFile(filename="",mode="wb",fileobj=raw,mtime=0) as stream:
                        for key in subset:
                            record = self.get(kind,key,passed_only=False)
                            if record is None:
                                raise ValueError("Missing evidence for publication")
                            stream.write((json.dumps(record,allow_nan=False,separators=(",", ":"))+"\n").encode())
                temporary.replace(path)
                manifests[kind].append({"file":str(path.relative_to(self.output)), "records":len(subset),
                    "bytes":path.stat().st_size, "sha256":hashlib.sha256(path.read_bytes()).hexdigest()})
        return manifests
