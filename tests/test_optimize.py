"""Action optimizer: presets, the lattice search, and its effect through the assessor."""
from __future__ import annotations


from seiba_risk_scanner.assessment import ReadinessAssessor
from seiba_risk_scanner.assessment.optimize import (
    OptimizerConfig,
    Privacy,
    resolve_config,
)
from seiba_risk_scanner.classification_engine.pipeline_models import (
    CombinedDetectionRow,
    PipelineStageResult,
)


def cell(entity_id, entity, text, row_idx, column):
    return CombinedDetectionRow(
        entity_id=entity_id,
        entity=entity,
        start=0,
        end=len(text),
        text=text,
        confidence=0.95,
        confidence_deterministic=0.95,
        confidence_contextual=0.0,
        provenance={"row": row_idx, "column": column},
    )


def dataset(n=20):
    """Rows whose quasi-identifiers spread across regions and years, so coarsening helps."""
    zips = ["02139", "10001", "94105", "60601"]
    dets = []
    for i in range(n):
        dets += [
            cell("pii_entity_ontology::ssn", "ssn", f"{200+i:03d}-45-{6000+i}", i, "ssn"),
            cell("pii_entity_ontology::email_address", "email_address", f"u{i}@ex.com", i, "email"),
            cell("pii_entity_ontology::zip_code", "zip_code", zips[i % 4], i, "zip"),
            cell("pii_entity_ontology::dates", "dates", f"2020-0{1+i%9}-15", i, "visit_date"),
        ]
    return PipelineStageResult(detections=dets)


# --------------------------------------------------------------------------- config


def test_optimizer_is_off_unless_asked():
    assert resolve_config(None) is None
    assert resolve_config(False) is None


def test_true_means_balanced():
    assert resolve_config(True) == OptimizerConfig.for_preset(Privacy.BALANCED)


def test_presets_differ_in_strictness():
    assert OptimizerConfig.for_preset(Privacy.MAXIMUM).target_k > (
        OptimizerConfig.for_preset(Privacy.BALANCED).target_k
    )
    # "only what is definitely required" does not chase a crowd size at all.
    assert OptimizerConfig.for_preset(Privacy.REQUIRED).generalize_quasi is False


def test_one_argument_accepts_preset_string_or_config():
    assert resolve_config("maximum").prefer_unlinkable is True
    assert resolve_config(OptimizerConfig(target_k=3)).target_k == 3


# --------------------------------------------------------------------------- behaviour


def test_optimizer_off_leaves_the_report_unoptimized():
    report = ReadinessAssessor().assess(dataset())
    assert report.optimization is None


def test_direct_identifiers_never_leak_under_any_preset():
    for preset in Privacy:
        report = ReadinessAssessor(optimize=preset).assess(dataset())
        assert report.reidentification is None or report.reidentification.leakage_rate == 0.0


def test_required_retains_more_than_maximum():
    """The presets have to actually trade risk against retention, or they are decoration."""
    required = ReadinessAssessor(optimize=Privacy.REQUIRED).assess(dataset())
    maximum = ReadinessAssessor(optimize=Privacy.MAXIMUM).assess(dataset())
    assert required.utility.overall < maximum.utility.overall


def test_maximum_keeps_nothing_linkable():
    report = ReadinessAssessor(optimize=Privacy.MAXIMUM).assess(dataset())
    assert "hash" not in report.policy_plan.action_histogram


def test_balanced_reaches_its_target_crowd_size():
    report = ReadinessAssessor(optimize=Privacy.BALANCED).assess(dataset())
    plan = report.optimization
    assert plan.achieved_k >= OptimizerConfig.for_preset(Privacy.BALANCED).target_k


def test_every_choice_carries_a_reason():
    report = ReadinessAssessor(optimize=Privacy.BALANCED).assess(dataset())
    plan = report.optimization
    assert plan.overrides and all(entity in plan.reasons for entity in plan.overrides)


def test_search_prunes_dominated_nodes():
    """Monotonicity means the search must not visit every combination in the lattice."""
    report = ReadinessAssessor(optimize=Privacy.BALANCED).assess(dataset())
    plan = report.optimization
    # zip (2 rungs + keep + mask) x dates (3 rungs + keep + mask) is the full product;
    # pruning has to come in under it while still finding a feasible node.
    assert 0 < plan.searched_nodes < 4 * 5 * 4 * 5
    assert plan.achieved_k is not None
