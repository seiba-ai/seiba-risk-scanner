# Contributing to Seiba Risk Scanner

Thanks for helping improve Seiba. This project detects and scores candidate
sensitive data — please treat fixtures, bug reports, and PRs accordingly.

By contributing, you agree that your contributions are licensed under the
[Apache License 2.0](LICENSE) (see also [NOTICE](NOTICE)).

Please read the [Code of Conduct](CODE_OF_CONDUCT.md).

## Never commit real PII or PHI

- Reproduce bugs with realistic **fake** values (`555` phone numbers,
  `example.com` emails, invented MRNs).
- Do not paste production logs, screenshots, or exports that contain real
  identifiers into issues or PRs.
- Security problems go through
  [private vulnerability reporting](https://github.com/seiba-ai/seiba-risk-scanner/security/advisories/new)
  — see [SECURITY.md](SECURITY.md).

## Development setup

Requires Python 3.12+.

```bash
git clone https://github.com/seiba-ai/seiba-risk-scanner.git
cd seiba-risk-scanner
pip install -e ".[dev]"
```

Optional extras: `.[ner-spacy]`, `.[ner-hf]`, `.[llm]` — see [Readme.md](Readme.md).

## Checks before you open a PR

```bash
ruff check --select E9,F .
pytest -m "not slow" -q
```

If your change touches detection, scoring, policy, or the gazetteer, also run
the eval gates (slow):

```bash
pytest -m slow -q
# or regenerating predictions:
python3 -m eval.runner --ner-backend openmed
```

Use the PR template checklist. If quality numbers move, explain why and only
re-cut a baseline when the new trade-off is intentional.

## What makes a good contribution

- **Bug fixes** with a minimal fake-data reproduction and a test when practical.
- **Entity / ontology coverage** via the entity-coverage issue template, or a
  focused YAML + test change.
- **Docs** that match the public API (`SeibaScanner`, assessment entry points).
- Prefer small, reviewable PRs over large mixed refactors.

## Vocabulary / gazetteer note

Raw MONDO / RxNorm / CHV dumps are **not** committed (see `.gitignore` and
[NOTICE](NOTICE)). The curated runtime artifact under
`med_ontology_sources/cleaned/` is what the package ships. Rebuild locally with
the gazetteer builder only if you have the upstream sources and the rights to
use them.

## Questions

Open a Discussion or an issue on
[seiba-ai/seiba-risk-scanner](https://github.com/seiba-ai/seiba-risk-scanner).
For security, use private reporting — not a public issue.
