#!/usr/bin/env python3
"""Citation gate for medical manuscripts — stdlib only.

Resolves every DOI/PMID through Crossref and PubMed, reads PubMed's editorial
notices (retracted publication, retraction notice, expression of concern,
erratum), and prints one ```review JSON block plus a Markdown table.

The division of labour is the point: this script answers "does the record exist,
and does PubMed say it was retracted or corrected?". It does **not** answer
"does the source support the sentence citing it" — that stays with the model,
which is also why an abstract-only judgement is provisional. And when a DOI
resolves but no PMID can be found, the status is ``retraction-unknown``, never
``ok``: PubMed is where the editorial notices live, and absence of a lookup is
not evidence of a clean record.

Usage:
    python citation_check.py --doi 10.1016/S0140-6736(97)11096-0
    python citation_check.py --pmid 9500320 --out review/citation-check.md
    python citation_check.py --manuscript draft.md --strict
    python citation_check.py --refs refs.json --offline
    python citation_check.py --manuscript draft.md --quiet

Exit codes: 0 checked (findings may still exist); 1 ``--strict`` and at least
one reference needs attention; 2 bad usage or unreadable input.

Network policy: NCBI E-utilities are anonymous at 3 requests/s unless
``NCBI_API_KEY`` is set in the environment (10/s); Crossref is paced at 1/s
unless ``--mailto`` (or ``CROSSREF_MAILTO``) puts the run in the polite pool.
The key and the address are never written to the cache, the review block or the
Markdown file. Lookups are cached in ``.openscience/citations/cache.json``;
``--offline`` reads only that cache and never opens a socket.
"""
from __future__ import annotations

import argparse
import contextlib
import difflib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable, Mapping, NamedTuple, Sequence

USER_AGENT = (
    "medagent-workbench-citation-check/0.8 "
    "(+https://github.com/LyZheFeng/medagent-workbench)"
)
CROSSREF_API = "https://api.crossref.org"
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
CACHE_VERSION = 1
DEFAULT_CACHE = ".openscience/citations/cache.json"
DEFAULT_OUT = "review/citation-check.md"

# Statuses, most severe first. `retraction-unknown` is deliberately not `ok`.
STATUS_ORDER = (
    "lookup-failed",
    "unresolved",
    "retracted",
    "concern",
    "corrected",
    "notice",
    "offline-miss",
    "retraction-unknown",
    "ok",
)
EDITORIAL_ORDER = ("retracted", "concern", "corrected", "notice")
RETRYABLE = {408, 429, 500, 502, 503, 504}
DOI_RE = re.compile(r"\b10\.\d{4,9}/[^\s\"'<>]+", re.IGNORECASE)
PMID_RE = re.compile(
    r"(?i)\b(?:PMID|PubMed(?:\s*(?:ID|identifier))?)\s*[:#]?\s*(\d{1,9})\b"
)
HEADING_RE = re.compile(r"^\s{0,3}(#{1,6})\s+(.*)$")
STOPWORDS = {"the", "a", "an"}
# Chinese prose puts its own punctuation right after a DOI.
CJK_TRAILING = "。，、；：！？）］｝》」』】"


class GateError(RuntimeError):
    """Bad input or an impossible request: the CLI exits 2."""


class UsageError(GateError):
    """argparse-level usage problem."""


class NetworkError(RuntimeError):
    """A lookup could not complete; the caller decides between failed and stale."""


# --------------------------------------------------------------------------- #
# Identifiers
# --------------------------------------------------------------------------- #


def clean_doi(raw: str | None) -> str:
    """Normalise a DOI from a URL, a ``doi:`` label, or a bare string."""
    if not raw:
        return ""
    text = str(raw).strip()
    match = re.match(r"(?i)^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", text)
    if match:
        text = text[match.end():]
    text = text.rstrip().rstrip(".,;:!?" + CJK_TRAILING)
    pairs = {")": "(", "]": "[", "}": "{"}
    while text and text[-1] in pairs:
        if text.count(pairs[text[-1]]) < text.count(text[-1]):
            text = text[:-1].rstrip(".,;:!?" + CJK_TRAILING)
        else:
            break
    return text.strip()


def valid_doi(doi: str) -> bool:
    return bool(re.fullmatch(r"10\.\d{4,9}/\S+", doi or ""))


def norm_doi(doi: str | None) -> str:
    return clean_doi(doi).lower()


def clean_pmid(raw: str | None) -> str:
    if raw is None:
        return ""
    match = PMID_RE.search(str(raw))
    if match:
        return match.group(1)
    digits = re.sub(r"\D", "", str(raw))
    return digits if digits and len(digits) <= 9 else ""


# --------------------------------------------------------------------------- #
# Inputs
# --------------------------------------------------------------------------- #


@dataclass
class Ref:
    doi: str = ""
    pmid: str = ""
    label: str = ""
    claim: str = ""
    context: str = ""
    origin: str = "cli"

    @property
    def key(self) -> str:
        if self.doi:
            return f"doi:{norm_doi(self.doi)}"
        return f"pmid:{self.pmid}"

    @property
    def name(self) -> str:
        return self.label or (self.doi or f"PMID {self.pmid}")

    def to_json(self) -> dict:
        out = {
            "reference": self.name,
            "origin": self.origin,
            "doi": self.doi,
            "pmid": self.pmid,
        }
        if self.claim:
            out["claim"] = self.claim
        if self.context:
            out["context"] = self.context[:240]
        return out


def read_text(path: Path) -> str:
    """Read UTF-8, BOM-marked UTF-16, or GB18030 (same set the other gates take)."""
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        try:
            return data.decode("utf-16")
        except UnicodeDecodeError as exc:
            raise GateError(f"cannot decode {path} as UTF-16") from exc
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise GateError(f"cannot decode {path} as UTF-8 or GBK")


def _context(line: str) -> str:
    return re.sub(r"\s+", " ", line).strip()[:240]


def refs_from_text(path: Path) -> tuple[list[Ref], list[str]]:
    """Find DOIs and labelled PMIDs in a manuscript, keeping line and heading."""
    text = read_text(path)
    warnings: list[str] = []
    refs: list[Ref] = []
    heading = ""
    for number, line in enumerate(text.splitlines(), 1):
        heading_match = HEADING_RE.match(line)
        if heading_match:
            heading = heading_match.group(2).strip()
            continue
        dois: list[str] = []
        for match in DOI_RE.finditer(line):
            doi = clean_doi(match.group(0))
            if valid_doi(doi) and doi not in dois:
                dois.append(doi)
        pmids: list[str] = []
        for match in PMID_RE.finditer(line):
            pmid = match.group(1)
            if pmid not in pmids:
                pmids.append(pmid)
        context = _context(line)
        origin = f"{path.name}:{number}"
        if heading:
            origin += f" (§{heading})"
        # A DOI and a PMID on one line are not assumed to describe the same
        # work: prose often cites two papers in one sentence. Each identifier is
        # checked on its own, and the results merge only when they resolve to the
        # same record.
        for doi in dois:
            refs.append(Ref(doi=doi, context=context, origin=origin))
        for pmid in pmids:
            refs.append(Ref(pmid=pmid, context=context, origin=origin))
    return refs, warnings


def refs_from_json(path: Path) -> list[Ref]:
    try:
        data = json.loads(read_text(path))
    except ValueError as exc:
        raise GateError(f"{path} is not valid JSON: {exc}") from exc
    if isinstance(data, Mapping):
        data = data.get("references")
    if not isinstance(data, list):
        raise GateError(f"{path}: expected a list of references")
    out: list[Ref] = []
    for index, item in enumerate(data, 1):
        if isinstance(item, str):
            item = {"doi": item}
        if not isinstance(item, Mapping):
            raise GateError(f"{path}: reference {index} is not an object")
        doi = clean_doi(str(item.get("doi") or ""))
        pmid = clean_pmid(str(item.get("pmid") or ""))
        if not doi and not pmid:
            raise GateError(f"{path}: reference {index} has neither doi nor pmid")
        if doi and not valid_doi(doi):
            raise GateError(f"{path}: reference {index}: not a DOI: {doi}")
        out.append(
            Ref(
                doi=doi,
                pmid=pmid,
                label=str(item.get("label") or "").strip(),
                claim=str(item.get("claim") or "").strip(),
                origin=f"{path.name}#{index}",
            )
        )
    return out


def refs_from_txt(path: Path) -> list[Ref]:
    """One identifier per line: ``doi:10.x``, bare ``10.x``, ``PMID: 123``, ``123``."""
    out: list[Ref] = []
    for number, line in enumerate(read_text(path).splitlines(), 1):
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        doi_match = DOI_RE.search(text)
        if doi_match:
            doi = clean_doi(doi_match.group(0))
            if not valid_doi(doi):
                raise GateError(f"{path}:{number}: not a DOI: {doi}")
            out.append(Ref(doi=doi, origin=f"{path.name}:{number}"))
            continue
        pmid = clean_pmid(text)
        if pmid and re.fullmatch(r"(?i)(?:PMID\s*[:#]?\s*)?\d{1,9}", text):
            out.append(Ref(pmid=pmid, origin=f"{path.name}:{number}"))
            continue
        raise GateError(
            f"{path}:{number}: expected a DOI or a PMID, got {text[:60]!r}"
        )
    return out


def merge_refs(refs: Iterable[Ref]) -> list[Ref]:
    """Deduplicate by DOI, then by PMID; a later PMID fills an earlier gap."""
    out: list[Ref] = []
    by_doi: dict[str, Ref] = {}
    by_pmid: dict[str, Ref] = {}
    for ref in refs:
        doi = norm_doi(ref.doi)
        pmid = ref.pmid
        if doi and doi in by_doi:
            existing = by_doi[doi]
            if pmid and not existing.pmid:
                existing.pmid = pmid
            continue
        if not doi and pmid and pmid in by_pmid:
            continue
        out.append(ref)
        if doi:
            by_doi[doi] = ref
        if pmid:
            by_pmid[pmid] = ref
    return out


def merge_results(results: Sequence["RefResult"]) -> list["RefResult"]:
    """One record per work: a DOI input and a PMID input for the same paper merge."""
    out: list[RefResult] = []
    by_doi: dict[str, RefResult] = {}
    by_pmid: dict[str, RefResult] = {}
    for result in results:
        doi = norm_doi(result.doi)
        pmid = result.pmid
        existing = by_doi.get(doi) if doi else None
        if existing is None and pmid:
            existing = by_pmid.get(pmid)
        if existing is not None:
            existing.doi = existing.doi or result.doi
            existing.pmid = existing.pmid or result.pmid
            existing.ref.doi = existing.ref.doi or result.ref.doi
            existing.ref.pmid = existing.ref.pmid or result.ref.pmid
            if result.ref.label and not existing.ref.label:
                existing.ref.label = result.ref.label
            if STATUS_ORDER.index(result.status) < STATUS_ORDER.index(existing.status):
                existing.status = result.status
            seen = {(flag["kind"], flag["source"], flag["detail"]) for flag in existing.flags}
            for flag in result.flags:
                key = (flag["kind"], flag["source"], flag["detail"])
                if key not in seen:
                    existing.flags.append(flag)
                    seen.add(key)
            seen_findings = {
                (finding.tag, finding.title, finding.evidence)
                for finding in existing.findings
            }
            for finding in result.findings:
                key = (finding.tag, finding.title, finding.evidence)
                if key not in seen_findings:
                    existing.findings.append(finding)
                    seen_findings.add(key)
            continue
        out.append(result)
        if doi:
            by_doi[doi] = result
        if pmid:
            by_pmid[pmid] = result
    return out


def collect_refs(args: argparse.Namespace) -> tuple[list[Ref], list[str]]:
    refs: list[Ref] = []
    warnings: list[str] = []
    for raw in args.doi:
        doi = clean_doi(raw)
        if not valid_doi(doi):
            raise GateError(f"--doi: not a DOI: {raw}")
        refs.append(Ref(doi=doi))
    for raw in args.pmid:
        pmid = clean_pmid(raw)
        if not pmid:
            raise GateError(f"--pmid: not a PMID: {raw}")
        refs.append(Ref(pmid=pmid))
    for name in args.refs:
        path = Path(name)
        if not path.is_file():
            raise GateError(f"no such file: {name}")
        if path.suffix.lower() in (".json",):
            refs.extend(refs_from_json(path))
        else:
            refs.extend(refs_from_txt(path))
    for name in args.manuscript:
        path = Path(name)
        if not path.is_file():
            raise GateError(f"no such file: {name}")
        found, notes = refs_from_text(path)
        refs.extend(found)
        warnings.extend(notes)
    return merge_refs(refs), warnings


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #


class Cache:
    """A JSON file of normalized lookups, replaced atomically and never secret."""

    def __init__(
        self,
        path: Path,
        max_age_days: float = 7.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = path
        self.max_age_days = max_age_days
        self.now = now or (lambda: datetime.now(timezone.utc))
        self.entries: dict[str, dict] = {}
        self.dirty = False
        self.load_error = ""
        self._load()

    def _load(self) -> None:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return
        except OSError as exc:
            self.load_error = f"could not read cache {self.path}: {exc}"
            return
        try:
            data = json.loads(raw)
        except ValueError:
            self.load_error = f"cache {self.path} is not valid JSON; ignoring it"
            return
        if (
            not isinstance(data, dict)
            or data.get("version") != CACHE_VERSION
            or not isinstance(data.get("entries"), dict)
        ):
            self.load_error = f"cache {self.path} has an unknown shape; ignoring it"
            return
        self.entries = data["entries"]

    def peek(self, key: str) -> dict | None:
        entry = self.entries.get(key)
        if not isinstance(entry, dict):
            return None
        if "fetched_at" not in entry or "record" not in entry:
            return None
        return entry

    def is_fresh(self, key: str) -> bool:
        entry = self.peek(key)
        if not entry:
            return False
        try:
            fetched = datetime.fromisoformat(str(entry["fetched_at"]))
        except (TypeError, ValueError):
            return False
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
        return self.now() - fetched <= timedelta(days=self.max_age_days)

    def put(self, key: str, *, record: dict | None, source: str, http_status: int | None) -> None:
        self.entries[key] = {
            "fetched_at": self.now().isoformat(timespec="seconds"),
            "source": source,
            "http_status": http_status,
            "record": record,
        }
        self.dirty = True

    def save(self) -> str | None:
        if not self.dirty:
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_name(self.path.name + ".tmp")
            temporary.write_text(
                json.dumps(
                    {"version": CACHE_VERSION, "entries": self.entries},
                    ensure_ascii=False,
                    indent=1,
                ),
                encoding="utf-8",
            )
            os.replace(temporary, self.path)
        except OSError as exc:
            return f"could not write cache {self.path}: {exc}"
        self.dirty = False
        return None


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #


class HttpResponse(NamedTuple):
    status: int
    body: bytes
    headers: Mapping[str, str]


@dataclass
class Lookup:
    record: dict | None
    http_status: int | None
    state: str  # fresh | cached | stale | failed | offline-miss
    error: str = ""

    def to_json(self) -> dict:
        out = {"state": self.state, "http_status": self.http_status}
        if self.record is not None:
            out["ok"] = True
        if self.error:
            out["error"] = self.error
        return out


class Http:
    """urllib with pacing, retries, and an injectable opener for tests."""

    def __init__(
        self,
        *,
        timeout: float = 15.0,
        mailto: str = "",
        api_key: str = "",
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        opener: Callable[[str, Mapping[str, str]], HttpResponse] | None = None,
    ) -> None:
        self.timeout = timeout
        self.mailto = mailto
        self.api_key = api_key
        self._sleep = sleep
        self._clock = clock
        self._opener = opener or self._urlopen
        self._last: dict[str, float] = {}
        self.max_attempts = 3
        self.requests = 0

    def _urlopen(self, url: str, headers: Mapping[str, str]) -> HttpResponse:
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, **headers}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                status = getattr(response, "status", None) or response.getcode()
                return HttpResponse(int(status), response.read(), dict(response.headers))
        except urllib.error.HTTPError as exc:
            body = b""
            with contextlib.suppress(OSError):
                body = exc.read() or b""
            return HttpResponse(int(exc.code), body, dict(exc.headers or {}))
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise NetworkError(str(reason)) from exc

    def _interval(self, url: str) -> float:
        host = urllib.parse.urlparse(url).netloc.lower()
        if host.endswith("ncbi.nlm.nih.gov"):
            return 0.11 if self.api_key else 0.34
        if host.endswith("crossref.org"):
            return 0.25 if self.mailto else 1.0
        return 0.0

    def get(self, url: str, headers: Mapping[str, str] | None = None) -> HttpResponse:
        host = urllib.parse.urlparse(url).netloc
        last = self._last.get(host)
        if last is not None:
            wait = self._interval(url) - (self._clock() - last)
            if wait > 0:
                self._sleep(wait)
        self._last[host] = self._clock()
        attempt = 0
        while True:
            attempt += 1
            self.requests += 1
            try:
                response = self._opener(url, headers or {})
            except NetworkError:
                if attempt >= self.max_attempts:
                    raise
                self._sleep(attempt)
                continue
            if response.status in RETRYABLE and attempt < self.max_attempts:
                self._sleep(self._retry_after(response.headers, attempt))
                continue
            return response

    @staticmethod
    def _retry_after(headers: Mapping[str, str], attempt: int) -> float:
        raw = ""
        for name, value in headers.items():
            if name.lower() == "retry-after":
                raw = str(value)
                break
        if raw.isdigit():
            return min(float(raw), 10.0)
        return min(float(attempt), 5.0)


# --------------------------------------------------------------------------- #
# Crossref + PubMed parsing
# --------------------------------------------------------------------------- #


def _first_text(value: object) -> str:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, str) and item.strip():
                return item.strip()
        return ""
    return value.strip() if isinstance(value, str) else ""


def _crossref_year(record: Mapping) -> str:
    for key in ("issued", "published-print", "published-online", "created"):
        node = record.get(key)
        if not isinstance(node, Mapping):
            continue
        parts = node.get("date-parts")
        if isinstance(parts, list) and parts and isinstance(parts[0], list) and parts[0]:
            return str(parts[0][0])
    return ""


def normalize_crossref(payload: object) -> dict:
    message = payload.get("message") if isinstance(payload, Mapping) else None
    if not isinstance(message, Mapping):
        raise NetworkError("Crossref returned an unexpected payload")

    def updates(key: str) -> list[dict]:
        out = []
        for item in message.get(key) or []:
            if not isinstance(item, Mapping):
                continue
            out.append(
                {
                    "type": str(item.get("type") or "").strip().lower(),
                    "doi": clean_doi(str(item.get("DOI") or "")),
                    "label": str(item.get("label") or "").strip(),
                }
            )
        return out

    return {
        "doi": clean_doi(str(message.get("DOI") or "")),
        "title": _first_text(message.get("title")),
        "journal": _first_text(message.get("container-title")),
        "year": _crossref_year(message),
        "type": str(message.get("type") or ""),
        "updated_by": updates("updated-by"),
        "update_to": updates("update-to"),
    }


def _node_text(node: ET.Element | None) -> str:
    if node is None:
        return ""
    return re.sub(r"\s+", " ", " ".join(node.itertext())).strip()


def normalize_pubmed(body: bytes) -> dict:
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise NetworkError(f"PubMed returned invalid XML: {exc}") from exc
    error = root.findtext(".//ERROR")
    if error and error.strip():
        raise NetworkError(f"PubMed: {error.strip()}")
    article = root.find(".//PubmedArticle")
    if article is None:
        article = root.find(".//PubmedBookArticle")
    if article is None:
        raise NetworkError("PubMed returned no article for this identifier")

    doi = ""
    for identifier in article.findall(".//ArticleIdList/ArticleId"):
        if (identifier.get("IdType") or "").lower() == "doi":
            doi = clean_doi(identifier.text or "")
            break

    year = ""
    pub_date = article.find(".//PubDate")
    if pub_date is not None:
        year = (pub_date.findtext("Year") or "").strip()
        if not year:
            medline = (pub_date.findtext("MedlineDate") or "").strip()
            found = re.search(r"\b(?:19|20)\d{2}\b", medline)
            year = found.group(0) if found else ""

    corrections = []
    for node in article.findall(".//CommentsCorrectionsList/CommentsCorrections"):
        corrections.append(
            {
                "reftype": str(node.get("RefType") or "").strip(),
                "refsource": (node.findtext("RefSource") or "").strip(),
                "pmid": (node.findtext("PMID") or "").strip(),
            }
        )

    return {
        "pmid": (article.findtext(".//PMID") or "").strip(),
        "doi": doi,
        "title": _node_text(article.find(".//ArticleTitle"))
        or _node_text(article.find(".//BookTitle")),
        "journal": (article.findtext(".//Journal/Title") or "").strip()
        or (article.findtext(".//Book/BookTitle") or "").strip(),
        "year": year,
        "publication_types": [
            _node_text(node)
            for node in article.findall(".//PublicationTypeList/PublicationType")
        ],
        "corrections": corrections,
    }


def pubmed_flags(record: Mapping) -> list[dict]:
    flags: list[dict] = []

    def add(kind: str, detail: str) -> None:
        flags.append({"kind": kind, "source": "pubmed", "detail": detail})

    for value in record.get("publication_types") or []:
        text = str(value).strip()
        lowered = text.lower()
        if lowered == "retracted publication":
            add("retracted", "PublicationType: Retracted Publication")
        elif lowered == "retraction of publication":
            add("notice", "PublicationType: Retraction of Publication")
        elif lowered == "expression of concern":
            add("concern", "PublicationType: Expression of Concern")
        elif lowered == "published erratum":
            add("notice", "PublicationType: Published Erratum")
    for correction in record.get("corrections") or []:
        reftype = str(correction.get("reftype") or "").lower()
        source = str(correction.get("refsource") or "").strip()
        if reftype == "retractionin":
            add("retracted", f"RetractionIn: {source}".strip())
        elif reftype == "retractionof":
            add("notice", f"RetractionOf: {source}".strip())
        elif reftype == "expressionofconcernin":
            add("concern", f"ExpressionOfConcernIn: {source}".strip())
        elif reftype == "expressionofconcernof":
            add("notice", f"ExpressionOfConcernOf: {source}".strip())
        elif reftype == "erratumin":
            add("corrected", f"ErratumIn: {source}".strip())
        elif reftype == "erratumfor":
            add("notice", f"ErratumFor: {source}".strip())
        elif reftype in ("updatein", "correctedandrepublishedin"):
            add("info", f"{correction.get('reftype')}: {source}".strip())
    return _dedupe_flags(flags)


def crossref_flags(record: Mapping) -> list[dict]:
    flags: list[dict] = []

    def kind_of(value: str) -> str | None:
        lowered = value.lower()
        if "retract" in lowered:
            return "retracted"
        if "concern" in lowered:
            return "concern"
        if "correct" in lowered or "erratum" in lowered or "corrigendum" in lowered:
            return "corrected"
        return None

    for update in record.get("updated_by") or []:
        kind = kind_of(str(update.get("type") or ""))
        if kind:
            flags.append(
                {
                    "kind": kind,
                    "source": "crossref",
                    "detail": f"updated-by {update.get('type')}: {update.get('doi') or update.get('label')}",
                }
            )
    for update in record.get("update_to") or []:
        kind = kind_of(str(update.get("type") or ""))
        if kind:
            flags.append(
                {
                    "kind": "notice",
                    "source": "crossref",
                    "detail": f"this record is an update of another work "
                    f"({update.get('type')}): {update.get('doi') or update.get('label')}",
                }
            )
    return _dedupe_flags(flags)


def _dedupe_flags(flags: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    out: list[dict] = []
    for flag in flags:
        key = (flag["kind"], flag["source"], flag["detail"])
        if key in seen:
            continue
        seen.add(key)
        out.append(flag)
    return out


# --------------------------------------------------------------------------- #
# Comparison
# --------------------------------------------------------------------------- #


def _norm_words(text: str) -> str:
    return re.sub(r"[\W_]+", "", (text or "").lower(), flags=re.UNICODE)


def _similar(left: str, right: str, threshold: float = 0.8) -> bool:
    a, b = _norm_words(left), _norm_words(right)
    if not a or not b:
        return True
    if min(len(a), len(b)) >= 20 and (a in b or b in a):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold


def _journal_similar(left: str, right: str) -> bool:
    def trim(value: str) -> str:
        words = re.findall(r"[0-9a-z\u4e00-\u9fff]+", value.lower())
        return "".join(word for word in words if word not in STOPWORDS)

    a, b = trim(left), trim(right)
    if not a or not b:
        return True
    return a == b or a in b or b in a or difflib.SequenceMatcher(None, a, b).ratio() >= 0.7


def metadata_conflicts(crossref: Mapping, pubmed: Mapping) -> list[dict]:
    conflicts: list[dict] = []
    if not _similar(str(crossref.get("title") or ""), str(pubmed.get("title") or "")):
        conflicts.append(
            {
                "field": "title",
                "crossref": str(crossref.get("title") or "")[:200],
                "pubmed": str(pubmed.get("title") or "")[:200],
            }
        )
    if not _journal_similar(str(crossref.get("journal") or ""), str(pubmed.get("journal") or "")):
        conflicts.append(
            {
                "field": "journal",
                "crossref": str(crossref.get("journal") or "")[:120],
                "pubmed": str(pubmed.get("journal") or "")[:120],
            }
        )
    left = str(crossref.get("year") or "").strip()
    right = str(pubmed.get("year") or "").strip()
    if left.isdigit() and right.isdigit() and abs(int(left) - int(right)) > 1:
        conflicts.append({"field": "year", "crossref": left, "pubmed": right})
    return conflicts


# --------------------------------------------------------------------------- #
# Checker
# --------------------------------------------------------------------------- #


@dataclass
class Finding:
    level: str  # error | warn | info
    tag: str
    title: str
    evidence: str
    reference: str = ""

    def to_json(self) -> dict:
        return {
            "level": self.level,
            "tag": self.tag,
            "title": self.title,
            "evidence": self.evidence,
            "reference": self.reference,
        }


@dataclass
class RefResult:
    ref: Ref
    status: str = "unresolved"
    doi: str = ""
    pmid: str = ""
    title: str = ""
    journal: str = ""
    year: str = ""
    flags: list[dict] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    lookups: dict[str, dict] = field(default_factory=dict)
    checked_at: str = ""
    cache_note: str = ""

    def to_json(self) -> dict:
        payload = {
            **self.ref.to_json(),
            "status": self.status,
            "doi": self.doi or self.ref.doi,
            "pmid": self.pmid or self.ref.pmid,
            "title": self.title,
            "journal": self.journal,
            "year": self.year,
            "flags": self.flags,
            "lookups": self.lookups,
            "checked_at": self.checked_at,
        }
        if self.cache_note:
            payload["cache"] = self.cache_note
        return payload


class Checker:
    def __init__(
        self,
        http: Http,
        cache: Cache,
        *,
        offline: bool = False,
        refresh: bool = False,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.http = http
        self.cache = cache
        self.offline = offline
        self.refresh = refresh
        self.now = now or (lambda: datetime.now().astimezone())

    # -- lookups ---------------------------------------------------------- #

    def _ncbi_url(self, endpoint: str, params: Mapping[str, str]) -> str:
        query = {"tool": "medagent-workbench", **params}
        if self.http.mailto:
            query["email"] = self.http.mailto
        if self.http.api_key:
            query["api_key"] = self.http.api_key
        return f"{EUTILS}/{endpoint}?{urllib.parse.urlencode(query)}"

    def _lookup(self, key: str, source: str, fetch: Callable[[], tuple[dict | None, int]]) -> Lookup:
        entry = self.cache.peek(key)
        if self.offline:
            if entry is not None:
                return Lookup(entry["record"], entry.get("http_status"), "cached")
            return Lookup(None, None, "offline-miss", f"{key} is not in the cache")
        if entry is not None and not self.refresh and self.cache.is_fresh(key):
            return Lookup(entry["record"], entry.get("http_status"), "cached")
        try:
            record, status = fetch()
        except NetworkError as exc:
            if entry is not None:
                return Lookup(entry["record"], entry.get("http_status"), "stale", str(exc))
            return Lookup(None, None, "failed", str(exc))
        self.cache.put(key, record=record, source=source, http_status=status)
        return Lookup(record, status, "fresh")

    def crossref(self, doi: str) -> Lookup:
        return self._lookup(
            f"crossref/v{CACHE_VERSION}/doi:{norm_doi(doi)}",
            "crossref",
            lambda: self._fetch_crossref(doi),
        )

    def esearch(self, doi: str) -> Lookup:
        return self._lookup(
            f"esearch/v{CACHE_VERSION}/doi:{norm_doi(doi)}",
            "pubmed",
            lambda: self._fetch_esearch(doi),
        )

    def pubmed(self, pmid: str) -> Lookup:
        return self._lookup(
            f"pubmed/v{CACHE_VERSION}/pmid:{pmid}",
            "pubmed",
            lambda: self._fetch_pubmed(pmid),
        )

    def _fetch_crossref(self, doi: str) -> tuple[dict | None, int]:
        url = f"{CROSSREF_API}/works/{urllib.parse.quote(doi, safe='')}"
        if self.http.mailto:
            url += "?" + urllib.parse.urlencode({"mailto": self.http.mailto})
        response = self.http.get(url, {"Accept": "application/json"})
        if response.status == 404:
            return None, 404
        if response.status != 200:
            raise NetworkError(f"Crossref returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise NetworkError("Crossref returned invalid JSON") from exc
        return normalize_crossref(payload), 200

    def _fetch_esearch(self, doi: str) -> tuple[dict | None, int]:
        url = self._ncbi_url(
            "esearch.fcgi",
            {
                "db": "pubmed",
                "retmode": "json",
                "term": f"{doi}[doi]",
            },
        )
        response = self.http.get(url, {"Accept": "application/json"})
        if response.status != 200:
            raise NetworkError(f"PubMed esearch returned HTTP {response.status}")
        try:
            payload = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, ValueError) as exc:
            raise NetworkError("PubMed esearch returned invalid JSON") from exc
        result = payload.get("esearchresult") if isinstance(payload, Mapping) else None
        if not isinstance(result, Mapping):
            raise NetworkError("PubMed esearch returned an unexpected payload")
        if result.get("ERROR"):
            raise NetworkError(f"PubMed esearch: {result['ERROR']}")
        ids = [str(value) for value in result.get("idlist") or [] if str(value).isdigit()]
        return {"pmid": ids[0] if ids else None, "count": len(ids)}, 200

    def _fetch_pubmed(self, pmid: str) -> tuple[dict | None, int]:
        url = self._ncbi_url(
            "efetch.fcgi", {"db": "pubmed", "id": pmid, "retmode": "xml"}
        )
        response = self.http.get(url, {"Accept": "application/xml"})
        if response.status == 404:
            return None, 404
        if response.status != 200:
            raise NetworkError(f"PubMed efetch returned HTTP {response.status}")
        return normalize_pubmed(response.body), 200

    # -- one reference ---------------------------------------------------- #

    def check(self, ref: Ref) -> RefResult:
        given_doi = clean_doi(ref.doi)
        given_pmid = ref.pmid
        doi = given_doi
        pmid = given_pmid
        cr = self.crossref(doi) if doi else None
        es = self.esearch(doi) if doi else None
        if es and es.record and not pmid:
            pmid = str(es.record.get("pmid") or "")
        pm = self.pubmed(pmid) if pmid else None

        lookups: dict[str, dict] = {}
        if cr is not None:
            lookups["crossref"] = cr.to_json()
        if es is not None:
            lookups["esearch"] = es.to_json()
        if pm is not None:
            lookups["pubmed"] = pm.to_json()

        if not doi and pm and pm.record and pm.record.get("doi"):
            doi = str(pm.record["doi"])
            cr = self.crossref(doi)
            lookups["crossref"] = cr.to_json()

        result = RefResult(
            ref=ref,
            doi=doi or ref.doi,
            pmid=pmid or ref.pmid,
            checked_at=self.now().isoformat(timespec="seconds"),
            lookups=lookups,
        )

        cr_record = cr.record if cr is not None else None
        pm_record = pm.record if pm is not None else None
        notes = [
            lookup.error
            for lookup in (cr, es, pm)
            if lookup is not None and lookup.state == "stale" and lookup.error
        ]

        if cr_record:
            result.title = str(cr_record.get("title") or "")
            result.journal = str(cr_record.get("journal") or "")
            result.year = str(cr_record.get("year") or "")
        if pm_record:
            result.title = result.title or str(pm_record.get("title") or "")
            result.journal = result.journal or str(pm_record.get("journal") or "")
            result.year = result.year or str(pm_record.get("year") or "")

        flags = _dedupe_flags(
            (pubmed_flags(pm_record) if pm_record else [])
            + (crossref_flags(cr_record) if cr_record else [])
        )
        result.flags = flags

        # --- status precedence ------------------------------------------- #
        # A cached DOI alone does not verify a record: the editorial notices
        # live in PubMed, so a missing PubMed lookup is a miss, not a pass.
        blocked: list[Lookup] = []
        if self.offline:
            if pm is not None and pm.state == "offline-miss":
                blocked.append(pm)
            if es is not None and es.state == "offline-miss" and not given_pmid:
                blocked.append(es)
            if (
                pm_record is None
                and cr is not None
                and cr.state == "offline-miss"
                and not given_pmid
            ):
                blocked.append(cr)

        if blocked:
            result.status = "offline-miss"
            result.findings.append(
                Finding(
                    "error",
                    "citation · offline",
                    "Not checked — the lookup is not cached",
                    "; ".join(lookup.error for lookup in blocked),
                    ref.name,
                )
            )
        elif (
            pm is not None and pm.state == "failed"
        ) or (es is not None and es.state == "failed" and pm_record is None):
            failed = [
                lookup
                for lookup in (cr, es, pm)
                if lookup is not None and lookup.state == "failed"
            ]
            result.status = "lookup-failed"
            result.findings.append(
                Finding(
                    "error",
                    "citation · lookup",
                    "Lookup failed — the record is unverified, not proven absent",
                    "; ".join(lookup.error for lookup in failed),
                    ref.name,
                )
            )
        elif pm is not None and pm_record is None:
            result.status = "unresolved"
            result.findings.append(
                Finding(
                    "error",
                    "citation · unresolved",
                    "Could not be resolved",
                    f"PubMed efetch returned HTTP {pm.http_status} for PMID {pmid}",
                    ref.name,
                )
            )
        elif pm_record is None and not pmid:
            if cr_record is not None:
                result.status = "retraction-unknown"
            elif cr is not None and cr.state == "failed":
                result.status = "lookup-failed"
                result.findings.append(
                    Finding(
                        "error",
                        "citation · lookup",
                        "Lookup failed — the record is unverified, not proven absent",
                        cr.error,
                        ref.name,
                    )
                )
            else:
                result.status = "unresolved"
                details = []
                if cr is not None:
                    details.append(f"Crossref HTTP {cr.http_status}")
                if es is not None:
                    details.append("PubMed esearch found no PMID for this DOI")
                result.findings.append(
                    Finding(
                        "error",
                        "citation · unresolved",
                        "Could not be resolved",
                        "; ".join(details) or "no DOI or PMID was resolvable",
                        ref.name,
                    )
                )
        else:
            kinds = {flag["kind"] for flag in flags}
            editorial = next((kind for kind in EDITORIAL_ORDER if kind in kinds), "")
            if editorial:
                result.status = editorial
            elif pm_record:
                result.status = "ok"
            else:
                result.status = "retraction-unknown"

        # --- cross-checks -------------------------------------------------- #
        if given_pmid and es and es.record and es.record.get("pmid"):
            moved = str(es.record["pmid"])
            if moved != given_pmid:
                result.findings.append(
                    Finding(
                        "error",
                        "citation · conflict",
                        "The DOI and the PMID point to different records",
                        f"DOI {doi} resolves to PMID {moved}, but PMID {given_pmid} was given",
                        ref.name,
                    )
                )
        if given_doi and pm_record and pm_record.get("doi"):
            published = norm_doi(str(pm_record["doi"]))
            if published and published != norm_doi(given_doi):
                result.findings.append(
                    Finding(
                        "error",
                        "citation · conflict",
                        "PubMed's DOI for this PMID is a different work",
                        f"PMID {pmid} carries DOI {published}, but {given_doi} was given",
                        ref.name,
                    )
                )
        if given_doi and given_pmid and es is not None and es.state == "failed":
            result.findings.append(
                Finding(
                    "warn",
                    "citation · lookup",
                    "DOI and PMID were not cross-checked",
                    f"PubMed esearch failed: {es.error}",
                    ref.name,
                )
            )
        if given_doi and pm_record and (cr is None or cr_record is None):
            if cr is not None and cr.state == "failed":
                result.findings.append(
                    Finding(
                        "warn",
                        "citation · lookup",
                        "Crossref metadata could not be read",
                        f"PubMed resolved PMID {pmid}, but Crossref failed: {cr.error}",
                        ref.name,
                    )
                )
            elif cr is not None:
                result.findings.append(
                    Finding(
                        "error",
                        "citation · unresolved",
                        "The DOI did not resolve",
                        f"Crossref returned HTTP {cr.http_status} for {given_doi}, "
                        f"but PMID {pmid} resolved",
                        ref.name,
                    )
                )
        if cr_record and pm_record:
            for conflict in metadata_conflicts(cr_record, pm_record):
                result.findings.append(
                    Finding(
                        "warn",
                        "citation · metadata",
                        f"Crossref and PubMed disagree on the {conflict['field']}",
                        f"Crossref: {conflict['crossref']} — PubMed: {conflict['pubmed']}",
                        ref.name,
                    )
                )

        # --- findings for the editorial state ------------------------------ #
        if result.status == "retracted":
            detail = "; ".join(
                f"{flag['source']}: {flag['detail']}"
                for flag in result.flags
                if flag["kind"] == "retracted"
            )
            result.findings.append(
                Finding(
                    "error",
                    "citation · retracted",
                    "Retracted source",
                    detail or "the record is marked retracted",
                    ref.name,
                )
            )
        elif result.status == "concern":
            detail = "; ".join(
                f"{flag['source']}: {flag['detail']}"
                for flag in result.flags
                if flag["kind"] == "concern"
            )
            result.findings.append(
                Finding(
                    "error",
                    "citation · concern",
                    "Expression of concern on the source",
                    detail or "the record carries an expression of concern",
                    ref.name,
                )
            )
        elif result.status == "corrected":
            detail = "; ".join(
                f"{flag['source']}: {flag['detail']}"
                for flag in result.flags
                if flag["kind"] == "corrected"
            )
            result.findings.append(
                Finding(
                    "warn",
                    "citation · corrected",
                    "The source has a correction or erratum",
                    detail or "cite the corrected version or say which version was used",
                    ref.name,
                )
            )
        elif result.status == "notice":
            detail = "; ".join(
                f"{flag['source']}: {flag['detail']}"
                for flag in result.flags
                if flag["kind"] in ("notice", "info")
            )
            result.findings.append(
                Finding(
                    "warn",
                    "citation · notice",
                    "This identifier is an editorial notice",
                    (detail or "the record is a retraction/erratum notice")
                    + " — cite the original study if that is what the claim needs",
                    ref.name,
                )
            )
        elif result.status == "retraction-unknown":
            result.findings.append(
                Finding(
                    "warn",
                    "citation · retraction-unknown",
                    "Retraction status unknown — no PMID",
                    "Crossref resolved the DOI, but no PubMed record was found for it, "
                    "so retraction and correction notices could not be read. This is not "
                    "evidence that the record is clean.",
                    ref.name,
                )
            )

        if notes:
            result.cache_note = "; ".join(notes)
        return result


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #


def summarize(results: Sequence[RefResult]) -> dict:
    counts = {status: 0 for status in STATUS_ORDER}
    for result in results:
        counts[result.status] += 1
    findings = [finding for result in results for finding in result.findings]
    return {
        "references": len(results),
        "statuses": {key: value for key, value in counts.items() if value},
        "errors": sum(1 for finding in findings if finding.level == "error"),
        "warnings": sum(1 for finding in findings if finding.level == "warn"),
    }


def note(results: Sequence[RefResult], offline: bool, warnings: Sequence[str]) -> str:
    summary = summarize(results)
    states = ", ".join(f"{count} {status}" for status, count in summary["statuses"].items())
    text = (
        "Citation gate — DOI/PMID resolution through Crossref and PubMed, plus "
        "PubMed's retraction, expression-of-concern and erratum notices. It does "
        "not judge whether a source supports the sentence citing it, and a "
        "reference without a PMID is reported as retraction status unknown, not "
        "as clean. "
        f"{summary['references']} reference(s): {states or 'none'}."
    )
    if offline:
        text += " Offline run: only cached lookups were used."
    if warnings:
        text += " " + " ".join(warnings[:3])
    return text


def render_markdown(review: Mapping) -> str:
    summary = review["summary"]
    statuses = ", ".join(
        f"{count} {status}" for status, count in summary["statuses"].items()
    )
    lines = [
        "# Citation check",
        "",
        f"Generated {review['generated_at']} · {summary['references']} reference(s) · "
        f"{'offline' if review['offline'] else 'Crossref + PubMed'}",
        "",
        f"Result: {statuses or 'none'}"
        + (f" · {summary['errors']} error(s), {summary['warnings']} warning(s)"
           if summary["errors"] or summary["warnings"] else ""),
        "",
        "> This gate resolves identifiers and reads PubMed's retraction/correction "
        "notices. It does not judge whether a source supports the claim it is cited "
        "for; that reading is still yours. A missing PMID means the retraction status "
        "was not checked — reported as unknown, not clean.",
        "",
        "## References",
        "",
        "| # | Reference | DOI | PMID | Status |",
        "|---|---|---|---|---|",
    ]
    for index, ref in enumerate(review["refs"], 1):
        status = ref["status"]
        label = _cell(ref.get("reference") or "")
        doi = _cell(ref.get("doi") or "—")
        pmid = _cell(ref.get("pmid") or "—")
        shown = f"**{status}**" if status != "ok" else status
        lines.append(f"| {index} | {label} | {doi} | {pmid} | {shown} |")
    lines.append("")

    if review["findings"]:
        lines.extend(["## Findings", ""])
        for finding in review["findings"]:
            lines.append(
                f"### [{finding['level']}] {finding['title']} — {finding['reference']}"
            )
            lines.append("")
            lines.append(f"- {finding['evidence']}")
            lines.append("")
    else:
        lines.extend(
            [
                "## Findings",
                "",
                "No retraction, concern, correction or resolution problem was found "
                "in the records that were checked. That is not a statement that the "
                "sources support their claims.",
                "",
            ]
        )

    lines.extend(["## Lookup detail", ""])
    for index, ref in enumerate(review["refs"], 1):
        parts = []
        for source in ("crossref", "esearch", "pubmed"):
            lookup = (ref.get("lookups") or {}).get(source)
            if not lookup:
                continue
            status = lookup.get("http_status")
            where = f"HTTP {status}" if status else "no status"
            parts.append(f"{source} {where} ({lookup.get('state')})")
            if lookup.get("error"):
                parts.append(f"{source} error: {lookup['error']}")
        lines.append(f"- {index}. {_cell(ref.get('reference') or '')} — " + " · ".join(parts))
    for warning in review.get("warnings") or []:
        lines.append(f"- warning: {warning}")
    lines.append("")
    return "\n".join(lines)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = _Parser(
        prog="citation_check.py",
        description="Resolve DOIs/PMIDs and read PubMed's editorial notices.",
    )
    parser.add_argument("--doi", action="append", default=[], metavar="DOI")
    parser.add_argument("--pmid", action="append", default=[], metavar="PMID")
    parser.add_argument("--refs", action="append", default=[], metavar="FILE")
    parser.add_argument("--manuscript", action="append", default=[], metavar="FILE")
    parser.add_argument("--out", default=DEFAULT_OUT, metavar="MARKDOWN")
    parser.add_argument("--no-md", action="store_true")
    parser.add_argument("--cache", default=DEFAULT_CACHE, metavar="FILE")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--refresh", action="store_true")
    parser.add_argument("--max-age-days", type=float, default=7.0, metavar="N")
    parser.add_argument("--max-refs", type=int, default=200, metavar="N")
    parser.add_argument("--mailto", default=os.environ.get("CROSSREF_MAILTO", ""))
    parser.add_argument("--timeout", type=float, default=15.0, metavar="SECONDS")
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args(list(argv))
    if args.max_refs < 1:
        raise UsageError("--max-refs must be at least 1")
    if args.max_age_days < 0:
        raise UsageError("--max-age-days cannot be negative")
    if args.timeout <= 0:
        raise UsageError("--timeout must be positive")
    return args


def run(args: argparse.Namespace) -> tuple[dict, str | None]:
    refs, warnings = collect_refs(args)
    if not refs:
        raise GateError(
            "no references given: use --doi, --pmid, --refs or --manuscript"
        )
    if len(refs) > args.max_refs:
        raise GateError(
            f"{len(refs)} references exceed --max-refs {args.max_refs}; raise the "
            "limit or split the run"
        )
    out_path = None if args.no_md else Path(args.out)
    if out_path is not None:
        resolved_out = out_path.resolve()
        for name in [*args.refs, *args.manuscript]:
            if Path(name).resolve() == resolved_out:
                raise GateError(f"--out would overwrite the input {name}")
        if Path(args.cache).resolve() == resolved_out:
            raise GateError("--out and --cache must be different files")

    cache = Cache(Path(args.cache), max_age_days=args.max_age_days)
    if cache.load_error:
        warnings.append(cache.load_error)
    http = Http(
        timeout=args.timeout,
        mailto=args.mailto.strip(),
        api_key=os.environ.get("NCBI_API_KEY", "").strip(),
    )
    checker = Checker(
        http, cache, offline=args.offline, refresh=args.refresh
    )
    results: list[RefResult] = []
    for index, ref in enumerate(refs, 1):
        if not args.quiet:
            print(f"[{index}/{len(refs)}] {ref.key}", file=sys.stderr)
        results.append(checker.check(ref))
    results = merge_results(results)
    cache_error = cache.save()
    if cache_error:
        warnings.append(cache_error)

    findings = sorted(
        (finding for result in results for finding in result.findings),
        key=lambda finding: ({"error": 0, "warn": 1, "info": 2}[finding.level], finding.reference),
    )
    review = {
        "gate": "citation-check",
        "version": 1,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "offline": bool(args.offline),
        "network": {
            "ncbi_key": bool(http.api_key),
            "polite_mailto": bool(http.mailto),
        },
        "refs": [result.to_json() for result in results],
        "findings": [finding.to_json() for finding in findings],
        "summary": summarize(results),
        "warnings": warnings,
        "note": note(results, args.offline, warnings),
    }
    markdown = render_markdown(review) if out_path is not None else None
    return review, markdown


def main(argv: Sequence[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")  # type: ignore[attr-defined]
        sys.stderr.reconfigure(errors="replace")  # type: ignore[attr-defined]
    except (AttributeError, ValueError):
        pass
    try:
        args = parse_args(argv)
    except UsageError as exc:
        print(f"citation_check.py: {exc}", file=sys.stderr)
        return 2
    except SystemExit as exc:  # --help
        return int(exc.code or 0)
    try:
        review, markdown = run(args)
    except GateError as exc:
        print(f"citation_check.py: {exc}", file=sys.stderr)
        return 2
    print("```review")
    print(json.dumps(review, ensure_ascii=False, indent=1))
    print("```")
    if markdown is not None:
        out = Path(args.out)
        try:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(markdown, encoding="utf-8")
        except OSError as exc:
            print(f"citation_check.py: could not write {out}: {exc}", file=sys.stderr)
            return 2
        if not args.quiet:
            print(f"wrote {out}", file=sys.stderr)
    if args.strict:
        failures = [f for f in review["findings"] if f["level"] == "error"]
        if failures:
            for finding in failures:
                print(
                    f"strict: {finding['reference']}: {finding['title']}",
                    file=sys.stderr,
                )
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))