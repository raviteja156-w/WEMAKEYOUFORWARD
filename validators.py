"""
Input validation for employer registration and company profile forms.
Pure functions — no Flask imports — so they are easy to unit test.
"""
import re

# ISO code, display name, international dial code. Australia first (primary market).
COUNTRIES = [
    {"code": "AU", "name": "Australia", "dial": "61"},
    {"code": "NZ", "name": "New Zealand", "dial": "64"},
    {"code": "IN", "name": "India", "dial": "91"},
    {"code": "GB", "name": "United Kingdom", "dial": "44"},
    {"code": "US", "name": "United States", "dial": "1"},
    {"code": "CA", "name": "Canada", "dial": "1"},
    {"code": "SG", "name": "Singapore", "dial": "65"},
    {"code": "HK", "name": "Hong Kong", "dial": "852"},
    {"code": "JP", "name": "Japan", "dial": "81"},
    {"code": "MY", "name": "Malaysia", "dial": "60"},
    {"code": "ID", "name": "Indonesia", "dial": "62"},
    {"code": "PH", "name": "Philippines", "dial": "63"},
    {"code": "IE", "name": "Ireland", "dial": "353"},
    {"code": "DE", "name": "Germany", "dial": "49"},
    {"code": "FR", "name": "France", "dial": "33"},
    {"code": "ZA", "name": "South Africa", "dial": "27"},
    {"code": "AE", "name": "United Arab Emirates", "dial": "971"},
]
COUNTRY_BY_CODE = {c["code"]: c for c in COUNTRIES}

_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")


def normalise_email(value):
    return (value or "").strip().lower()


def validate_email(email):
    """Return an error message, or None if the address looks valid."""
    if not email:
        return "Enter your email address."
    if len(email) > 254 or not _EMAIL_RE.match(email):
        return "Enter a valid email address, like you@company.com."
    return None


def validate_new_password(password):
    if not password:
        return "Create a password."
    if len(password) < 8:
        return "Use at least 8 characters."
    if len(password) > 128:
        return "Use 128 characters or fewer."
    if not re.search(r"[A-Za-z]", password) or not re.search(r"\d", password):
        return "Include at least one letter and one number."
    return None


def clean_text(value, max_len):
    """Trim and collapse internal whitespace."""
    return re.sub(r"\s+", " ", (value or "").strip())[:max_len]


def digits_only(value):
    return re.sub(r"\D", "", value or "")


def format_abn(digits):
    return f"{digits[:2]} {digits[2:5]} {digits[5:8]} {digits[8:11]}" if len(digits) == 11 else digits


def is_valid_abn(value):
    """Official ABN checksum: subtract 1 from the first digit, apply weights, sum % 89 == 0."""
    d = digits_only(value)
    if len(d) != 11:
        return False
    nums = [int(c) for c in d]
    nums[0] -= 1
    weights = [10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19]
    return sum(n * w for n, w in zip(nums, weights)) % 89 == 0


def normalise_phone(country_code, value):
    """
    Return (national_digits, error). Leading trunk zeros are dropped, so
    '0412 345 678' and '412 345 678' are stored identically.
    """
    digits = digits_only(value).lstrip("0")
    if not digits:
        return "", "Enter a contact number."
    if country_code == "AU":
        if len(digits) != 9 or digits[0] not in "23478":
            return "", "Enter a valid Australian number, like 412 345 678."
    elif not 6 <= len(digits) <= 12:
        return "", "Enter a valid phone number."
    return digits, None


def format_phone(country_code, digits):
    country = COUNTRY_BY_CODE.get(country_code)
    if not country or not digits:
        return digits
    if len(digits) == 9:
        return f"+{country['dial']} {digits[:3]} {digits[3:6]} {digits[6:]}"
    return f"+{country['dial']} {digits}"
