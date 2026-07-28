from enum import StrEnum
from typing import Callable, Dict, Union

from dateutil import parser as dateutil_parser

from seiba_risk_scanner.classification_engine.deterministic_detectors import validators


# ============================================================================
# Placeholder for ontology enums that are format-only (regex layer)
# No checksum/logic in validators; return True so detection can proceed.
# ============================================================================

def _format_only_noop(_: str) -> bool:
    """Format-only entity; validation is done by regex/pattern layer. Always returns True."""
    return True


# ============================================================================
# Date span: ontology calls validators with one string; is_valid_date needs a format.
# ============================================================================

def _validate_date_span_common_formats(text: str) -> bool:
    cleaned = text.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y%m%d", "%m-%d-%Y", "%d-%m-%Y"):
        if validators.is_valid_date(cleaned, fmt):
            return True
    try:
        dateutil_parser.parse(cleaned, fuzzy=False)
        return True
    except (ValueError, TypeError, dateutil_parser.ParserError):
        return False


# ============================================================================
# Validator names — values match ontology YAML validators.enum strings exactly.
# ============================================================================

class ValidatorName(StrEnum):
    # PII
    VALIDATE_PHONE_US = "VALIDATE_PHONE_US"
    VALIDATE_US_SSN = "VALIDATE_US_SSN"
    VALIDATE_POSTAL_CODE_FORMAT = "VALIDATE_POSTAL_CODE_FORMAT"
    VALIDATE_LATITUDE = "VALIDATE_LATITUDE"
    VALIDATE_LONGITUDE = "VALIDATE_LONGITUDE"
    VALIDATE_DATE = "VALIDATE_DATE"
    VALIDATE_UNIX_TIMESTAMP = "VALIDATE_UNIX_TIMESTAMP"
    VALIDATE_TIMESTAMP = "VALIDATE_TIMESTAMP"
    VALIDATE_IMEI = "VALIDATE_IMEI"
    VALIDATE_IPV4_RANGE = "VALIDATE_IPV4_RANGE"
    VALIDATE_WEB_URL = "VALIDATE_WEB_URL"
    VALIDATE_VIN = "VALIDATE_VIN"
    VALIDATE_CANADIAN_SIN = "VALIDATE_CANADIAN_SIN"
    VALIDATE_INDIAN_AADHAAR = "VALIDATE_INDIAN_AADHAAR"
    VALIDATE_US_ITIN = "VALIDATE_US_ITIN"
    VALIDATE_UK_NHS = "VALIDATE_UK_NHS"
    # PHI
    VALIDATE_NPI = "VALIDATE_NPI"
    # Financial
    VALIDATE_LUHN_CHECKSUM = "VALIDATE_LUHN_CHECKSUM"
    VALIDATE_ABA_ROUTING_NUMBER = "VALIDATE_ABA_ROUTING_NUMBER"
    VALIDATE_IBAN = "VALIDATE_IBAN"


ValidatorCallable = Callable[[str], Union[bool, tuple]]


VALIDATOR_REGISTRY: Dict[ValidatorName, ValidatorCallable] = {
    ValidatorName.VALIDATE_PHONE_US: validators.validate_phone_us,
    ValidatorName.VALIDATE_US_SSN: validators.validate_us_ssn,
    ValidatorName.VALIDATE_POSTAL_CODE_FORMAT: _format_only_noop,
    ValidatorName.VALIDATE_LATITUDE: validators.validate_latitude,
    ValidatorName.VALIDATE_LONGITUDE: validators.validate_longitude,
    ValidatorName.VALIDATE_DATE: _validate_date_span_common_formats,
    ValidatorName.VALIDATE_UNIX_TIMESTAMP: validators.is_unix_timestamp,
    ValidatorName.VALIDATE_TIMESTAMP: validators.validate_timestamp,
    ValidatorName.VALIDATE_IMEI: validators.validate_imei,
    ValidatorName.VALIDATE_IPV4_RANGE: validators.validate_ipv4_range,
    ValidatorName.VALIDATE_WEB_URL: validators.validate_web_url,
    ValidatorName.VALIDATE_VIN: validators.validate_vin,
    ValidatorName.VALIDATE_CANADIAN_SIN: validators.validate_canadian_sin,
    ValidatorName.VALIDATE_INDIAN_AADHAAR: validators.validate_indian_aadhaar,
    ValidatorName.VALIDATE_US_ITIN: validators.validate_us_itin,
    ValidatorName.VALIDATE_UK_NHS: validators.validate_uk_nhs,
    ValidatorName.VALIDATE_NPI: validators.validate_npi,
    ValidatorName.VALIDATE_LUHN_CHECKSUM: validators.luhn_checksum,
    ValidatorName.VALIDATE_ABA_ROUTING_NUMBER: validators.validate_aba_routing_number,
    ValidatorName.VALIDATE_IBAN: validators.validate_iban,
}


def get_validator_function(validator_name: ValidatorName) -> ValidatorCallable:
    """Return the validator callable for a parsed ontology enum."""
    return VALIDATOR_REGISTRY[validator_name]
