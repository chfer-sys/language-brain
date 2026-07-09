"""Parsers for dictionary source files.

Each module under ``parsers/`` implements ``parse(path: str) -> list[dict]``
where each dict has keys: ``hanzi``, ``pinyin``, ``english``, ``frequency``,
``part_of_speech``.
"""

from scripts.parsers.subtlex_csv import parse

__all__ = ["parse"]
