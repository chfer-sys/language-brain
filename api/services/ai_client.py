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
    '  "english": string, a literal English translation\n'
    '  "meaning": string, a richer English gloss that captures the '
    "communicative intent — what the speaker is actually trying to say, "
    'not just a word-for-word rendering\n'
    '  "words": list of single-character or contiguous tokens, in order\n'
    '  "word_refs": list of tone-marked pinyin, one per entry in "words"\n'
    '  "groups": list of { "id": slug, "display_name": human, '
    '"description": short } — topic categories the sentence belongs to\n'
    '  "antonyms": list of pinyin (with tones) for any word in this '
    "sentence whose opposite is also a word the user likely knows\n"
    "\n"
    "Never include prose outside the JSON. Never echo the prompt. "
    "Never include the user's note in the response."
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
            response = requests.post(
                url, headers=headers, json=payload, timeout=30
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

    Tolerates models that wrap the JSON in a ```json ... ``` fence.
    Raises :class:`ValueError` if the content is not parseable, or
    if any required key is missing.
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

    groups_raw = data["groups"]
    if not isinstance(groups_raw, list):
        raise ValueError("'groups' must be a list")

    groups: list[ProposedGroup] = []
    for g in groups_raw:
        if not isinstance(g, dict):
            raise ValueError("each group must be an object")
        gid = g.get("id")
        if not isinstance(gid, str) or not gid:
            raise ValueError("each group must have a non-empty string 'id'")
        groups.append(
            ProposedGroup(
                id=gid,
                display_name=str(g.get("display_name", "") or ""),
                description=str(g.get("description", "") or ""),
            )
        )

    words = data["words"]
    if not isinstance(words, list) or not all(isinstance(w, str) for w in words):
        raise ValueError("'words' must be a list of strings")

    word_refs = data["word_refs"]
    if not isinstance(word_refs, list) or not all(isinstance(w, str) for w in word_refs):
        raise ValueError("'word_refs' must be a list of strings")

    antonyms = data["antonyms"]
    if not isinstance(antonyms, list) or not all(isinstance(a, str) for a in antonyms):
        raise ValueError("'antonyms' must be a list of strings")

    return ProposedLabels(
        pinyin=str(data["pinyin"]),
        english=str(data["english"]),
        meaning=str(data["meaning"]),
        words=list(words),
        word_refs=list(word_refs),
        groups=groups,
        antonyms=list(antonyms),
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
