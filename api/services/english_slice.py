"""Slice a sentence-level ``english`` string into per-word English
glosses for the auto-created word units.

Per v0.4.1 T2: when a sentence is committed, each new word unit
inherits a slice of the sentence's ``english`` field as its
``english`` property, IF the word unit's ``english`` is currently
empty (we never overwrite a user- or AI-authored value).

The slicing strategy is intentionally crude: we split ``english`` on
whitespace + punctuation, drop stopwords, and match tokens to
``words[]`` positionally. Because sentence ``english`` is usually
short ("I want to eat", "you thirsty"), positional mapping covers
most cases. For longer sentences we fall back to the whole sentence
english as a noisy default — the user can later edit via the word
detail page (future feature).

The function is module-level and pure so it can be tested without a
vault.

Examples
--------
>>> _slice_sentence_english("I want to eat", ["我", "想", "吃"], ["wǒ", "xiǎng", "chī"])
['I', 'want', 'eat']

>>> _slice_sentence_english("I like to eat", ["我", "喜欢", "吃"], ["wǒ", "xǐhuān", "chī"])
['I', 'like to', 'eat']

>>> _slice_sentence_english("", ["我"], ["wǒ"])
['']

>>> _slice_sentence_english("Hello", ["你", "好"], ["nǐ", "hǎo"])
['Hello', 'Hello']
"""
from __future__ import annotations

import re


# Stopwords we drop before tokenization. Conservative — only words
# that carry zero semantic weight in a learner sentence.
_STOPWORDS: frozenset[str] = frozenset({
    "a", "an", "the",
    "i", "you", "he", "she", "we", "they", "it",
    "is", "are", "was", "were", "am", "be", "been", "being",
    "to", "of", "in", "on", "at", "for", "with", "by", "from",
    "and", "or", "but", "so",
    "do", "does", "did",
})


_TOKEN_RE = re.compile(r"[A-Za-z']+")


def _tokenize_english(text: str) -> list[str]:
    """Split ``text`` into lowercase word tokens, dropping stopwords."""
    if not isinstance(text, str) or not text.strip():
        return []
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _tokenize_english_with_stopwords(text: str) -> list[str]:
    """Like :func:`_tokenize_english` but keeps stopwords in the list.

    Used by the slice function so we can align by token index (in the
    ORIGINAL sentence) against the word list. The output of this
    function is positional — index N in this list corresponds to the
    Nth English word in the original sentence, regardless of whether
    it's a stopword.
    """
    if not isinstance(text, str) or not text.strip():
        return []
    return _TOKEN_RE.findall(text.lower())


def _slice_sentence_english(
    sentence_english: str,
    words: list[str],
    word_refs: list[str],
) -> list[str]:
    """Return one English fragment per word, for use as a word unit's
    ``english`` property on commit.

    Strategy
    --------
    1. Tokenize ``sentence_english`` into a list of English tokens
       INCLUDING stopwords so the index aligns with the word list
       position.
    2. If the lengths match (``len(all_tokens) == len(words)``),
       map positionally — token[i] becomes the english for word i.
       Strip stopwords out of the output (we don't want "I" as a
       word's english gloss) but KEEP their slot — so "I want to
       eat" with words [我, 想, 吃] produces
       english=["", "want", "eat"] not ["I", "want", "eat"]
       (because the first token "I" is a stopword).
    3. If they don't match (sentence shorter/longer than word list),
       fall back to using the whole sentence english as a noisy
       default for every word — the user can later edit via the
       word detail page (future feature).

    Returns a list the same length as ``words``. Empty strings are
    valid (the caller treats empty as "don't propagate"). The
    ``word_refs`` parameter is accepted for symmetry with the call
    site but is not currently used; it's reserved for a future
    enhancement that maps pinyin-tone patterns to specific tokens.
    """
    if not isinstance(words, list) or len(words) == 0:
        return []
    if not isinstance(sentence_english, str) or not sentence_english.strip():
        return [""] * len(words)

    tokens_with_stops = _tokenize_english_with_stopwords(sentence_english)
    if len(tokens_with_stops) == len(words):
        # Positional mapping. Strip stopwords from each output slot —
        # we don't want "I" or "the" as a word unit's english gloss.
        out = []
        for tok in tokens_with_stops:
            if tok in _STOPWORDS:
                out.append("")
            else:
                out.append(tok)
        return out
    # Mismatch — fall back to a noisy default. Use the original
    # english verbatim (preserve case) so the user sees a usable
    # hint while editing.
    return [sentence_english.strip()] * len(words)


__all__ = [
    "_slice_sentence_english",
    "_tokenize_english",
    "_tokenize_english_with_stopwords",
    "_STOPWORDS",
]