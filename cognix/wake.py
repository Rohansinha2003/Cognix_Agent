"""Wake-phrase matching on a speech transcript.

Speech recognisers have never seen the word "Cognix", so it comes back as
"Cognics", "Kognix", "Cog Nix", "Haykognix"… This module accepts those
spellings while refusing look-alikes that are not the wake phrase
("cognac", "cog mix", "The Cognix was off…").

Rules:
  * "hey/ok/hi … Cognix" wakes anywhere in an utterance.
  * A bare "Cognix" wakes only when it opens the utterance.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

WAKE_NAME = "Cognix"
WAKE_PHRASE = f"Hey {WAKE_NAME}"

GREETINGS = {"hey", "hay", "hi", "hello", "ok", "okay", "yo", "he", "heya"}

# co-g-n-i-x with the consonant/vowel slips recognisers make.
_NAME = r"[ck]o[gck]{1,2}n[aeiou](?:x|xs|cs|ks|cks)"
_NAME_RE = re.compile(rf"^{_NAME}$")
_GLUED_RE = re.compile(rf"^(?:hey|hay|he|hi|ok|okay)({_NAME})$")  # "haykognix"
_TOKEN_RE = re.compile(r"[a-z0-9']+")


@dataclass(frozen=True)
class WakeMatch:
    command: str   # what was said after the wake phrase ("" if nothing)
    greeted: bool  # True if a greeting ("hey", "ok"…) preceded the name


def _tokens(text: str):
    """(normalised token, start, end) for each word in the text."""
    lowered = text.lower()
    return [(m.group().replace("'", ""), m.start(), m.end()) for m in _TOKEN_RE.finditer(lowered)]


def find_wake(text: str) -> WakeMatch | None:
    """Locate the wake phrase; returns the command that follows it, or None."""
    toks = _tokens(text)
    for i, (tok, _start, end) in enumerate(toks):
        glued = bool(_GLUED_RE.match(tok))
        span_end = end
        is_name = glued or bool(_NAME_RE.match(tok))
        if not is_name and i + 1 < len(toks):
            # "cog nix" / "cog nicks": the name split across two words
            if _NAME_RE.match(tok + toks[i + 1][0]):
                is_name = True
                span_end = toks[i + 1][2]
        if not is_name:
            continue
        greeted = glued or (i > 0 and toks[i - 1][0] in GREETINGS)
        opens_utterance = all(t[0] in GREETINGS for t in toks[:i])
        if not (greeted or opens_utterance):
            continue  # "pass me the cognix" — a mis-hearing, not a wake
        command = text[span_end:].strip(" \t\n,.!?;:-–—\"'")
        return WakeMatch(command=command, greeted=greeted)
    return None


def strip_wake(text: str) -> str:
    """Remove a leading wake phrase from a command, if present."""
    match = find_wake(text)
    if match is not None:
        return match.command
    return text.strip()
