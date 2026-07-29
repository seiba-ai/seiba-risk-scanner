# Configuration

Seiba’s bundled entity definitions are YAML configuration, not hard-coded Python rules. The three bundled ontology files cover PII, PHI, and financial data; see the [entity taxonomy](entities.md) for their current contents.

## Scanner configuration

```python
from seiba_risk_scanner import SeibaScanner

scanner = SeibaScanner(
    min_confidence=0.3,
    ner_backend="openmed",  # or "spacy"
    enable_gazetteer=True,
)
```

You can supply a custom NER runner or a Hugging Face token-classification model through `make_custom_ner_runner()` and `make_hf_ner_runner()`. Unmapped model labels are dropped, so supply a label-to-entity mapping for custom models.

## Custom ontologies

Point the scanner to your own ontology files:

```python
scanner = SeibaScanner(ontology_paths=["my_pii.yaml", "my_phi.yaml"])
```

An entity definition controls detection patterns, validators, contextual phrases, its `data_class`, optional policy label, and default action. A compact example:

```yaml
entities:
  date_of_birth:
    regex_patterns:
      accepted_patterns: ["..."]
      confidence_weight: 0.75
    contextual_phrases:
      values: ["dob", "date of birth", "born on"]
      confidence_weight: 0.85
    classification:
      category: PHI
      data_class: quasi_identifier
    de_identifier: DATE_OF_BIRTH
    default_action: generalize:year
```

Invalid ontology configuration fails during loading rather than being silently ignored.

## Policies and actions

`ReadinessAssessor` resolves an action for each finding, then can execute it. Override a specific entity for one run:

```python
from seiba_risk_scanner.assessment import ReadinessAssessor

assessor = ReadinessAssessor(
    action_overrides={"age": "generalize:10_year_band"},
    execute_policy=True,
)
```

Actions are `keep`, `mask`, `redact`, `hash`, `replace`, `format_preserve`, and `generalize[:level]`. Generalization is available only for values with a defensible coarsening ladder:

| Value type | Levels |
|---|---|
| Dates | `month`, `year`, `decade` |
| Ages | `5_year_band`, `10_year_band`, `20_year_band` |
| ZIP codes | `3_digit`, `1_digit` |
| Coordinates | `1_decimal`, `integer` |

## Optimizer

The optimizer selects actions rather than requiring you to set one action per entity. It aims to meet a chosen privacy target with the least loss of analytical usefulness.

```python
from seiba_risk_scanner.assessment import ReadinessAssessor
from seiba_risk_scanner.assessment.optimize import Privacy

assessor = ReadinessAssessor(optimize=Privacy.BALANCED)
```

`Privacy.MAXIMUM`, `Privacy.BALANCED`, and `Privacy.REQUIRED` represent different privacy targets. Inspect `report.optimization` to see the chosen overrides and their reasons.
