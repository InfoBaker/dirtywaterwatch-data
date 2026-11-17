"""Parsers of operators' e-mail notices (not a feed: pipeline/ingest/operator_mail.py reads the stored mail and calls them).

One module per sender format. Each exposes VERSION (raise it when the parser's output changes, so stored messages are
read again) and parse(mail, spec, ctx) -> Result. A parser reads labelled facts only; it never copies a signature, a
greeting or a contact line, and a shape it does not know is a failure with its reason, never a guess.
"""
from __future__ import annotations

from . import ct_deep_press, holyoke, manchester, somerville, springfield

PARSERS = {m.NAME: m for m in (holyoke, springfield, manchester, somerville, ct_deep_press)}
