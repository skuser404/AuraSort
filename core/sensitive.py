"""Deterministic confidential-content detection (regex + checksum validation + keywords). Runs locally, before and
independently of any language model. Only the kind of match and a masked form are ever kept, never the value."""
import re

LEVELS = ("normal", "sensitive", "confidential")
RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# ---------------- checksums ----------------
_VERHOEFF_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6], [3, 4, 0, 1, 2, 8, 9, 5, 6, 7],
               [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1], [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3],
               [8, 7, 6, 5, 9, 3, 2, 1, 0, 4], [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_VERHOEFF_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2], [8, 9, 1, 6, 0, 4, 3, 5, 2, 7],
               [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1], [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def luhn_ok(digits):
    """Why: card numbers carry a Luhn check digit; random 16-digit numbers almost never pass."""
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
        alt = not alt
    return total % 10 == 0


def verhoeff_ok(digits):
    """Why: Aadhaar numbers end in a Verhoeff check digit."""
    c = 0
    for i, ch in enumerate(reversed(digits)):
        c = _VERHOEFF_D[c][_VERHOEFF_P[i % 8][int(ch)]]
    return c == 0


def iban_ok(iban):
    """Why: IBANs carry an ISO 7064 mod-97 check."""
    s = iban[4:] + iban[:4]
    num = "".join(str(int(ch, 36)) for ch in s)
    return int(num) % 97 == 1


# ---------------- patterns ----------------
_CARD = re.compile(r"(?<![\d-])(?:\d[ -]?){12,18}\d(?![\d-])")
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]){11,30}\b")
_IFSC = re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b")
_ACCOUNT = re.compile(r"(?i)\b(?:a/c|acct|account)(?:\s*(?:no|number|#))?\.?\s*[:\-]?\s*(\d{9,18})\b")
_AADHAAR = re.compile(r"(?<!\d)[2-9]\d{3}[ -]?\d{4}[ -]?\d{4}(?!\d)")
_PAN = re.compile(r"\b[A-Z]{3}[ABCFGHLJPT][A-Z]\d{4}[A-Z]\b")
_GSTIN = re.compile(r"\b\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b")
_SSN = re.compile(r"\b(?!000|666|9\d\d)\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]{2,}\b")
_PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[ -]?)?(?:\d[ -]?){9,11}\d(?!\d)")
_PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----")
_TOKENS = re.compile(r"\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{36}|github_pat_[A-Za-z0-9_]{40,}|xox[abprs]-[A-Za-z0-9-]{10,}|AIza[0-9A-Za-z_-]{35})\b")
_PASSWORD = re.compile(r"(?i)\b(?:password|passwd|pwd|passcode)\s*[:=]\s*(\S{4,})")
_CARD_IIN = re.compile(r"^(?:4|5[1-5]|2[2-7]|3[47]|6(?:011|5)|35|30[0-5]|36|38)")

KEYWORDS = (  # (level, label, regex)
    ("confidential", "Bank statement", r"\b(?:bank|account) statement\b|\bstatement of account\b"),
    ("confidential", "Salary slip", r"\b(?:salary|pay) ?slip\b|\bpayslip\b"),
    ("confidential", "Tax return", r"\bincome tax return\b|\btax return\b|\bform[ -]?16\b|\bITR-?\d\b"),
    ("confidential", "Credit report", r"\bCIBIL\b|\bcredit (?:report|score)\b"),
    ("sensitive", "Loan document", r"\bloan (?:account|agreement|sanction|statement)\b|\bEMI schedule\b"),
    ("sensitive", "Passport or licence details", r"\bpassport (?:no|number)\b|\bdriving licen[cs]e\b|\bDL No\b"),
    ("sensitive", "Offer letter", r"\boffer letter\b|\bletter of offer\b|\bwe are pleased to offer you\b"),
    ("sensitive", "Appraisal", r"\bperformance (?:appraisal|review)\b|\bappraisal letter\b"),
    ("sensitive", "Contract or NDA", r"\bnon-disclosure agreement\b|\bNDA\b|\bemployment (?:contract|agreement)\b|\bconfidentiality agreement\b"),
    ("sensitive", "Medical record", r"\bmedical report\b|\bdiagnosis\b|\bprescription\b|\blab(?:oratory)? report\b|\bdischarge summary\b"),
)
_KEYWORDS = [(lvl, label, re.compile(rx, re.I)) for lvl, label, rx in KEYWORDS]
_RESUME = re.compile(r"(?i)\b(?:resume|curriculum vitae|\bCV\b)")


def mask(value, keep=4):
    """Why: results may show *that* a number was found, never the number itself."""
    v = re.sub(r"[\s-]", "", value)
    return "•" * max(0, min(8, len(v) - keep)) + v[-keep:] if len(v) > keep else "•" * len(v)


def _hit(found, level, label, value=None):
    """Why: one reason per kind of finding, with a count and one masked example."""
    r = found.setdefault(label, dict(level=level, label=label, count=0, masked=""))
    r["count"] += 1
    if value and not r["masked"]:
        r["masked"] = mask(value)
    if RANK[level] > RANK[r["level"]]:
        r["level"] = level


def _cards(text, found):
    for m in _CARD.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if 13 <= len(d) <= 19 and _CARD_IIN.match(d) and luhn_ok(d) and len(set(d)) > 1:
            _hit(found, "confidential", "Card number", d)


def _ids(text, found):
    for m in _AADHAAR.finditer(text):
        d = re.sub(r"\D", "", m.group(0))
        if verhoeff_ok(d) and len(set(d)) > 2:
            _hit(found, "confidential", "Aadhaar number", d)
    for m in _PAN.finditer(text):
        _hit(found, "confidential", "PAN number", m.group(0))
    for m in _GSTIN.finditer(text):
        _hit(found, "sensitive", "GSTIN", m.group(0))
    for m in _SSN.finditer(text):
        _hit(found, "confidential", "SSN-style number", m.group(0))
    for m in _IBAN.finditer(text):
        iban = m.group(0).replace(" ", "")
        if 15 <= len(iban) <= 34 and iban_ok(iban):
            _hit(found, "confidential", "IBAN", iban)
    ifsc = _IFSC.search(text)
    if ifsc:
        _hit(found, "sensitive", "IFSC code", ifsc.group(0))
    for m in _ACCOUNT.finditer(text):
        _hit(found, "confidential", "Bank account number", m.group(1))


def _secrets(text, found):
    if _PRIVATE_KEY.search(text):
        _hit(found, "confidential", "Private key")
    for m in _TOKENS.finditer(text):
        _hit(found, "confidential", "API key or token", m.group(0))
    for m in _PASSWORD.finditer(text):
        _hit(found, "confidential", "Password in text", m.group(1))


def scan(text, name=""):
    """Why: the rule-based verdict: level + reasons (each with a count and a masked example). Never returns raw values."""
    text = text or ""
    found = {}
    _cards(text, found)
    _ids(text, found)
    _secrets(text, found)
    hay = f"{name}\n{text}"
    for lvl, label, rx in _KEYWORDS:
        if rx.search(hay):
            _hit(found, lvl, label)
    if _RESUME.search(hay) and (_EMAIL.search(text) or _PHONE.search(text)):
        _hit(found, "sensitive", "Resume with contact details")
    reasons = sorted(found.values(), key=lambda r: (-RANK[r["level"]], r["label"]))
    level = max((r["level"] for r in reasons), key=RANK.get, default="normal")
    return dict(level=level, reasons=reasons)


def redact(text):
    """Why: before any cloud call, detected IDs, numbers and secrets are replaced by placeholders (data minimisation)."""
    out = _PRIVATE_KEY.sub("[PRIVATE KEY]", text or "")
    out = _TOKENS.sub("[TOKEN]", out)
    out = _PASSWORD.sub(lambda m: m.group(0).replace(m.group(1), "[PASSWORD]"), out)
    out = _IBAN.sub(lambda m: "[IBAN]" if iban_ok(m.group(0).replace(" ", "")) else m.group(0), out)
    out = _CARD.sub(lambda m: "[CARD]" if luhn_ok(re.sub(r"\D", "", m.group(0))) else m.group(0), out)
    out = _AADHAAR.sub(lambda m: "[AADHAAR]" if verhoeff_ok(re.sub(r"\D", "", m.group(0))) else m.group(0), out)
    out = _PAN.sub("[PAN]", out)
    out = _GSTIN.sub("[GSTIN]", out)
    out = _SSN.sub("[ID]", out)
    out = _ACCOUNT.sub(lambda m: m.group(0).replace(m.group(1), "[ACCOUNT]"), out)
    out = _EMAIL.sub("[EMAIL]", out)
    return _PHONE.sub("[PHONE]", out)


def combine(rule, model_raise=None):
    """Why: the model may raise the level (with a stated reason) but can never lower a rule-based flag."""
    level, reasons = rule["level"], list(rule["reasons"])
    if model_raise and model_raise.get("level") in LEVELS and RANK[model_raise["level"]] > RANK[level]:
        level = model_raise["level"]
        reasons.append(dict(level=level, label=("Model: " + str(model_raise.get("reason") or "flagged"))[:90], count=1, masked="", by="model"))
    return dict(level=level, reasons=reasons)
