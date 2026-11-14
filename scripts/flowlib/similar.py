"""Find closed tickets that read like a new one, to show the estimator real sizes.

Pure, no dependencies: TF-IDF cosine over title and body. Paths count double,
since two tickets naming the same directory usually touch the same code.
"""

from __future__ import annotations

import math
import re
from collections import Counter

# Words every ticket uses, which say nothing about the work.
STOP = set("""the and for with that this from into are not but can its it's has have was were will
when what which who how all any each one two out our you your they them their then than also only
use used uses using need needs should must may per via etc see new add adds added make makes
ticket issue acceptance criteria expected paths part done""".split())


def tokens(text: str) -> list:
    text = (text or "").lower()
    paths = re.findall(r"[\w.-]+(?:/[\w.*-]+)+", text)
    # every directory prefix of a path, so backend/internal/plans/x.go meets backend/internal/plans/
    prefixes = []
    for p in paths:
        parts = p.strip("/").split("/")
        prefixes += ["/".join(parts[: i + 1]) for i in range(1, len(parts))]
    words = [w for w in re.findall(r"[a-z][a-z0-9_]{2,}", text) if w not in STOP]
    return words + prefixes * 2


def _vector(toks: list, idf: dict) -> dict:
    counts = Counter(toks)
    vec = {t: (1 + math.log(n)) * idf.get(t, 0.0) for t, n in counts.items()}
    norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
    return {t: v / norm for t, v in vec.items()}


class Index:
    """Closed cases (backtest.cases rows), searchable by text."""

    def __init__(self, cases: list):
        self.cases = cases
        docs = [tokens(f"{c['title']}\n{c.get('body', '')}") for c in cases]
        df = Counter(t for d in docs for t in set(d))
        n = len(docs) or 1
        self.idf = {t: math.log((1 + n) / (1 + k)) + 1 for t, k in df.items()}
        self.vectors = [_vector(d, self.idf) for d in docs]

    def nearest(self, title: str, body: str, k: int = 5, before: str | None = None,
                exclude: int | None = None) -> list:
        """The k most similar cases. `before` keeps only cases closed before that
        time, so a backtest never shows a ticket its own future."""
        q = _vector(tokens(f"{title}\n{body}"), self.idf)
        scored = []
        for case, vec in zip(self.cases, self.vectors):
            if case["number"] == exclude or (before and (case.get("closed_at") or "") >= before):
                continue
            sim = sum(w * vec.get(t, 0.0) for t, w in q.items())
            scored.append((sim, case))
        scored.sort(key=lambda x: -x[0])
        return [c for s, c in scored[:k] if s > 0]
