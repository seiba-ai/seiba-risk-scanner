# Security Policy

Seiba handles personal and health data, so a defect here can expose exactly the information the
tool exists to protect. Please report problems privately.

## Reporting a vulnerability

**Use GitHub's private reporting: [Report a vulnerability](https://github.com/seiba-ai/seiba-risk-scanner/security/advisories/new).**
It is visible only to maintainers until a fix ships.

Do not open a public issue, pull request, or discussion for a security problem.

**Never include real personal or health data in a report.** Reproduce the issue with realistic
fake values instead. If it genuinely only reproduces with real data, say so and describe the
*shape* of the input — we will arrange a private channel rather than have you paste it anywhere.

Please include:

- what happens, and what should happen instead
- a minimal reproduction using fake data
- the version (`pip show seiba-risk-scanner`) and Python version
- the NER backend in use, and any non-default configuration

**Response targets:** acknowledgement within 3 business days, an initial assessment within 10.
We will tell you whether we consider it a vulnerability and, if so, our intended timeline. We
will credit you in the advisory and changelog unless you ask us not to.

Please give us reasonable time to ship a fix before disclosing publicly. We are a small team; if
you have a deadline, tell us early and we will work to it.

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | Yes |
| < 0.1 | No |

Pre-1.0, security fixes land on the latest minor release only. There are no backports.

## What counts as a vulnerability

This is a detection and de-identification tool, so the boundary is not obvious. Things we treat
as security issues:

- **A de-identification bypass** — a policy reports a value as scrubbed while the original
  survives in the output, or a value is recoverable from what was written in its place.
- **Data leaving the machine.** All inference is local by design. Any code path that transmits
  scanned content anywhere — other than the LLM stage when *you* explicitly configure a remote
  backend — is a vulnerability. Report it.
- **Sensitive values written where they should not be**, such as an exception message, log line,
  or report field that echoes a raw identifier the policy was supposed to remove.
- **A crafted input that causes denial of service**, for example a pathological string that makes
  a detection pattern run in exponential time.
- **Anything exploitable in the usual sense** — arbitrary code execution when loading an ontology
  YAML or a model, path traversal when writing a report, unsafe deserialization.
- **Dependency vulnerabilities** that are reachable through Seiba.

## What does **not** count

These are real concerns and we want to hear about them — but as ordinary bug reports, not
security advisories:

- **A missed detection (false negative).** Seiba finds *candidate* sensitive values. No detector
  is complete, published recall is well below 100%, and the tool is explicitly not a certified
  de-identification solution. A missed entity is a coverage bug — please
  [file an issue](https://github.com/seiba-ai/seiba-risk-scanner/issues) with fake data reproducing it.
- **A false positive**, or a severity score you disagree with. Severity is rule-based and every
  finding carries a `rule_trace` explaining it; disagreements are design discussions.
- **Re-identification of data you scrubbed with a deliberately weak policy.** Choosing `keep`
  or a gentle generalization is a documented trade-off, and the report tells you what it cost.

## Known security-relevant limitations

Disclosed here because you should weigh them before relying on Seiba, not because they are
unreported defects:

- **Deterministic surrogates are dictionary-attackable.** `hash` and `replace` run with
  `consistent=True, seed=0` so records stay joinable across a dataset. That determinism means an
  attacker who knows the value space can build a lookup table and reverse the mapping. Do not
  treat hashed identifiers as anonymous against an adversary who can guess candidate values.
- **`ACTION_SEVERITY_RETENTION` is an unvalidated estimate.** How much severity survives each
  action (hash 0.15, replace 0.10) is hand-picked, not measured. Residual-risk numbers built on
  it are indicative, not guarantees.
- **Residual severity is partial.** It recomputes the exposure index and severity histogram; the
  HIPAA checklist, compliance summary and review queue still describe the *pre-scrub* data.
- **Detection quality varies by population.** Non-Anglo surname recall is lower than Anglo
  surname recall, and is currently unquantified. Only English is supported. Evaluate on your own
  data before relying on it.
- **The scanner cannot infer health context.** A patient registry is byte-identical to a
  marketing list; without `health_context=True` the HIPAA tagging will be wrong.

## Scope

This policy covers the `seiba-risk-scanner` package in this repository.

Vulnerabilities in dependencies — OpenMed, spaCy, transformers, PyTorch — should go to those
projects. If the issue is in *how Seiba uses* a dependency, it is ours; report it here.
