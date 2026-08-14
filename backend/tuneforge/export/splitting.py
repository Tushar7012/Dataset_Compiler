from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class SplitResult:
    train: list = field(default_factory=list)
    eval: list = field(default_factory=list)
    leakage_warning: bool = False


def split_train_eval(records: list, *, seed: int = 42, eval_fraction: float = 0.1) -> SplitResult:
    """Splits by *document* (source_hash), never by row — a row from a
    document in eval must never come from a document also in train, or the
    eval score would be measuring memorization of near-identical content,
    not generalization.
    """
    document_hashes = sorted({r.metadata.source_hash for r in records})
    if len(document_hashes) <= 1:
        return SplitResult(train=list(records), eval=[], leakage_warning=True)

    rng = random.Random(seed)
    shuffled = document_hashes[:]
    rng.shuffle(shuffled)
    eval_count = max(1, round(len(shuffled) * eval_fraction))
    eval_hashes = set(shuffled[:eval_count])

    train = [r for r in records if r.metadata.source_hash not in eval_hashes]
    eval_records = [r for r in records if r.metadata.source_hash in eval_hashes]
    return SplitResult(train=train, eval=eval_records, leakage_warning=False)
