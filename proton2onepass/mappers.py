"""Item mappers: Proton Pass item dict -> 1PUX item dict.

Each mapper returns a fully-formed 1PUX item. Passkey/attachment/skip
*reporting* is handled by the caller scanning the raw export, not here.
"""
from __future__ import annotations

from datetime import datetime

from .writer import new_id

_TRAITS = {"keyboard": "default", "correction": "default", "capitalization": "default"}

CATEGORY = {
    "login": "001",
    "creditCard": "002",
    "note": "003",
    "identity": "004",
    "alias": "001",   # default; may become 003 via --alias-as note
    "custom": "003",
}


# ---- value wrappers ---------------------------------------------------------

def _string(s):
    return {"string": s or ""}


def _concealed(s):
    return {"concealed": s or ""}


def _totp(uri):
    return {"totp": uri or ""}


def _date(raw):
    """Proton timestamp -> 1PUX {"date": <unix int|null>}."""
    if raw is None or raw == "":
        return {"date": None}
    if isinstance(raw, (int, float)):
        return {"date": int(raw)}
    s = str(raw).strip()
    if s.isdigit():
        return {"date": int(s)}
    for parse in (
        lambda x: datetime.fromisoformat(x),
        lambda x: datetime.strptime(x, "%Y-%m-%d"),
        lambda x: datetime.strptime(x, "%m/%d/%Y"),
    ):
        try:
            return {"date": int(parse(s).timestamp())}
        except (ValueError, TypeError):
            continue
    return {"string": s}  # un-parseable -> keep as text, never drop


def _month_year(raw):
    """Credit-card expiry -> {"monthYear": YYYYMM} or None if un-parseable."""
    if not raw:
        return None
    s = str(raw).strip()
    for fmt in ("%Y-%m", "%m/%Y", "%Y-%m-%d", "%m/%y"):
        try:
            d = datetime.strptime(s, fmt)
            return d.year * 100 + d.month
        except ValueError:
            continue
    # bare YYYYMM
    if s.isdigit() and len(s) == 6:
        return int(s)
    return None


# ---- field / section builders ----------------------------------------------

def _field(title, value, guarded=False, multiline=False):
    return {
        "title": title or "",
        "id": new_id(),
        "value": value,
        "guarded": guarded,
        "multiline": multiline,
        "dontGenerate": False,
        "inputTraits": dict(_TRAITS),
    }


def _section(title, fields, name=""):
    return {"title": title or "", "name": name or "", "fields": fields}


def _overview(title, *, url="", urls=None, subtitle=""):
    # `subtitle` is REQUIRED by 1Password's 1pux importer (omitting the key
    # causes the whole item to be rejected). Always include it, even if "".
    ov = {"title": title or "", "url": url or "", "subtitle": subtitle or "",
          "icons": None, "watchtowerExclusions": None}
    if urls is not None:
        ov["urls"] = urls
    return ov


def _login_field(value, name, designation, field_type):
    return {
        "value": value or "",
        "id": "",
        "name": name,
        "fieldType": field_type,
        "designation": designation,
    }


def _extra_fields(data):
    """Map Proton data.extraFields[] -> list of 1PUX section fields."""
    out = []
    for ef in data.get("extraFields") or []:
        name = ef.get("fieldName") or ""
        t = ef.get("type")
        d = ef.get("data") or {}
        if t == "text":
            out.append(_field(name, _string(d.get("content", ""))))
        elif t == "hidden":
            out.append(_field(name, _concealed(d.get("content", ""))))
        elif t == "totp":
            uri = d.get("totpUri") or d.get("content") or ""
            if uri:
                out.append(_field(name or "one-time password", _totp(uri)))
        elif t == "timestamp":
            out.append(_field(name, _date(d.get("timestamp"))))
        else:
            c = d.get("content")
            if isinstance(c, str) and c:
                out.append(_field(name, _string(c)))
    return out


def _extra_section(data):
    fields = _extra_fields(data)
    return [_section("", fields, name=new_id())] if fields else []


# ---- envelope ---------------------------------------------------------------

def _envelope(item, category, details, overview):
    return {
        "uuid": new_id(),
        "favIndex": 0,
        "createdAt": int(item.get("createTime") or 0),
        "updatedAt": int(item.get("modifyTime") or 0),
        "state": "active",
        "categoryUuid": category,
        "details": details,
        "overview": overview,
    }


def _meta(item):
    return item.get("data", {}).get("metadata", {}) or {}


# ---- per-type mappers -------------------------------------------------------

def map_login(item, opts):
    data = item.get("data", {})
    c = data.get("content", {}) or {}
    meta = _meta(item)
    username = (c.get("itemUsername") or "").strip()
    email = (c.get("itemEmail") or "").strip()
    password = c.get("password") or ""

    login_fields = []
    extra = []
    primary = username or email
    if primary:
        # username primary; email becomes username only when no username exists
        login_fields.append(
            _login_field(primary, "username" if username else "email", "username", "T")
        )
    if username and email:
        extra.append(_field("email", _string(email)))
    if password:
        login_fields.append(_login_field(password, "password", "password", "P"))

    sections = []
    totp = c.get("totpUri") or ""
    if totp:
        sections.append(_section("", [_field("one-time password", _totp(totp))], name="add more"))
    extra += _extra_fields(data)
    if extra:
        sections.append(_section("", extra, name=new_id()))

    urls = [u for u in (c.get("urls") or []) if u]
    overview = _overview(
        meta.get("name", ""),
        url=urls[0] if urls else "",
        urls=[{"label": "", "url": u, "mode": "default"} for u in urls],
        subtitle=primary,
    )
    details = {
        "loginFields": login_fields,
        "notesPlain": meta.get("note", "") or "",
        "sections": sections,
        "passwordHistory": [],
    }
    return _envelope(item, "001", details, overview)


def map_alias(item, opts):
    data = item.get("data", {})
    meta = _meta(item)
    alias = item.get("aliasEmail") or ""
    note = meta.get("note", "") or ""
    title = meta.get("name", "") or ""

    if getattr(opts, "alias_as", "login") == "note":
        body = note
        if alias:
            body = f"Alias: {alias}\n\n{note}".strip()
        details = {"loginFields": [], "notesPlain": body,
                   "sections": _extra_section(data), "passwordHistory": []}
        return _envelope(item, "003", details, _overview(title, subtitle=alias))

    login_fields = []
    if alias:
        login_fields.append(_login_field(alias, "username", "username", "T"))
    # A Login with only a username (no password/URL/section) is rejected by the
    # importer, so surface the alias address as a section field too.
    sections = _extra_section(data)
    if alias:
        sections = [_section("", [_field("alias", _string(alias))])] + sections
    details = {"loginFields": login_fields, "notesPlain": note,
               "sections": sections, "passwordHistory": []}
    overview = _overview(title, urls=[], subtitle=alias)
    return _envelope(item, "001", details, overview)


def map_note(item, opts):
    data = item.get("data", {})
    meta = _meta(item)
    details = {"loginFields": [], "notesPlain": meta.get("note", "") or "",
               "sections": _extra_section(data), "passwordHistory": []}
    return _envelope(item, "003", details, _overview(meta.get("name", "")))


def map_custom(item, opts):
    # Proton custom item: fields live in extraFields (content.sections seen empty).
    return map_note(item, opts)


def map_credit_card(item, opts):
    data = item.get("data", {})
    c = data.get("content", {}) or {}
    meta = _meta(item)
    fields = []
    if c.get("cardholderName"):
        fields.append(_field("cardholder name", _string(c["cardholderName"])))
    if c.get("number"):
        fields.append(_field("number", {"creditCardNumber": c["number"]}))
    if c.get("verificationNumber"):
        fields.append(_field("verification number", _concealed(c["verificationNumber"])))
    my = _month_year(c.get("expirationDate"))
    if my is not None:
        fields.append(_field("expiry date", {"monthYear": my}))
    elif c.get("expirationDate"):
        fields.append(_field("expiry date", _string(c["expirationDate"])))
    if c.get("pin"):
        fields.append(_field("PIN", _concealed(c["pin"])))
    # cardType is an opaque int enum in Proton; not reliably decodable -> skip.

    sections = [_section("", fields)] if fields else []
    sections += _extra_section(data)
    details = {"loginFields": [], "notesPlain": meta.get("note", "") or "",
               "sections": sections, "passwordHistory": []}
    return _envelope(item, "002", details, _overview(meta.get("name", "")))


_IDENTITY_SKIP = {"extraPersonalDetails", "extraAddressDetails", "extraContactDetails",
                  "extraWorkDetails", "extraSections"}


def _humanize(key):
    out = []
    for ch in key:
        if ch.isupper():
            out.append(" ")
        out.append(ch)
    return "".join(out).strip().lower()


def map_identity(item, opts):
    data = item.get("data", {})
    c = data.get("content", {}) or {}
    meta = _meta(item)
    fields = []
    for key, val in c.items():
        if key in _IDENTITY_SKIP:
            continue
        if isinstance(val, str) and val.strip():
            if key.lower() in ("birthdate", "birthday"):
                fields.append(_field(_humanize(key), _date(val)))
            else:
                fields.append(_field(_humanize(key), _string(val)))
    # flatten the extra* arrays (each entry: {fieldName, type, data:{content}})
    for key in _IDENTITY_SKIP:
        for entry in c.get(key) or []:
            if isinstance(entry, dict) and "fieldName" in entry:
                content = (entry.get("data") or {}).get("content", "")
                if content:
                    fields.append(_field(entry.get("fieldName") or "", _string(content)))

    sections = [_section("Personal Information", fields)] if fields else []
    sections += _extra_section(data)
    details = {"loginFields": [], "notesPlain": meta.get("note", "") or "",
               "sections": sections, "passwordHistory": []}
    return _envelope(item, "004", details, _overview(meta.get("name", "")))


_MAPPERS = {
    "login": map_login,
    "alias": map_alias,
    "note": map_note,
    "custom": map_custom,
    "creditCard": map_credit_card,
    "identity": map_identity,
}


def map_item(item, opts):
    """Dispatch on Proton item type. Unknown types -> Secure Note (never drop)."""
    itype = item.get("data", {}).get("type", "")
    mapper = _MAPPERS.get(itype, map_note)
    return mapper(item, opts), itype
