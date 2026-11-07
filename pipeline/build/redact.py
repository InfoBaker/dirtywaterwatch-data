"""Private individuals' names in quoted source text become "[name removed]" (an export step).

Several feeds quote an operator's free text ("How incident was resolved", COMMENTS,
additionalInformation), and some of it names a resident: "Building owner contacted to repair pump
station.  Robert Sacks was his name." common.strip_personal already drops personal keys and scrubs
emails, phones and staff names ("Inspector X", "contact X at"); this pass covers the rest of the names
(docs/plan.md: raw keeps the source record with personal fields removed, staff names included). It is
deliberately conservative: agency, company, street and water names stay.

  candidate  two or three capitalised words (one after an honorific) that are not place, water,
             organisation, street or header words. The lexicon: data/waters-new-england.csv (names and towns),
             data/waters-extra.json, data/waters-nhd.json, data/dischargers.json, data/outfalls-*.json, the records' own
             name fields (utility, permittee, water body, beach) and keys, US states, months,
             weekdays, and the words the records use in lower case. A run ending in a street, water or
             organisation word ("Boston Post Rd", "Fort Point Channel", "Fred Mold Park", "Francis
             Xavier plaza apartments") is a place, not a name.
  removed    a candidate the text marks as a person (Hit.contexts):
               honorific    Mr / Mrs / Ms / Mx / Dr before it ("Dr" after a word is Drive)
               role         resident, homeowner, property / building / home owner, tenant, neighbor,
                            landlord, occupant, customer, complainant, caller, a relative (niece, son,
                            wife ...) next to it; "owner of"
                            after it; "call from" / "complaint by" before it
               name_cue     the text says it is a name ("Robert Sacks was his name", "named Jane Doe")
               phone_email  a phone number or email (or its "[phone removed]") right after it
               address      a street address next to it            } only when the name starts with
               contact      spoke with / per / reported by / from  } a common given name (Nancy,
                            ...; operator, director ...; "X of the  } Doug ...), so that a company
                            Town of Orange", "X arrived ...";       } or street is never taken
                            "Person Reporting:", "Contact at Scene:", "referred to")
               title        a job title joined to the name by a comma, bracket or dash ("X, Operator at
                            the ...", "X (Director of ...)"), a person's title before it ("Mayor X",
                            "Dispatcher X"), or the name opening a dated notice ("On June 5, 2026, X
                            with the Town of ...") -- for names that do not start with a common given
                            name (a town's name, or a rare one)
             A single given name is removed only next to a role, a name cue or a phone ("Cathy,
             homeowner of ..."); a surname only after an honorific. A two- or three-word name marked
             once is removed wherever it appears in the export. After a name is removed from a
             string, later mentions in that string of its given name or surname ("Dan Gregory ... Dan
             arrived") go too, unless they are part of a place name ("Prince William", "Taylor St").
  water field  a discharge report's receiving-water field (waterbody_text, raw "Receiving Waterbody",
             RECEIVING_WATER_BODY ...) holding only a name (person_shaped: two to four capitalised words led by a
             common given name, no water, place or organisation word, no known name; or name_like: no word of it
             known to the lexicon) is removed whole, and the name everywhere else (several CT DEEP reports put the
             reporter's name there). Such a value never enters the lexicon as a place name (waterish). Beach,
             HAB, shellfish and rain advisories are exempt: their field names a site.
  blocklist  data/build/name-blocklist.json (gitignored with data/build: it quotes the names; the
             lexicon also reads data/name-blocklist.json when there is one): names the owner wants
             removed everywhere, in any context.
  allowlist  data/name-allowlist.json: phrases never removed (false positives such as "Mr. Rooter",
             a drain company); they never come up as candidates again.

build/name_review.py lists every candidate, removed or not, for the owner (data/build/name-review.json).
"""
from __future__ import annotations

import csv
import json
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from common import BUILD_DIR, DATA_DIR, EMAIL_RE, load_outfall_registry

REDACTED = "[name removed]"
SITE_TYPES = {"beach_advisory", "beach_closure", "hab_advisory", "shellfish_closure", "rain_advisory"}
ALLOWLIST = DATA_DIR / "name-allowlist.json"
BLOCKLIST = BUILD_DIR / "name-blocklist.json"       # data/build is gitignored: the file quotes the names
# top-level fields that can quote a source's text (raw is walked in full)
FREE_TEXT_FIELDS = ("waterbody_text", "outfall_name", "volume_text", "advice_text", "parse_error", "material")
# the contexts that remove a name (drop one here to stop removing on it; name_review still lists it)
AUTO_CONTEXTS = ("honorific", "role", "name_cue", "phone_email", "address", "contact", "title", "action")
SINGLE_CONTEXTS = ("role", "name_cue", "phone_email", "action")      # enough for a lone given name
# a phone number with area code: top-level free text is not scrubbed by common.strip_personal (only raw is), and the
# short "300-1000" form of common.PHONE_RE would take a volume range
PHONE10_RE = re.compile(r"(?<![\w-])(?:\+?1[\s.-]?)?(?:\(\d{3}\)|\d{3})[\s.-]?\d{3}[\s.-]\d{4}(?![\w-])")

# ---------------------------------------------------------------- word lists

FUNCTION = set("""
the a an and or but nor of on at in to for from with by into onto upon via per as than then also after before
during once while if because since until about approx approximately around near between below above under over
is are was were be been being am has have had do does did will would shall should can could may might must
he she they we i you it his her hers him them their theirs our ours my your its this that these those there here
who whom whose which what when where why how not no yes all any some each every both either neither none
called contacted spoke spoken talked notified reported informed advised told asked met visited said stated
regarding concerning
please see note notes attn attention re cc fyi thanks thank
mr mrs ms mx dr miss sir madam
inspector investigator resident residents homeowner homeowners owner owners tenant tenants neighbor neighbors
neighbour neighbours complainant complainants caller callers landlord landlords landowner occupant occupants
customer customers staff crew crews operator operators supervisor superintendent foreman engineer manager
director chief personnel contractor plumber employee technician
mayor councilman councilwoman commissioner sheriff deputy captain lieutenant sergeant dispatcher biologist specialist
assistant asst administrator coordinator officer mechanic electrician clerk treasurer analyst scientist
""".split())
HONORIFICS = {"mr", "mrs", "ms", "mx", "dr"}
# a run that ends in one of these is a place or an organisation (see _segments)
KILL = set("""
street st road rd avenue ave av lane ln drive way wy court ct place pl circle cir boulevard blvd bvld highway hwy
route rte rt turnpike tpke pike parkway pkwy terrace terr ter trail path extension ext square sq plaza mall center
centre alley row crossing heights hts steet sreet
river brook brk stream creek pond lake reservoir harbor harbour bay cove inlet channel canal basin falls marsh
swamp estuary sound beach island isle point neck shore lagoon dam spillway outlet fork branch
department dept division authority commission committee district company co inc llc corp corporation
associates association agency office services service utilities utility wpca wpcf wwtf wwtp potw wpcp wtp stp
plant facility station works treatment pollution sewer sewers sewerage wastewater water town city village borough
county state commonwealth university college school academy hospital church library museum cemetery cemetary
airport marina hotel motel restaurant apartments apts apartment condominiums condominium condos condo estates manor
gardens towers industries industrial realty properties construction contractors contracting engineering
engineers environmental plumbing excavating excavation paving market supermarket store shop bank club bridge
tunnel pier wharf landing terminal building bldg complex tower pump ps interceptor siphon regulator outfall
manhole chamber tank park farm farms golf course rink arena stadium mill mills hall memorial
""".split())
STATES = """alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho
illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri
montana nebraska nevada new hampshire jersey mexico york north carolina dakota ohio oklahoma oregon pennsylvania
rhode island south tennessee texas utah vermont virginia washington west wisconsin wyoming district columbia
al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd oh ok or pa
ri sc sd tn tx ut vt va wa wv wi wy dc""".split()
CALENDAR = """january february march april may june july august september october november december jan feb mar apr
jun jul aug sep sept oct nov dec monday tuesday wednesday thursday friday saturday sunday mon tue tues wed thu thur
thurs fri sat sun""".split()
HEADER_WORDS = """location address comments comment notes status type date time volume quantity event report incident
cause description name total estimated estimate final rainfall weather discovered resolved utility municipality
receiving waterbody group regulator other explanation bypass sewage overflow discharge combined sanitary storm""".split()
# common given names: a candidate starting with one is kept even when its words are ordinary words
# ("Mark Brown"); the address and contact contexts need one. Town names (Sharon, Warren ...) are dropped.
FIRST_NAMES = set("""
james john robert michael william david richard joseph thomas charles christopher daniel matthew anthony mark
donald steven stephen paul andrew joshua kenneth kevin brian george timothy ronald edward jason jeffrey ryan jacob
gary nicholas eric jonathan larry justin scott brandon benjamin samuel gregory alexander frank patrick raymond jack
dennis jerry tyler aaron jose adam nathan henry douglas zachary peter kyle ethan walter noah jeremy christian keith
roger terry gerald harold sean austin carl arthur lawrence dylan jesse jordan bryan billy joe bruce gabriel logan
albert willie alan juan wayne elijah randy roy vincent ralph eugene russell bobby philip phillip louis bill bob
jim tom mike dave dan steve rick rich chris matt tony ken ted fred ed eddie al ron don doug greg jeff joel marc
mario luis carlos francis frederick norman howard leonard earl stanley glenn gordon wesley todd craig dale curtis
allen victor martin ernest shawn derek travis luke ian evan jared cody marcus nathaniel jimmy johnny danny tommy
chad brett brent troy darren dean neil barry kurt brad rob bert hank ray manny kenny ricky jon nate sam ben
mary patricia jennifer linda elizabeth barbara susan jessica sarah karen lisa nancy betty margaret sandra ashley
kimberly emily donna michelle carol amanda dorothy melissa deborah stephanie rebecca laura cynthia kathleen amy
angela anna brenda pamela emma nicole helen samantha katherine christine debra rachel carolyn janet catherine maria
heather diane ruth julie olivia joyce virginia victoria kelly lauren christina joan evelyn judith megan andrea
cheryl hannah jacqueline martha gloria teresa ann anne sara frances kathryn janice jean abigail alice judy sophia
denise doris marilyn danielle beverly isabella theresa diana natalie brittany charlotte marie kayla alexis
lori jane sue kathy cathy kate katie liz beth meg jen jenn jill gail peggy paula wendy tina tracy holly erin
colleen eileen maureen kristen kristin allison heidi tammy joanne debbie carla carmen rita lynn suzanne valerie
aidan alec alex alfred allan alvin andre andy angelo antonio archie armando arnold barney benny bernard bernie
blake brendan bryce buddy byron calvin cameron carlton casey cecil cesar chuck clarence claude clayton cliff
clifford colin conor connor corey cory curt damian damon darrell darryl davey derrick desmond devin dewey dexter
dick dino dom dominic donnie duane dustin dwayne dwight edgar edmund eduardo edwin eli elliot elliott elmer emil
emilio enrique erik ernie esteban felix fernando floyd francisco frankie freddie gene geoff geoffrey gerard gerry
gilbert gino glen graham gus guy harry harvey hector herb herbert homer horace howie hugh hugo ignacio irving isaac
ivan jaime jake jamal jamie javier jay jeffery jerome jimmie joey johnnie jonah jorge josh julian julio karl kirk
leo leon leroy lester lewis lloyd lou louie lucas mack malcolm manuel marco marcos marty marvin mathew maurice
melvin micah mickey miguel mitch mitchell morris murray myron neal ned nelson nick nicky noel norm oliver omar
orlando oscar otis owen pablo pat pedro percy pete phil pierre preston quentin rafael ramon randall raul reggie
reginald rene ricardo robbie roberto rod rodney roland rolando ronnie ross ruben rudy russ salvatore sammy santiago
saul scotty sergio seth shane shaun simon stan stu stuart sylvester teddy terrence theodore tim timmy toby tomas
trevor tristan vern vernon vic vince wallace walt wendell wes wilbur willard willis winston xavier zach alejandro
diego drew
adrienne agnes aileen alexandra alexa alicia alison allie alma alyssa amelia ana angie anita annette annie
antoinette arlene audrey barb becky belinda bernadette bertha bethany betsy bettie bianca bonnie brandi bridget
caitlin camille candace cara carly caroline carrie cassandra cassie cecilia celeste charlene chelsea cherie chloe
christie christy cindy claire clara claudia connie constance cora courtney cristina dana darlene deanna debby
debora deirdre delores dianne dina dolores dora doreen dottie edith eleanor elena elise eliza ella ellen eloise
elsie emilia erica erika esther ethel eunice eva faye felicia fiona flora florence francine gabriela gabrielle
gayle genevieve geraldine gina ginny gladys glenda gretchen gwen hailey harriet hazel helena hilda ilene iliana
isabel jackie jaclyn janelle janine jasmine jeanette jeanne jeannie jenna jennie jenny jessie jillian joann joanna
jocelyn jodi jody johanna josephine juanita julia juliana julianne justine kara karin karla katelyn kathie katrina
kendra kerry kim kimberley kristina kristy laurie leah leigh lena leslie lillian lilly lindsay lindsey lois
loretta lorraine louise lucia lucille lucy luisa lydia lynda lynne mabel madeline maggie mandy marcia margie margo
mariana marianne marla marlene marsha martina maryann matilda maxine meghan melanie melinda melody mercedes
meredith mia michele mildred millie mindy miranda miriam molly mona monica monique myra nadine naomi natasha nellie
nina nora norma olga paige pam patsy patty pauline phyllis polly priscilla rachael ramona raquel regina renee
rhonda roberta rochelle rosa rosalie rosemary roxanne sabrina sally sallie selena serena shannon shari shala
shauna sheila shelby shelly sherri sherry silvia simone sofia sonia sonja sophie stacey stacy stella susanna susie
tamara tami tanya tara terri tiffany toni tonya tracey tricia trisha ursula vanessa vera vicki vickie vicky viola
vivian wanda wilma yolanda yvonne zoe
""".split())

_UP, _LO = "A-ZÀ-ÖØ-Þ", "a-zß-öø-ÿ"
TOKEN = (rf"(?:(?:[{_UP}][{_LO}]*['’]?[{_UP}][{_LO}]+|[{_UP}][{_LO}]+)(?:-[{_UP}][{_LO}]+)?(?!\w)"
         rf"|[{_UP}]\.(?=[ ]))")
RUN_RE = re.compile(rf"(?<![\w'’.-]){TOKEN}(?:[ ]{{1,3}}{TOKEN})*")
WORD_RE = re.compile(r"[^\W\d_]+(?:['’-][^\W\d_]+)*")
LOWER_WORD_RE = re.compile(r"(?<![\w'’-])[a-z]{2,}(?![\w'’-])")
CAP_WORD_RE = re.compile(r"(?<![\w'’-])[A-Z][a-z]+(?![\w'’-])")
ACRONYM_RE = re.compile(r"(?<![\w'’-])[A-Z]{2,}(?![\w'’-])")
NEXT_WORD = re.compile(r"[ ]{1,3}([^\W\d_]+)")
HAS_CAPS = re.compile(r"[A-Z][a-z]|[A-Z]{2}")

_SEP = r"[ ]{0,2}(?:[,:(\[]|-|–|—)?[ ]{0,2}"              # what may stand between a name and its context
_RESIDENT = (r"(?:resident|home[- ]?owner|property[- ]owner|building[- ]owner|house[- ]owner|land[- ]?owner|"
             r"tenant|neighbou?r|landlord|occupant|customer|complainant|complaintant|caller|niece|nephew|daughter|son|wife|husband|"
             r"brother|sister|mother|father|aunt|uncle|cousin)")
HON_BEFORE = re.compile(r"(?<![\w'’])(Mr|Mrs|Ms|Mx|Dr)\.?[ ]{1,2}$", re.I)
ROLE_BEFORE = re.compile(rf"\b{_RESIDENT}s?\b{_SEP}(?:(?:named|is|was)[ ]{{1,2}})?$", re.I)
ROLE_AFTER = re.compile(rf"^(?:[ ]{{0,2}}(?:[,(\[]|-|–|—)[ ]{{0,2}}|[ ]{{1,2}}(?:is|was|who[ ]is)[ ]{{1,2}})(?:(?:the|a|an)[ ]{{1,2}})?"
                        rf"(?:(?:local|nearby|private|area|adjacent|concerned|downstream)[ ]{{1,2}})?"
                        rf"(?:{_RESIDENT}\b|owner[ ]of\b)", re.I)
CUE_BEFORE = re.compile(r"(?:\b(?:his|her|their|whose)[ ]{1,2}name[ ]{1,2}(?:is|was)[ ]{0,2}:?[ ]{0,2}|"
                        r"\bnamed[ ]{1,2}|\bname[ ]{0,2}:[ ]{0,2})$", re.I)
CUE_AFTER = re.compile(r"^[ ]{0,2},?[ ]{0,2}(?:was|is)[ ]{1,2}(?:his|her|their|the[ ]{1,2}\w+(?:'s)?)[ ]{1,2}name\b", re.I)
_STREET = (r"(?i:street|st|road|rd|avenue|ave|av|lane|ln|drive|dr|way|court|ct|place|pl|circle|cir|boulevard|blvd|"
           r"highway|hwy|route|rte|rt|turnpike|tpke|pike|parkway|pkwy|terrace|terr|ter|trail|square|sq|extension|ext)")
_STREETWORDS = r"street|st|road|rd|avenue|ave|lane|ln|drive|dr|way|court|ct|place|pl|boulevard|blvd|park|plant|station|center"
_ADDRESS = rf"\b\d{{1,6}}[A-Za-z]?(?:-\d{{1,5}})?[ ]{{1,2}}(?:[NSEW]\.?[ ])?(?:[A-Z][\w'’.-]*[ ]{{1,2}}){{0,3}}{_STREET}\b\.?"
ADDR_AFTER = re.compile(rf"^{_SEP}(?:(?i:of|at|on|from|lives at|resides at|residing at|located at)[ ]{{1,2}}|@[ ]?)?{_ADDRESS}")
ADDR_BEFORE = re.compile(rf"{_ADDRESS}{_SEP}$")
PHONE_AFTER = re.compile(rf"^{_SEP}<?(?:(?i:at|tel\.?|phone|cell|ph\.?|e-?mail|number|#)[ ]{{0,2}}:?[ ]{{0,2}})?"
                         r"(?:\[phone removed\]|\[email removed\]|[\w.+-]+@[\w-]+\.|\(?\d{3}\)?[ .-]?\d{3}[ .-]\d{4})")
_STAFF = (r"(?:operator|supervisor|superintendent|foreman|engineer|manager|director|personnel|contractor|plumber|"
          r"employee|technician|staff|inspector|investigator|chief|administrator|coordinator|owner|mechanic|"
          r"electrician|official|officer|agent|representative|rep|mayor|dispatcher|biologist|specialist|assistant|asst|"
          r"deputy|sheriff|captain|lieutenant|sergeant|commissioner|councilman|councilwoman|clerk|treasurer|analyst|"
          r"scientist|planner|attorney|consultant)")
CONTACT_BEFORE = re.compile(
    rf"(?:\b(?:spoke|spoken|talked|met|meeting|conversation|discussion|email(?:ed)?|e-mail(?:ed)?|text(?:ed)?|"
    rf"call(?:ed)?(?:[ ]in)?|calls|phoned|contact(?:ed)?|notif(?:ied|y)|inform(?:ed)?|advis(?:ed|e)|told|asked|sent|"
    rf"left[ ]a[ ]message|message|complaints?|complained)(?:[ ](?:with|to|for|from|by|of))?|\b(?:reported|notified|submitted|observed|discovered|found|"
    rf"identified|witnessed|shoveled[ ]up|cleaned[ ]up|confirmed|approved|requested)[ ]by|\bper|\baccording[ ]to|"
    rf"\b(?:from|by|with|attn:?|c/o|cc:?)|\b{_STAFF}s?(?:[ ](?:is|was|named))?|"
    # form fields and referrals: "Person Reporting: X", "Contact at Scene: X", "referred to X", "land belonging to X"
    rf"\bperson[ ]{{1,2}}(?:reporting|contacted|completing|submitting|calling)|\bcontact[ ]at[ ]scene|\breporting[ ]party|"
    rf"\breferr?(?:ed|al)(?:[ ]to)?|\bforwarded[ ]to|\bbelonging[ ]to|\bproperty[ ]of)"
    rf"(?:[ ]{{1,2}}(?-i:[A-Z]{{2,6}}))?{_SEP}$", re.I)       # an agency's initials may stand between ("call from RHMO X")
CONTACT_AFTER = re.compile(
    rf"^(?:{_SEP}(?:(?:the|a|an|our)[ ]{{1,2}})?(?:[\w&.-]+[ ]{{1,2}}){{0,3}}{_STAFF}\b|"
    rf"[ ]{{0,2}},?[ ]{{1,2}}(?:from|of|with)[ ]{{1,2}}(?:the[ ]{{1,2}})?(?:(?-i:[A-Z])|(?:town|city|county|village|state|department|dept|co)\b)|"
    rf"[ ]{{1,2}}(?:called|calls|reported|stated|said|says|spoke|notified|informed|advised|arrived|responded|"
    rf"emailed|indicated|confirmed|observed|noticed|discovered|found|requested|is[ ]contacting|"
    rf"(?:was|were|has[ ]been|will[ ]be)[ ](?:notified|contacted|informed|called|emailed|advised))\b)", re.I)

# "title" context (a person whether or not the name starts with a common given name): a job title joined to
# the name by a comma, bracket or dash ("X, Operator at the ...", "X (Director of ...)"), a person's title
# before it ("Mayor X"), or the name opening a dated notice ("On June 5, 2026, X with the Town of ...")
_TITLE = (r"(?:operator|supervisor|superintendent|foreman|engineer|manager|director|technician|inspector|investigator|chief|"
          r"administrator|coordinator|electrician|officer|mayor|dispatcher|biologist|specialist|assistant|asst|deputy|sheriff|"
          r"captain|lieutenant|sergeant|commissioner|councilman|councilwoman|clerk|treasurer|analyst|scientist|planner|plumber)")
# the words between the name and the title are descriptors ("Environmental Services Manager"), not a new clause
# ("Bridgeman Civil, and our oncall consultant"), and the title is not a street ("N. Mechanic Street")
TITLE_NEXT = re.compile(rf"^[ ]{{0,2}}[,(][ ]{{0,2}}(?:(?:the|a|an)[ ]{{1,2}})?(?:(?!(?:our|the|a|an|who|which|that|his|her|their)\b)[\w&.-]+[ ]{{1,2}}){{0,3}}"
                        rf"{_TITLE}\b(?![ ]{{1,2}}(?:{_STREETWORDS})\b)", re.I)
TITLE_BEFORE = re.compile(rf"\b{_TITLE}[ ]{{1,2}}$", re.I)
_MONTH = (r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|"
          r"nov(?:ember)?|dec(?:ember)?)\.?")
DATED_BEFORE = re.compile(rf"\b(?:{_MONTH}[ ]{{1,2}}\d{{1,2}}(?:st|nd|rd|th)?,?[ ]{{1,2}}\d{{4}}|\d{{1,2}}/\d{{1,2}}/\d{{2,4}})[ ]{{0,2}},?[ ]{{1,2}}"
                          rf"(?:(?:at|around|approximately|about)[ ]{{1,2}})*(?:\d{{1,2}}(?::\d{{2}})?[ ]{{0,2}}(?:[ap]\.?m\.?|hrs?)?[ ]{{0,2}},?[ ]{{1,2}})?$", re.I)

# a lone given name doing what a person does ("Jason arrived on scene", "Connor with the Authority advised")
SOLO_AFTER = re.compile(r"^(?:[ ]{1,2}(?:with|from|of)[ ]{1,2}(?:the[ ]{1,2})?(?-i:[A-Z])[^.;:]{0,60}?)?[ ]{1,2}(?:did[ ]say|said|says|stated|"
                        r"advised|informed|arrived|spoke|responded|emailed|confirmed|notified|indicated|requested|directed|explained|"
                        r"told|called|reported)\b", re.I)
# "Surname, Given" before an email or phone: the header of a quoted message ("from Doe, Jane <[email removed]>")
LASTFIRST_BEFORE_CONTACT = re.compile(r"(?<![\w'’])[A-Z][\w'’-]+,[ ]{1,2}[A-Z][\w'’-]+(?=[ ]{0,2}<?[ ]{0,2}(?:\[(?:email|phone) removed\]|[\w.+-]+@))")

# a job title after a marked name: "Dan Gregory Plant Superintendent" is a person, not a plant
TITLE_AFTER = re.compile(rf"[ ]{{1,3}}(?:[^\W\d_]+[ ]{{1,3}}){{1,2}}{_STAFF}\b", re.I)
# a caller or complainant: with an address next to the name, enough without a common given name
CALLER_BEFORE = re.compile(rf"\b(?:(?:phone[ ])?call(?:ed)?(?:[ ]in)?[ ](?:from|by)|calls?[ ]from|complaints?[ ](?:from|by)|"
                           rf"(?:reported|notified)[ ]by|message[ ](?:from|with)){_SEP}$", re.I)

# ---------------------------------------------------------------- lexicon

def _words(name) -> list[str]:
    if not isinstance(name, str):
        return []
    return [w.lower() for w in WORD_RE.findall(name)]


def _norm(phrase: str) -> str:
    return " ".join(_words(phrase))


def _ngrams(words: list[str], n_max: int = 3):
    for n in range(1, n_max + 1):
        for i in range(len(words) - n + 1):
            yield " ".join(words[i:i + n])


def _read(path: Path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


@lru_cache(maxsize=4)
def reference_names(data_dir: str) -> tuple[frozenset, frozenset]:
    """(names, towns) from the reference files: water, town, discharger, outfall and permittee names
    (whole names); towns lower case on their own (a town is never taken as a given name)."""
    d = Path(data_dir)
    names, towns = set(), set()
    p = d / "waters-new-england.csv"
    if p.exists():
        with p.open(newline="") as fh:
            for row in csv.DictReader(fh):
                names.add(row.get("name") or "")
                towns.update(t.strip() for t in (row.get("towns") or "").split(";"))
    for fname in ("waters-extra.json", "waters-nhd.json"):
        extra = _read(d / fname, {}) or {}
        for w in extra.get("waters") or []:
            names.update([w.get("name") or "", *(w.get("aliases") or [])])
            towns.update(w.get("towns") or [])
        for k in ("skipped", "missing"):
            names.update(x.get("name") or "" for x in extra.get(k) or [])
    dis = _read(d / "dischargers.json", [])
    for x in (dis.get("dischargers") if isinstance(dis, dict) else dis) or []:
        names.update([x.get("name") or "", *(x.get("receiving_waters") or [])])
        towns.update(x.get("towns") or [])
    # every official registry file (data/outfalls-*.json); the provisional places built from the reports are not
    # reference names (their text comes from the records being redacted)
    for o in load_outfall_registry(d, provisional=False):
        names.update(str(o.get(k) or "") for k in ("permittee", "outfall_name", "receiving_water_echo", "water_name"))
        towns.add(str(o.get("city") or ""))
    names |= towns
    return frozenset(n for n in names if n), frozenset(t.lower() for t in towns if t)


def load_list(path: Path) -> list[str]:
    """data/name-allowlist.json or data/name-blocklist.json: {"names": [...]} (a bare list works too)."""
    d = _read(path, {})
    rows = d.get("names", []) if isinstance(d, dict) else d
    return [str(x).strip() for x in rows or [] if str(x).strip()]


def blocklist(data_dir: Path) -> list[str]:
    """The owner's blocklist: data/build/name-blocklist.json (gitignored: it quotes the names), plus
    data/name-blocklist.json when there is one."""
    out: list[str] = []
    for p in (data_dir / BLOCKLIST.relative_to(DATA_DIR), data_dir / BLOCKLIST.name):
        out += [n for n in load_list(p) if n not in out]
    return out


# raw keys whose short values name a utility, permittee, water or beach (never a private person)
NAME_FIELD = re.compile(r"(utility|municipality|town|permit+ee|facility|water ?body|receiving|beach|site ?name|"
                        r"location ?name|management|collection_system|group name)", re.I)
# the receiving-water fields: the top-level waterbody_text and raw keys such as "Receiving Waterbody",
# RECEIVING_WATER_BODY, "Waterbody Name"
WATER_FIELD = re.compile(r"(?:^waterbody_text$|(?:receiving|water[ _]?body))", re.I)
PERSON_SHAPE = re.compile(rf"[{_UP}][\w'’-]*\.?(?:[ ]{{1,2}}[{_UP}][\w'’-]*\.?){{1,3}}")


def person_shaped(text, data_dir: Path = DATA_DIR) -> bool:
    """A receiving-water value that is only a person's name, not a water: two to four capitalised words (a
    middle initial allowed), the first a common given name that is not a town, none of them a water, place,
    street, organisation or ordinary function word, and the whole not a known water, town, discharger or
    outfall name (reference_names). Several CT DEEP reports put the reporter's name in this field; a name
    there carries no other context the redaction could read."""
    t = str(text or "").strip()
    if not t or len(t) > 40 or "[" in t:
        return False
    s = shadow(t)
    if not PERSON_SHAPE.fullmatch(s):
        return False
    words = [w.lower() for w in WORD_RE.findall(s)]
    if not 2 <= len(words) <= 4:
        return False
    known, towns = _reference_norm(str(data_dir))
    if words[0] not in FIRST_NAMES or words[0] in towns:
        return False
    if any(w in KILL or w in WATER_WORDS or w in FUNCTION or w in STATES or w in HEADER_WORDS for w in words):
        return False
    return _norm(t) not in known


def name_like(text, lex: "Lexicon") -> bool:
    """A receiving-water value of two or three capitalised words none of which the lexicon knows (not a water,
    town, place, organisation or ordinary word of the records, not a water word) and that is no known name: a
    name whose given name is not on the common list. Needs the export's lexicon (build_lexicon)."""
    t = str(text or "").strip()
    if not t or len(t) > 40 or "[" in t:
        return False
    s = shadow(t)
    if not PERSON_SHAPE.fullmatch(s):
        return False
    words = [w.lower() for w in WORD_RE.findall(s)]
    if not 2 <= len(words) <= 3 or any(len(w) < 2 for w in words):
        return False
    if any(w in lex.vocab or w in KILL or w in WATER_WORDS for w in words):
        return False
    known, _ = _reference_norm(lex.data_dir)
    return _norm(t) not in known and _norm(t) not in lex.known


# water words KILL lacks ("Herbert Run" is a stream)
WATER_WORDS = set("""run runs kill gut narrows flowage fork forks spring springs millpond tributary trib wetland wetlands
ditch drain culvert race raceway hollow slough bayou reach sluice""".split())


@lru_cache(maxsize=4)
def _reference_norm(data_dir: str) -> tuple[frozenset, frozenset]:
    """(the reference names normalised, the towns) for person_shaped: reference_names plus every water of the
    data/waters-*.json files, each also without its last word ("Frances Slocum" for Frances Slocum Lake)."""
    names, towns = reference_names(data_dir)
    known = {_norm(n) for n in names}
    for p in sorted(Path(data_dir).glob("waters-*.json")):
        d = _read(p, {}) or {}
        for w in (d.get("waters") if isinstance(d, dict) else d) or []:
            if isinstance(w, dict):
                for n in [w.get("name") or "", *(w.get("aliases") or [])]:
                    words = _words(n)
                    known.add(" ".join(words))
                    if len(words) >= 3 or (len(words) == 2 and words[-1] in KILL | WATER_WORDS):
                        known.add(" ".join(words[:-1]))
    known.discard("")
    return frozenset(known), towns


def waterish(text, data_dir: Path = DATA_DIR) -> bool:
    """A receiving-water value that reads as a water: it has a water or place word, or is a known name (a
    reporter's name in the field must not enter the lexicon as a place)."""
    words = _words(text)
    return any(w in KILL or w in WATER_WORDS for w in words) or _norm(text) in _reference_norm(str(data_dir))[0]


def water_field(path: str) -> bool:
    """Whether a field path (iter_texts) is a receiving-water field."""
    return bool(WATER_FIELD.search(path.rsplit(".", 1)[-1]))


@dataclass
class Lexicon:
    vocab: set = field(default_factory=set)        # ordinary, place, organisation and header words (lower case)
    common: set = field(default_factory=set)       # ordinary words only (no place names)
    known: set = field(default_factory=set)        # one- to three-word pieces of place and organisation names
    first_names: set = field(default_factory=set)
    allow: set = field(default_factory=set)        # normalised phrases never removed
    block: list = field(default_factory=list)      # phrases always removed
    cache: dict = field(default_factory=dict, repr=False)
    data_dir: str = str(DATA_DIR)                   # the reference files (person_shaped)

    def is_vocab(self, tok: str) -> bool:
        return tok.lower().rstrip(".") in self.vocab

    def is_known(self, phrase: str) -> bool:
        low = _norm(phrase)
        return low in self.known or low in self.allow


def build_lexicon(records=(), data_dir: Path = DATA_DIR, allow: list | None = None, block: list | None = None) -> Lexicon:
    """The stoplists from the reference files plus what the records themselves show: their keys, the
    short values of their name fields, and the words they use in lower case (pump, station, called;
    counted once per distinct string). allow / block default to data/name-*.json."""
    names, towns = reference_names(str(data_dir))
    allow = load_list(data_dir / ALLOWLIST.name) if allow is None else allow
    block = blocklist(data_dir) if block is None else block
    texts, key_words, corpus_names = set(), set(), set()
    for rec in records:
        for path, s in iter_texts(rec):
            texts.add(s)
            if len(s) <= 60 and NAME_FIELD.search(path.rsplit(".", 1)[-1]) and not re.search(r"\d", s) \
                    and not (water_field(path) and not waterish(s, data_dir)):
                corpus_names.add(s)       # a receiving-water value is a place name only when it looks like a water
        for k in _keys(rec.get("raw")):
            key_words.update(_words(k))
    lower, cap, acronyms = Counter(), Counter(), set()
    for s in texts:
        if shouting(s):
            continue
        lower.update(set(LOWER_WORD_RE.findall(s)))
        cap.update({w.lower() for w in CAP_WORD_RE.findall(s)})
        acronyms.update(a.lower() for a in ACRONYM_RE.findall(s))
    common = {w for w, n in lower.items() if n >= 3 or (n >= 2 and 2 * n >= cap.get(w, 0))}
    common |= FUNCTION | set(HEADER_WORDS) | set(CALENDAR) | key_words
    vocab = common | KILL | set(STATES) | acronyms
    known = set()
    for n in (*names, *corpus_names):
        words = _words(n)
        vocab.update(words)
        known.update(_ngrams(words))
    for n in allow:                      # "Fort Point Channel" covers "Fort Point"; "Mr. Rooter" not "Rooter"
        words = _words(n)
        vocab.update(words)
        known.update(g for g in _ngrams(words) if " " in g or len(words) == 1)
    return Lexicon(vocab=vocab, common=common, known=known, first_names=FIRST_NAMES - towns,
                   allow={_norm(a) for a in allow}, block=block, data_dir=str(data_dir))


def _keys(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from _keys(v)
    elif isinstance(o, list):
        for v in o:
            yield from _keys(v)


# ---------------------------------------------------------------- finding names

def shouting(s: str) -> bool:
    """Mostly upper-case text (CT DEEP's COMMENTS): read with each word capitalised."""
    letters = sum(c.isalpha() for c in s)
    return letters >= 8 and sum(c.isupper() for c in s) > 0.8 * letters


def shadow(s: str) -> str:
    """The text as read for names: upper-case text with each word capitalised, same length."""
    if not shouting(s):
        return s
    return re.sub(r"[A-Za-z]+", lambda m: m.group(0)[0] + m.group(0)[1:].lower(), s)


@dataclass(frozen=True)
class Hit:
    phrase: str            # the name as written, words joined by one space
    start: int             # span of the name in the text
    end: int
    cut: int               # where a removal starts (at the honorific when there is one)
    contexts: frozenset
    first_name: bool

    @property
    def words(self) -> int:
        return len(self.phrase.split())

    @property
    def auto(self) -> bool:
        ctx = self.contexts & set(AUTO_CONTEXTS)
        if self.words == 1:                         # a surname after an honorific; a given name by a role
            return "honorific" in ctx or (self.first_name and bool(ctx & set(SINGLE_CONTEXTS)))
        return bool(ctx)


def _segments(toks, lex: Lexicon):
    """Split a run of capitalised words at function words. A place or organisation word ("Rd",
    "Channel", "Park") takes the word before it, and the ones before that back to an ordinary word
    ("Boston Post Rd", "Martin Luther King Jr Blvd", "Fred Mold Park"; but "Robert Sacks Regarding
    Sewer" keeps "Robert Sacks"). Yields (segment, index of an honorific just before it or None)."""
    kind = []
    for i, (_, _, t) in enumerate(toks):
        low = t.lower().rstrip(".")
        if low == "dr" and i > 0 and kind[i - 1] not in ("func", "hon"):
            kind.append("kill")                                   # "Oak Dr": a street
        elif low in HONORIFICS:
            kind.append("hon")
        elif low in FUNCTION:
            kind.append("func")
        elif low in KILL:
            kind.append("kill")
        else:
            kind.append("word")
    for i, k in enumerate(kind):
        if k == "kill":
            j = i - 1
            while j >= 0 and kind[j] == "word":
                kind[j] = "dead"
                if toks[j][2].lower() in lex.common:
                    break
                j -= 1
    seg, hon = [], None
    for i, k in enumerate(kind):
        if k == "word":
            if not seg and i > 0 and kind[i - 1] == "hon":
                hon = i - 1
            seg.append(toks[i])
        else:
            if seg:
                yield seg, hon
            seg, hon = [], None
    if seg:
        yield seg, hon


def find_names(text: str, lex: Lexicon) -> tuple[Hit, ...]:
    """Candidate names in one string, each with the contexts that mark it as a person (cached)."""
    got = lex.cache.get(text)
    if got is None:
        got = lex.cache[text] = tuple(_find(text, lex))
    return got


def _find(text: str, lex: Lexicon):
    if not text or text.startswith(("http://", "https://")) or not HAS_CAPS.search(text):
        return
    s = shadow(text)
    shouted = s != text
    for m in RUN_RE.finditer(s):
        toks = [(m.start() + t.start(), m.start() + t.end(), t.group(0)) for t in re.finditer(r"\S+", m.group(0))]
        for seg, hon_idx in _segments(toks, lex):
            hon_start = toks[hon_idx][0] if hon_idx is not None else None
            if hon_start is None and seg[0] is toks[0]:          # "Mr. Sacks": the honorific ends the run before
                hm = HON_BEFORE.search(s, max(0, seg[0][0] - 6), seg[0][0])
                if hm and _honorific_ok(s, hm):
                    hon_start = hm.start()
            if hon_start is None:
                while len(seg) > 2 and lex.is_vocab(seg[0][2]) and (seg[0][2].lower() not in lex.first_names or shouted):
                    seg = seg[1:]
                while len(seg) > 2 and lex.is_vocab(seg[-1][2]):
                    seg = seg[:-1]
            words = [t for _, _, t in seg]
            w0 = words[0].lower()
            first = w0 in lex.first_names and not (shouted and w0 in lex.common)
            if len(words) == 1 and not first and hon_start is None and w0 in FIRST_NAMES and not (shouted and w0 in lex.common):
                # a given name that is also a town ("Wayne did say ...") is a name when it acts like a person
                first = SOLO_AFTER.search(s[seg[-1][1]:seg[-1][1] + 100]) is not None
            if len(words) > 3 or all(w.endswith(".") for w in words):
                continue
            if len(words) == 1 and hon_start is None and not first:
                continue
            if hon_start is None and len(words) >= 2 and not (first or any(not lex.is_vocab(w) for w in words)):
                continue
            start, end = seg[0][0], seg[-1][1]
            nxt = NEXT_WORD.match(s, end)
            if nxt and nxt.group(1).lower() in KILL:              # "Francis Xavier plaza", "Nathan Hale road"
                continue
            phrase = " ".join(words)
            if lex.is_known(phrase):
                continue
            ctx = _contexts(s, start, end, hon_start is not None, first, words)
            hit = Hit(phrase, start, end, hon_start if hon_start is not None else start, frozenset(ctx), first)
            if len(words) == 1 and not hit.auto:                  # a lone word is listed only when removed
                continue
            yield hit


def _honorific_ok(s: str, hm) -> bool:
    """'Dr' is an honorific only after a lower-case word, punctuation or the start ("45 Oak Dr. Smith"
    is a street)."""
    if hm.group(1).lower() != "dr":
        return True
    return re.search(r"(?:^|[^\w\s]|\b[a-z]\w*)[ ]{0,2}$", s[max(0, hm.start() - 30):hm.start()]) is not None


def _contexts(s: str, start: int, end: int, honorific: bool, first: bool, words) -> set:
    before, after = s[max(0, start - 60):start], s[end:end + 80]
    ctx = set()
    if honorific:
        ctx.add("honorific")
    if ROLE_BEFORE.search(before) or ROLE_AFTER.search(after):
        ctx.add("role")
    if CUE_BEFORE.search(before) or CUE_AFTER.search(after):
        ctx.add("name_cue")
    if PHONE_AFTER.search(after):
        ctx.add("phone_email")
    if len(words) == 1 and first and SOLO_AFTER.search(after):
        ctx.add("action")
    if len(words) >= 2:
        given = first or (len(words[0]) == 2 and words[0].endswith("."))
        address = ADDR_AFTER.search(after) or ADDR_BEFORE.search(before)
        if given or (address and CALLER_BEFORE.search(before)):
            if address:
                ctx.add("address")
            if CONTACT_BEFORE.search(before) or CONTACT_AFTER.search(after):
                ctx.add("contact")
        if TITLE_NEXT.search(after) or TITLE_BEFORE.search(before) or DATED_BEFORE.search(before):
            ctx.add("title")
    return ctx


# ---------------------------------------------------------------- walking records

def iter_texts(rec: dict):
    """(field path, string) for every string in raw and in the free-text top-level fields."""
    for k in FREE_TEXT_FIELDS:
        if isinstance(rec.get(k), str):
            yield k, rec[k]
    yield from _walk(rec.get("raw"), "raw")


def _walk(o, path):
    if isinstance(o, dict):
        for k, v in o.items():
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(o, list):
        for v in o:
            yield from _walk(v, f"{path}[]")
    elif isinstance(o, str):
        yield path, o


def _map_strings(o, fn):
    if isinstance(o, dict):
        return {k: _map_strings(v, fn) for k, v in o.items()}
    if isinstance(o, list):
        return [_map_strings(v, fn) for v in o]
    if isinstance(o, str):
        return fn(o)
    return o


# ---------------------------------------------------------------- removal

def allowed(h: Hit, s: str, lex: Lexicon) -> bool:
    return _norm(h.phrase) in lex.allow or _norm(s[h.cut:h.end]) in lex.allow


def marked_names(records, lex: Lexicon) -> set[str]:
    """Two- and three-word names (lower case) that some record marks as a person, minus the allowlist."""
    out = set()
    for rec in records:
        site = rec.get("event_type") in SITE_TYPES          # an advisory's water field names its site
        for path, s in iter_texts(rec):
            if not site and water_field(path) and (person_shaped(s, Path(lex.data_dir)) or name_like(s, lex)) \
                    and _norm(s) not in lex.allow:
                out.add(" ".join(WORD_RE.findall(s)).lower())          # a person's name given as the water
                continue
            for h in find_names(s, lex):
                if h.auto and h.words >= 2 and not allowed(h, shadow(s), lex):
                    out.add(h.phrase.lower())
    return out


def _phrase_re(phrases) -> re.Pattern | None:
    alts = sorted({p.strip() for p in phrases if p.strip()}, key=len, reverse=True)
    if not alts:
        return None
    body = "|".join(r"[ ]{1,3}".join(re.escape(w) for w in a.split()) for a in alts)
    # not inside a word ("O'Brien"), but after an opening quote ("receiving water 'Jane Doe' has no ...")
    return re.compile(rf"(?<![\w])(?<![\w]['’])(?:{body})(?![\w])", re.I)


class Redactor:
    """Removes, in any string: names this string marks as a person, the names marked anywhere
    (`marked`, from marked_names) and the blocklist; never an allowlisted phrase."""

    def __init__(self, lex: Lexicon, marked: set):
        self.lex, self.marked = lex, marked
        self._marked_re = _phrase_re(marked)
        self._block_re = _phrase_re(lex.block)
        self._cache: dict[str, str] = {}

    def text(self, t: str) -> str:
        out = self._cache.get(t)
        if out is None:
            out = self._cache[t] = self._text(t)
        return out

    def _text(self, t: str) -> str:
        if not t or t.startswith(("http://", "https://")):
            return t
        s = shadow(t)
        spans = [(h.cut, h.end) for h in find_names(t, self.lex) if h.auto and not allowed(h, s, self.lex)]
        if self._marked_re:
            for m in self._marked_re.finditer(s):
                nxt = NEXT_WORD.match(s, m.end())
                if nxt and nxt.group(1).lower() in KILL and not TITLE_AFTER.match(s, m.end()):
                    continue                                       # "Robert Sacks Park" is a place;
                cut = m.start()                                    # "Dan Gregory Plant Superintendent" a person
                hm = HON_BEFORE.search(s, max(0, cut - 6), cut)
                if hm and _honorific_ok(s, hm):
                    cut = hm.start()
                spans.append((cut, m.end()))
        if self._block_re:
            spans += [(m.start(), m.end()) for m in self._block_re.finditer(s)]
        spans += [(m.start(), m.end()) for m in LASTFIRST_BEFORE_CONTACT.finditer(s)]
        if not spans:
            return t
        merged = [tuple(x) for x in _merge(spans)]
        merged = _merge(merged + self._later_mentions(s, merged))
        out, pos = [], 0
        for a, b in merged:
            out.append(t[pos:a])
            out.append(REDACTED)
            pos = b
        out.append(t[pos:])
        return "".join(out)

    def _later_mentions(self, s: str, merged) -> list:
        """Spans of the given name or surname of a removed two- or three-word name, mentioned alone later in
        the same string ("Dan Quillfeather ... Dan arrived", "RHMO Quillfeather"). A given name is taken only as a
        lone capitalised word, a surname only when it is not a place, organisation or ordinary word; a word
        followed by a street or water word ("Taylor St") or inside a longer capitalised run is a place."""
        given, sur = set(), set()
        for a, b in merged:
            words = [w for w in WORD_RE.findall(s[a:b]) if w.lower() not in HONORIFICS | {"name", "removed"}]
            if not 2 <= len(words) <= 3:
                continue
            g, f = words[0], words[-1]
            if len(g) >= 3 and g.lower() in FIRST_NAMES and g.lower() not in self.lex.common:
                given.add(g)
            if len(f) >= 4 and f.lower() not in self.lex.vocab:
                sur.add(f)
        out = []
        for word, is_given in [(w, True) for w in given] + [(w, False) for w in sur]:
            for m in re.finditer(rf"(?<![\w'’-]){re.escape(word)}(?![\w-])", s):
                if any(a <= m.start() < b for a, b in merged):
                    continue
                nxt = NEXT_WORD.match(s, m.end())
                if nxt and nxt.group(1).lower() in KILL:
                    continue
                if is_given:
                    after = re.match(r"[ ]{1,2}[A-Z][a-z]", s[m.end():m.end() + 4])
                    before = re.search(r"[A-Z][a-z]+[ ]{1,2}$", s[max(0, m.start() - 30):m.start()])
                    if after or before:
                        continue
                out.append((m.start(), m.end()))
        return out

    def event(self, rec: dict) -> dict:
        out = dict(rec)
        # a beach, HAB, shellfish or rain advisory names its site, never a reporter: the water fields of
        # discharge reports only
        site = rec.get("event_type") in SITE_TYPES
        for k in FREE_TEXT_FIELDS:
            if isinstance(out.get(k), str):
                v = _scrub_contact(k, out[k])
                out[k] = self.water(v) if water_field(k) and not site else self.text(v)
        if out.get("raw"):
            out["raw"] = _map_strings(out["raw"], self.text) if site else _map_raw(out["raw"], self)
        return out

    def water(self, t: str) -> str:
        """A receiving-water value of a discharge report: a person's name standing as the water is removed whole
        (person_shaped, or name_like: no word of it is a known or ordinary word); otherwise the free-text pass."""
        if (person_shaped(t, Path(self.lex.data_dir)) or name_like(t, self.lex)) and _norm(t) not in self.lex.allow:
            return REDACTED
        return self.text(t)

    def note(self, t, swaps=()):
        """Pipeline text that can quote a record's free text (a placement note, an unplaced or set-aside reason,
        a status line): the same redaction as the free-text fields before it is written (review 2026-11-03 P1-1).
        First every quote of a field the redaction changed is swapped for the field's redacted form (quote_swaps:
        a quote cut short mid-name is caught there), then emails, phone numbers and names go as in a free-text
        field (marked names and the blocklist anywhere in the text)."""
        if not isinstance(t, str) or not t:
            return t
        for old, new in swaps:
            if old in t:
                t = t.replace(old, new)
        return self.text(_scrub_contact("note", t))


# build/status.py quotes a record's free text in its notes cut to these lengths (status.QUOTE_CHARS)
QUOTE_LENGTHS = (40, 60, 160)


def _cut(t: str, n: int) -> str:
    """t[:n], not ending inside a "[name removed]" (or phone, email) marker."""
    s = t[:n]
    i = s.rfind("[")
    if i != -1 and "]" not in s[i:]:
        j = t.find("]", i)
        if j != -1:
            s = t[:j + 1]
    return s


def quote_swaps(orig: dict, red: dict) -> list[tuple[str, str]]:
    """[(text as a pipeline note quotes it, its redacted form)] for every free-text field of a record that the
    redaction changed (orig: the record before, red: after): the field whole and cut to each of QUOTE_LENGTHS,
    stripped as the notes strip it, longest first. [] when nothing was removed."""
    out: dict[str, str] = {}
    for k in FREE_TEXT_FIELDS:
        a, b = orig.get(k), red.get(k)
        if not isinstance(a, str) or not isinstance(b, str) or a == b:
            continue
        a, b = a.strip(), b.strip()
        for n in (None, *QUOTE_LENGTHS):
            old = a if n is None else a[:n]
            if len(old) >= 3 and old not in out:
                out[old] = b if n is None else _cut(b, n)
    return sorted(out.items(), key=lambda kv: -len(kv[0]))


# ---------------------------------------------------------------- the export's self-check

_SCAN_WORDS = re.compile(r"[^\W\d_]+")


class BlockScan:
    """Finds the blocklisted names in a text with the redactor's own phrase rule (_phrase_re), fast enough for the
    whole of out/: a text is searched for a name only when it holds every word of that name."""

    def __init__(self, names):
        self.phrases = [(n, frozenset(_SCAN_WORDS.findall(n.lower())), _phrase_re([n])) for n in names if n.strip()]
        self.words = frozenset().union(*(ws for _, ws, _ in self.phrases)) if self.phrases else frozenset()

    def found(self, text: str) -> list[str]:
        """The blocklisted names in the text (as listed), [] when none."""
        if not self.phrases or not text:
            return []
        have = self.words.intersection(_SCAN_WORDS.findall(text.lower()))
        if not have:
            return []
        return [n for n, ws, rx in self.phrases if ws <= have and rx.search(text)]


def _map_raw(o, r: "Redactor", key: str = ""):
    """raw with every string through the free-text pass, and receiving-water fields through Redactor.water."""
    if isinstance(o, dict):
        return {k: _map_raw(v, r, str(k)) for k, v in o.items()}
    if isinstance(o, list):
        return [_map_raw(v, r, key) for v in o]
    if isinstance(o, str):
        return r.water(o) if key and water_field(key) else r.text(o)
    return o


def _scrub_contact(field: str, v: str) -> str:
    """Emails (and, outside advice_text, whose agency numbers are public) phone numbers in a top-level
    free-text field: common.strip_personal reaches raw only, and a quoted message header carries a name."""
    v = EMAIL_RE.sub("[email removed]", v)
    return v if field == "advice_text" else PHONE10_RE.sub("[phone removed]", v)


def _merge(spans):
    spans = sorted(spans)
    merged = [list(spans[0])]
    for a, b in spans[1:]:
        if a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return merged


def redactor_for(events: list[dict], data_dir: Path = DATA_DIR) -> Redactor:
    lex = build_lexicon(events, data_dir)
    return Redactor(lex, marked_names(events, lex))


def redact_events(events: list[dict], data_dir: Path = DATA_DIR, redactor: Redactor | None = None) -> list[dict]:
    """The export's pass: names of private individuals in quoted source text -> "[name removed]".
    Builds the lexicon from these events, finds the names marked as a person anywhere and removes
    them everywhere, with the blocklist and never the allowlist. Returns new records; the input is
    not changed. redactor: one already built from these events (redactor_for), so the caller can run
    the same one over its own text that quotes the records (Redactor.note)."""
    r = redactor or redactor_for(events, data_dir)
    return [r.event(e) for e in events]
