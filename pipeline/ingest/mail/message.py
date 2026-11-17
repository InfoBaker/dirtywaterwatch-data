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


def verified(mail: Mail, spec: dict) -> tuple[bool, str]:
    """Whether the message comes from the list's sender, by Cloudflare's own check: the From domain is one of the
    list's senders, and DMARC passed for that From domain or DKIM passed for one of the list's signing domains."""
    if not mail.auth_found:
        return False, "no Authentication-Results from the receiving host"
    if not _matches(mail.from_domain, spec.get("senders") or []):
        return False, "From domain is not one of the list's senders"
    if mail.dmarc_pass_from and mail.dmarc_pass_from == mail.from_domain:
        return True, "DMARC pass for the From domain"
    if any(_matches(d, spec.get("dkim") or []) for d in mail.dkim_pass):
        return True, "DKIM pass for the list's signing domain"
    return False, "neither DMARC for the From domain nor DKIM for the list's signing domain passed"


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
