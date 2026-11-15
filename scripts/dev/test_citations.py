#!/usr/bin/env python3
"""Tests for the citation gate (runtime/skills/core/citation-reviewer).

Run: python scripts/dev/test_citations.py

Stdlib unittest, no network: every Crossref/PubMed response is the recorded
shape (trimmed) or a synthetic edge case, injected through a fake opener. Live
lookups run only with CITATIONS_LIVE=1.

The Wakefield record (PMID 9500320) is the anchor: PubMed carries both
``Retracted Publication`` and ``RetractionIn`` for it, which is why the gate
treats PubMed as authoritative for editorial notices and reports a DOI that has
no PMID as ``retraction-unknown`` rather than clean.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True  # never leave __pycache__ in the shipped skill dir

_ROOT = Path(__file__).resolve().parents[2]
_MOD = _ROOT / "runtime/skills/core/citation-reviewer/citation_check.py"
_spec = importlib.util.spec_from_file_location("citation_check", _MOD)
assert _spec and _spec.loader
cit = importlib.util.module_from_spec(_spec)
sys.modules["citation_check"] = cit
_spec.loader.exec_module(cit)

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
WAKEFIELD_DOI = "10.1016/S0140-6736(97)11096-0"
NORMAL_DOI = "10.1056/NEJMoa2034577"


def response(body: str, status: int = 200, headers: dict | None = None) -> cit.HttpResponse:
    return cit.HttpResponse(status, body.encode("utf-8"), headers or {})


CROSSREF_WAKEFIELD = json.dumps(
    {
        "status": "ok",
        "message": {
            "DOI": WAKEFIELD_DOI,
            "title": [
                "RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific "
                "colitis, and pervasive developmental disorder in children"
            ],
            "container-title": ["The Lancet"],
            "issued": {"date-parts": [[1998, 2, 28]]},
            "type": "journal-article",
            "updated-by": [
                {"type": "retraction", "DOI": "10.1016/S0140-6736(10)60175-4"},
                {"type": "correction", "DOI": "10.1016/S0140-6736(04)15715-2"},
            ],
        },
    }
)

CROSSREF_NORMAL = json.dumps(
    {
        "status": "ok",
        "message": {
            "DOI": NORMAL_DOI,
            "title": ["Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine"],
            "container-title": ["New England Journal of Medicine"],
            "issued": {"date-parts": [[2020, 12, 31]]},
            "type": "journal-article",
        },
    }
)

CROSSREF_NOTICE = json.dumps(
    {
        "status": "ok",
        "message": {
            "DOI": "10.1016/S0140-6736(10)60175-4",
            "title": ["Retraction—Ileal-lymphoid-nodular hyperplasia, non-specific "
                      "colitis, and pervasive developmental disorder in children"],
            "container-title": ["The Lancet"],
            "issued": {"date-parts": [[2010, 2, 6]]},
            "type": "journal-article",
            "update-to": [{"type": "retraction", "DOI": WAKEFIELD_DOI}],
        },
    }
)

PUBMED_WAKEFIELD = """<?xml version="1.0" ?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation>
   <PMID>9500320</PMID>
   <Article>
    <ArticleTitle>RETRACTED: Ileal-lymphoid-nodular hyperplasia, non-specific
     colitis, and pervasive developmental disorder in children</ArticleTitle>
    <Journal><Title>The Lancet</Title>
     <JournalIssue><PubDate><Year>1998</Year><Month>Feb</Month></PubDate></JournalIssue>
    </Journal>
    <PublicationTypeList>
     <PublicationType>Retracted Publication</PublicationType>
     <PublicationType>Journal Article</PublicationType>
    </PublicationTypeList>
   </Article>
   <CommentsCorrectionsList>
    <CommentsCorrections RefType="RetractionIn">
     <RefSource>Lancet. 2004 Mar 6;363(9411):750.</RefSource>
    </CommentsCorrections>
    <CommentsCorrections RefType="RetractionIn">
     <RefSource>Lancet. 2010 Feb 6;375(9713):445.</RefSource>
    </CommentsCorrections>
    <CommentsCorrections RefType="ExpressionOfConcernIn">
     <RefSource>Eur J Gastroenterol Hepatol. 2011 Nov;23(11):1082.</RefSource>
    </CommentsCorrections>
   </CommentsCorrectionsList>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
   <ArticleId IdType="doi">10.1016/S0140-6736(97)11096-0</ArticleId>
   <ArticleId IdType="pubmed">9500320</ArticleId>
  </ArticleIdList></PubmedData>
 </PubmedArticle>
</PubmedArticleSet>
"""

PUBMED_NORMAL = """<?xml version="1.0" ?>
<PubmedArticleSet>
 <PubmedArticle>
  <MedlineCitation>
   <PMID>33301246</PMID>
   <Article>
    <ArticleTitle>Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine</ArticleTitle>
    <Journal><Title>The New England journal of medicine</Title>
     <JournalIssue><PubDate><Year>2020</Year><Month>Dec</Month></PubDate></JournalIssue>
    </Journal>
    <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
   </Article>
  </MedlineCitation>
  <PubmedData><ArticleIdList>
   <ArticleId IdType="doi">10.1056/NEJMoa2034577</ArticleId>
  </ArticleIdList></PubmedData>
 </PubmedArticle>
</PubmedArticleSet>
"""

PUBMED_ERRATUM = """<?xml version="1.0" ?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
 <PMID>11111111</PMID>
 <Article>
  <ArticleTitle>A trial with a correction</ArticleTitle>
  <Journal><Title>BMJ</Title>
   <JournalIssue><PubDate><Year>2020</Year></PubDate></JournalIssue></Journal>
  <PublicationTypeList><PublicationType>Journal Article</PublicationType></PublicationTypeList>
 </Article>
 <CommentsCorrectionsList>
  <CommentsCorrections RefType="ErratumIn"><RefSource>BMJ. 2021;372:n1.</RefSource></CommentsCorrections>
 </CommentsCorrectionsList>
</MedlineCitation></PubmedArticle></PubmedArticleSet>
"""

PUBMED_NOTICE = """<?xml version="1.0" ?>
<PubmedArticleSet><PubmedArticle><MedlineCitation>
 <PMID>22222222</PMID>
 <Article>
  <ArticleTitle>Retraction: a trial</ArticleTitle>
  <Journal><Title>BMJ</Title>
   <JournalIssue><PubDate><Year>2021</Year></PubDate></JournalIssue></Journal>
  <PublicationTypeList><PublicationType>Retraction of Publication</PublicationType></PublicationTypeList>
 </Article>
 <CommentsCorrectionsList>
  <CommentsCorrections RefType="RetractionOf"><RefSource>BMJ. 2020;370:m1.</RefSource></CommentsCorrections>
 </CommentsCorrectionsList>
</MedlineCitation></PubmedArticle></PubmedArticleSet>
"""

ESEARCH_FOUND = json.dumps({"esearchresult": {"count": "1", "idlist": ["9500320"]}})
ESEARCH_NORMAL = json.dumps({"esearchresult": {"count": "1", "idlist": ["33301246"]}})
ESEARCH_EMPTY = json.dumps({"esearchresult": {"count": "0", "idlist": []}})
ESEARCH_OTHER = json.dumps({"esearchresult": {"count": "1", "idlist": ["99999999"]}})


class FakeHttp:
    """Duck-typed Http: substring routes, ordered, with an optional call limit."""

    def __init__(self, routes, api_key: str = "", mailto: str = ""):
        self.routes = list(routes)
        self.api_key = api_key
        self.mailto = mailto
        self.calls: list[str] = []

    def get(self, url, headers=None):
        self.calls.append(url)
        for marker, outcome in self.routes:
            if marker in url:
                if isinstance(outcome, Exception):
                    raise outcome
                return outcome
        raise AssertionError(f"unexpected URL in test: {url}")


def make_checker(
    tmp: str,
    routes,
    *,
    offline: bool = False,
    refresh: bool = False,
    cache_age_days: float = 7.0,
    cache: cit.Cache | None = None,
) -> tuple[cit.Checker, FakeHttp, cit.Cache]:
    fake = FakeHttp(routes)
    cache = cache or cit.Cache(
        Path(tmp) / "cache.json", max_age_days=cache_age_days, now=lambda: NOW
    )
    return cit.Checker(fake, cache, offline=offline, refresh=refresh, now=lambda: NOW), fake, cache


def run_main(argv: list[str]) -> tuple[int, str, str]:
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cit.main(argv)
    return code, out.getvalue(), err.getvalue()


def review_of(stdout: str) -> dict:
    return json.loads(stdout.split("```review")[1].split("```")[0])


class Identifiers(unittest.TestCase):
    def test_doi_from_url_label_and_trailing_punctuation(self):
        self.assertEqual(cit.clean_doi("https://doi.org/10.1000/abc"), "10.1000/abc")
        self.assertEqual(cit.clean_doi("doi: 10.1000/abc."), "10.1000/abc")
        self.assertEqual(cit.clean_doi(" 10.1000/abc; "), "10.1000/abc")

    def test_markdown_link_closing_paren_is_not_part_of_the_doi(self):
        self.assertEqual(cit.clean_doi("10.1000/abc)"), "10.1000/abc")
        # A balanced pair is part of the DOI (the Wakefield DOI has one).
        self.assertEqual(
            cit.clean_doi("10.1016/S0140-6736(97)11096-0"),
            "10.1016/S0140-6736(97)11096-0",
        )

    def test_doi_validation(self):
        self.assertTrue(cit.valid_doi("10.1000/abc"))
        self.assertFalse(cit.valid_doi("11.1000/abc"))
        self.assertFalse(cit.valid_doi("10.1000"))
        self.assertFalse(cit.valid_doi("nonsense"))

    def test_pmid_label_and_bare_digits(self):
        self.assertEqual(cit.clean_pmid("PMID: 9500320"), "9500320")
        self.assertEqual(cit.clean_pmid("9500320"), "9500320")
        self.assertEqual(cit.clean_pmid("PMID 123"), "123")
        self.assertEqual(cit.clean_pmid("no number"), "")

    def test_doi_keys_are_case_insensitive(self):
        self.assertEqual(cit.norm_doi("10.1016/S0140-6736(97)11096-0"),
                         cit.norm_doi("10.1016/s0140-6736(97)11096-0"))


class ManuscriptScan(unittest.TestCase):
    def scan(self, text: str, *, encoding: str = "utf-8") -> tuple[list[cit.Ref], list[str]]:
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "draft.md"
        path.write_text(text, encoding=encoding)
        return cit.refs_from_text(path)

    def test_doi_and_pmid_on_the_same_line_are_not_forced_into_one_pair(self):
        # Prose can cite two papers in one line: a DOI and a PMID are separate
        # inputs; they merge only after both resolve to the same record.
        refs, notes = self.scan(
            "# Results\nOur earlier trial (doi: 10.1000/abc) and the 2020 study "
            "(PMID: 12345678) found X.\n"
        )
        self.assertEqual(notes, [])
        self.assertEqual(len(refs), 2)
        self.assertEqual(refs[0].doi, "10.1000/abc")
        self.assertEqual(refs[1].pmid, "12345678")
        self.assertIn("§Results", refs[0].origin)
        self.assertIn(":2", refs[0].origin)

    def test_pmid_label_alone_is_a_reference(self):
        refs, _ = self.scan("As shown before (PubMed: 9500320), the claim is contested.\n")
        self.assertEqual([ref.pmid for ref in refs], ["9500320"])

    def test_years_are_not_mistaken_for_pmids(self):
        refs, _ = self.scan("The 2020 cohort (published 2021) was analysed.\n")
        self.assertEqual(refs, [])

    def test_duplicate_doi_keeps_the_first_place(self):
        refs, _ = self.scan(
            "First mention: 10.1000/abc.\n"
            "Later: 10.1000/abc and PMID: 55555555.\n"
        )
        refs = cit.merge_refs(refs)
        self.assertEqual([(ref.doi, ref.pmid) for ref in refs],
                         [("10.1000/abc", ""), ("", "55555555")])
        self.assertIn(":1", refs[0].origin)

    def test_several_identifiers_on_one_line_stay_separate(self):
        refs, notes = self.scan("See 10.1000/a and 10.1000/b, PMID: 77777777.\n")
        self.assertEqual([ref.doi for ref in refs[:2]], ["10.1000/a", "10.1000/b"])
        self.assertEqual(refs[2].pmid, "77777777")
        self.assertEqual(notes, [])

    def test_doi_in_a_markdown_link(self):
        refs, _ = self.scan("See [the trial](https://doi.org/10.1000/abc).\n")
        self.assertEqual([ref.doi for ref in refs], ["10.1000/abc"])

    def test_utf16_and_gbk_manuscripts_are_read(self):
        for encoding in ("utf-16", "gbk"):
            refs, _ = self.scan("见 10.1000/abc。\n", encoding=encoding)
            self.assertEqual([ref.doi for ref in refs], ["10.1000/abc"], encoding)


class RefFiles(unittest.TestCase):
    def test_json_list_and_object_wrapper(self):
        tmp = tempfile.mkdtemp()
        for payload in (
            [{"doi": WAKEFIELD_DOI, "pmid": "9500320", "label": "Wakefield 1998"}],
            {"references": [{"doi": WAKEFIELD_DOI, "label": "Wakefield 1998"}]},
        ):
            path = Path(tmp) / "refs.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            refs = cit.refs_from_json(path)
            self.assertEqual(refs[0].doi, WAKEFIELD_DOI)
            self.assertEqual(refs[0].label, "Wakefield 1998")

    def test_json_reference_needs_an_identifier(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "refs.json"
        path.write_text('[{"label": "no id"}]', encoding="utf-8")
        with self.assertRaises(cit.GateError):
            cit.refs_from_json(path)

    def test_json_rejects_an_invalid_doi(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "refs.json"
        path.write_text('[{"doi": "not-a-doi"}]', encoding="utf-8")
        with self.assertRaises(cit.GateError):
            cit.refs_from_json(path)

    def test_txt_accepts_doi_pmid_labels_and_comments(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "refs.txt"
        path.write_text(
            "# a comment\n10.1000/abc\nPMID: 9500320\n12345678\n", encoding="utf-8"
        )
        refs = cit.refs_from_txt(path)
        self.assertEqual(len(refs), 3)
        self.assertEqual(refs[0].doi, "10.1000/abc")
        self.assertEqual(refs[1].pmid, "9500320")
        self.assertEqual(refs[2].pmid, "12345678")

    def test_txt_rejects_a_line_that_is_neither(self):
        tmp = tempfile.mkdtemp()
        path = Path(tmp) / "refs.txt"
        path.write_text("Smith 2020, a good paper\n", encoding="utf-8")
        with self.assertRaises(cit.GateError):
            cit.refs_from_txt(path)


class CrossrefParsing(unittest.TestCase):
    def test_metadata_and_updated_by(self):
        record = cit.normalize_crossref(json.loads(CROSSREF_WAKEFIELD))
        self.assertEqual(record["doi"], WAKEFIELD_DOI)
        self.assertIn("Ileal-lymphoid-nodular", record["title"])
        self.assertEqual(record["journal"], "The Lancet")
        self.assertEqual(record["year"], "1998")
        flags = cit.crossref_flags(record)
        self.assertIn("retracted", {flag["kind"] for flag in flags})
        self.assertIn("corrected", {flag["kind"] for flag in flags})

    def test_update_to_is_a_notice_not_a_retraction_of_this_record(self):
        # Direction matters: `update-to` means this record updates the other one.
        record = cit.normalize_crossref(json.loads(CROSSREF_NOTICE))
        flags = cit.crossref_flags(record)
        self.assertEqual({flag["kind"] for flag in flags}, {"notice"})

    def test_unexpected_payload_is_a_network_error(self):
        with self.assertRaises(cit.NetworkError):
            cit.normalize_crossref({"status": "ok"})


class PubMedParsing(unittest.TestCase):
    def test_wakefield_record_carries_the_retraction(self):
        record = cit.normalize_pubmed(PUBMED_WAKEFIELD.encode("utf-8"))
        self.assertEqual(record["pmid"], "9500320")
        self.assertEqual(record["doi"], WAKEFIELD_DOI)
        self.assertEqual(record["journal"], "The Lancet")
        self.assertEqual(record["year"], "1998")
        self.assertNotIn("<i>", record["title"])
        flags = cit.pubmed_flags(record)
        kinds = [flag["kind"] for flag in flags]
        self.assertGreaterEqual(kinds.count("retracted"), 2)
        self.assertIn("concern", kinds)

    def test_erratum_is_a_correction_and_a_retraction_notice_is_a_notice(self):
        erratum = cit.normalize_pubmed(PUBMED_ERRATUM.encode("utf-8"))
        self.assertEqual({flag["kind"] for flag in cit.pubmed_flags(erratum)}, {"corrected"})
        notice = cit.normalize_pubmed(PUBMED_NOTICE.encode("utf-8"))
        self.assertEqual({flag["kind"] for flag in cit.pubmed_flags(notice)}, {"notice"})

    def test_medline_date_fallback_and_empty_doi(self):
        xml = PUBMED_NORMAL.replace(
            "<PubDate><Year>2020</Year><Month>Dec</Month></PubDate>",
            "<PubDate><MedlineDate>2020 Dec 15</MedlineDate></PubDate>",
        ).replace(
            '<ArticleId IdType="doi">10.1056/NEJMoa2034577</ArticleId>',
            '<ArticleId IdType="pmc">PMC777</ArticleId>',
        )
        record = cit.normalize_pubmed(xml.encode("utf-8"))
        self.assertEqual(record["year"], "2020")
        self.assertEqual(record["doi"], "")

    def test_error_payload_and_missing_article_fail_loudly(self):
        with self.assertRaises(cit.NetworkError):
            cit.normalize_pubmed(b"<eFetchResult><ERROR>Invalid id</ERROR></eFetchResult>")
        with self.assertRaises(cit.NetworkError):
            cit.normalize_pubmed(b"<PubmedArticleSet></PubmedArticleSet>")
        with self.assertRaises(cit.NetworkError):
            cit.normalize_pubmed(b"not xml")


class StatusRules(unittest.TestCase):
    def check(self, tmp, routes, **kwargs):
        checker, _, _ = make_checker(tmp, routes, **kwargs)
        return checker.check(cit.Ref(doi=WAKEFIELD_DOI))

    def test_retracted_beats_concern_and_correction(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.check(
                tmp,
                [
                    ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                    ("esearch.fcgi", response(ESEARCH_FOUND)),
                    ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
                ],
            )
            self.assertEqual(result.status, "retracted")
            self.assertEqual(len(result.findings), 1)
            self.assertEqual(result.findings[0].level, "error")
            self.assertIn("Retracted Publication", result.findings[0].evidence)

    def test_doi_without_pmid_is_unknown_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.check(
                tmp,
                [
                    ("api.crossref.org", response(CROSSREF_NORMAL)),
                    ("esearch.fcgi", response(ESEARCH_EMPTY)),
                ],
            )
            self.assertEqual(result.status, "retraction-unknown")
            self.assertEqual(result.findings[0].level, "warn")
            self.assertIn("not", result.findings[0].evidence.lower())

    def test_crossref_404_and_no_pmid_is_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.check(
                tmp,
                [
                    ("api.crossref.org", response("{}", 404)),
                    ("esearch.fcgi", response(ESEARCH_EMPTY)),
                ],
            )
            self.assertEqual(result.status, "unresolved")
            self.assertEqual(result.findings[0].level, "error")

    def test_transport_failure_is_lookup_failed_not_unresolved(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = self.check(
                tmp,
                [
                    ("api.crossref.org", cit.NetworkError("timed out")),
                    ("esearch.fcgi", cit.NetworkError("timed out")),
                ],
            )
            self.assertEqual(result.status, "lookup-failed")
            self.assertIn("timed out", result.findings[0].evidence)

    def test_dead_doi_with_a_live_pmid_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", response("{}", 404)),
                    ("esearch.fcgi", response(ESEARCH_FOUND)),
                    ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
                ],
            )
            result = checker.check(cit.Ref(doi=WAKEFIELD_DOI, pmid="9500320"))
            self.assertEqual(result.status, "retracted")
            dead = [f for f in result.findings if f.tag == "citation · unresolved"]
            self.assertEqual(len(dead), 1)
            self.assertEqual(dead[0].level, "error")

    def test_crossref_outage_with_pubmed_ok_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", cit.NetworkError("HTTP 503")),
                    ("esearch.fcgi", response(ESEARCH_FOUND)),
                    ("efetch.fcgi", response(PUBMED_NORMAL)),
                ],
            )
            result = checker.check(cit.Ref(doi=NORMAL_DOI, pmid="33301246"))
            self.assertEqual(result.status, "ok")
            warnings = [f for f in result.findings if f.level == "warn"]
            self.assertEqual(len(warnings), 1)
            self.assertIn("Crossref", warnings[0].title)

    def test_doi_and_pmid_conflict_when_esearch_returns_another_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                    ("esearch.fcgi", response(ESEARCH_OTHER)),
                    ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
                ],
            )
            result = checker.check(cit.Ref(doi=WAKEFIELD_DOI, pmid="9500320"))
            conflicts = [f for f in result.findings if f.tag == "citation · conflict"]
            self.assertEqual(len(conflicts), 1)
            self.assertEqual(conflicts[0].level, "error")

    def test_pubmed_doi_for_the_pmid_must_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            other = PUBMED_WAKEFIELD.replace(
                '<ArticleId IdType="doi">10.1016/S0140-6736(97)11096-0</ArticleId>',
                '<ArticleId IdType="doi">10.1016/S0140-6736(97)99999-9</ArticleId>',
            )
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                    ("esearch.fcgi", response(ESEARCH_FOUND)),
                    ("efetch.fcgi", response(other)),
                ],
            )
            result = checker.check(cit.Ref(doi=WAKEFIELD_DOI, pmid="9500320"))
            conflicts = [f for f in result.findings if f.tag == "citation · conflict"]
            self.assertEqual(len(conflicts), 1)

    def test_metadata_disagreement_is_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            changed = CROSSREF_NORMAL.replace(
                "Safety and Efficacy of the BNT162b2 mRNA Covid-19 Vaccine",
                "An entirely different paper about something else",
            ).replace("2020", "2015")
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", response(changed)),
                    ("esearch.fcgi", response(ESEARCH_FOUND)),
                    ("efetch.fcgi", response(PUBMED_NORMAL)),
                ],
            )
            result = checker.check(cit.Ref(doi=NORMAL_DOI, pmid="33301246"))
            metadata = [f for f in result.findings if f.tag == "citation · metadata"]
            fields = {f.title.rsplit(" ", 1)[-1].rstrip(".") for f in metadata}
            self.assertIn("title", fields)
            self.assertIn("year", fields)

    def test_lancet_abbreviation_is_not_a_conflict(self):
        self.assertTrue(cit._journal_similar("The Lancet", "Lancet"))
        self.assertTrue(
            cit._journal_similar(
                "The New England journal of medicine", "New England Journal of Medicine"
            )
        )

    def test_notice_status_for_a_retraction_notice(self):
        with tempfile.TemporaryDirectory() as tmp:
            checker, _, _ = make_checker(
                tmp,
                [
                    ("api.crossref.org", response(CROSSREF_NOTICE)),
                    ("esearch.fcgi", response(json.dumps(
                        {"esearchresult": {"count": "1", "idlist": ["22222222"]}}))),
                    ("efetch.fcgi", response(PUBMED_NOTICE)),
                ],
            )
            result = checker.check(
                cit.Ref(doi="10.1016/S0140-6736(10)60175-4")
            )
            self.assertEqual(result.status, "notice")
            self.assertTrue(any("notice" in finding.tag for finding in result.findings))


class CacheRules(unittest.TestCase):
    def test_second_run_uses_the_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = cit.Cache(Path(tmp) / "cache.json", now=lambda: NOW)
            routes = [
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_NORMAL)),
            ]
            checker, fake, _ = make_checker(tmp, routes, cache=cache)
            first = checker.check(cit.Ref(doi=NORMAL_DOI))
            self.assertEqual(first.status, "ok")
            calls = len(fake.calls)
            cache.save()
            again, fake2, _ = make_checker(tmp, routes, cache=cit.Cache(
                Path(tmp) / "cache.json", now=lambda: NOW))
            second = again.check(cit.Ref(doi=NORMAL_DOI))
            self.assertEqual(second.status, "ok")
            self.assertEqual(len(fake2.calls), 0)
            self.assertGreater(calls, 0)

    def test_stale_cache_is_refetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text(json.dumps({
                "version": 1,
                "entries": {
                    "crossref/v1/doi:" + NORMAL_DOI.lower(): {
                        "fetched_at": (NOW - timedelta(days=9)).isoformat(),
                        "source": "crossref",
                        "http_status": 200,
                        "record": cit.normalize_crossref(json.loads(CROSSREF_NORMAL)),
                    }
                },
            }), encoding="utf-8")
            cache = cit.Cache(path, max_age_days=7, now=lambda: NOW)
            self.assertFalse(cache.is_fresh("crossref/v1/doi:" + NORMAL_DOI.lower()))
            checker, fake, _ = make_checker(tmp, [
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_EMPTY)),
            ], cache=cache)
            checker.check(cit.Ref(doi=NORMAL_DOI))
            self.assertTrue(any("api.crossref.org" in call for call in fake.calls))

    def test_refresh_ignores_a_fresh_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = cit.Cache(Path(tmp) / "cache.json", now=lambda: NOW)
            routes = [
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_EMPTY)),
            ]
            checker, _, _ = make_checker(tmp, routes, cache=cache)
            checker.check(cit.Ref(doi=NORMAL_DOI))
            again, fake, _ = make_checker(tmp, routes, cache=cache, refresh=True)
            again.check(cit.Ref(doi=NORMAL_DOI))
            self.assertTrue(any("api.crossref.org" in call for call in fake.calls))

    def test_offline_never_opens_a_socket(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = cit.Cache(Path(tmp) / "cache.json", now=lambda: NOW)
            routes = [
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_NORMAL)),
            ]
            checker, _, _ = make_checker(tmp, routes, cache=cache)
            checker.check(cit.Ref(doi=NORMAL_DOI))
            cache.save()
            offline, fake, _ = make_checker(tmp, [], offline=True, cache=cache)
            result = offline.check(cit.Ref(doi=NORMAL_DOI))
            self.assertEqual(result.status, "ok")
            self.assertEqual(fake.calls, [])

    def test_offline_miss_is_reported_not_silently_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            offline, fake, _ = make_checker(tmp, [], offline=True)
            result = offline.check(cit.Ref(doi=NORMAL_DOI))
            self.assertEqual(result.status, "offline-miss")
            self.assertEqual(fake.calls, [])
            self.assertEqual(result.findings[0].level, "error")

    def test_corrupt_cache_is_ignored_with_a_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            path.write_text("{not json", encoding="utf-8")
            cache = cit.Cache(path, now=lambda: NOW)
            self.assertIn("not valid JSON", cache.load_error)
            checker, _, _ = make_checker(tmp, [
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_EMPTY)),
            ], cache=cache)
            self.assertEqual(checker.check(cit.Ref(doi=NORMAL_DOI)).status,
                             "retraction-unknown")
            self.assertIsNone(cache.save())
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["version"], 1)

    def test_cache_is_replaced_atomically_and_holds_no_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = cit.Cache(path, now=lambda: NOW)
            cache.put("crossref/v1/doi:10.1000/abc", record={"title": "x"},
                      source="crossref", http_status=200)
            self.assertIsNone(cache.save())
            self.assertFalse((path.parent / "cache.json.tmp").exists())
            body = path.read_text(encoding="utf-8")
            self.assertEqual(json.loads(body)["version"], 1)
            self.assertNotIn("@", body)

    def test_empty_cache_is_not_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cache.json"
            cache = cit.Cache(path, now=lambda: NOW)
            self.assertIsNone(cache.save())
            self.assertFalse(path.exists())


class HttpRules(unittest.TestCase):
    def test_429_is_retried_with_retry_after(self):
        sleeps: list[float] = []
        responses = [response("", 429, {"Retry-After": "2"}), response("ok")]
        http = cit.Http(
            sleep=sleeps.append,
            clock=lambda: 0.0,
            opener=lambda url, headers: responses.pop(0),
        )
        result = http.get("https://api.crossref.org/works/10.1000/abc")
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b"ok")
        self.assertEqual(sleeps, [2.0])

    def test_404_is_not_retried(self):
        calls = []

        def opener(url, headers):
            calls.append(url)
            return response("", 404)

        http = cit.Http(sleep=lambda _: None, clock=lambda: 0.0, opener=opener)
        self.assertEqual(http.get("https://api.crossref.org/works/x").status, 404)
        self.assertEqual(len(calls), 1)

    def test_pacing_prefers_the_key_and_the_polite_pool(self):
        anonymous = cit.Http(sleep=lambda _: None, clock=lambda: 0.0)
        keyed = cit.Http(api_key="k", sleep=lambda _: None, clock=lambda: 0.0)
        polite = cit.Http(mailto="a@b.c", sleep=lambda _: None, clock=lambda: 0.0)
        ncbi = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
        crossref = "https://api.crossref.org/works/x"
        self.assertGreater(anonymous._interval(ncbi), keyed._interval(ncbi))
        self.assertGreater(anonymous._interval(crossref), polite._interval(crossref))


class EndToEnd(unittest.TestCase):
    def fake_factory(self, fake):
        return lambda **kwargs: fake

    def test_cli_writes_markdown_and_prints_one_review_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeHttp([
                ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
            ])
            out = Path(tmp) / "review.md"
            argv = [
                "--doi", WAKEFIELD_DOI,
                "--cache", str(Path(tmp) / "cache.json"),
                "--out", str(out), "--quiet",
            ]
            with mock.patch.object(cit, "Http", self.fake_factory(fake)):
                code, stdout, stderr = run_main(argv)
            self.assertEqual(code, 0)
            review = review_of(stdout)
            self.assertEqual(review["gate"], "citation-check")
            self.assertEqual(review["refs"][0]["status"], "retracted")
            self.assertIn("not", review["note"].lower())
            body = out.read_text(encoding="utf-8")
            self.assertIn("# Citation check", body)
            self.assertIn("retracted", body)
            self.assertIn("does not judge whether a source supports", body)
            self.assertNotIn("SECRET", body)

    def test_doi_and_pmid_for_one_paper_are_one_reference(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeHttp([
                ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
            ])
            argv = [
                "--doi", WAKEFIELD_DOI, "--pmid", "9500320",
                "--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet",
            ]
            with mock.patch.object(cit, "Http", self.fake_factory(fake)):
                code, stdout, _ = run_main(argv)
            self.assertEqual(code, 0)
            review = review_of(stdout)
            self.assertEqual(review["summary"]["references"], 1)
            self.assertEqual(review["refs"][0]["pmid"], "9500320")

    def test_manuscript_pair_merges_only_after_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            draft = Path(tmp) / "draft.md"
            draft.write_text(
                "The 1998 paper (doi: 10.1016/S0140-6736(97)11096-0, "
                "PMID: 9500320) was retracted.\n",
                encoding="utf-8",
            )
            fake = FakeHttp([
                ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
            ])
            argv = [
                "--manuscript", str(draft),
                "--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet",
            ]
            with mock.patch.object(cit, "Http", self.fake_factory(fake)):
                code, stdout, _ = run_main(argv)
            self.assertEqual(code, 0)
            review = review_of(stdout)
            self.assertEqual(review["summary"]["references"], 1)
            self.assertEqual(review["refs"][0]["status"], "retracted")
            self.assertEqual(review["refs"][0]["pmid"], "9500320")

    def test_strict_exits_1_on_a_retraction_and_0_when_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            retracted = FakeHttp([
                ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
            ])
            clean = FakeHttp([
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_NORMAL)),
                ("efetch.fcgi", response(PUBMED_NORMAL)),
            ])
            base = ["--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet", "--strict"]
            with mock.patch.object(cit, "Http", self.fake_factory(retracted)):
                code, _, err = run_main(["--doi", WAKEFIELD_DOI, *base])
            self.assertEqual(code, 1)
            self.assertIn("strict:", err)
            with mock.patch.object(cit, "Http", self.fake_factory(clean)):
                code, _, _ = run_main(["--doi", NORMAL_DOI, *base])
            self.assertEqual(code, 0)

    def test_no_references_and_usage_errors_exit_2(self):
        self.assertEqual(run_main(["--no-md"])[0], 2)
        self.assertEqual(run_main(["--doi", "10.1000/a", "--max-refs", "0"])[0], 2)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "refs.txt"
            path.write_text("10.1000/a\n", encoding="utf-8")
            code, _, _ = run_main([
                "--refs", str(path), "--out", str(path),
                "--cache", str(Path(tmp) / "cache.json"),
            ])
            self.assertEqual(code, 2)

    def test_max_refs_is_enforced(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main([
                "--doi", "10.1000/a", "--doi", "10.1000/b", "--max-refs", "1",
                "--cache", str(Path(tmp) / "cache.json"), "--no-md",
            ])
            self.assertEqual(code, 2)
            self.assertIn("max-refs", err)

    def test_the_api_key_never_reaches_the_review_or_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeHttp([
                ("api.crossref.org", response(CROSSREF_NORMAL)),
                ("esearch.fcgi", response(ESEARCH_EMPTY)),
            ], api_key="SECRET-NCBI-KEY")
            out = Path(tmp) / "review.md"
            argv = [
                "--doi", NORMAL_DOI,
                "--cache", str(Path(tmp) / "cache.json"),
                "--out", str(out), "--quiet",
            ]
            with mock.patch.dict(os.environ, {"NCBI_API_KEY": "SECRET-NCBI-KEY"}), \
                    mock.patch.object(cit, "Http", self.fake_factory(fake)):
                code, stdout, _ = run_main(argv)
            self.assertEqual(code, 0)
            self.assertNotIn("SECRET-NCBI-KEY", stdout)
            self.assertNotIn("SECRET-NCBI-KEY", out.read_text(encoding="utf-8"))
            self.assertTrue(any("api_key=SECRET-NCBI-KEY" in call for call in fake.calls))

    def test_console_output_survives_gbk(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake = FakeHttp([
                ("api.crossref.org", response(CROSSREF_WAKEFIELD)),
                ("esearch.fcgi", response(ESEARCH_FOUND)),
                ("efetch.fcgi", response(PUBMED_WAKEFIELD)),
            ])
            argv = [
                "--doi", WAKEFIELD_DOI,
                "--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet",
            ]
            with mock.patch.object(cit, "Http", self.fake_factory(fake)):
                code, stdout, _ = run_main(argv)
            self.assertEqual(code, 0)
            stdout.encode("gbk")  # must not raise


@unittest.skipUnless(
    os.environ.get("CITATIONS_LIVE") == "1",
    "live lookups: set CITATIONS_LIVE=1 (hits Crossref and PubMed)",
)
class Live(unittest.TestCase):
    def test_wakefield_is_retracted_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main([
                "--doi", WAKEFIELD_DOI, "--pmid", "9500320",
                "--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet",
            ])
            self.assertEqual(code, 0)
            review = review_of(stdout)
            self.assertEqual(review["refs"][0]["status"], "retracted")

    def test_a_normal_trial_is_ok_live(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, stdout, _ = run_main([
                "--doi", NORMAL_DOI,
                "--cache", str(Path(tmp) / "cache.json"), "--no-md", "--quiet",
            ])
            self.assertEqual(code, 0)
            review = review_of(stdout)
            self.assertEqual(review["refs"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main(verbosity=2)