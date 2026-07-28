import re
from typing import Optional, Tuple
from datetime import datetime
from urllib.parse import urlparse
import phonenumbers
from phonenumbers import NumberParseException
from dateutil import parser as date_parser


# ============================================================================
# Phone Number Validators
# ============================================================================

KNOWN_COUNTRY_CODES = {
    '1', '7', '20', '27', '30', '31', '32', '33', '34', '36', '39', '40', '41', '43', '44',
    '45', '46', '47', '48', '49', '51', '52', '53', '54', '55', '56', '57', '58', '60', '61',
    '62', '63', '64', '65', '66', '81', '82', '84', '86', '90', '91', '92', '93', '94', '95',
    '98', '212', '213', '216', '218', '220', '221', '222', '223', '224', '225', '226', '227',
    '228', '229', '230', '231', '232', '233', '234', '235', '236', '237', '238', '239', '240',
    '241', '242', '243', '244', '245', '246', '248', '249', '250', '251', '252', '253', '254',
    '255', '256', '257', '258', '260', '261', '262', '263', '264', '265', '266', '267', '268',
    '269', '290', '291', '297', '298', '299', '350', '351', '352', '353', '354', '355', '356',
    '357', '358', '359', '370', '371', '372', '373', '374', '375', '376', '377', '378', '380',
    '381', '382', '383', '385', '386', '387', '389', '420', '421', '423', '500', '501', '502',
    '503', '504', '505', '506', '507', '508', '509', '590', '591', '592', '593', '594', '595',
    '596', '597', '598', '599', '670', '672', '673', '674', '675', '676', '677', '678', '679',
    '680', '681', '682', '683', '684', '685', '686', '687', '688', '689', '690', '691', '692',
    '850', '852', '853', '855', '856', '880', '886', '960', '961', '962', '963', '964', '965',
    '966', '967', '968', '970', '971', '972', '973', '974', '975', '976', '977', '992', '993',
    '994', '995', '996', '998'
}


def validate_e164_phone(phone: str) -> Tuple[bool, Optional[str]]:
    """
    Validate phone number in E.164 format (checksum/logic only; no regex).

    E.164 rules: starts with +, 7-15 digits, first digit 1-9, optional known country code.
    Separators are stripped via character filter (no regex).
    """
    # Keep only '+' and digits (strip separators without regex)
    chars = [c for c in phone if c == '+' or c.isdigit()]
    if not chars or chars[0] != '+':
        return False, None
    digits = ''.join(chars[1:])
    if not digits:
        return False, None
    if len(digits) > 15:
        return False, None
    if len(digits) < 7:
        return False, None
    if digits[0] not in '123456789':
        return False, None
    # Optional: match known country code (1-3 digits)
    for length in [3, 2, 1]:
        if len(digits) >= length:
            potential_code = digits[:length]
            if potential_code in KNOWN_COUNTRY_CODES:
                break
    return True, '+' + digits


def validate_phone_number_with_library(phone: str, region: Optional[str] = None) -> Tuple[bool, Optional[str]]:
    try:
        parsed = phonenumbers.parse(phone, region)
        is_valid = phonenumbers.is_valid_number(parsed)
        
        if is_valid:
            formatted = phonenumbers.format_number(parsed, phonenumbers.PhoneNumberFormat.E164)
        else:
            formatted = None
        
        return is_valid, formatted
    except NumberParseException:
        return False, None


def validate_phone_us(phone: str) -> Tuple[bool, Optional[str]]:
    """NANP and other US-parseable numbers; ontology-driven detection passes one string."""
    return validate_phone_number_with_library(phone, "US")


# ============================================================================
# National ID Validators
# ============================================================================

def validate_us_ssn(ssn: str) -> bool:
    cleaned = ''.join(c for c in ssn if c.isdigit())
    
    if len(cleaned) != 9:
        return False
    
    area = cleaned[0:3]
    group = cleaned[3:5]
    serial = cleaned[5:9]
    
    if area == '000' or area == '666':
        return False
    if area.startswith('9'):
        return False
    
    if group == '00':
        return False
    
    if serial == '0000':
        return False
    
    return True


def validate_us_itin(itin: str) -> bool:
    cleaned = ''.join(c for c in itin if c.isdigit())
    
    if len(cleaned) != 9:
        return False
    
    if cleaned[0] != '9':
        return False
    
    if cleaned[3] not in ['7', '8']:
        return False
    
    return True


def validate_canadian_sin(sin: str) -> bool:
    cleaned = ''.join(c for c in sin if c.isdigit())
    
    if len(cleaned) != 9:
        return False
    
    if cleaned == '000000000':
        return False
    
    if len(set(cleaned)) == 1:
        return False
    
    digit_sum = sum(int(d) for d in cleaned)
    if digit_sum == 0:
        return False
    
    return True


def validate_indian_aadhaar(aadhaar: str) -> bool:
    cleaned = ''.join(c for c in aadhaar if c.isdigit())

    if len(cleaned) != 12:
        return False

    if cleaned[0] in ['0', '1']:
        return False

    if len(set(cleaned)) == 1:
        return False

    return True


def validate_uk_nhs(nhs: str) -> bool:
    digits = ''.join(c for c in nhs if c.isdigit())

    if len(digits) != 10:
        return False

    total = sum(int(digits[i]) * (10 - i) for i in range(9))
    check = 11 - (total % 11)
    if check == 11:
        check = 0
    if check == 10:
        return False

    return check == int(digits[9])


def validate_npi(npi: str) -> bool:
    """NPI: Luhn check over the 10 digits prefixed with the 80840 issuer id."""
    digits = ''.join(c for c in npi if c.isdigit())

    if len(digits) != 10:
        return False

    return luhn_checksum("80840" + digits)


# ============================================================================
# Financial Validators
# ============================================================================

def luhn_checksum(card_number: str) -> bool:
    digits = ''.join(c for c in card_number if c.isdigit())
    
    if not digits:
        return False
    
    digits = digits[::-1]
    
    total = 0
    for i, digit in enumerate(digits):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    
    return total % 10 == 0


def validate_aba_routing_number(routing: str) -> bool:
    digits = ''.join(c for c in routing if c.isdigit())
    
    if len(digits) != 9:
        return False
    
    weights = [3, 7, 1, 3, 7, 1, 3, 7, 1]
    total = sum(int(digits[i]) * weights[i] for i in range(9))
    
    return total % 10 == 0


def validate_iban(iban: str) -> bool:
    iban = ''.join(c for c in iban.upper() if not c.isspace())
    
    if len(iban) < 15 or len(iban) > 34:
        return False
    
    if len(iban) < 4:
        return False
    
    if not iban[:2].isalpha():
        return False
    
    if not all(c.isalnum() for c in iban[2:]):
        return False
    
    rearranged = iban[4:] + iban[:4]
    
    numeric = ''
    for char in rearranged:
        if char.isdigit():
            numeric += char
        else:
            numeric += str(ord(char) - ord('A') + 10)
    
    remainder = int(numeric) % 97
    
    return remainder == 1


# ============================================================================
# Device and Vehicle Validators
# ============================================================================

def validate_imei(imei: str) -> bool:
    digits = ''.join(c for c in imei if c.isdigit())
    
    if len(digits) != 15:
        return False
    
    return luhn_checksum(digits)


def validate_vin(vin: str) -> bool:
    vin = vin.upper().strip()
    
    if len(vin) != 17:
        return False
    
    if 'I' in vin or 'O' in vin or 'Q' in vin:
        return False
    
    if not all(c.isalnum() for c in vin):
        return False
    
    return True


# ============================================================================
# Network and Address Validators
# ============================================================================

def validate_ipv4_range(ip: str) -> bool:
    parts = ip.split('.')
    
    if len(parts) != 4:
        return False
    
    for part in parts:
        if not part.isdigit():
            return False
        value = int(part)
        if value < 0 or value > 255:
            return False
    
    return True


def validate_web_url(url: str) -> bool:
    try:
        # Scheme-less URLs (e.g. www.example.com) get a default scheme so they parse.
        parsed = urlparse(url if "://" in url else f"http://{url}")

        if parsed.scheme not in ('http', 'https'):
            return False
        
        if not parsed.netloc:
            return False
        
        if '.' not in parsed.netloc:
            return False
        
        domain_parts = parsed.netloc.split('.')
        if len(domain_parts) < 2:
            return False
        
        tld = domain_parts[-1].split(':')[0]
        if len(tld) < 2:
            return False
        
        return True
    except (ValueError, AttributeError):
        return False


# ============================================================================
# Geospatial Validators
# ============================================================================

def validate_latitude(lat: str) -> bool:
    try:
        cleaned = lat.strip().upper()
        
        is_south = 'S' in cleaned
        cleaned = ''.join(c for c in cleaned if c not in 'NS').strip()
        
        try:
            value = float(cleaned)
            if is_south:
                value = -abs(value)
            return -90.0 <= value <= 90.0
        except ValueError:
            pass
        
        return False
    except (ValueError, AttributeError):
        return False


def validate_longitude(lon: str) -> bool:
    try:
        cleaned = lon.strip().upper()
        
        is_west = 'W' in cleaned
        cleaned = ''.join(c for c in cleaned if c not in 'EW').strip()
        
        try:
            value = float(cleaned)
            if is_west:
                value = -abs(value)
            return -180.0 <= value <= 180.0
        except ValueError:
            pass
        
        return False
    except (ValueError, AttributeError):
        return False


# ============================================================================
# Date and Time Validators
# ============================================================================

def is_valid_date(date_string: str, date_format: str) -> bool:
    try:
        datetime.strptime(date_string, date_format)
        return True
    except ValueError:
        return False


def validate_date_year_range(date_string: str, min_year: int = 1900, max_year: int = 2100) -> Tuple[bool, Optional[str]]:
    try:
        parsed = date_parser.parse(date_string, fuzzy=False)
        
        if parsed.year < min_year:
            return False, f"Date year {parsed.year} is before minimum year {min_year}"
        if parsed.year > max_year:
            return False, f"Date year {parsed.year} is after maximum year {max_year}"
        
        return True, None
    except (ValueError, TypeError, date_parser.ParserError) as e:
        return False, f"Date string '{date_string}' cannot be parsed as date: {str(e)}"


def is_unix_timestamp(text: str) -> bool:
    digits = ''.join(c for c in text if c.isdigit())
    
    if len(digits) == 10:
        try:
            timestamp = int(digits)
            if 0 <= timestamp <= 978307200:
                return True
        except ValueError:
            pass
    elif len(digits) == 13:
        try:
            timestamp = int(digits) // 1000
            if 0 <= timestamp <= 978307200:
                return True
        except ValueError:
            pass

    return False


_CLOCK_TIME_RE = re.compile(
    r"^\s*(?P<hour>\d{1,2})(?::(?P<minute>[0-5]\d)(?::(?P<second>[0-5]\d))?)?\s*(?P<meridiem>[ap]\.?m\.?)?\s*$",
    re.IGNORECASE,
)


def is_clock_time(text: str) -> bool:
    """True for a time of day: "11:45 PM", "8:30", "14:05", "3am".

    Bare hours are only a time when a meridiem says so, otherwise "3" is just a number.
    """
    match = _CLOCK_TIME_RE.match(text or "")
    if match is None:
        return False
    hour = int(match.group("hour"))
    meridiem = match.group("meridiem")
    if meridiem:
        return 1 <= hour <= 12
    if match.group("minute") is None:
        return False
    return 0 <= hour <= 23


def validate_timestamp(text: str) -> bool:
    """A point in time: either a unix epoch or a clock time."""
    return is_unix_timestamp(text) or is_clock_time(text)


# ============================================================================
# Insurance Validators
# ============================================================================

def validate_insurance_id(insurance_id: str) -> Tuple[bool, Optional[str]]:
    if len(insurance_id) < 8 or len(insurance_id) > 15:
        return False, f"Insurance ID length {len(insurance_id)} is outside valid range (8-15)"
    
    cleaned = insurance_id.replace('-', '').replace('_', '')
    if not cleaned.isalnum():
        return False, f"Insurance ID '{insurance_id}' contains invalid characters (must be alphanumeric)"
    
    if not any(c.isdigit() for c in insurance_id):
        return False, f"Insurance ID '{insurance_id}' must contain at least one digit (rejecting pure alphabetic strings)"

    if not any(c.isalpha() for c in insurance_id):
        return False, f"Insurance ID '{insurance_id}' must contain at least one letter (rejecting digit-only tokens)"
    
    return True, None
