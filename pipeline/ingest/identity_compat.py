"""Reader normalization frozen at e70b9758 for ID comparisons only.

These pure transforms never write a published field. Kept separately so preserving
source text cannot duplicate history or evade requests scoped to historical IDs.
"""
from __future__ import annotations
from ingest import identity_text

def al_numbers(v: str) -> str:
    """strip_house_numbers' leftovers (AL_HOUSE_RE): a leading house number or a list of them before a word."""
    import ingest.al_adem_sso as M

    def repl(m):
        before = v[max(0, m.start() - 16):m.start()]
        if M.ROUTE_WORD.search(before):
            return m.group(0)
        if M.ID_WORD.search(before) and (not M.STREET_AFTER.match(v[m.end():])):
            return m.group(0)
        return M.HOUSE_NUMBER_REMOVED
    return M.AL_HOUSE_RE.sub(repl, v)

def al_clean(v) -> str | None:
    """Free text as typed, scrubbed: e-mails, phones, staff names, then every street address's house number
    (common.strip_house_numbers, then strip_al_house_numbers for the forms it leaves)."""
    import ingest.al_adem_sso as M
    if v is None:
        return None
    s = ' '.join(str(v).split())
    if not s:
        return None
    return al_numbers(identity_text.strip_house_numbers(identity_text.scrub_text(s))) or None

def al_street(v: str | None) -> str | None:
    """A location with every house number removed: al_adem_sso.clean_text (common.strip_house_numbers and the
    Alabama forms), then any number still standing on its own that no route word precedes ("2025", "1234-B MAIN
    ST", "99/105 SUMMIT BOULEVARD"); ordinals ("15th Ave") and route numbers ("Highway 150") stay."""
    import ingest.al_jefferson_county_soa as M
    s = al_clean(v)
    if not s:
        return None

    def repl(m):
        return m.group(0) if M.ROUTE_BEFORE.search(s[:m.start()]) else M.HOUSE_NUMBER_REMOVED
    s = M.GLUED_NUMBER.sub(lambda m: f'{m.group(1)} {M.HOUSE_NUMBER_REMOVED}', s)
    s = M.GLUED_BEFORE.sub(M.HOUSE_NUMBER_REMOVED + ' ', s)
    s = M.LEFT_NUMBER.sub(repl, s)
    s = M.re.sub(f'(?:{M.re.escape(M.HOUSE_NUMBER_REMOVED)}\\s*[-/&,]?\\s*){{2,}}', M.HOUSE_NUMBER_REMOVED + ' ', s)
    return ' '.join(s.split()) or None

def al_point(text: str) -> tuple[float | None, float | None, str | None]:
    """(lat, lon, None) rounded to POINT_DECIMALS, or (None, None, why the point is not used)."""
    import ingest.al_jefferson_county_soa as M
    t = ' '.join((text or '').replace('\t', ' ').split())
    if not t:
        return (None, None, 'the row gives no map point')
    m = M.POINT.match(t)
    if not m:
        return (None, None, 'the map link is not one latitude and one longitude')
    lat, lon = (float(m.group(1)), float(m.group(2)))
    if not (M.AL_BOX[2] <= lat <= M.AL_BOX[3] and M.AL_BOX[0] <= lon <= M.AL_BOX[1]):
        return (None, None, 'the map point lies outside Alabama')
    return (round(lat, M.POINT_DECIMALS), round(lon, M.POINT_DECIMALS), None)

def nv_field(s: str, what: str='water') -> str:
    """A name field cleaned before any save (verification pass P1-3): one that can carry a person is withheld whole,
    named by a digest of its text so the record's id never depends on order; the rest scrubbed."""
    import ingest.nv_state_parks_hab as M
    if not isinstance(s, str) or not s:
        return s
    if M.personal_field(s):
        import hashlib
        return f'{what} withheld {hashlib.sha256(s.encode()).hexdigest()[:10]}'
    return identity_text.scrub_text(s)

def md_people(text: str, allow: set[str] | None=None) -> str:
    """Names after an honorific in free text -> [name removed] (allowlisted phrases such as "Mr. Rooter" stay)."""
    import ingest.md_mde_overflows as M
    if not text:
        return text
    allow = M._allowlist() if allow is None else allow

    def rep(m):
        return m.group(0) if ' '.join(M.re.sub('[^a-z0-9]+', ' ', m.group(0).lower()).split()) in allow else M.redact.REDACTED
    return M.HONORIFIC.sub(rep, text)

def md_row(row: dict, allow: set[str]) -> dict:
    import ingest.md_mde_overflows as M
    out = dict(row)
    for k in M.FREE_TEXT_FIELDS:
        if out.get(k):
            out[k] = md_people(out[k], allow)
    return out

def ma_row(obj):
    """Drop personal keys (reporterName, createdBy, modifiedBy, uploadedBy ...) and mask email
    addresses in free text, recursively. Used on everything before it is saved."""
    import ingest.ma_massdep as M
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k not in M.KEEP_KEYS and (M.PERSONAL_KEYS.search(str(k)) or str(k).lower() in M.EXTRA_PERSONAL):
                continue
            out[k] = ma_row(v)
        return out
    if isinstance(obj, list):
        return [ma_row(v) for v in obj]
    if isinstance(obj, str) and '@' in obj:
        return M.EMAIL_RE.sub('[email removed]', obj)
    return obj

def mi_owner_names(v: str) -> str:
    """'property owned by <given> <surname> at ...' -> 'property owned by [name removed] at ...', and
    "<given> <surname>'s back yard" -> "[name removed]'s back yard" (a body stays)."""
    import ingest.mi_egle_mienviro as M

    def body(name):
        return M._site_words(name) or M.re.search('(?i)\\b(llc|inc|corp|company|co|ltd|lp)\\b', name)

    def one(m):
        name = m.group(2)
        if body(name):
            return m.group(0)
        return m.group(0)[:m.start(2) - m.start(0)] + M.NAME_REMOVED

    def poss(m):
        return m.group(0) if body(m.group(1)) else M.NAME_REMOVED + m.group(0)[len(m.group(1)):]
    return M.OWNER_POSSESSIVE.sub(poss, M.OWNER_CUE.sub(one, v))

def mi_address_numbers(v: str) -> str:
    """Every number that reads as a house number in free text (ADDR_NUMBER, AT_NUMBER) -> [house number removed]."""
    import ingest.mi_egle_mienviro as M

    def one(m):
        before, after = (v[max(0, m.start(1) - 16):m.start(1)], v[m.end(1):m.end(1) + 16])
        if M.NUMBER_WORD_BEFORE.search(before) or M.QUANTITY_AFTER.match(after):
            return m.group(0)
        return m.group(0)[:m.start(1) - m.start(0)] + M.HOUSE_NUMBER_REMOVED + m.group(0)[m.end(1) - m.start(0):]
    v = M.ADDR_NUMBER.sub(one, v)
    return M.AT_NUMBER.sub(one, v)

def mi_text(v: str) -> str:
    """A filer's free text as the record keeps it: emails, phones and staff names (scrub_text), owners' and residents'
    names, and house numbers cut."""
    import ingest.mi_egle_mienviro as M
    return mi_address_numbers(identity_text.strip_house_numbers(mi_owner_names(identity_text.scrub_text(M.clean(v)))))

def generic_text(text):
    """Emails, phone numbers, staff titles and names after an honorific removed from free text."""
    import ingest.generic.fieldmap as M
    return generic_people(identity_text.scrub_text(text)) if isinstance(text, str) else text

def generic_people(text: str, allow=None) -> str:
    """Names after an honorific -> [name removed] (allowlisted phrases such as "Mr. Rooter" stay)."""
    import ingest.generic.fieldmap as M
    if not text:
        return text
    allow = M._allowlist() if allow is None else allow

    def rep(m):
        return m.group(0) if ' '.join(M.re.sub('[^a-z0-9]+', ' ', m.group(0).lower()).split()) in allow else M.REDACTED
    return M.HONORIFIC.sub(rep, text)

def generic_row(row: dict, block: dict) -> tuple[dict, list[str]]:
    """(only the safe fields, the safe fields dropped because their value is an object or a list). A dotted safe
    field keeps that nested leaf under its dotted name; an object is never kept whole (its keys were not reviewed).
    Free-text fields are scrubbed (emails, phones, staff titles, names after an honorific)."""
    import ingest.generic.fieldmap as M
    out, dropped = ({}, [])
    for f in block['safe_fields']:
        v = row[f] if f in row else M.get(row, f)
        if isinstance(v, (dict, list)):
            dropped.append(f)
            continue
        if f in row or v is not None:
            out[f] = v
    if block.get('transform') == 'ingest.tx_transforms.tx_tceq_record':
        ids = M.re.findall('\\bSSO\\s*ID\\s*#?\\s*(\\d{1,6})\\b', str(out.get('incident_description') or ''), M.re.I)
        saved = row.get('_houston_sso_ids')
        if isinstance(saved, list):
            ids.extend((i for i in saved if isinstance(i, str) and M.re.fullmatch('[0-9]{1,6}', i)))
        if ids:
            out['_houston_sso_ids'] = sorted({str(int(i)) for i in ids if int(i) > 0})
    mode = block.get('free_text_scrub')
    for f in block.get('free_text') or ():
        if isinstance(out.get(f), str):
            out[f] = generic_strict_names(out[f]) if mode == 'strict_names' else generic_strict(out[f]) if mode == 'strict' else generic_text(out[f])
    nd = block.get('round_coords')
    if nd is not None:
        for f in ('_x', '_y'):
            if isinstance(out.get(f), (int, float)):
                out[f] = round(float(out[f]), int(nd))
    for f in block.get('operator_fields') or ():
        if isinstance(out.get(f), str) and out[f].strip():
            if identity_text.scrub_discharger({'discharger_name': out[f]})['discharger_name'] == M.NAME_REMOVED:
                out[f] = M.NAME_REMOVED
    return (out, dropped)

def generic_strict(text):
    """free_text_scrub: strict (a filer's free text that can carry residents' names and home addresses): scrub, then
    owners' and residents' names and every house number cut, as Michigan's filer text is (mi_egle_mienviro.free_text),
    with a number after a slash read as one at the start of a field, and lot, apartment and unit numbers cut. Road
    numbers ("FM 1960") and a segment number before a water ("2202 Arroyo Colorado Above Tidal") are not house
    numbers and stay."""
    import ingest.generic.fieldmap as M
    if not isinstance(text, str):
        return text
    from ingest import mi_egle_mienviro as MI
    keep: list[str] = []

    def hold(m):
        keep.append(m.group(0))
        i, tag = (len(keep) - 1, '')
        while True:
            tag = 'abcdefghijklmnopqrstuvwxyz'[i % 26] + tag
            i = i // 26 - 1
            if i < 0:
                break
        return f'Qzqx{tag}'
    t = M.ROAD_NUMBER.sub(hold, text)
    t = M.SEGMENT_BEFORE_WATER.sub(lambda m: m.group(0) if M.STREET_AHEAD.match(t[m.end():]) else hold(m), t)
    t = M.re.sub('(?<=[A-Za-z.)])/(?=\\s*\\d)', '/ ', t)
    t = M.UNIT_NUMBER.sub(lambda m: f'{m.group(1)} [house number removed]', t)
    t = generic_people(mi_text(t))
    t = M.HOUSE_RANGE.sub('[house number removed]', t)
    t = M.STREET_HOUSE.sub(lambda m: m.group(0) if m.start() and t[m.start() - 1] == '#' and (len(m.group(1)) < 3) else '[house number removed]', t)

    def back(m):
        i = 0
        for c in m.group(1):
            i = i * 26 + 'abcdefghijklmnopqrstuvwxyz'.index(c) + 1
        return keep[i - 1] if 0 < i <= len(keep) else m.group(0)
    t = M.re.sub('Qzqx([a-z]+)', back, t)
    return t


def generic_strict_names(text):
    return _identity_redactor().text(generic_strict(text))


from functools import lru_cache

@lru_cache(maxsize=1)
def _identity_redactor():
    from build import redact
    from common import DATA_DIR
    # Empty event set: cue rules only, never the retired private blocklist.
    return redact.Redactor(redact.build_lexicon([], DATA_DIR, block=[]), set())


def fl_text(text) -> str | None:
    """The notice text with personal fields removed (see the module docstring). Every labelled personal field
    loses its value up to the next safe label, or to the end of the text when none follows."""
    from ingest import fl_dep_pnp as M
    if text is None:
        return None
    s = str(text).replace('¿', "'").replace('&#8209;', '-')
    out, pos = ([], 0)
    while True:
        m = M.PERSON_LABEL.search(s, pos)
        if not m:
            out.append(s[pos:])
            break
        if m.start() and s[m.start() - 1] == '[':
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        blank = M.BLANK_VALUE.match(s, m.end())
        if blank:
            out.append(s[pos:blank.end()])
            pos = blank.end()
            continue
        after = s[m.end():m.end() + 4]
        bare = m.group(0).lower() == 'name'
        before = s[max(0, m.start() - 20):m.start()].split()
        if bare and before and (before[-1].strip('.,').lower() in M.NAME_OF_THING):
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        if bare and (not M.LABEL_END.match(after)) and (not M.re.search('\\b(?:Name|NAME)\\s+(?:Represents|Title|Phone)', s[m.start():m.start() + 40])):
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        if not bare and M.re.sub('\\s+', ' ', m.group(0).lower()) in M.LABEL_ONLY_WITH_COLON and (not M.LABEL_END.match(after)):
            out.append(s[pos:m.end()])
            pos = m.end()
            continue
        out.append(s[pos:m.end()])
        nxt = M.SAFE_LABEL.search(s, m.end())
        if M.re.sub('\\s+', ' ', m.group(0).lower()) in M.NAME_VALUE_LABELS:
            stop = M.VALUE_STOP.search(s, m.end(), m.end() + M.VALUE_REACH)
            if stop and (nxt is None or stop.start() < nxt.start()):
                out.append(': [removed] ')
                pos = stop.end()
                continue
        if nxt:
            out.append(': [removed] ' if not s[m.end():nxt.start()].strip(' :#?-') else ': [removed] ')
            pos = nxt.start()
        else:
            out.append(': [removed]')
            break
    s = ''.join(out)
    s = M.re.sub('(:\\s*)+: \\[removed\\]', ': [removed]', s)
    s = M.TITLE_THEN_NAME.sub(M._drop_title_name, s)
    s = M.NAME_WITH_AGENCY.sub(M._drop_name_with_agency, s)
    s = M.NAME_THEN_TITLE.sub(lambda m: m.group(0) if M._not_person(m.group(1)) else '[name removed]', s)
    s = M.FIRST_PERSON_NAME.sub(lambda m: m.group(0) if M._not_person(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.TITLE_ORG_NAME.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.NAME_BEFORE_CONTACT.sub(lambda m: m.group(0) if M._company_or_place(m.group(1)) else '[name removed]', s)
    s = M.NAME_THEN_AGENCY.sub(lambda m: m.group(0) if M._company_or_place(m.group(1)) else '[name removed]', s)
    s = M.AGENCY_THEN_NAME.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.NAMED_CUE.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.GREETING_NAME.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.CUE_NAME_CAPS.sub(M._drop_caps_cue, s)
    s = M.HONORIFIC_NAME.sub('[name removed]', s)
    s = M.EMAIL_HEADER.sub('[e-mail header removed]', s)
    s = M.EMAIL_ADDRESSEE.sub('[name removed] ', s)
    s = M.drop_given_pairs(s)
    s = M.CUE_NAME.sub(M._drop_cue_name, s)
    s = M.CUE_INITIAL.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) or M._place_after(m) else m.group(1) + '[name removed]', s)
    s = M.NAME_BEFORE_ACTION.sub(M._drop_named_before_action, s)
    s = M.INITIAL_BEFORE_ACTION.sub(M._drop_named_before_action, s)
    s = M.RANK_SURNAME.sub(lambda m: m.group(0) if M._company_or_place(m.group(2)) else m.group(1) + '[name removed]', s)
    s = M.AGENCY_DASH_SURNAME.sub('\\1[name removed]', s)
    s = identity_text.scrub_text(s)
    s = M.SPACE.sub(' ', s).strip()
    return s or None

def fl_name(v):
    """INCIDENT_NAME or FACILITY_NAME with personal data removed. Filers often type their own name, or a resident's,
    as the incident or facility name (a staff member's name as the incident name; a homeowner's name as the facility
    of a complaint): a value that is only a person's name (build.redact.person_shaped, read in any case) becomes
    "[name removed]"; names inside a longer value go as in the notice text (common given name + surname, Mr./Ms.),
    and e-mails and phone numbers as everywhere."""
    from ingest import fl_dep_pnp as M
    if not isinstance(v, str):
        return v
    s = M.SPACE.sub(' ', identity_text.scrub_text(v)).strip()
    if not s:
        return s
    words = {w.lower() for w in M.re.split('[\\s\\-/.,()]+', s) if w}
    if not words & (M.NOT_PERSON_WORDS | M.PLACE_AFTER) and (M.redact.person_shaped(s) or M.redact.person_shaped(M.string.capwords(s))):
        return '[name removed]'
    if s.islower() or s.isupper():
        c = M.drop_given_pairs(M.HONORIFIC_NAME.sub('[name removed]', M.string.capwords(s)))
        if '[name removed]' in c:
            return c
    s = M.HONORIFIC_NAME.sub('[name removed]', s)
    return M.drop_given_pairs(s)

def fl_row(a: dict) -> dict:
    """The attributes this module keeps: the safe fields only, the relationship as a code, the text scrubbed, the
    incident and facility names cleared of people's names, the house number of an address the text ties to a residence
    or a resident (common.residence_numbers) cut from the names and the address line too, and, for a notice filed by a
    member of the public, no street address, no house number anywhere and the point rounded to about 100 m: the facility
    of a complaint is often the filer's or a neighbour's home."""
    from ingest import fl_dep_pnp as M
    out = {k: a.get(k) for k in M.SAFE_FIELDS if k in a}
    out['_filer'] = M.relationship_code(a.get(M.RELATIONSHIP_FIELD)) if M.RELATIONSHIP_FIELD in a else a.get('_filer')
    homes = M.residence_numbers(out['INCIDENT_REPORT']) if isinstance(out.get('INCIDENT_REPORT'), str) else []
    for k in ('INCIDENT_REPORT', 'INCIDENT_NAME', 'FACILITY_NAME'):
        if isinstance(out.get(k), str):
            out[k] = fl_text(out[k]) if k == 'INCIDENT_REPORT' else fl_name(out[k])
            if out[k] and homes:
                out[k] = identity_text.drop_house_numbers(out[k], homes)
    for k in ('FACILITY_ADDRESS_LINE_1', 'FACILITY_ADDRESS_LINE_2'):
        if isinstance(out.get(k), str) and homes:
            out[k] = identity_text.drop_house_numbers(out[k], homes)
    if out['_filer'] == 'citizen':
        for k in ('FACILITY_ADDRESS_LINE_1', 'FACILITY_ADDRESS_LINE_2'):
            if out.get(k):
                out[k] = '[address removed]'
        for k in ('INCIDENT_REPORT', 'INCIDENT_NAME', 'FACILITY_NAME'):
            if isinstance(out.get(k), str):
                out[k] = identity_text.strip_house_numbers(out[k])
        lat0 = M.fnum(out.get('LATITUDE'))
        if lat0 is not None:
            given = a.get('_coord_precision_m')
            out['_coord_precision_m'] = given if isinstance(given, int) else max(M.CITIZEN_PRECISION_M, M.precision_m(lat0))
        for k in ('LATITUDE', 'LONGITUDE'):
            v = M.fnum(out.get(k))
            if v is not None:
                out[k] = round(v, M.CITIZEN_COORD_DIGITS)
    return out


def de_text(value):
    """DNREC's historical text form, used only in South Carolina identities."""
    from ingest import de_dnrec_derns as M
    if not value:
        return value
    return M.NAMED_PERSON.sub(M._cut_name, identity_text.scrub_text(identity_text.strip_house_numbers(value)))


def ia_text(value):
    """Iowa/Idaho's historical normalization, used only for identity."""
    from ingest import ia_id_privacy as M
    if value is None:
        return None
    text = identity_text.strip_house_numbers(identity_text.scrub_text(str(value)))
    text = M.ADDRESS_RE.sub(M._house, text)
    text = M.COORD_RE.sub(M._round_coord, text)
    probe = M.STREET_ABBR_RE.sub(lambda m: m.group(1) + ' Street', text)
    probe = M.AGENCY_CONTACTED_RE.sub('reached ', probe)
    if text != M.WITHHELD and (M.names_a_person(probe) or M.HOME_OF_RE.search(probe)):
        return M.WITHHELD
    return text
