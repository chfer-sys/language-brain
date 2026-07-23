"""AI client: single chokepoint for all calls to the language model.

SPEC §6 AC8: every call to the AI provider goes through this module.
Tests monkey-patch the `propose_labels` symbol exported here; the
rest of the application never reaches into the underlying provider
directly.

Two implementations live in this module:

* :class:`HttpAIClient` — talks to the configured MiniMax-compatible
  HTTP endpoint using the `LANGUAGE_BRAIN_AI_KEY` from settings.
  Used in production. The key is read from settings (which is
  populated from env at process start); it is never logged, printed,
  or included in any error message.

* :class:`MockAIClient` — returns hand-crafted labels without any
  network call. Used in tests, in the offline-labeling fallback
  (future), and as a safety net when no key is configured.

A factory :func:`get_ai_client` returns the mock when no key is
configured and the HTTP client otherwise. Both implementations
expose the same `propose_labels(hanzi, note) -> ProposedLabels`
method, which is the only function the rest of the app calls.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Protocol

from api.config import get_settings

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public data model
# ---------------------------------------------------------------------------


@dataclass
class ProposedGroup:
    """A group the AI proposes for the new sentence.

    Mirrors the input shape of ``ensure_groups_from_proposed`` in
    ``api.services.group_helpers``.
    """

    id: str
    display_name: str = ""
    description: str = ""


@dataclass
class ProposedLabels:
    """The full set of labels the AI proposes for a hanzi sentence.

    All fields are populated by both the HTTP and mock clients, per
    SPEC §6 AC6. The user edits any field before committing the
    sentence to the vault.
    """

    pinyin: str
    english: str
    meaning: str
    words: list[str] = field(default_factory=list)
    word_refs: list[str] = field(default_factory=list)
    groups: list[ProposedGroup] = field(default_factory=list)
    antonyms: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return the JSON-serializable dict shape AC6 requires."""
        return {
            "pinyin": self.pinyin,
            "english": self.english,
            "meaning": self.meaning,
            "words": list(self.words),
            "word_refs": list(self.word_refs),
            "groups": [g.__dict__.copy() for g in self.groups],
            "antonyms": list(self.antonyms),
        }


# ---------------------------------------------------------------------------
# Client protocol
# ---------------------------------------------------------------------------


class AIClient(Protocol):
    """The single contract the rest of the app uses.

    Implementations: :class:`HttpAIClient`, :class:`MockAIClient`.
    """

    def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
        """Return the AI's label proposals for ``hanzi``.

        ``note`` is an optional user-supplied English hint. The mock
        client ignores it; the HTTP client passes it through.
        """
        ...


# ---------------------------------------------------------------------------
# System prompt — kept here so the format is auditable in one place
# ---------------------------------------------------------------------------


_SYSTEM_PROMPT: str = (
    "You are a labeling assistant for a Chinese language learner's "
    "personal knowledge base. The user gives you a hanzi sentence and "
    "optionally a short English note. You respond with a single JSON "
    "object and nothing else. The JSON object has these keys:\n"
    '  "pinyin": string, tone-marked pinyin for the whole sentence\n'
    '  "english": string, a literal English translation (the kind a '
    "dictionary would give)\n"
    '  "meaning": string, a richer English gloss that captures the '
    "communicative intent — what the speaker is actually trying to say, "
    "not just a word-for-word rendering. This MUST be a different string "
    "from `english` and MUST add information the literal translation "
    "omits (situational context, emotional register, the speaker's "
    "intent, implied subject/object). If the literal and the rich gloss "
    "would be identical, the sentence has no hidden intent — set "
    "`meaning` to a one-sentence paraphrase that explains WHEN and WHY "
    "a learner would use this sentence, not just WHAT it says.\n"
    '  "words": list of single-character or contiguous tokens, in order\n'
    '  "word_refs": list of tone-marked pinyin, one per entry in "words"\n'
    '  "groups": list of { "id": slug, "display_name": human, '
    '"description": short } — topic categories the sentence belongs to\n'
    '  "antonyms": list of HAZI characters that are antonyms of any '
    "word in this sentence. Use hanzi (e.g. 饱, 热), NOT pinyin. "
    "Only include antonyms the user would plausibly already know.\n"
    "\n"
    "SEGMENTATION RULES (your words[] must match these):\n"
    "1. Treat the following compounds as SINGLE words (do not split):\n"
    "   - Verbs with 了-complement: 受不了, 了解, 了不起, 得到, 觉得, "
    "感到, 学会, 记得, 遇见, 想到, 发现\n"
    "   - Function-word compounds: 为了, 除了, 罢了, 得了\n"
    "   - High-frequency words: 可以, 没有, 什么, 怎么, 为什么, 因为, "
    "所以, 但是, 现在, 今天, 明天, 昨天, 时候, 意思, 问题, 喜欢, 知道\n"
    "2. The character 了 is POLYSEMOUS:\n"
    "   - 'liǎo' (3rd tone, complement) in compounds like 受不了, 了解, "
    "了不起 — keep these as single tokens\n"
    "   - 'le' (neutral tone, aspect particle) in sentence-final "
    "positions like 吃了, 走了 — split off as its own token\n"
    "3. Match the lengths of `words` and `word_refs`. Each entry in "
    "words is one hanzi token; the matching entry in word_refs is "
    "the tone-marked pinyin for that entire token.\n"
    "\n"
    "Never include prose outside the JSON. Never echo the prompt. "
    "Never include the user's note in the response. Never set "
    "`meaning` equal to `english`."
)


def _user_prompt(hanzi: str, note: str) -> str:
    if note:
        return f"Sentence: {hanzi}\nNote: {note}"
    return f"Sentence: {hanzi}"


# ---------------------------------------------------------------------------
# HTTP client — production path
# ---------------------------------------------------------------------------


class HttpAIClient:
    """Talks to the configured MiniMax-compatible HTTP endpoint.

    The API key is read from ``get_settings().ai_key`` lazily on each
    call, so a key added to the environment after process start is
    picked up on the next request (useful for tests and for the
    offline-then-online case described in SPEC §7).
    """

    def __init__(self, endpoint: str | None = None, model: str | None = None) -> None:
        s = get_settings()
        self._endpoint = endpoint or s.ai_endpoint
        self._model = model or s.ai_model

    # ponytail: 256-entry cache; personal scale, repeat sentences are instant. Ceiling: restart clears. Cached object must not be mutated by callers.
    @lru_cache(maxsize=256)
    def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
        if not isinstance(hanzi, str) or not hanzi.strip():
            raise ValueError("hanzi must be a non-empty string")
        if not isinstance(note, str):
            raise ValueError("note must be a string")

        s = get_settings()
        if s.ai_key is None:
            # Defensive: the factory should not have built an HTTP
            # client when the key is unset. Fail loudly rather than
            # silently downgrade to a mock.
            raise RuntimeError(
                "HttpAIClient.propose_labels called with no AI key configured; "
                "use MockAIClient or set LANGUAGE_BRAIN_AI_KEY"
            )

        # The key is read here, used in the Authorization header, and
        # never stored on self, never logged, never put in an error
        # message. The scrub filter in api.config catches the rare
        # accidental log line, but the right answer is to not log it
        # at all.
        api_key = s.ai_key.get_secret_value()

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _user_prompt(hanzi, note)},
            ],
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            # ponytail: caps runaway reasoning tokens (30-60s → ~10-20s); 2000 leaves headroom for the ~300-token JSON — tune down if truncations appear (they degrade to the local fallback).
            "max_tokens": 2000,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = self._endpoint.rstrip("/") + "/chat/completions"

        # The actual HTTP call. We import requests lazily so the test
        # environment doesn't need it installed when only the mock
        # client is exercised.
        import requests  # type: ignore[import-untyped]

        try:
            # ponytail: 120s ceiling — reasoning models (deepseek-v4-flash) run 30-60s; the prior 30s timed out every call.
            response = requests.post(
                url, headers=headers, json=payload, timeout=120
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            # Sanitize: do not include the URL with any embedded key,
            # do not include the response body (which may echo the
            # prompt with the user's note). Just the status if known.
            status = getattr(getattr(exc, "response", None), "status_code", None)
            raise RuntimeError(
                f"AI request failed (status={status}): {type(exc).__name__}"
            ) from exc

        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                "AI response missing expected 'choices[0].message.content' field"
            ) from exc

        return _parse_labels_json(content)


# ---------------------------------------------------------------------------
# Mock client — used in tests and offline
# ---------------------------------------------------------------------------


class MockAIClient:
    """Returns hand-crafted labels without any network call.

    The default mock makes no attempt at translation quality; tests
    inspect the shape. A test that needs realistic labels can pass a
    `proposer` callable to the constructor — this is the seam T9
    (and any future integration test) uses to inject a richer
    fixture.
    """

    def __init__(self, proposer: Any | None = None) -> None:
        self._proposer = proposer
        self.call_count: int = 0
        self.last_hanzi: str | None = None
        self.last_note: str | None = None

    def propose_labels(self, hanzi: str, note: str = "") -> ProposedLabels:
        if not isinstance(hanzi, str) or not hanzi.strip():
            raise ValueError("hanzi must be a non-empty string")
        if not isinstance(note, str):
            raise ValueError("note must be a string")

        self.call_count += 1
        self.last_hanzi = hanzi
        self.last_note = note

        if self._proposer is not None:
            return self._proposer(hanzi, note)

        # Default: derive labels from the hanzi itself, naively.
        # Tests that care about real pinyin/english/meaning pass a
        # custom proposer; this default is for the "I have a key but
        # want to bypass the network" path.
        tokens = [ch for ch in hanzi if not ch.isspace()]
        return ProposedLabels(
            pinyin=hanzi,  # placeholder; not valid pinyin
            english=note or "(mock translation)",
            meaning=note or "(mock meaning gloss)",
            words=tokens,
            word_refs=tokens,  # placeholder; not valid pinyin
            groups=[],
            antonyms=[],
        )


# ---------------------------------------------------------------------------
# Parsing — used by HttpAIClient and any test that builds labels from JSON
# ---------------------------------------------------------------------------


def _parse_labels_json(content: str) -> ProposedLabels:
    """Parse the AI's JSON content into a :class:`ProposedLabels`.

    Tolerant of three model behaviors observed in the wild:

    1. **Markdown fence** — some models wrap JSON in ```` ```json ... ``` ````;
       we strip the fence.
    2. **Reasoning prefix** — some models (notably MiniMax-M2) prepend a
       ``<think>...</think>`` block before the JSON. We strip the
       entire ``<think>...</think>`` block (handling the case where
       it has no closing tag gracefully).
    3. **Rich object shapes** — some models return ``words: [{"word":
       "我", "pinyin": "wǒ", ...}]`` instead of the schema's
       ``words: ["我", ...]``. We normalize each entry to a string
       by extracting the most semantically relevant field (the
       ``word`` key for words/word_refs/antonyms, the ``id``+``display_name``
       for groups).

    Raises :class:`ValueError` if the content is not parseable, or
    if any required key is missing after normalization.
    """
    if not isinstance(content, str):
        raise ValueError("AI content must be a string")

    text = content.strip()

    # Strip a leading ```json fence if present.
    if text.startswith("```"):
        text = text.strip("`")
        # After stripping backticks, the first line may be "json".
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()

    # Strip reasoning blocks. Some models (MiniMax-M2) prepend a
    # <think>...</think> section. We remove the entire block. If the
    # block is unterminated (model got cut off mid-reasoning), we
    # fall through and let the JSON parser raise — it's better to
    # surface a parse error than silently lose the response.
    import re

    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()

    # If the response is still not pure JSON (e.g. the model wrapped
    # the JSON in prose), try to find the first balanced { ... } block.
    if not text.startswith("{"):
        start = text.find("{")
        if start == -1:
            # Not even a '{' in the response — fall through to the
            # json.loads below which will raise JSONDecodeError, then
            # we surface the standard "not valid JSON" message.
            pass
        else:
            # Walk braces to find the matching close.
            depth = 0
            end = -1
            for i in range(start, len(text)):
                ch = text[i]
                if ch == "{":
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end == -1:
                raise ValueError("AI content is not valid JSON: unbalanced braces")
            text = text[start:end]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"AI content is not valid JSON: {exc.msg}") from exc

    if not isinstance(data, dict):
        raise ValueError("AI content JSON must be an object")

    required = ("pinyin", "english", "meaning", "words", "word_refs", "groups", "antonyms")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"AI response missing required keys: {missing}")

    # Normalize each list field. Each entry may be either a bare
    # string (the schema's expected shape) or an object (the rich
    # shape some models return). We extract the most semantically
    # relevant field per entry.
    def _coerce_string(entry: object, *preferred_keys: str) -> str:
        if isinstance(entry, str):
            return entry
        if isinstance(entry, dict):
            for key in preferred_keys:
                val = entry.get(key)
                if isinstance(val, str) and val.strip():
                    return val
            # Fall back to the first string value in the dict.
            for val in entry.values():
                if isinstance(val, str) and val.strip():
                    return val
            return ""
        return str(entry)

    def _coerce_string_list(field_name: str, *preferred_keys: str) -> list[str]:
        raw = data[field_name]
        if not isinstance(raw, list):
            raise ValueError(f"'{field_name}' must be a list")
        out: list[str] = []
        for entry in raw:
            s = _coerce_string(entry, *preferred_keys)
            if s:
                out.append(s)
        return out

    words = _coerce_string_list("words", "word", "hanzi", "token")
    word_refs = _coerce_string_list("word_refs", "id", "ref", "pinyin", "word")
    antonyms = _coerce_string_list("antonyms", "antonym", "word", "id")

    groups_raw = data["groups"]
    if not isinstance(groups_raw, list):
        raise ValueError("'groups' must be a list")

    def _slugify(s: str) -> str:
        """Convert a free-form name into a slug id.

        Lowercase, spaces → hyphens, drop non-alphanumeric (except
        hyphens), then collapse runs of hyphens.
        """
        out = s.lower().strip().replace(" ", "-")
        out = "".join(c for c in out if c.isalnum() or c == "-")
        # Collapse consecutive hyphens.
        while "--" in out:
            out = out.replace("--", "-")
        return out.strip("-")

    groups: list[ProposedGroup] = []
    for g in groups_raw:
        if isinstance(g, str):
            # Bare-string group: derive a slug id from the name. We
            # do NOT auto-populate display_name (it stays empty when
            # the model only gave us a bare string) to preserve the
            # existing contract that bare-string entries produce
            # empty-string display_name.
            slug = _slugify(g)
            if not slug:
                continue
            groups.append(
                ProposedGroup(id=slug, display_name="", description="")
            )
            continue
        if not isinstance(g, dict):
            continue
        # Look for the id under several common keys (different models
        # use different field names). The first non-empty wins.
        gid = None
        for key in ("id", "name", "group", "slug", "display_name"):
            v = g.get(key)
            if isinstance(v, str) and v.strip():
                gid = v
                break
        if gid is None:
            continue
        clean_id = _slugify(gid)
        if not clean_id:
            continue
        # display_name: prefer the original 'display_name' key if it
        # looks like a name (not the id), otherwise fall back to the
        # pre-slugify gid.
        display_name = str(g.get("display_name") or "").strip()
        if not display_name:
            # Try 'name' as a friendlier display_name source.
            display_name = str(g.get("name") or "").strip()
        groups.append(
            ProposedGroup(
                id=clean_id,
                display_name=display_name,
                description=str(g.get("description") or "").strip(),
            )
        )

    return ProposedLabels(
        pinyin=str(data["pinyin"]).strip(),
        english=str(data["english"]).strip(),
        meaning=str(data["meaning"]).strip(),
        words=words,
        word_refs=word_refs,
        groups=groups,
        antonyms=antonyms,
    )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


_client_singleton: AIClient | None = None


def get_ai_client(force: str | None = None) -> AIClient:
    """Return a process-wide AI client.

    ``force`` is for tests and ops:
      * ``"mock"`` — always return a fresh :class:`MockAIClient`
      * ``"http"`` — always return an :class:`HttpAIClient`
        (raises if no key is configured)
      * ``None`` (default) — return mock when no key is configured,
        HTTP client otherwise. Also cached as a module singleton.
    """
    global _client_singleton
    if force == "mock":
        return MockAIClient()
    if force == "http":
        return HttpAIClient()

    if _client_singleton is None:
        s = get_settings()
        if s.ai_key is None:
            log.info("AI key not configured; using MockAIClient")
            _client_singleton = MockAIClient()
        else:
            log.info("AI key configured; using HttpAIClient")
            _client_singleton = HttpAIClient()

    return _client_singleton


def reset_ai_client_singleton() -> None:
    """Drop the cached singleton. Tests use this between cases."""
    global _client_singleton
    _client_singleton = None


__all__ = [
    "AIClient",
    "HttpAIClient",
    "MockAIClient",
    "ProposedGroup",
    "ProposedLabels",
    "get_ai_client",
    "reset_ai_client_singleton",
    "_parse_labels_json",
]
