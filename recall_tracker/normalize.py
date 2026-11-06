"""Safe fixes for raw CSV cells, and the issue code when a cell is bad.

Only safe fixes are made. Nothing is ever guessed:

* VIN: trim, upper case, remove spaces and hyphens. Then it must be 17
  characters, with no I, O or Q, and a valid check digit.
* Campaign id: loose forms such as rc2026-1 or "RC 2026 001" become
  RC-2026-001.
* Dates: MM/DD/YYYY (the dealership's format) or YYYY-MM-DD, stored as ISO
  YYYY-MM-DD. A date after the as-of date is FUTURE_DATE.
* tech_note: kept byte for byte. It is free text and is never parsed,
  trimmed or acted on.

Each check returns a Result. A good cell has a value and no issue code. A
bad cell has issue_code set (from the REC-18 list) and a plain one-sentence
reason the coordinator can read. Applying a fix to an already fixed value
gives the same value back.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .vin import has_valid_check_digit

# Header names are compared ignoring case, spaces and punctuation, so that
# "VIN", "Vin #" and "vin" all mean vin.
HEADER_ALIASES = {
    "vin": "vin",
    "campaignid": "campaign_id",
    "campaign": "campaign_id",
    "noticedate": "notice_date",
    "repairdate": "repair_date",
    "technote": "tech_note",
}

_SPACES_AND_HYPHENS = re.compile(r"[\s\-]+")
_CAMPAIGN = re.compile(r"RC[\s_\-]*([0-9]{4})[\s_\-]*([0-9]{1,3})",
                       re.IGNORECASE | re.ASCII)
_US_DATE = re.compile(r"([0-9]{1,2})/([0-9]{1,2})/([0-9]{4})", re.ASCII)
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})", re.ASCII)
_VIN_ALLOWED = set("ABCDEFGHJKLMNPRSTUVWXYZ0123456789")

MIN_YEAR = 1900


@dataclass(frozen=True)
class Result:
    """Outcome of checking one cell."""

    value: object = None          # fixed value (str, or date for dates)
    issue_code: str | None = None
    reason: str | None = None

    @property
    def ok(self) -> bool:
        return self.issue_code is None


def _bad(code: str, reason: str) -> Result:
    return Result(None, code, reason)


def _blank(raw: str | None) -> bool:
    return raw is None or raw.strip() == ""


def normalize_header(name: str) -> str | None:
    """Map a raw header to its contract column name, or None if unknown."""
    key = re.sub(r"[^0-9a-z]", "", name.lower())
    return HEADER_ALIASES.get(key)


def normalize_vin(raw: str | None) -> Result:
    if _blank(raw):
        return _bad("MISSING_VALUE", "VIN is blank.")
    vin = _SPACES_AND_HYPHENS.sub("", raw).upper()
    if len(vin) != 17:
        return _bad("BAD_VIN",
                    f"VIN {raw.strip()} has {len(vin)} characters, not 17.")
    banned = sorted(set(vin) & set("IOQ"))
    if banned:
        letters = " and ".join(banned)
        word = "letter" if len(banned) == 1 else "letters"
        return _bad("BAD_VIN", f"VIN {raw.strip()} contains the {word} "
                               f"{letters}, which a VIN never uses.")
    if not set(vin) <= _VIN_ALLOWED:
        return _bad("BAD_VIN",
                    f"VIN {raw.strip()} contains a character a VIN never uses.")
    if not has_valid_check_digit(vin):
        return _bad("BAD_VIN", f"VIN {raw.strip()} has a wrong check digit.")
    return Result(vin)


def normalize_campaign(raw: str | None) -> Result:
    if _blank(raw):
        return _bad("MISSING_VALUE", "Campaign id is blank.")
    m = _CAMPAIGN.fullmatch(raw.strip())
    if not m or int(m.group(2)) == 0 or int(m.group(1)) < MIN_YEAR:
        return _bad("BAD_CAMPAIGN",
                    f"Campaign id {raw.strip()} cannot be read.")
    return Result(f"RC-{m.group(1)}-{int(m.group(2)):03d}")


def parse_date(raw: str | None, label: str = "Date",
               as_of: date | None = None) -> Result:
    """Read a date. label is used in the reason, e.g. "Notice date"."""
    if _blank(raw):
        return _bad("MISSING_VALUE", f"{label} is blank.")
    text = raw.strip()
    year = month = day = None
    if m := _US_DATE.fullmatch(text):
        month, day, year = (int(g) for g in m.groups())
    elif m := _ISO_DATE.fullmatch(text):
        year, month, day = (int(g) for g in m.groups())
    if year is None:
        return _bad("BAD_DATE", f"{label} {text} cannot be read as a date.")
    try:
        if year < MIN_YEAR:
            raise ValueError
        d = date(year, month, day)
    except ValueError:
        return _bad("BAD_DATE", f"{label} {text} is not a real date.")
    if as_of is not None and d > as_of:
        return _bad("FUTURE_DATE",
                    f"{label} {text} is after the as-of date "
                    f"{as_of.strftime('%m/%d/%Y')}.")
    return Result(d)


def normalize_date(raw: str | None, label: str = "Date",
                   as_of: date | None = None) -> Result:
    """Like parse_date, but the value is the ISO string YYYY-MM-DD."""
    res = parse_date(raw, label, as_of)
    return Result(res.value.isoformat()) if res.ok else res


def normalize_note(raw: str | None) -> str:
    """tech_note is free text: returned exactly as written, never read."""
    return "" if raw is None else raw
