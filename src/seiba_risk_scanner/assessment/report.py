from __future__ import annotations

from collections import defaultdict
from typing import Dict, List, Literal, Optional, Sequence, Tuple

from seiba_risk_scanner.assessment.models import (
    AssessedFinding,
    ComplianceStat,
    EntitySeverityRollup,
    HipaaIdentifier,
    HipaaIdentifierStat,
    ExposureBreakdown,
    RecordRiskProfile,
    Regulation,
    ReidSection,
    SensitiveDataReadinessReport,
    SeverityLevel,
)

_H = HipaaIdentifier
# Entity name -> HIPAA Safe Harbor category. Entities absent here are not Safe Harbor
# identifiers: `state` is permitted (only subdivisions *smaller* than state count), and
# clinical values (diagnoses, labs, vitals) are the health data itself, not identifiers.
HIPAA_IDENTIFIER_MAP: Dict[str, HipaaIdentifier] = {
    "person_names": _H.NAMES,
    "physician_names": _H.NAMES,
    "city": _H.GEOGRAPHIC_SUBDIVISION,
    "county": _H.GEOGRAPHIC_SUBDIVISION,
    "zip_code": _H.GEOGRAPHIC_SUBDIVISION,
    "street_address": _H.GEOGRAPHIC_SUBDIVISION,
    "po_box": _H.GEOGRAPHIC_SUBDIVISION,
    "latitude_coordinates": _H.GEOGRAPHIC_SUBDIVISION,
    "longitude_coordinates": _H.GEOGRAPHIC_SUBDIVISION,
    "dates": _H.DATES,
    "date_of_birth": _H.DATES,
    "date_of_death": _H.DATES,
    "timestamps": _H.DATES,
    "relative_date_expressions": _H.DATES,
    "age": _H.DATES,
    "card_expiry_date": _H.DATES,
    "phone_number": _H.TELEPHONE,
    "fax_number": _H.FAX,
    "email_address": _H.EMAIL,
    "ssn": _H.SSN,
    "medical_record_number_mrn": _H.MEDICAL_RECORD_NUMBER,
    "health_plan_beneficiary_number": _H.HEALTH_PLAN_BENEFICIARY_NUMBER,
    "account_reference_number": _H.ACCOUNT_NUMBER,
    "bank_account_number": _H.ACCOUNT_NUMBER,
    "credit_card_number": _H.ACCOUNT_NUMBER,
    "cvv_code": _H.ACCOUNT_NUMBER,
    "iban": _H.ACCOUNT_NUMBER,
    "routing_number_aba": _H.ACCOUNT_NUMBER,
    "swift_bic": _H.ACCOUNT_NUMBER,
    "crypto_wallet_address": _H.ACCOUNT_NUMBER,
    "payment_transaction_id": _H.ACCOUNT_NUMBER,
    "certificate_license_number": _H.CERTIFICATE_LICENSE_NUMBER,
    "drivers_license_number": _H.CERTIFICATE_LICENSE_NUMBER,
    "vehicle_identification_number_vin": _H.VEHICLE_IDENTIFIER,
    "device_serial_number": _H.DEVICE_IDENTIFIER,
    "imei_number": _H.DEVICE_IDENTIFIER,
    "mac_address": _H.DEVICE_IDENTIFIER,
    "web_url": _H.URL,
    "ip_address": _H.IP_ADDRESS,
    "fingerprints": _H.BIOMETRIC_IDENTIFIER,
    "voiceprints": _H.BIOMETRIC_IDENTIFIER,
    "retinal_scans": _H.BIOMETRIC_IDENTIFIER,
    "dna_sequences": _H.BIOMETRIC_IDENTIFIER,
    "genomic_variants": _H.BIOMETRIC_IDENTIFIER,
    "facial_photographs": _H.FULL_FACE_PHOTO,
    "unique_identifier": _H.OTHER_UNIQUE_ID,
    "uuid_guid": _H.OTHER_UNIQUE_ID,
    "provider_npi": _H.OTHER_UNIQUE_ID,
    "provider_tax_id_ein": _H.OTHER_UNIQUE_ID,
    "claim_control_number": _H.OTHER_UNIQUE_ID,
    "authorization_precertification_code": _H.OTHER_UNIQUE_ID,
    "us_ein": _H.OTHER_UNIQUE_ID,
    "us_itin": _H.OTHER_UNIQUE_ID,
    "passport_number": _H.OTHER_UNIQUE_ID,
    "us_passport_number": _H.OTHER_UNIQUE_ID,
    "uk_passport_number": _H.OTHER_UNIQUE_ID,
    "indian_passport_number": _H.OTHER_UNIQUE_ID,
    "german_passport_number": _H.OTHER_UNIQUE_ID,
    "canadian_passport_number": _H.OTHER_UNIQUE_ID,
    "australian_passport_number": _H.OTHER_UNIQUE_ID,
    "indian_aadhaar_number": _H.OTHER_UNIQUE_ID,
    "canadian_social_insurance_number_sin": _H.OTHER_UNIQUE_ID,
    "uk_national_insurance_number_nino": _H.OTHER_UNIQUE_ID,
    "uk_nhs_number": _H.OTHER_UNIQUE_ID,
}

SEVERE_LEVELS = frozenset({SeverityLevel.CRITICAL, SeverityLevel.HIGH})
_LEVEL_ORDER = (
    SeverityLevel.INFO,
    SeverityLevel.LOW,
    SeverityLevel.MEDIUM,
    SeverityLevel.HIGH,
    SeverityLevel.CRITICAL,
)

def _worst(levels: Sequence[SeverityLevel]) -> SeverityLevel:
    return max(levels, key=_LEVEL_ORDER.index) if levels else SeverityLevel.INFO


class ReportBuilder:
    """Summarises scored findings into the readiness report. No scoring happens here."""

    def __init__(
        self,
        *,
        uniqueness_floor: float = 0.5,
        critical_floor: float = 40.0,
    ) -> None:
        self.uniqueness_floor = uniqueness_floor
        self.critical_floor = critical_floor

    def build(
        self,
        findings: Sequence[AssessedFinding],
        record_labels: Sequence[str],
        locations: Sequence[str],
        reid: Optional[ReidSection],
        strong_entities: Dict[str, set],
        min_population: int = 0,
    ) -> SensitiveDataReadinessReport:
        index, breakdown = self._exposure(
            findings, reid, len(set(record_labels)), min_population
        )
        return SensitiveDataReadinessReport(
            findings=list(findings),
            severity_histogram=self._histogram(findings),
            per_entity=self._per_entity(findings),
            per_record=self._per_record(findings, record_labels, strong_entities),
            heatmap=self._heatmap(findings, locations),
            compliance_summary=self._compliance(findings),
            hipaa_checklist=self._hipaa_checklist(findings),
            review_queue=sorted(
                (f for f in findings if f.assessment.needs_review),
                key=lambda f: -f.assessment.risk_score,
            ),
            reidentification=reid,
            exposure_index=index,
            exposure_breakdown=breakdown,
        )

    @staticmethod
    def _histogram(findings: Sequence[AssessedFinding]) -> Dict[SeverityLevel, int]:
        counts = {level: 0 for level in _LEVEL_ORDER}
        for finding in findings:
            counts[finding.assessment.level] += 1
        return counts

    @staticmethod
    def _per_entity(findings: Sequence[AssessedFinding]) -> Dict[str, EntitySeverityRollup]:
        # Keyed on entity *name*: the same concept defined in two ontology files (pii::dates
        # and phi::dates) is one row to a reader, not two with different regulation tags.
        grouped: Dict[str, List[AssessedFinding]] = defaultdict(list)
        for finding in findings:
            grouped[finding.detection.entity].append(finding)
        return {
            entity_id: EntitySeverityRollup(
                count=len(group),
                max_level=_worst([f.assessment.level for f in group]),
                mean_risk_score=sum(f.assessment.risk_score for f in group) / len(group),
                compliance_tags=sorted({t for f in group for t in f.assessment.compliance_tags}),
            )
            for entity_id, group in sorted(grouped.items())
        }

    @staticmethod
    def _per_record(
        findings: Sequence[AssessedFinding],
        record_labels: Sequence[str],
        strong_entities: Dict[str, set],
    ) -> Dict[str, RecordRiskProfile]:
        grouped: Dict[str, List[AssessedFinding]] = defaultdict(list)
        for finding, label in zip(findings, record_labels):
            grouped[label].append(finding)
        return {
            label: RecordRiskProfile(
                finding_count=len(group),
                risk_mass=sum(f.assessment.risk_score for f in group),
                strong_identifier_types=len(strong_entities.get(label, ())),
                worst_level=_worst([f.assessment.level for f in group]),
                is_singleton=any(
                    t.rule_id == "reid:singleton" for f in group for t in f.assessment.rule_trace
                ),
            )
            for label, group in sorted(grouped.items())
        }

    @staticmethod
    def _heatmap(
        findings: Sequence[AssessedFinding], locations: Sequence[str]
    ) -> Dict[str, Dict[SeverityLevel, int]]:
        """Where risk lives: location x severity, cell = finding count. Sparse by design —
        an absent cell is zero, and most (location, severity) pairs are empty."""
        grid: Dict[str, Dict[SeverityLevel, int]] = defaultdict(lambda: defaultdict(int))
        for finding, location in zip(findings, locations):
            grid[location][finding.assessment.level] += 1
        return {location: dict(cells) for location, cells in sorted(grid.items())}

    @staticmethod
    def _compliance(findings: Sequence[AssessedFinding]) -> Dict[Regulation, ComplianceStat]:
        grouped: Dict[Regulation, List[SeverityLevel]] = defaultdict(list)
        for finding in findings:
            for tag in finding.assessment.compliance_tags:
                grouped[tag].append(finding.assessment.level)
        return {
            tag: ComplianceStat(count=len(levels), max_level=_worst(levels))
            for tag, levels in sorted(grouped.items())
        }

    @staticmethod
    def _hipaa_checklist(
        findings: Sequence[AssessedFinding],
    ) -> Dict[HipaaIdentifier, HipaaIdentifierStat]:
        """All 18 categories always present — a zero is the informative part of a checklist."""
        checklist = {identifier: HipaaIdentifierStat() for identifier in HipaaIdentifier}
        for finding in findings:
            identifier = HIPAA_IDENTIFIER_MAP.get(finding.detection.entity)
            if identifier is None:
                continue
            stat = checklist[identifier]
            stat.finding_count += 1
            if finding.detection.entity not in stat.entities:
                stat.entities.append(finding.detection.entity)
        for stat in checklist.values():
            stat.entities.sort()
        return checklist

    def _exposure(
        self,
        findings: Sequence[AssessedFinding],
        reid: Optional[ReidSection],
        record_count: int = 0,
        min_population: int = 0,
    ) -> Tuple[float, ExposureBreakdown]:
        """How much sensitive material is exposed, 0-100. Deliberately not a grade.

        Volume-independent: proportions, not counts, so a 10-row sample and a 10k-row table
        with the same profile read alike. Unmeasured uniqueness is treated as worst case, so
        a missing population can never flatter the number.
        """
        levels = [f.assessment.level for f in findings]
        severity_share = (
            sum(1 for level in levels if level in SEVERE_LEVELS) / len(levels) if levels else 0.0
        )
        uniqueness: Optional[float] = None
        if reid and reid.record_count:
            uniqueness = reid.records_below_k_threshold / reid.record_count

        mode: Literal["severity_only", "severity_x_uniqueness"]
        if uniqueness is None:
            risk, mode = severity_share, "severity_only"
        else:
            risk = severity_share * (
                self.uniqueness_floor + (1.0 - self.uniqueness_floor) * uniqueness
            )
            mode = "severity_x_uniqueness"

        index = max(0.0, min(100.0, 100.0 * risk))
        # One re-identifiable critical record must not average away behind benign findings.
        floored = SeverityLevel.CRITICAL in levels and index < self.critical_floor
        if floored:
            index = self.critical_floor
        return (
            round(index, 1),
            ExposureBreakdown(
                severity_share=round(severity_share, 4),
                uniqueness=None if uniqueness is None else round(uniqueness, 4),
                mode=mode,
                critical_floor_applied=floored,
                record_count=record_count,
                min_population=min_population,
            ),
        )


__all__ = ["ReportBuilder", "HIPAA_IDENTIFIER_MAP"]
