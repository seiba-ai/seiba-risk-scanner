"""
Merge deterministic and NER spans, then resolve with contextual fusion (last layer).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, replace
from functools import lru_cache
from typing import Dict, List, Literal, Optional, Tuple

# Context-candidate hypotheses start from a moderate prior so a candidate with strong
# contextual evidence can beat a low-confidence deterministic detection.
# Defaults match SeibaScanner rescue_* constructor args.
_DEFAULT_CONTEXT_CANDIDATE_BASE = 0.50
_DEFAULT_RESCUE_MIN_CANDIDATE_CTX = 0.3
_DEFAULT_RESCUE_DET_THRESHOLD = 0.5
_DEFAULT_RESCUE_MARGIN = 0.05

# Contextual score below this counts as "no evidence". The rescue margin compares the two
# entities' contextual scores, which is only meaningful when at least one of them has any:
# with both at zero the comparison always favours the deterministic hit regardless of how
# weak it is, so context would act as a veto rather than a booster.
_CONTEXT_EVIDENCE_EPS = 1e-6

# Back-compat aliases used by internal comments / older call sites.
_CONTEXT_CANDIDATE_BASE = _DEFAULT_CONTEXT_CANDIDATE_BASE
_CONTEXT_CANDIDATE_MIN_CTX = _DEFAULT_RESCUE_MIN_CANDIDATE_CTX
_CONTEXT_CANDIDATE_CTX_THRESHOLD = _DEFAULT_RESCUE_DET_THRESHOLD

from seiba_risk_scanner.classification_engine.contextual.contextual_words import (
    ContextEvidence,
    ContextualWordsScorer,
    fuse_confidence,
    rank_entity_candidates,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors.deterministic_detector import (
    DeterministicDetectionRow,
    DeterministicStageResult,
    _compute_confidence,
    _validator_result_to_bool,
)
from seiba_risk_scanner.classification_engine.deterministic_detectors.validators_config import (
    get_validator_function,
)
from seiba_risk_scanner.classification_engine.ner.backends.base import NerSpanRecord
from seiba_risk_scanner.classification_engine.ontologies.ontology_loader import (
    EntityConfig,
    resolve_entity_alias,
)
from seiba_risk_scanner.classification_engine.pipeline_models import CombinedDetectionRow, ContextCandidate
from seiba_risk_scanner.config import FusionConfig


@dataclass(frozen=True)
class _Hypothesis:
    entity_id: str
    base_confidence: float
    kind: Literal["deterministic", "ner", "context_candidate"]
    ner_label: Optional[str] = None
    # Finer entity this hypothesis was rolled up from via is_a, if any.
    subtype: Optional[str] = None


def _span_matches_any_pattern(span_text: str, patterns: list[str]) -> bool:
    """Return True if span_text contains a match for any of the entity's accepted_patterns."""
    for p in patterns:
        try:
            if re.search(p, span_text):
                return True
        except re.error:
            continue
    return False


def _primary_entity_id(
    det: Optional[DeterministicDetectionRow],
    ner_list: List[NerSpanRecord],
) -> Optional[str]:
    if det is not None:
        return det.entity_id
    if ner_list:
        return ner_list[0].entity_id
    return None


def _primary_ner_base(ner_list: List[NerSpanRecord], primary_id: str) -> float:
    for nr in ner_list:
        if nr.entity_id == primary_id:
            return nr.confidence_ner
    if ner_list:
        return ner_list[0].confidence_ner
    return 0.0


def _build_hypotheses_for_span(
    det: Optional[DeterministicDetectionRow],
    ner_list: List[NerSpanRecord],
    *,
    text: str,
    start: int,
    end: int,
    configs: Dict[str, EntityConfig],
    scorer: ContextualWordsScorer,
    context_window_before: int,
    context_window_after: int,
    extra_before_text: Optional[str],
    extra_after_text: Optional[str],
    rescue_min_candidate_ctx: float = _DEFAULT_RESCUE_MIN_CANDIDATE_CTX,
    decisive_key_entity_id: Optional[str] = None,
    decisive_key_candidate_base: float = _CONTEXT_CANDIDATE_BASE,
) -> List[_Hypothesis]:
    hyps: List[_Hypothesis] = []
    seen_ids: set[str] = set()

    if det is not None:
        # Two detectors naming the same entity must not score below either one alone. The
        # deterministic hypothesis is registered first, so without this a deliberately
        # low-weight regex (a bare-digit or prefixed-ID fallback) would shadow a confident
        # NER hit for that same entity and drag the span under the confidence floor.
        base_confidence = max(
            [det.confidence]
            + [nr.confidence_ner for nr in ner_list if nr.entity_id == det.entity_id]
        )
        # Subtype from whichever aliased detector at this span carries one.
        det_subtype = det.detected_subtype or next(
            (nr.detected_subtype for nr in ner_list if nr.entity_id == det.entity_id and nr.detected_subtype),
            None,
        )
        hyps.append(
            _Hypothesis(
                entity_id=det.entity_id,
                base_confidence=base_confidence,
                kind="deterministic",
                subtype=det_subtype,
            )
        )
        seen_ids.add(det.entity_id)

    for nr in ner_list:
        if nr.entity_id in seen_ids:
            continue
        seen_ids.add(nr.entity_id)
        hyps.append(
            _Hypothesis(
                entity_id=nr.entity_id,
                base_confidence=nr.confidence_ner,
                kind="ner",
                ner_label=nr.label,
                subtype=nr.detected_subtype,
            )
        )

    primary_id = _primary_entity_id(det, ner_list)
    if primary_id is not None:
        ranked = rank_entity_candidates(
            text=text,
            start=start,
            end=end,
            context_window_before=context_window_before,
            context_window_after=context_window_after,
            configs=configs,
            scorer=scorer,
            detected_entity_id=primary_id,
            top_k=3,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
        )
        span_text = text[start:end]
        for cand_id, _cand_ev in ranked:
            # The subtype's phrases ("Dr.", "MD") still nominate the candidate; it is only
            # reported as the entity it is a kind of. When the parent is already a
            # hypothesis here, the candidate is that same claim and collapses into it.
            canonical_id = resolve_entity_alias(cand_id, configs)
            if canonical_id in seen_ids:
                continue
            if _cand_ev.score < rescue_min_candidate_ctx:
                continue
            cand_cfg = configs.get(cand_id)
            # Context alone can nominate a pattern-less entity, so negative patterns are
            # the only shape guard it has (section headings and ticket ids sitting near
            # "company"/"employer" phrases become organizations). Check the entity this
            # will be *reported* as too — the patterns live on the is_a parent, while
            # cand_id is the nominating subtype.
            if any(
                cfg is not None
                and cfg.prohibited_patterns
                and any(_matches_prohibited(p, span_text) for p in cfg.prohibited_patterns)
                for cfg in (cand_cfg, configs.get(canonical_id))
            ):
                continue
            if cand_cfg is not None and cand_cfg.accepted_patterns:
                if not _span_matches_any_pattern(span_text, cand_cfg.accepted_patterns):
                    continue
            # A validator is a shape guard even without patterns: date_of_birth is
            # pattern-less but VALIDATE_DATE keeps context from stamping "SSN" (a spaCy
            # ORG landing nearby "date"/"birth" words) as a birth date.
            if cand_cfg is not None and not _validator_passes(cand_cfg, span_text):
                continue
            # Cross-ontology rescue: when a candidate has patterns, the span must match
            # at least one. Pattern-less entities rely on context alone.
            if _is_cross_ontology_rescue(primary_id, cand_id):
                cand_cfg = cand_cfg or configs.get(cand_id)
                if cand_cfg is not None and cand_cfg.accepted_patterns:
                    if not _span_matches_any_pattern(span_text, cand_cfg.accepted_patterns):
                        continue
            seen_ids.add(canonical_id)
            # The column key decisively names this entity: enter high enough to outrank a
            # confident NER span on the same cell, so the span is relabelled rather than
            # dropped (boost-only fusion caps the ordinary base too low to ever win).
            base = (
                decisive_key_candidate_base
                if canonical_id == decisive_key_entity_id
                else _CONTEXT_CANDIDATE_BASE
            )
            hyps.append(
                _Hypothesis(
                    entity_id=canonical_id,
                    base_confidence=base,
                    kind="context_candidate",
                    subtype=cand_id if canonical_id != cand_id else None,
                )
            )

    return hyps


def _drop_prohibited_ner_spans(
    ner_spans: List[NerSpanRecord], configs: Dict[str, EntityConfig]
) -> List[NerSpanRecord]:
    """Apply each entity's ``prohibited_patterns`` to NER spans, not just regex hits.

    Without this the ontology's negative patterns silently constrain only the
    deterministic loop, so a pattern-less entity (organization, person_names) has no
    declarative way to reject a shape NER keeps mislabelling — section headers and
    ticket ids read as companies.
    """
    kept: List[NerSpanRecord] = []
    for span in ner_spans:
        cfg = configs.get(span.entity_id)
        patterns = cfg.prohibited_patterns if cfg is not None else None
        if patterns and any(_matches_prohibited(p, span.text) for p in patterns):
            continue
        kept.append(span)
    return kept


@lru_cache(maxsize=256)
def _compiled_prohibited(pattern: str) -> Optional[re.Pattern[str]]:
    try:
        return re.compile(pattern)
    except re.error:
        return None


def _matches_prohibited(pattern: str, text: str) -> bool:
    compiled = _compiled_prohibited(pattern)
    return compiled is not None and compiled.search(text) is not None


def _validator_passes(cfg: EntityConfig, span_text: str) -> bool:
    """Run the entity's validator on the span; entities without one always pass."""
    if cfg.validator_enum is None:
        return True
    try:
        return _validator_result_to_bool(get_validator_function(cfg.validator_enum)(span_text))
    except Exception:  # noqa: BLE001
        return False


def _rescore_deterministic(
    det: DeterministicDetectionRow,
    *,
    text: str,
    start: int,
    end: int,
    configs: Dict[str, EntityConfig],
    scorer: ContextualWordsScorer,
    context_window_before: int,
    context_window_after: int,
    extra_before_text: Optional[str],
    extra_after_text: Optional[str],
    fusion_weight_deterministic: float,
    fusion_weight_contextual: float,
) -> Optional[Tuple[EntityConfig, ContextEvidence, float]]:
    """Re-score the deterministic hit a denied rescue falls back to. None when unusable."""
    det_cfg = configs.get(det.entity_id)
    if det_cfg is None:
        return None
    det_ev = scorer.score_span_with_evidence(
        text,
        start,
        end,
        det_cfg,
        context_window_before,
        context_window_after,
        extra_before_text=extra_before_text,
        extra_after_text=extra_after_text,
    )
    reverted_fused = fuse_confidence(
        det.confidence,
        det_ev.score,
        weight_deterministic=fusion_weight_deterministic,
        weight_contextual=fusion_weight_contextual,
    )
    return det_cfg, det_ev, reverted_fused


def _find_context_override(
    text: str,
    start: int,
    end: int,
    span_text: str,
    override_configs: List[Tuple[str, EntityConfig]],
    scorer: ContextualWordsScorer,
    fusion: FusionConfig,
) -> Optional[Tuple[str, EntityConfig, ContextEvidence, float]]:
    """
    Highest-scoring ``context_rescue_override`` entity that matches this span by
    regex, passes its validator, and clears the contextual bar. Lets a precise but
    low-base identifier (e.g. NHS number) take a span away from a greedier overlap
    (phone/fax) purely on strong adjacent context — no per-label prefix hacks.
    """
    best: Optional[Tuple[str, EntityConfig, ContextEvidence, float]] = None
    for eid, cfg in override_configs:
        if cfg.accepted_patterns and not _span_matches_any_pattern(span_text, cfg.accepted_patterns):
            continue
        if not _validator_passes(cfg, span_text):
            continue
        ev = scorer.score_span_with_evidence(
            text, start, end, cfg,
            fusion.context_window_before, fusion.context_window_after,
            extra_before_text=fusion.extra_before_text,
            extra_after_text=fusion.extra_after_text,
        )
        # Require a real phrase hit, not just an ambient score: an override reclaims a span
        # only on actual proximity evidence (a "DOB"/"deceased" word for date_of_birth/death,
        # "NHS" for the NHS number). Without this a date next to an unrelated name could be
        # grabbed as a birth date on score alone.
        if ev.score < fusion.rescue_det_threshold or not ev.matched_phrases:
            continue
        conf = _compute_confidence(cfg, has_validator=cfg.validator_enum is not None, validator_passed=True)
        fused = fuse_confidence(
            conf, ev.score,
            weight_deterministic=fusion.fusion_weight_deterministic,
            weight_contextual=fusion.fusion_weight_contextual,
        )
        if best is None or fused > best[3]:
            best = (eid, cfg, ev, fused)
    return best


def _max_ner_confidence_at_span(ner_list: List[NerSpanRecord]) -> Optional[float]:
    if not ner_list:
        return None
    return max(nr.confidence_ner for nr in ner_list)


def _ontology_prefix(entity_id: str) -> str:
    """Return the ontology stem, e.g. 'fin_entity_ontology' from 'fin_entity_ontology::cvv_code'."""
    return entity_id.split("::")[0] if "::" in entity_id else ""


def _is_cross_ontology_rescue(original_id: Optional[str], candidate_id: str) -> bool:
    """Return True when a rescue would move a span from one ontology family to another."""
    if original_id is None:
        return False
    return _ontology_prefix(original_id) != _ontology_prefix(candidate_id)


# ---------------------------------------------------------------------------
# Span-level entity precedence
# ---------------------------------------------------------------------------
# Lower number = higher priority.  When two spans from DIFFERENT entities
# overlap (even partially) the span with the lower priority number is dropped.
# Entities at the same tier keep both spans — confidence already resolves ties
# for the same entity via _deduplicate_overlapping_same_entity.
#
# Design rationale:
#   Tier 1 — exact-format entities with validators: always win over everything.
#   Tier 2 — regex-based structured identifiers + validated dates.
#   Tier 3 — mixed regex + NER (addresses, clinical IDs).
#   Tier 4 — pure-NER entities (person_names, city): lose on any overlap with
#             a structured entity, eliminating the majority of NER over-tagging.
# ---------------------------------------------------------------------------
_ENTITY_PRIORITY: Dict[str, int] = {
    # Tier 1
    "pii_entity_ontology::email_address": 1,
    "pii_entity_ontology::ssn": 1,
    "pii_entity_ontology::ip_address": 1,
    "pii_entity_ontology::us_itin": 1,
    "pii_entity_ontology::canadian_social_insurance_number_sin": 1,
    "pii_entity_ontology::indian_aadhaar_number": 1,
    "pii_entity_ontology::imei_number": 1,
    "pii_entity_ontology::uuid_guid": 1,
    "pii_entity_ontology::mac_address": 1,
    "fin_entity_ontology::crypto_wallet_address": 1,
    # Tier 2
    "pii_entity_ontology::phone_number": 2,
    "pii_entity_ontology::fax_number": 2,
    "pii_entity_ontology::uk_nhs_number": 2,
    "pii_entity_ontology::zip_code": 2,
    "pii_entity_ontology::dates": 2,
    "pii_entity_ontology::age": 2,
    "phi_entity_ontology::dates": 2,
    "fin_entity_ontology::credit_card_number": 2,
    "fin_entity_ontology::cvv_code": 2,
    "fin_entity_ontology::card_expiry_date": 2,
    "fin_entity_ontology::bank_account_number": 2,
    "fin_entity_ontology::routing_number_aba": 2,
    "fin_entity_ontology::iban": 2,
    "fin_entity_ontology::payment_transaction_id": 2,
    "pii_entity_ontology::unique_identifier": 2,
    "phi_entity_ontology::medical_record_number_mrn": 2,
    "phi_entity_ontology::relative_date_expressions": 2,
    "pii_entity_ontology::relative_date_expressions": 2,
    # Tier 3
    "pii_entity_ontology::street_address": 3,
    "phi_entity_ontology::genomic_variants": 3,
    "phi_entity_ontology::vital_signs": 3,
    "phi_entity_ontology::medication_dosage": 3,
    "phi_entity_ontology::medical_condition": 3,
    "phi_entity_ontology::medication_name": 3,
    "phi_entity_ontology::icd10_diagnosis_codes": 3,
    "phi_entity_ontology::claim_control_number": 3,
    "phi_entity_ontology::health_plan_beneficiary_number": 3,
    # Tier 4 — pure NER; suppressed whenever a structured entity overlaps
    "pii_entity_ontology::person_names": 4,
    "phi_entity_ontology::physician_names": 4,
    "pii_entity_ontology::city": 4,
    # Pattern-less like its neighbours here: at the default tier 3 an ORG span read off a
    # person's name silently suppressed the person. Same tier keeps both and lets
    # confidence decide.
    "pii_entity_ontology::organization": 4,
}
_DEFAULT_ENTITY_PRIORITY = 3  # unlisted entities sit at tier 3


def _suppress_lower_priority_overlapping_spans(
    rows: List[CombinedDetectionRow],
) -> List[CombinedDetectionRow]:
    """
    Drop spans whose entity has a lower priority (higher tier number) when a
    higher-priority entity span overlaps them.

    Only applies when the two spans belong to DIFFERENT entities.  Same-entity
    deduplication is handled by ``_deduplicate_overlapping_same_entity``.

    Key effect: NER-only entities (person_names, city — tier 4) are suppressed
    whenever a regex/validator-based entity (tiers 1-3) occupies any overlapping
    character range, removing the majority of dates↔person_names confusion.
    """
    if len(rows) <= 1:
        return rows

    remove_ids: set = set()

    for i, row_a in enumerate(rows):
        if id(row_a) in remove_ids:
            continue
        prio_a = _ENTITY_PRIORITY.get(row_a.entity_id, _DEFAULT_ENTITY_PRIORITY)

        for row_b in rows[i + 1 :]:
            if id(row_b) in remove_ids:
                continue
            if row_a.entity_id == row_b.entity_id:
                continue

            # Check for any character-level overlap
            overlap_start = max(row_a.start, row_b.start)
            overlap_end = min(row_a.end, row_b.end)
            if overlap_start >= overlap_end:
                continue  # no overlap

            prio_b = _ENTITY_PRIORITY.get(row_b.entity_id, _DEFAULT_ENTITY_PRIORITY)

            if prio_a < prio_b:
                remove_ids.add(id(row_b))
            elif prio_b < prio_a:
                remove_ids.add(id(row_a))
                break  # row_a is already marked; stop checking its partners
            # Equal priority → keep both; confidence handles it if they're the same entity

    return [r for r in rows if id(r) not in remove_ids]


def _suppress_strictly_contained_spans(rows: List[CombinedDetectionRow]) -> List[CombinedDetectionRow]:
    """
    Drop a span that is strictly contained within a DIFFERENT entity's span when the outer
    span has equal or higher confidence. Prevents short-pattern entities (cvv_code,
    card_expiry_date) from being emitted as sub-spans of credit_card_number, dates, etc.
    """
    if len(rows) <= 1:
        return rows

    remove_ids: set = set()
    for candidate in rows:
        if id(candidate) in remove_ids:
            continue
        for container in rows:
            if id(container) == id(candidate):
                continue
            if container.entity_id == candidate.entity_id:
                continue
            if (
                container.start <= candidate.start
                and candidate.end <= container.end
                and container.confidence >= candidate.confidence
            ):
                remove_ids.add(id(candidate))
                break

    return [r for r in rows if id(r) not in remove_ids]


def _deduplicate_overlapping_same_entity(rows: List[CombinedDetectionRow]) -> List[CombinedDetectionRow]:
    """
    Remove shorter sibling spans when a longer span with the same entity_id overlaps them.
    Handles det+NER duplicate pairs for the same underlying match.
    """
    if len(rows) <= 1:
        return rows

    by_entity: Dict[str, List[CombinedDetectionRow]] = defaultdict(list)
    for row in rows:
        by_entity[row.entity_id].append(row)

    remove_ids: set = set()
    for entity_rows in by_entity.values():
        if len(entity_rows) <= 1:
            continue
        sorted_rows = sorted(entity_rows, key=lambda r: (-(r.end - r.start), -r.confidence))
        for i, longer in enumerate(sorted_rows):
            for shorter in sorted_rows[i + 1 :]:
                if id(shorter) in remove_ids:
                    continue
                overlap_start = max(longer.start, shorter.start)
                overlap_end = min(longer.end, shorter.end)
                if overlap_start < overlap_end:
                    remove_ids.add(id(shorter))

    return [r for r in rows if id(r) not in remove_ids]


def _apply_entity_aliases(
    det_stage: DeterministicStageResult,
    ner_spans: List[NerSpanRecord],
    configs: Dict[str, EntityConfig],
) -> Tuple[DeterministicStageResult, List[NerSpanRecord]]:
    """Rewrite subtype detections to the entity they are a kind of, before anything competes.

    Applied at the front so that a subtype hit and a supertype hit for the same span are
    recognised as the same claim (they reinforce via the shared entity_id) rather than
    fighting each other as rival hypotheses.
    """

    def alias(entity_id: str) -> Optional[EntityConfig]:
        canonical = resolve_entity_alias(entity_id, configs)
        return configs.get(canonical) if canonical != entity_id else None

    det_rows = []
    for row in det_stage.detections:
        cfg = alias(row.entity_id)
        det_rows.append(
            row.model_copy(
                update={
                    "entity_id": cfg.entity_id,
                    "entity": cfg.name,
                    "ontology": cfg.ontology,
                    "detected_subtype": row.entity_id,
                }
            )
            if cfg is not None
            else row
        )

    aliased_ner = []
    for span in ner_spans:
        cfg = alias(span.entity_id)
        aliased_ner.append(
            replace(span, entity_id=cfg.entity_id, ontology=cfg.ontology, detected_subtype=span.entity_id)
            if cfg is not None
            else span
        )

    return det_stage.model_copy(update={"detections": det_rows}), aliased_ner


def resolve_deterministic_and_ner_to_combined(
    text: str,
    det_stage: DeterministicStageResult,
    ner_spans: List[NerSpanRecord],
    configs: Dict[str, EntityConfig],
    scorer: ContextualWordsScorer,
    fusion: FusionConfig,
) -> List[CombinedDetectionRow]:
    """
    For each exact (start, end) present in deterministic or NER results, form competing
    hypotheses, run contextual scoring per hypothesis, fuse, and keep the best fused score.
    """
    det_stage, ner_spans = _apply_entity_aliases(det_stage, ner_spans, configs)
    ner_spans = _drop_prohibited_ner_spans(ner_spans, configs)
    min_fused_confidence = fusion.min_fused_confidence
    fusion_weight_deterministic = fusion.fusion_weight_deterministic
    fusion_weight_contextual = fusion.fusion_weight_contextual
    context_window_before = fusion.context_window_before
    context_window_after = fusion.context_window_after
    extra_before_text = fusion.extra_before_text
    extra_after_text = fusion.extra_after_text
    provenance_if_no_det = fusion.provenance_if_no_det
    rescue_det_threshold = fusion.rescue_det_threshold
    rescue_margin = fusion.rescue_margin
    rescue_min_candidate_ctx = fusion.rescue_min_candidate_ctx

    det_by_span: Dict[Tuple[int, int], DeterministicDetectionRow] = {}
    for d in det_stage.detections:
        det_by_span[(d.start, d.end)] = d

    ner_by_span: Dict[Tuple[int, int], List[NerSpanRecord]] = {}
    for nr in ner_spans:
        key = (nr.start, nr.end)
        ner_by_span.setdefault(key, []).append(nr)

    all_spans = set(det_by_span.keys()) | set(ner_by_span.keys())
    combined: List[CombinedDetectionRow] = []
    override_configs = [(eid, cfg) for eid, cfg in configs.items() if cfg.context_rescue_override]

    for span in sorted(all_spans):
        start, end = span
        det = det_by_span.get(span)
        ner_list = ner_by_span.get(span, [])
        span_text = text[start:end]

        if override_configs:
            override = _find_context_override(text, start, end, span_text, override_configs, scorer, fusion)
            if override is not None:
                ov_eid, ov_cfg, ov_ev, ov_fused = override
                if ov_fused >= min_fused_confidence and (det is None or det.entity_id != ov_eid):
                    combined.append(
                        CombinedDetectionRow(
                            winner_kind="context_candidate",
                            entity_id=ov_eid,
                            entity=ov_cfg.name,
                            start=start,
                            end=end,
                            text=span_text,
                            confidence=ov_fused,
                            confidence_deterministic=det.confidence if det is not None else 0.0,
                            confidence_contextual=ov_ev.score,
                            confidence_ner=None,
                            contextual_matches=ov_ev.matched_phrases,
                            contextual_matches_before=ov_ev.matched_in_before,
                            contextual_matches_after=ov_ev.matched_in_after,
                            rescue_applied=det is not None,
                            original_entity_id=det.entity_id if det is not None else None,
                            original_entity=det.entity if det is not None else None,
                            original_ontology=det.ontology if det is not None else None,
                            ontology=ov_cfg.ontology,
                            provenance=det.provenance if det is not None else provenance_if_no_det,
                        )
                    )
                    continue

        hyps = _build_hypotheses_for_span(
            det,
            ner_list,
            text=text,
            start=start,
            end=end,
            configs=configs,
            scorer=scorer,
            context_window_before=context_window_before,
            context_window_after=context_window_after,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
            rescue_min_candidate_ctx=rescue_min_candidate_ctx,
            decisive_key_entity_id=fusion.decisive_key_entity_id,
            decisive_key_candidate_base=fusion.decisive_key_candidate_base,
        )
        if not hyps:
            continue

        best_fused = -1.0
        best_h: Optional[_Hypothesis] = None
        best_ev: Optional[ContextEvidence] = None
        best_cfg: Optional[EntityConfig] = None
        primary_ctx: Optional[float] = None

        for h in hyps:
            cfg = configs.get(h.entity_id)
            if cfg is None:
                continue
            ev = scorer.score_span_with_evidence(
                text,
                start,
                end,
                cfg,
                context_window_before,
                context_window_after,
                extra_before_text=extra_before_text,
                extra_after_text=extra_after_text,
            )
            fused = fuse_confidence(
                h.base_confidence,
                ev.score,
                weight_deterministic=fusion_weight_deterministic,
                weight_contextual=fusion_weight_contextual,
            )
            # Context candidates only get a boost when context clears rescue_det_threshold.
            if h.kind == "context_candidate" and ev.score < rescue_det_threshold:
                fused = h.base_confidence
            if det is not None and h.entity_id == det.entity_id:
                primary_ctx = ev.score
            if fused > best_fused:
                best_fused = fused
                best_h = h
                best_ev = ev
                best_cfg = cfg

        if best_h is None or best_cfg is None or best_ev is None:
            continue

        if best_fused < min_fused_confidence:
            continue

        rescue_applied = bool(det is not None and best_h.entity_id != det.entity_id)

        # Rescue gates: only relabel when deterministic confidence is weak enough,
        # and the candidate's contextual score beats the primary by rescue_margin.
        if rescue_applied and det is not None:
            det_cfg0 = configs.get(det.entity_id)
            # Validator-lock: a checksum-verified deterministic hit is proof, not a
            # guess — NER may never relabel it (context-override path is handled above).
            if (
                det_cfg0 is not None
                and det_cfg0.validator_enum is not None
                and _validator_passes(det_cfg0, span_text)
            ):
                rescue_applied = False
            elif det.confidence >= rescue_det_threshold:
                rescue_applied = False
            elif (
                primary_ctx is not None
                and (primary_ctx > _CONTEXT_EVIDENCE_EPS or best_ev.score > _CONTEXT_EVIDENCE_EPS)
                and best_ev.score < primary_ctx + rescue_margin
            ):
                # Only decided on context when a side actually has some; otherwise the
                # hypothesis competition already picked the more confident entity.
                rescue_applied = False
            if not rescue_applied:
                reverted = _rescore_deterministic(
                    det,
                    text=text,
                    start=start,
                    end=end,
                    configs=configs,
                    scorer=scorer,
                    context_window_before=context_window_before,
                    context_window_after=context_window_after,
                    extra_before_text=extra_before_text,
                    extra_after_text=extra_after_text,
                    fusion_weight_deterministic=fusion_weight_deterministic,
                    fusion_weight_contextual=fusion_weight_contextual,
                )
                if reverted is None:
                    continue
                det_cfg, det_ev, reverted_fused = reverted
                if reverted_fused >= min_fused_confidence:
                    best_h = _Hypothesis(
                        entity_id=det.entity_id,
                        base_confidence=det.confidence,
                        kind="deterministic",
                        subtype=det.detected_subtype,
                    )
                    best_cfg = det_cfg
                    best_ev = det_ev
                    best_fused = reverted_fused
                else:
                    # The hit we reverted to is too weak to emit on its own. Dropping the
                    # span would discard the challenger too, which already cleared the
                    # floor — keep it rather than losing the detection entirely.
                    rescue_applied = True

        # Guard: a span with no digits should not be rescued — it is almost certainly a
        # prefix-only pattern match landing on the wrong entity.
        if rescue_applied and det is not None and not any(c.isdigit() for c in span_text):
            rescue_applied = False
            reverted = _rescore_deterministic(
                det,
                text=text,
                start=start,
                end=end,
                configs=configs,
                scorer=scorer,
                context_window_before=context_window_before,
                context_window_after=context_window_after,
                extra_before_text=extra_before_text,
                extra_after_text=extra_after_text,
                fusion_weight_deterministic=fusion_weight_deterministic,
                fusion_weight_contextual=fusion_weight_contextual,
            )
            if reverted is None:
                continue
            det_cfg, det_ev, reverted_fused = reverted
            if reverted_fused >= min_fused_confidence:
                best_h = _Hypothesis(
                    entity_id=det.entity_id,
                    base_confidence=det.confidence,
                    kind="deterministic",
                    subtype=det.detected_subtype,
                )
                best_cfg = det_cfg
                best_ev = det_ev
                best_fused = reverted_fused
            else:
                rescue_applied = True

        ranked_out = rank_entity_candidates(
            text=text,
            start=start,
            end=end,
            context_window_before=context_window_before,
            context_window_after=context_window_after,
            configs=configs,
            scorer=scorer,
            detected_entity_id=best_h.entity_id,
            top_k=3,
            extra_before_text=extra_before_text,
            extra_after_text=extra_after_text,
        )
        candidates: Optional[List[ContextCandidate]] = None
        if ranked_out:
            candidates = []
            for cand_entity_id, cand_ev in ranked_out:
                cand_cfg = configs.get(cand_entity_id)
                cand_entity_name = cand_cfg.name if cand_cfg is not None else cand_entity_id
                candidates.append(
                    ContextCandidate(
                        entity_id=cand_entity_id,
                        entity=cand_entity_name,
                        confidence_contextual=cand_ev.score,
                        matched_phrases=cand_ev.matched_phrases,
                        matched_in_before=cand_ev.matched_in_before,
                        matched_in_after=cand_ev.matched_in_after,
                    )
                )

        orig_id = det.entity_id if rescue_applied and det is not None else None
        orig_ent = det.entity if rescue_applied and det is not None else None
        orig_ont = det.ontology if rescue_applied and det is not None else None

        conf_det = det.confidence if det is not None else 0.0
        conf_ner_out: Optional[float] = None
        if best_h.kind == "ner":
            conf_ner_out = best_h.base_confidence
        elif ner_list:
            conf_ner_out = _max_ner_confidence_at_span(ner_list)

        combined.append(
            CombinedDetectionRow(
                winner_kind=best_h.kind,
                entity_id=best_h.entity_id,
                entity=best_cfg.name,
                start=start,
                end=end,
                text=span_text,
                confidence=best_fused,
                confidence_deterministic=conf_det,
                confidence_contextual=best_ev.score,
                confidence_ner=conf_ner_out,
                contextual_matches=best_ev.matched_phrases,
                contextual_matches_before=best_ev.matched_in_before,
                contextual_matches_after=best_ev.matched_in_after,
                candidates=candidates,
                rescue_applied=rescue_applied,
                original_entity_id=orig_id,
                original_entity=orig_ent,
                original_ontology=orig_ont,
                ontology=best_cfg.ontology,
                ner_label=best_h.ner_label if best_h.kind == "ner" else None,
                detected_subtype=best_h.subtype,
                provenance=det.provenance if det is not None else provenance_if_no_det,
            )
        )

    combined.sort(key=lambda r: (r.start, -r.confidence))
    combined = _suppress_strictly_contained_spans(combined)
    combined = _deduplicate_overlapping_same_entity(combined)
    combined = _suppress_lower_priority_overlapping_spans(combined)
    return combined
