from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from datasketch import MinHash, MinHashLSH

from tuneforge.validation.structural import render_record_text


def _normalized_hash(text: str) -> str:
    normalized = " ".join(text.split()).lower()
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


@dataclass
class DeduplicationResult:
    kept: list = field(default_factory=list)
    exact_duplicates: int = 0
    near_duplicates: int = 0


def deduplicate(records: list, *, near_duplicate_threshold: float = 0.85, num_perm: int = 128) -> DeduplicationResult:
    """Two passes: exact duplicates first (cheap, a normalized-text hash),
    then near-duplicates via local MinHash LSH on whatever survives — no
    point running the more expensive LSH pass over rows already dropped.
    """
    seen_hashes: set[str] = set()
    exact_pass: list = []
    exact_duplicates = 0

    for record in records:
        text_hash = _normalized_hash(render_record_text(record))
        if text_hash in seen_hashes:
            exact_duplicates += 1
            continue
        seen_hashes.add(text_hash)
        exact_pass.append(record)

    lsh = MinHashLSH(threshold=near_duplicate_threshold, num_perm=num_perm)
    kept: list = []
    near_duplicates = 0
    for index, record in enumerate(exact_pass):
        minhash = MinHash(num_perm=num_perm)
        for shingle in render_record_text(record).split():
            minhash.update(shingle.encode("utf-8"))
        if lsh.query(minhash):
            near_duplicates += 1
            continue
        lsh.insert(str(index), minhash)
        kept.append(record)

    return DeduplicationResult(kept=kept, exact_duplicates=exact_duplicates, near_duplicates=near_duplicates)
