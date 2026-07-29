"""Optional LLM gap-fill stage — runs after deterministic+NER+contextual fusion.

Identifies entity types missing or below confidence threshold, sends targeted
prompts to a local LLM, and returns new candidate spans for merging.

Backends (fastest to slowest for eval):
  "openai"       — OpenAI API or any compatible endpoint (Groq, Together, Azure, Anthropic-proxy)
                   pip install openai  |  set OPENAI_API_KEY env var
                   Groq example: llm_base_url="https://api.groq.com/openai/v1"
                                 llm_model="llama-3.1-8b-instant"
  "transformers" — HuggingFace Hub model, fully embedded (pip install transformers accelerate)
                   Any HF instruct model: "Qwen/Qwen2.5-3B-Instruct", "microsoft/Phi-3.5-mini-instruct"
                   Auto-selects CUDA → MPS → CPU. 4-bit quant: pip install bitsandbytes
  "ollama"       — local ollama server (pip install requests)
  "llama_cpp"    — embedded GGUF inference (pip install llama-cpp-python)
  "vllm"         — OpenAI-compatible HTTP endpoint (pip install requests)

Performance targets (per document, gaps coverage):
  openai / gpt-4o-mini    ~1–3 s    (API, $0.00015/1k tokens)
  openai / groq-llama3    ~0.5–2 s  (free tier, very fast)
  transformers / GPU      ~3–10 s
  transformers / CPU      ~30–90 s  ← the slow path; use openai for eval
"""

from __future__ import annotations

import json
import os
import threading
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, MutableMapping, Optional, Tuple

import requests
import yaml

from seiba_risk_scanner.classification_engine.pipeline_models import CombinedDetectionRow
from seiba_risk_scanner.config import LLMBackendName

_HINTS_PATH = Path(__file__).parent / "label_maps" / "llm_entity_hints.yaml"

# Entities with deterministic F1 ≈ 1.0 — never sent to LLM.
_SKIP_SUFFIXES = frozenset({
    "email_address", "ssn", "ip_address", "credit_card_number", "cvv_code",
    "routing_number_aba", "zip_code", "medical_record_number_mrn", "account_number",
    "payment_transaction_id", "icd10_diagnosis_codes", "medication_dosage",
    "vital_signs", "claim_control_number", "phone_number", "imei_number",
    "us_itin", "uuid_guid",
})

_CHUNK_SIZE = 2_000    # smaller = fewer tokens per call = faster inference
_CHUNK_OVERLAP = 100
_DEFAULT_LLM_CONFIDENCE = 0.68
_MAX_NEW_TOKENS = 256  # entity lists are short; 512 was wasteful

BACKENDS = tuple(member.value for member in LLMBackendName)


# ---------------------------------------------------------------------------
# Span record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class LLMSpanRecord:
    start: int
    end: int
    text: str
    entity_id: str
    confidence_llm: float
    pipeline: str


# ---------------------------------------------------------------------------
# Backend ABC + implementations
# ---------------------------------------------------------------------------

class LLMBackend(ABC):
    @abstractmethod
    def complete(self, prompt: str, *, timeout: int = 60) -> str: ...

    @property
    @abstractmethod
    def pipeline_name(self) -> str: ...


class _OpenAIBackend(LLMBackend):
    """OpenAI SDK backend — works with OpenAI, Azure, Groq, Together, Fireworks, etc.

    Set api_key via llm_api_key param or OPENAI_API_KEY env var.
    For Groq: base_url="https://api.groq.com/openai/v1", model="llama-3.1-8b-instant"
    For Together: base_url="https://api.together.xyz/v1", model="meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
    """

    def __init__(self, model: str, base_url: Optional[str] = None, api_key: Optional[str] = None):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise ImportError("pip install openai") from e
        self._model = model
        self._client = OpenAI(
            api_key=api_key or os.environ.get("OPENAI_API_KEY", ""),
            base_url=base_url or None,
        )

    def complete(self, prompt: str, *, timeout: int = 60) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=_MAX_NEW_TOKENS,
            timeout=timeout,
        )
        return str(resp.choices[0].message.content or "")

    @property
    def pipeline_name(self) -> str:
        return "openai"


class _OllamaBackend(LLMBackend):
    def __init__(self, model: str, base_url: str = "http://localhost:11434"):
        self._model = model
        self._url = base_url.rstrip("/") + "/api/chat"

    def complete(self, prompt: str, *, timeout: int = 60) -> str:
        resp = requests.post(
            self._url,
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "format": "json",
                "stream": False,
                "options": {"temperature": 0.0, "num_predict": _MAX_NEW_TOKENS},
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return str(resp.json()["message"]["content"])

    @property
    def pipeline_name(self) -> str:
        return "ollama"


class _LlamaCppBackend(LLMBackend):
    def __init__(self, model_path: str, n_ctx: int = 4096):
        try:
            from llama_cpp import Llama
        except ImportError as e:
            raise ImportError("pip install llama-cpp-python") from e
        self._llm = Llama(model_path=model_path, n_ctx=n_ctx, verbose=False)

    def complete(self, prompt: str, *, timeout: int = 60) -> str:
        resp = self._llm.create_chat_completion(
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
            max_tokens=_MAX_NEW_TOKENS,
        )
        return str(resp["choices"][0]["message"]["content"])

    @property
    def pipeline_name(self) -> str:
        return "llama_cpp"


class _VLLMBackend(LLMBackend):
    def __init__(self, model: str, base_url: str = "http://localhost:8000"):
        self._model = model
        self._url = base_url.rstrip("/") + "/v1/chat/completions"

    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        resp = requests.post(
            self._url,
            json={
                "model": self._model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {"type": "json_object"},
                "temperature": 0.0,
                "max_tokens": _MAX_NEW_TOKENS,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        return str(resp.json()["choices"][0]["message"]["content"])

    @property
    def pipeline_name(self) -> str:
        return "vllm"


class _TransformersBackend(LLMBackend):
    """HuggingFace transformers backend — no server required.

    Downloads the model from the Hub on first use (cached in ~/.cache/huggingface).
    Device priority: CUDA → MPS (Apple Silicon) → CPU.
    For 4-bit quantization: pip install bitsandbytes, then pass load_in_4bit=True.

    Note: CPU inference is very slow (30–90 s/chunk). Use openai backend for eval.
    """

    def __init__(self, model_id: str, **kwargs: Any):
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer, pipeline as hf_pipeline
        except ImportError as e:
            raise ImportError("pip install transformers accelerate") from e

        self._model_id = model_id

        # Explicit device selection: CUDA > MPS > CPU
        if torch.cuda.is_available():
            device_map = "auto"
        elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            device_map = "mps"
        else:
            device_map = "cpu"

        load_kwargs: Dict[str, Any] = {
            "torch_dtype": "auto",
            "device_map": device_map,
            **kwargs,
        }
        tokenizer = AutoTokenizer.from_pretrained(model_id)
        model = AutoModelForCausalLM.from_pretrained(model_id, **load_kwargs)
        self._pipe = hf_pipeline("text-generation", model=model, tokenizer=tokenizer)

    def complete(self, prompt: str, *, timeout: int = 120) -> str:
        out: Any = self._pipe(
            [{"role": "user", "content": prompt}],
            max_new_tokens=_MAX_NEW_TOKENS,
            do_sample=False,
            temperature=None,
            top_p=None,
            pad_token_id=getattr(self._pipe.tokenizer, "eos_token_id", None),
        )
        generated = out[0]["generated_text"]
        if isinstance(generated, list):
            return str(generated[-1].get("content", "") or "")
        return str(generated)

    @property
    def pipeline_name(self) -> str:
        return "transformers"


# ---------------------------------------------------------------------------
# Backend registry (lazy, thread-safe)
# ---------------------------------------------------------------------------

_registry: Dict[tuple, LLMBackend] = {}
_registry_lock = threading.Lock()


def _get_backend(name: str, model: str, base_url: Optional[str], api_key: Optional[str] = None) -> LLMBackend:
    key = (name, model, base_url)
    if key in _registry:
        return _registry[key]
    with _registry_lock:
        if key in _registry:
            return _registry[key]
        if name == "openai":
            b: LLMBackend = _OpenAIBackend(model, base_url=base_url, api_key=api_key)
        elif name == "transformers":
            b = _TransformersBackend(model)
        elif name == "ollama":
            b = _OllamaBackend(model, base_url=base_url or "http://localhost:11434")
        elif name == "llama_cpp":
            b = _LlamaCppBackend(model_path=model)
        elif name == "vllm":
            b = _VLLMBackend(model, base_url=base_url or "http://localhost:8000")
        else:
            raise ValueError(f"Unknown LLM backend: {name!r}. Valid: {BACKENDS}")
        _registry[key] = b
    return b


# ---------------------------------------------------------------------------
# Hints loading (cached)
# ---------------------------------------------------------------------------

_hints_cache: Optional[Dict[str, Any]] = None
_hints_lock = threading.Lock()


def _load_hints() -> Dict[str, Any]:
    global _hints_cache
    if _hints_cache is not None:
        return _hints_cache
    with _hints_lock:
        if _hints_cache is None:
            _hints_cache = yaml.safe_load(_HINTS_PATH.read_text(encoding="utf-8")) or {}
    return _hints_cache


def _short(entity_id: str) -> str:
    return entity_id.split("::")[-1] if "::" in entity_id else entity_id


def _entity_id_for_short(short: str, hints: Dict[str, Any]) -> Optional[str]:
    for eid in hints:
        if _short(eid) == short:
            return eid
    return None


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def _build_prompt(
    chunk: str,
    target_ids: List[str],
    chunk_found: List[CombinedDetectionRow],
    hints: Dict[str, Any],
) -> str:
    already = "\n".join(
        f'  - "{d.text}" ({_short(d.entity_id)})' for d in chunk_found
    ) or "  (none)"

    target_lines = []
    for eid in target_ids:
        h = hints.get(eid, {})
        desc = h.get("description", _short(eid))
        exs = ", ".join(f'"{e}"' for e in h.get("examples", [])[:3])
        line = f"  - {_short(eid)}: {desc}"
        if exs:
            line += f" (e.g. {exs})"
        target_lines.append(line)

    return (
        "You are a sensitive data detector. Find entities NOT already listed below.\n\n"
        f"Already detected (skip):\n{already}\n\n"
        "Find ONLY these entity types:\n" + "\n".join(target_lines) + "\n\n"
        'Return ONLY a JSON array. Each item: {"text": "<exact substring>", '
        '"entity_type": "<type_from_list>", "confidence": <0.0-1.0>}\n'
        "If nothing found, return [].\n\n"
        f'Text:\n"""{chunk}"""'
    )


# ---------------------------------------------------------------------------
# Response parsing + span alignment
# ---------------------------------------------------------------------------

def _parse_and_align(
    raw: str,
    chunk: str,
    chunk_offset: int,
    hints: Dict[str, Any],
    pipeline: str,
) -> List[LLMSpanRecord]:
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            data = next((v for v in data.values() if isinstance(v, list)), [])
        if not isinstance(data, list):
            return []
    except (json.JSONDecodeError, StopIteration):
        return []

    records: List[LLMSpanRecord] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        span_text = str(item.get("text", "")).strip()
        entity_type = str(item.get("entity_type", ""))
        conf = max(0.0, min(1.0, float(item.get("confidence", _DEFAULT_LLM_CONFIDENCE))))

        if not span_text or not entity_type:
            continue

        entity_id = _entity_id_for_short(entity_type, hints)
        if entity_id is None:
            continue

        idx = chunk.find(span_text)
        if idx == -1:
            idx = chunk.lower().find(span_text.lower())
            if idx == -1:
                continue
            span_text = chunk[idx: idx + len(span_text)]

        records.append(LLMSpanRecord(
            start=chunk_offset + idx,
            end=chunk_offset + idx + len(span_text),
            text=span_text,
            entity_id=entity_id,
            confidence_llm=conf,
            pipeline=pipeline,
        ))

    return records


# ---------------------------------------------------------------------------
# Gap detection + chunking
# ---------------------------------------------------------------------------

def _gap_entity_ids(
    existing: List[CombinedDetectionRow],
    hints: Dict[str, Any],
    skip_if_above: float,
    coverage: str,
) -> List[str]:
    """Return hint entity IDs to send to the LLM based on coverage policy."""
    if coverage == "full":
        return list(hints.keys())
    high_conf: set[str] = {d.entity_id for d in existing if d.confidence >= skip_if_above}
    return [eid for eid in hints if eid not in high_conf]


def _iter_chunks(text: str) -> List[Tuple[str, int]]:
    """Split text into overlapping chunks of _CHUNK_SIZE chars."""
    if len(text) <= _CHUNK_SIZE:
        return [(text, 0)]
    chunks: List[Tuple[str, int]] = []
    start = 0
    while start < len(text):
        end = min(start + _CHUNK_SIZE, len(text))
        chunks.append((text[start:end], start))
        if end >= len(text):
            break
        start = end - _CHUNK_OVERLAP
    return chunks


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_llm_gap_fill(
    text: str,
    *,
    existing: List[CombinedDetectionRow],
    backend: str,
    model: str,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    coverage: str = "gaps",
    llm_skip_if_above: float = 0.85,
    concurrency: int = 4,
    verbose: bool = False,
    timings: Optional[MutableMapping[str, float]] = None,
) -> List[LLMSpanRecord]:
    """
    Run LLM pass after deterministic+NER+contextual pipeline.

    coverage="gaps" (default): only ask for entity types not already at high confidence.
    coverage="full": ask for all hint entity types.

    Chunks are processed in parallel (concurrency=4 by default) for speed.
    Use backend="openai" for eval — 10-50x faster than local CPU inference.
    """
    if not text:
        return []

    hints = _load_hints()
    if not hints:
        return []

    active_hints = {eid: v for eid, v in hints.items() if _short(eid) not in _SKIP_SUFFIXES}
    gap_ids = _gap_entity_ids(existing, active_hints, llm_skip_if_above, coverage)
    if not gap_ids:
        if verbose:
            print("[LLM] All target entities already at high confidence — skipping.")
        return []

    b = _get_backend(backend, model, base_url, api_key)
    chunks = _iter_chunks(text)
    t0 = time.perf_counter()

    # Build (chunk, offset, chunk_found) tuples up front
    tasks: List[Tuple[str, int, List[CombinedDetectionRow]]] = []
    for chunk, offset in chunks:
        chunk_end = offset + len(chunk)
        chunk_found = [d for d in existing if d.start >= offset and d.end <= chunk_end]
        tasks.append((chunk, offset, chunk_found))

    # Process chunks in parallel — API backends get a big speedup; local inference
    # is GPU-bound so concurrency=1 avoids contention overhead there.
    results: List[LLMSpanRecord] = []
    _lock = threading.Lock()

    def _process(task: Tuple[str, int, List[CombinedDetectionRow]]) -> List[LLMSpanRecord]:
        chunk, offset, chunk_found = task
        prompt = _build_prompt(chunk, gap_ids, chunk_found, active_hints)
        try:
            raw = b.complete(prompt)
        except Exception as exc:
            if verbose:
                print(f"[LLM] Backend error (offset={offset}): {exc}")
            return []
        spans = _parse_and_align(raw, chunk, offset, active_hints, b.pipeline_name)
        if verbose:
            print(f"[LLM] chunk offset={offset} len={len(chunk)} → {len(spans)} span(s)")
        return spans

    if concurrency <= 1 or len(tasks) == 1:
        for task in tasks:
            results.extend(_process(task))
    else:
        with ThreadPoolExecutor(max_workers=min(concurrency, len(tasks))) as pool:
            futures = {pool.submit(_process, t): t for t in tasks}
            for fut in as_completed(futures):
                spans = fut.result()
                with _lock:
                    results.extend(spans)

    if timings is not None:
        timings["llm_s"] = time.perf_counter() - t0

    # Deduplicate identical span+entity across chunk boundaries
    seen: set[tuple] = set()
    deduped: List[LLMSpanRecord] = []
    for r in results:
        key = (r.start, r.end, r.entity_id)
        if key not in seen:
            seen.add(key)
            deduped.append(r)

    return deduped
