"""PII anonymizer: strips personal data before sending prompts to foreign AI.

TZ section 10.1. Applied automatically for OPENAI / ANTHROPIC providers so that
no personal data ever leaves the RU perimeter (152-FZ).
"""
from __future__ import annotations

import re

# Pre-compiled for speed
PHONE_RE = re.compile(r"\+7[\s\-\(]?\d{3}[\s\-\) ]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
NAME_RE = re.compile(r"\b[А-ЯЁ][а-яё]{2,}\s+[А-ЯЁ][а-яё]{2,}\b")
ADDRESS_RE = re.compile(
    r"(г\.?\s+)?[А-ЯЁ][а-яё]+,\s+(ул\.?\s+|пр-кт\.?\s+)?[А-ЯЁа-яё\s]+\d+[а-яё]?"
)


def anonymize(text: str) -> str:
    """Replace PII with placeholders before sending to foreign AI providers."""
    if not text:
        return text
    text = PHONE_RE.sub("[PHONE]", text)
    text = EMAIL_RE.sub("[EMAIL]", text)
    text = NAME_RE.sub("[NAME]", text)
    text = ADDRESS_RE.sub("[ADDRESS]", text)
    return text
