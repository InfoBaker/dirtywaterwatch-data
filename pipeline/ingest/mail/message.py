"""One stored message read as data: its text, its sender's verified domain and its times (not a feed).

The raw message (RFC 822, as the mail Worker archived it) is parsed in memory and never written anywhere by the
pipeline. Only what a parser takes from labelled lines reaches a record; addresses, phones and signatures stay behind.
"""
from __future__ import annotations

import email
import email.policy
import email.utils
import html
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime

# Cloudflare Email Routing writes its own Authentication-Results at the top of every message it accepts; a header
# further down was written by someone else (the sender can put anything there), so only the first one is read, and only
# when it names Cloudflare's receiving host.
AUTHSERV = "mx.cloudflare.net"


@dataclass
class Mail:
    inbound_id: str
    received_at: str                    # the mail Worker's receipt time (UTC ISO): the notice's publication time to us
    list_id: str | None
    subject: str = ""
    text: str = ""                      # the plain-text part, else the HTML part as text
    sent_at: str | None = None          # the Date header, as the sender's clock wrote it (kept, never a start)
    from_domain: str | None = None
    dmarc_pass_from: str | None = None  # header.from of a DMARC pass in Cloudflare's result
    dkim_pass: set = field(default_factory=set)   # signing domains with dkim=pass in Cloudflare's result
    auth_found: bool = False
    marks: str = ""                     # the headers a platform binding may name (List-Id, List-Unsubscribe, Sender,
                                        # Return-Path, X-* ids), for verification only; never saved


@dataclass
class Result:
    kind: str                           # notice | not_notice | account | needs_rule | failed
    records: list = field(default_factory=list)
    note: str | None = None


def html_to_text(h: str) -> str:
    h = re.sub(r"(?is)<(script|style|head)\b.*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>|</tr>|</td>|</th>|</h\d>|</table>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    return html.unescape(h)


def tidy(t: str) -> str:
    t = t.replace("\r\n", "\n").replace("\r", "\n").replace("\xa0", " ").replace("​", "")
    t = re.sub(r"[ \t]+", " ", t)
    t = re.sub(r" ?\n ?", "\n", t)
    return re.sub(r"\n{2,}", "\n", t).strip()


def _domain(addr: str | None) -> str | None:
    if not addr:
        return None
    _, a = email.utils.parseaddr(str(addr))
    return a.rsplit("@", 1)[1].lower().strip(".> ") if "@" in a else None


def read_auth(value: str) -> tuple[bool, str | None, set]:
    """(Cloudflare's header?, DMARC-passed From domain, DKIM-passed signing domains) from one Authentication-Results."""
    v = re.sub(r"\s+", " ", value or "")
    if not v.lower().lstrip().startswith(AUTHSERV):
        return False, None, set()
    dmarc = None
    dkim = set()
    for part in v.split(";"):
        p = part.strip().lower()
        m = re.match(r"dmarc=pass\b.*?header\.from=([\w.-]+)", p)
        if m:
            dmarc = m.group(1).strip(".")
        m = re.match(r"dkim=pass\b(.*)", p)
        if m:
            d = re.search(r"header\.d=([\w.-]+)", m.group(1))
            i = re.search(r"header\.i=[^@\s]*@([\w.-]+)", m.group(1))
            for x in (d, i):
                if x:
                    dkim.add(x.group(1).strip("."))
    return True, dmarc, dkim


def parse_mail(raw: bytes, inbound_id: str, received_at: str, list_id: str | None) -> Mail:
    m = email.message_from_bytes(raw, policy=email.policy.default)
    mail = Mail(inbound_id=inbound_id, received_at=received_at, list_id=list_id)
    try:
        mail.subject = tidy(str(m.get("subject") or ""))
    except Exception:  # noqa: BLE001 - a malformed header is read as empty
        mail.subject = ""
    try:
        d = email.utils.parsedate_to_datetime(str(m.get("date"))) if m.get("date") else None
        mail.sent_at = d.astimezone(UTC).isoformat().replace("+00:00", "Z") if d and d.tzinfo else None
    except (TypeError, ValueError):
        mail.sent_at = None
    try:
        mail.from_domain = _domain(str(m.get("from") or ""))
    except Exception:  # noqa: BLE001
        mail.from_domain = None
    auth = m.get_all("authentication-results") or []
    try:
        mail.marks = "\n".join(f"{k}: {v}" for k, v in m.items()
                               if k.lower() in ("list-id", "list-unsubscribe", "sender", "return-path")
                               or k.lower().startswith("x-"))
    except Exception:  # noqa: BLE001
        mail.marks = ""
    if auth:
        mail.auth_found, mail.dmarc_pass_from, mail.dkim_pass = read_auth(str(auth[0]))
    plain, htm = None, None
    for part in m.walk():
        if part.is_multipart() or part.get_content_disposition() == "attachment":
            continue
        ct = part.get_content_type()
        try:
            body = part.get_content()
        except Exception:  # noqa: BLE001 - an undecodable part is skipped
            continue
        if not isinstance(body, str):
            continue
        if ct == "text/plain" and plain is None:
            plain = body
        elif ct == "text/html" and htm is None:
            htm = body
    mail.text = tidy(plain if plain and plain.strip() else html_to_text(htm or ""))
    return mail


def _matches(dom: str | None, allowed) -> bool:
    return bool(dom) and any(dom == a or dom.endswith("." + a) for a in allowed)


def verified(mail: Mail, spec: dict) -> tuple[str | None, str]:
    """(trust, how) by Cloudflare's own check. "operator": the From domain is one of the operator's own domains
    (spec.senders) and DMARC passed for it, or DKIM passed for that same domain. "platform": the message was sent
    through a shared platform the list uses (spec.platform.domains: Everbridge, Constant Contact), DKIM or DMARC
    passed for that platform, the From domain is the operator's or the platform's, and every mark the binding names
    (spec.platform.body_marks in the text, header_marks in the List-Id, List-Unsubscribe, Sender, Return-Path or
    X- headers) is present; a platform's customers can all send from its domain, so such a message proves less, and
    operator_mail lets it only add to another source's record of the same discharge. None: neither."""
    if not mail.auth_found:
        return None, "no Authentication-Results from the receiving host"
    own = spec.get("senders") or []
    if _matches(mail.from_domain, own):
        if mail.dmarc_pass_from and mail.dmarc_pass_from == mail.from_domain:
            return "operator", "DMARC pass for the operator's From domain"
        if any(d == mail.from_domain or _matches(d, own) for d in mail.dkim_pass):
            return "operator", "DKIM pass for the operator's domain"
    plat = spec.get("platform") or {}
    pdoms = plat.get("domains") or []
    from_ok = _matches(mail.from_domain, own) or (plat.get("allow_platform_from") and _matches(mail.from_domain, pdoms))
    if pdoms and from_ok:
        passed = any(_matches(d, pdoms) for d in mail.dkim_pass) or \
            (mail.dmarc_pass_from and _matches(mail.dmarc_pass_from, pdoms))
        if passed:
            missing = [m for m in plat.get("body_marks") or [] if m not in mail.text]
            missing += [m for m in plat.get("header_marks") or [] if m not in mail.marks]
            if not missing:
                return "platform", "DKIM or DMARC pass for the list's platform, with the binding's marks"
            return None, "the list's platform passed, but a mark of the operator's binding is missing"
    if not _matches(mail.from_domain, own + list(pdoms)):
        return None, "From domain is not one of the list's senders"
    return None, "neither DMARC nor DKIM passed for the operator's domain or the list's platform"


WATER_WORDS = re.compile(r"(?i)\b(river|brook|canal|creek|stream|pond|lake|bay|harbou?r|reservoir|basin|channel|cove|"
                         r"sound|inlet|estuary|run|kill|fork|branch|ocean|beach)\b")
VOLUME_SHAPE = (r"(?:about |approximately |approx\.? |est\.? |estimated )?\d[\d,]*(?:\.\d+)?"
                r"(?:\s*(?:gallons?|gal\.?|million gallons|MG|MGal))?")
PLACE_SHAPE = r"[A-Za-z][A-Za-z .,'&()/-]*"


def clean_text(v, shape: str | None = None, maxlen: int = 120, water: bool = False) -> str | None:
    """A labelled value fit to save: one line, at most maxlen, no '@', unchanged by the pipeline's scrub of phones,
    addresses and staff names, matching `shape` when one is given, and naming a water when `water`; else None (the
    caller notes which field was set aside, never its text)."""
    from common import scrub_text
    if v is None:
        return None
    v = re.sub(r"\s+", " ", str(v)).strip(" :;")
    if not v or len(v) > maxlen or "@" in v or scrub_text(v) != v:
        return None
    if shape and not re.fullmatch(shape, v, re.I):
        return None
    if water and not WATER_WORDS.search(v):
        return None
    return v


def outfall_number(text: str | None) -> tuple[int | None, str]:
    """'CSO 021B' -> (21, 'B'); 'SPR012' -> (12, ''); 'HOL02' -> (2, ''); anything else -> (None, '')."""
    m = re.search(r"(?i)\b(?:CSO|SPR|HOL|SOM|OUTFALL)[\s#_-]*0*(\d{1,3})(?:[_-]?([A-Z]))?(?![\d])", text or "")
    if not m:
        return None, ""
    return int(m.group(1)), (m.group(2) or "").upper()


def iso_utc(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


def parse_iso(s) -> datetime | None:
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00")) if s else None
    except ValueError:
        return None
    return d.replace(tzinfo=UTC) if d is not None and d.tzinfo is None else d
