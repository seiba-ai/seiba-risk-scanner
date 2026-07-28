"""OpenMed-backed policy shim: resolve (and optionally execute) de-id actions."""

from seiba_risk_scanner.policy.bridge import (
    DATA_CLASS_TO_POLICY_CLASS,
    canonical_label_for,
    seiba_mask_token,
    openmed_policy_class_for,
)
from seiba_risk_scanner.policy.executor import (
    apply_action_to_text,
    execute_plan,
    scrub_text,
)
from seiba_risk_scanner.policy.generalize import (
    DEFAULT_LEVELS,
    LADDERS,
    generalize,
    kind_for_label,
)
from seiba_risk_scanner.policy.models import (
    ActionRecord,
    PolicyPlanSection,
)

# Resolver imports assessment types; keep it lazy so assessment.models can import
# policy.models without a cycle through this package __init__.
def __getattr__(name: str):
    if name == "PolicyResolver":
        from seiba_risk_scanner.policy.resolver import PolicyResolver

        return PolicyResolver
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ActionRecord",
    "DATA_CLASS_TO_POLICY_CLASS",
    "DEFAULT_LEVELS",
    "LADDERS",
    "PolicyPlanSection",
    "PolicyResolver",
    "apply_action_to_text",
    "canonical_label_for",
    "seiba_mask_token",
    "execute_plan",
    "generalize",
    "kind_for_label",
    "openmed_policy_class_for",
    "scrub_text",
]
