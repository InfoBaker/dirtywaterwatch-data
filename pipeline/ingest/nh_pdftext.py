"""Minimal pure-Python PDF text extraction for the NH permittee PDFs (shared helper, not a feed).

pdfplumber and pdftotext are not available on the build machine, so this reads what simple
generated PDFs need: objects and object streams, FlateDecode, content streams and Form XObjects,
and the text operators (Tf Tm Td TD T* TL Tj TJ ' "), with literal and hex strings decoded as
Latin-1 (fonts without ToUnicode maps; fine for report tables of numbers and dates). It returns
positioned text items so callers can rebuild table rows by y and columns by x. Scanned PDFs
(images only) return no items: the caller records a parse_error.
"""
from __future__ import annotations

import re
import zlib

_OBJ = re.compile(rb"(\d+)\s+(\d+)\s+obj\b(.*?)\bendobj", re.S)
_STREAM = re.compile(rb"stream\r?\n(.*?)\r?\n?endstream", re.S)


def _streams(pdf: bytes) -> dict[int, tuple[bytes, bytes | None]]:
    """obj number -> (dictionary bytes, decoded stream or None)."""
    out: dict[int, tuple[bytes, bytes | None]] = {}
    for m in _OBJ.finditer(pdf):
        num, body = int(m.group(1)), m.group(3)
        sm = _STREAM.search(body)
        head = body[:sm.start()] if sm else body
        data = None
        if sm:
            raw = sm.group(1)
            if b"/FlateDecode" in head:
                try:
                    data = zlib.decompressobj().decompress(raw)
                except zlib.error:
                    data = None
            elif b"/Filter" not in head:
                data = raw
        out[num] = (head, data)
        if b"/ObjStm" in head and data:   # objects packed in an object stream
            first = int(re.search(rb"/First\s+(\d+)", head).group(1))
            nums = re.findall(rb"(\d+)\s+(\d+)", data[:first])
            offs = [(int(a), int(b)) for a, b in nums]
            for i, (onum, off) in enumerate(offs):
                end = offs[i + 1][1] if i + 1 < len(offs) else len(data) - first
                out.setdefault(onum, (data[first + off:first + end], None))
    return out


_TOK = re.compile(rb"\((?:\\.|[^\\()]|\((?:\\.|[^\\()])*\))*\)|<[0-9A-Fa-f\s]*>|\[|\]|/[^\s/\[\]()<>]+|[-+]?\d*\.?\d+|[A-Za-z'\"*]+[0-9]?|<<|>>", re.S)


def _lit(tok: bytes) -> str:
    if tok.startswith(b"<"):
        h = re.sub(rb"\s", b"", tok[1:-1])
        if len(h) % 2:
            h += b"0"
        return bytes.fromhex(h.decode()).decode("latin-1")
    s = tok[1:-1]
    out, i = bytearray(), 0
    esc = {b"n": b"\n", b"r": b"\r", b"t": b"\t", b"b": b"\b", b"f": b"\f", b"(": b"(", b")": b")", b"\\": b"\\"}
    while i < len(s):
        c = s[i:i + 1]
        if c == b"\\" and i + 1 < len(s):
            n = s[i + 1:i + 2]
            if n in esc:
                out += esc[n]
                i += 2
                continue
            m = re.match(rb"[0-7]{1,3}", s[i + 1:i + 4])
            if m:
                out.append(int(m.group(0), 8) & 255)
                i += 1 + len(m.group(0))
                continue
            i += 1
            continue
        out += c
        i += 1
    return out.decode("latin-1")


def _run(content: bytes, items: list, page: int) -> None:
    stack: list = []
    tm = [1, 0, 0, 1, 0, 0]
    lm = [1, 0, 0, 1, 0, 0]
    leading = 0.0

    def move(tx, ty):
        nonlocal tm, lm
        lm = [lm[0], lm[1], lm[2], lm[3], lm[4] + tx * lm[0] + ty * lm[2], lm[5] + tx * lm[1] + ty * lm[3]]
        tm = list(lm)

    def show(text):
        if text.strip():
            items.append({"page": page, "x": round(tm[4], 2), "y": round(tm[5], 2), "text": text})

    arr = None
    for t in _TOK.findall(content):
        if t == b"[":
            arr = []
            continue
        if t == b"]":
            stack.append(arr)
            arr = None
            continue
        if arr is not None:
            arr.append(t)
            continue
        if t[:1] in b"(<" and t not in (b"<<",):
            stack.append(t)
            continue
        if re.fullmatch(rb"[-+]?\d*\.?\d+", t) or t.startswith(b"/"):
            stack.append(t)
            continue
        op = t
        try:
            if op == b"BT":
                tm, lm = [1, 0, 0, 1, 0, 0], [1, 0, 0, 1, 0, 0]
            elif op == b"Tm":
                lm = [float(x) for x in stack[-6:]]
                tm = list(lm)
            elif op == b"Td":
                move(float(stack[-2]), float(stack[-1]))
            elif op == b"TD":
                leading = -float(stack[-1])
                move(float(stack[-2]), float(stack[-1]))
            elif op == b"TL":
                leading = float(stack[-1])
            elif op == b"T*":
                move(0, -leading)
            elif op == b"Tj":
                show(_lit(stack[-1]))
            elif op == b"'":
                move(0, -leading)
                show(_lit(stack[-1]))
            elif op == b'"':
                move(0, -leading)
                show(_lit(stack[-1]))
            elif op == b"TJ":
                parts = stack[-1] if isinstance(stack[-1], list) else []
                show("".join(_lit(p) for p in parts if p[:1] in b"(<"))
        except (IndexError, ValueError, TypeError):
            pass
        stack = []


def text_items(pdf: bytes) -> list[dict]:
    """Positioned text items: {page, x, y, text}. 'page' counts content streams in order (one
    per page or Form XObject, whichever carries the text)."""
    objs = _streams(pdf)
    items: list[dict] = []
    page = 0
    for num in sorted(objs):
        head, data = objs[num]
        if not data or b"/Image" in head or b"/ObjStm" in head or b"/XRef" in head:
            continue
        if b"BT" not in data:
            continue
        page += 1
        _run(data, items, page)
    return items


def rows(items: list[dict], ytol: float = 3.0) -> list[list[dict]]:
    """Group items into rows by page and y (top to bottom), each row sorted by x."""
    out: list[list[dict]] = []
    for p in sorted({i["page"] for i in items}):
        its = sorted((i for i in items if i["page"] == p), key=lambda i: (-i["y"], i["x"]))
        cur: list[dict] = []
        for it in its:
            if cur and abs(it["y"] - cur[0]["y"]) > ytol:
                out.append(sorted(cur, key=lambda i: i["x"]))
                cur = []
            cur.append(it)
        if cur:
            out.append(sorted(cur, key=lambda i: i["x"]))
    return out
