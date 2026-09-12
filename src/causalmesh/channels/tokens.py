"""Token accounting for coordination cost (spec §45).

§45 requires coordination cost to be separable from task-reasoning cost, and
both are reported in tokens because that is the unit a model's context is
actually billed and bounded in.

**This is an estimator, not a tokenizer.** No model runs in the mock-agent
configuration, so there is no authoritative tokenizer to consult, and
importing one would add a heavy dependency whose vocabulary would differ from
whichever model a later study used anyway.

The estimate is deliberately simple and its bias is documented rather than
hidden: roughly four characters per token, the widely used approximation for
English text under byte-pair encodings. It will overcount on repetitive
structured JSON, which BPE compresses well, and undercount on dense
identifiers.

What matters for the experiment is that the estimator is **deterministic and
identical across arms**. The C1→C2 contrast is a ratio between two channels
measured the same way, so a constant multiplicative bias cancels. An
absolute token count from this module should not be quoted as a model's true
usage, and `docs/analysis.md` says so.
"""

from __future__ import annotations

__all__ = ["CHARS_PER_TOKEN", "estimate_tokens"]

# The conventional approximation for English text under BPE tokenizers.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    """Estimate the token count of a string.

    Rounds up, so any non-empty text costs at least one token: reporting zero
    for a short injection would make a real coordination cost disappear from
    the accounting entirely.
    """
    if not text:
        return 0
    return (len(text) + CHARS_PER_TOKEN - 1) // CHARS_PER_TOKEN
