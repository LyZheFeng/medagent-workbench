#!/usr/bin/env python3
"""Reporting-guideline gate for medical manuscripts — stdlib only.

Reads a report/manuscript (Markdown, plain text, or extracted PDF text) and checks
the reporting-checklist items that a submission cannot pass without: ethics
approval, informed consent, registration numbers, confidence intervals, missing
data, de-identification, participant flow, and the design-specific items of
STROBE, CONSORT, CARE, STARD and PRISMA.

This is a *presence* check, never a quality judgment: it answers "does the text
say anything about missing data?", not "is the missing-data handling right?". The
distinction is the point — a model asked to "check STROBE compliance" invents
findings, while a fixed list of patterns gives the same answer twice.

Every finding names the official checklist item it comes from, with the version
on purpose: STROBE 2007, CONSORT 2025 (and the CONSORT 2010 number in brackets,
because journals still ask for that one), CARE 2013, STARD 2015, PRISMA 2020. The
official wording behind each cited number lives in CHECKLISTS below, transcribed
from the checklist the source URL names, and `--list` prints it, so "which item
is missing" and "what does it ask for" are the same answer.

Output: one ```review fenced JSON block on stdout, the app's reviewer contract
(`level` error|warn|ok, `tag`, `title`, `evidence`, plus a `note`).

Usage:
    python check_report.py report.md                 # detect the design
    python check_report.py --design stard report.md  # force one
    python check_report.py --sections report.md      # items must sit in their section
    python check_report.py --list stard              # print the checklist
    python check_report.py --design consort *.md     # several files
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

# --------------------------------------------------------------------------- #
# Official checklists
#
# Transcribed from the document each `source` names, retrieved 2026-11-15. Only
# the items this gate cites are transcribed; `total` is the number of numbered
# items in the whole checklist, which the tests check, so a truncated list cannot
# pass silently. The text is an excerpt of the official wording, trimmed where a
# sub-item's detail does not change what an author has to write.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Checklist:
    id: str
    design: str
    label: str
    source: str
    total: int
    items: Mapping[str, str]


CHECKLISTS: dict[str, Checklist] = {
    "strobe": Checklist(
        "strobe", "strobe", "STROBE 2007",
        "https://www.strobe-statement.org/checklists/", 22,
        {
            "1a": "Indicate the study's design with a commonly used term in the "
                  "title or the abstract",
            "4": "Present key elements of study design early in the paper",
            "5": "Describe the setting, locations, and relevant dates, including "
                 "periods of recruitment, exposure, follow-up, and data collection",
            "6a": "Give the eligibility criteria, and the sources and methods of "
                  "selection of participants",
            "7": "Clearly define all outcomes, exposures, predictors, potential "
                 "confounders, and effect modifiers. Give diagnostic criteria, if "
                 "applicable",
            "12a": "Describe all statistical methods, including those used to "
                   "control for confounding",
            "12c": "Explain how missing data were addressed",
            "13a": "Report numbers of individuals at each stage of study — eg "
                   "numbers potentially eligible, examined for eligibility, "
                   "confirmed eligible, included in the study, completing "
                   "follow-up, and analysed",
            "16a": "Give unadjusted estimates and, if applicable, "
                   "confounder-adjusted estimates and their precision (eg, 95% "
                   "confidence interval). Make clear which confounders were "
                   "adjusted for and why they were included",
            "19": "Discuss limitations of the study, taking into account sources "
                  "of potential bias or imprecision. Discuss both direction and "
                  "magnitude of any potential bias",
            "22": "Give the source of funding and the role of the funders for the "
                  "present study and, if applicable, for the original study on "
                  "which the present article is based",
        },
    ),
    "consort2025": Checklist(
        "consort2025", "consort", "CONSORT 2025",
        "https://www.consort-spirit.org/ (checklist PDF, BMJ 2025;388:e081123)", 30,
        {
            "2": "Name of trial registry, identifying number (with URL) and date "
                 "of registration",
            "4": "Where and how the individual de-identified participant data "
                 "(including data dictionary), statistical code and any other "
                 "materials can be accessed",
            "5a": "Sources of funding and other support (e.g., supply of drugs), "
                  "and role of funders in the design, conduct, analysis and "
                  "reporting of the trial",
            "5b": "Financial and other conflicts of interest of the manuscript "
                  "authors",
            "9": "Description of trial design including type of trial (e.g., "
                 "parallel group, crossover), allocation ratio, and framework "
                 "(e.g., superiority, equivalence, non-inferiority, exploratory)",
            "14": "Pre-specified primary and secondary outcomes, including the "
                  "specific measurement variable, analysis metric, method of "
                  "aggregation, and time point for each outcome",
            "16a": "How sample size was determined, including all assumptions "
                   "supporting the sample size calculation",
            "17a": "Who generated the random allocation sequence and the method "
                   "used",
            "18": "Mechanism used to implement the random allocation sequence "
                  "(e.g., central computer/telephone; sequentially numbered, "
                  "opaque, sealed containers), describing any steps to conceal "
                  "the sequence until interventions were assigned",
            "20a": "Who was blinded after assignment to interventions (e.g., "
                   "participants, care providers, outcome assessors, data "
                   "analysts)",
            "21b": "Definition of who is included in each analysis (e.g., all "
                   "randomised participants), and in which group",
            "22a": "For each group, the numbers of participants who were randomly "
                   "assigned, received intended intervention, and were analysed "
                   "for the primary outcome",
            "26": "For each primary and secondary outcome, by group: the number "
                  "of participants included in the analysis, the result for each "
                  "group, and the estimated effect size and its precision (such "
                  "as 95% confidence interval)",
            "27": "All harms or unintended events in each group",
            "30": "Trial limitations, addressing sources of potential bias, "
                  "imprecision, generalisability, and, if relevant, multiplicity "
                  "of analyses",
        },
    ),
    "consort2010": Checklist(
        "consort2010", "consort", "CONSORT 2010",
        "https://www.consort-spirit.org/ (BMJ 2010;340:c332)", 25,
        {
            "3a": "Description of trial design (such as parallel, factorial) "
                  "including allocation ratio",
            "6a": "Completely defined pre-specified primary and secondary outcome "
                  "measures, including how and when they were assessed",
            "7a": "How sample size was determined",
            "8a": "Method used to generate the random allocation sequence",
            "9": "Mechanism used to implement the random allocation sequence "
                 "(such as sequentially numbered containers), describing any "
                 "steps taken to conceal the sequence until interventions were "
                 "assigned",
            "11a": "If done, who was blinded after assignment to interventions "
                   "(for example, participants, care providers, those assessing "
                   "outcomes) and how",
            "13a": "For each group, the numbers of participants who were randomly "
                   "assigned, received intended treatment, and were analysed for "
                   "the primary outcome",
            "16": "For each group, number of participants (denominator) included "
                  "in each analysis and whether the analysis was by original "
                  "assigned groups",
            "17a": "For each primary and secondary outcome, results for each "
                   "group, and the estimated effect size and its precision (such "
                   "as 95% confidence interval)",
            "19": "All important harms or unintended effects in each group",
            "20": "Trial limitations, addressing sources of potential bias, "
                  "imprecision, and, if relevant, multiplicity of analyses",
            "23": "Registration number and name of trial registry",
            "25": "Sources of funding and other support (such as supply of "
                  "drugs), role of funders",
        },
    ),
    "care": Checklist(
        "care", "care", "CARE 2013",
        "https://www.care-statement.org/checklist", 13,
        {
            "5a": "De-identified patient specific information",
            "5c": "Medical, family, and psycho-social history including relevant "
                  "genetic information",
            "7": "Historical and current information from this episode of care "
                 "organized as a timeline",
            "8a": "Diagnostic testing (such as PE, laboratory testing, imaging, "
                  "surveys)",
            "9a": "Types of therapeutic intervention (such as pharmacologic, "
                  "surgical, preventive, self-care)",
            "10a": "Clinician and patient-assessed outcomes (if available)",
            "10b": "Important follow-up diagnostic and other test results",
            "11a": "A scientific discussion of the strengths AND limitations "
                   "associated with this case report",
            "13": "Did the patient give informed consent? Please provide if "
                  "requested",
        },
    ),
    "stard": Checklist(
        "stard", "stard", "STARD 2015",
        "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC4623764/fullTextXML "
        "(BMJ 2015;351:h5527)", 30,
        {
            "10a": "Index test, in sufficient detail to allow replication",
            "10b": "Reference standard, in sufficient detail to allow replication",
            "12a": "Definition of and rationale for test positivity cut-offs or "
                   "result categories of the index test, distinguishing "
                   "pre-specified from exploratory",
            "13a": "Whether clinical information and reference standard results "
                   "were available to the performers or readers of the index test",
            "15": "How indeterminate index test or reference standard results "
                  "were handled",
            "19": "Flow of participants, using a diagram",
            "22": "Time interval and any clinical interventions between index "
                  "test and reference standard",
            "23": "Cross tabulation of the index test results (or their "
                  "distribution) by the results of the reference standard",
            "24": "Estimates of diagnostic accuracy and their precision (such as "
                  "95% confidence intervals)",
            "26": "Study limitations, including sources of potential bias, "
                  "statistical uncertainty, and generalisability",
            "30": "Sources of funding, and the role of funders",
        },
    ),
    "prisma": Checklist(
        "prisma", "prisma", "PRISMA 2020",
        "https://www.prisma-statement.org/prisma-2020-checklist "
        "(BMJ 2021;372:n71)", 27,
        {
            "5": "Specify the inclusion and exclusion criteria for the review and "
                 "how studies were grouped for the syntheses",
            "6": "Specify all databases, registers, websites, organisations, "
                 "reference lists and other sources searched or consulted to "
                 "identify studies. Specify the date when each source was last "
                 "searched or consulted",
            "7": "Present the full search strategies for all databases, registers "
                 "and websites, including any filters and limits used",
            "11": "Specify the methods used to assess risk of bias in the "
                  "included studies, including details of the tool(s) used, how "
                  "many reviewers assessed each study and whether they worked "
                  "independently",
            "13d": "Describe any methods used to synthesize results and provide a "
                   "rationale for the choice(s). If meta-analysis was performed, "
                   "describe the model(s), method(s) to identify the presence and "
                   "extent of statistical heterogeneity, and software package(s) "
                   "used",
            "14": "Describe any methods used to assess risk of bias due to "
                  "missing results in a synthesis (arising from reporting biases)",
            "16a": "Describe the results of the search and selection process, "
                   "from the number of records identified in the search to the "
                   "number of studies included in the review, ideally using a "
                   "flow diagram",
            "20b": "Present results of all statistical syntheses conducted. If "
                   "meta-analysis was done, present for each the summary estimate "
                   "and its precision and measures of statistical heterogeneity",
            "21": "Present assessments of risk of bias due to missing results "
                  "(arising from reporting biases) for each synthesis assessed",
            "23b": "Discuss any limitations of the evidence included in the "
                   "review",
            "24a": "Provide registration information for the review, including "
                   "register name and registration number, or state that the "
                   "review was not registered",
            "24b": "Indicate where the review protocol can be accessed, or state "
                   "that a protocol was not prepared",
            "25": "Describe sources of financial or non-financial support for the "
                  "review, and the role of the funders or sponsors in the review",
            "26": "Declare any competing interests of review authors",
            "27": "Report which of the following are publicly available and "
                  "where they can be found: template data collection forms; data "
                  "extracted from included studies; data used for all analyses; "
                  "analytic code; any other materials used in the review",
        },
    ),
}

# --------------------------------------------------------------------------- #
# Checklist items
#
# Patterns are searched case-insensitively; the first hit makes the item present.
# Both languages are covered on purpose: this workbench is Chinese-first, and a
# Chinese manuscript reporting "伦理审批" satisfies STROBE as well as one that says
# "ethics approval".
#
# `cites` names the official item(s) behind each check as (checklist id, number).
# A design-specific check cites one checklist; the cross-cutting ones cite every
# checklist that has a matching item, and the finding names only the one that
# belongs to the design being checked. `requirement` is shown instead when the
# design's checklist has no such item — "no number" is the honest answer there.
#
# `sections` is what --sections enforces: where the checklist puts the item, so a
# manuscript that mentions missing data only in the Discussion is told to move it
# to Methods. Items whose evidence legitimately lives in prose (CARE's narrative)
# declare nothing and are only existence-checked.
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    critical: bool
    patterns: tuple[str, ...]
    cites: tuple[tuple[str, str], ...] = ()
    hint: str = ""
    requirement: str = ""
    sections: tuple[str, ...] = ()


COMMON: tuple[Item, ...] = (
    Item(
        "ethics", "ethics approval or a waiver", True,
        (r"ethic", r"\bIRB\b", r"institutional review", r"伦理", r"审查批件"),
        hint="Name the approving body and the approval number.",
        requirement="human-subjects research requirement: no numbered item in "
                    "any of the five checklists; journals and ethics boards "
                    "require it",
        sections=("methods", "other"),
    ),
    Item(
        "consent", "informed consent or a documented waiver", True,
        (r"informed consent", r"consent waiv", r"written consent",
         r"知情同意", r"免除知情同意"),
        cites=(("care", "13"),),
        hint="State whether consent was written or oral, or why it was waived.",
        requirement="human-subjects research requirement: CARE 2013 item 13 is "
                    "the only numbered item; the other four checklists have none",
        sections=("methods", "other"),
    ),
    Item(
        "limitations", "a limitations section", False,
        (r"limitation", r"局限", r"局限性与不足"),
        cites=(("strobe", "19"), ("consort2025", "30"), ("consort2010", "20"),
               ("care", "11a"), ("stard", "26"), ("prisma", "23b")),
        sections=("discussion",),
    ),
    Item(
        "funding", "funding or a statement that there was none", False,
        (r"funding", r"funded by", r"grant", r"资金", r"资助", r"无资助"),
        cites=(("strobe", "22"), ("consort2025", "5a"), ("consort2010", "25"),
               ("stard", "30"), ("prisma", "25")),
        requirement="journal requirement: CARE 2013 has no funding item",
        sections=("other",),
    ),
    Item(
        "conflicts", "conflicts of interest", False,
        (r"conflicts? of interest", r"competing interests?", r"declaration of interests?",
         r"利益冲突", r"无利益冲突"),
        cites=(("consort2025", "5b"), ("prisma", "26")),
        requirement="journal requirement: only CONSORT 2025 and PRISMA 2020 number "
                    "it (ICMJE disclosure forms cover the rest)",
        sections=("other",),
    ),
    Item(
        "data-availability", "data availability", False,
        (r"data availability", r"available (?:on|from) request", r"数据可用", r"数据可向"),
        cites=(("consort2025", "4"), ("prisma", "27")),
        requirement="journal or funder requirement: only CONSORT 2025 and PRISMA "
                    "2020 number it",
        sections=("other",),
    ),
    Item(
        "ci", "confidence intervals on the effect estimates", True,
        (r"95\s*%\s*(?:CI|confidence interval)", r"confidence interval",
         r"95\s*%\s*(?:置信区间|可信区间)", r"置信区间", r"可信区间"),
        cites=(("strobe", "16a"), ("consort2025", "26"), ("consort2010", "17a"),
               ("stard", "24"), ("prisma", "20b")),
        hint="Report every headline estimate with its interval; a bare point "
             "estimate hides the precision the reader needs.",
        requirement="journal and reviewer expectation: no CARE 2013 item asks for "
                    "it, and a case report rarely has an effect estimate to put an "
                    "interval on",
        sections=("results",),
    ),
)

STROBE: tuple[Item, ...] = (
    Item("design", "the study design is named", True,
         (r"cohort", r"case[- ]control", r"cross[- ]sectional", r"队列", r"病例对照", r"横断面"),
         cites=(("strobe", "1a"), ("strobe", "4")),
         sections=("title", "abstract", "methods")),
    Item("setting", "setting, locations and dates", False,
         (r"\bsetting\b", r"conducted (?:at|in|between)", r"研究现场", r"研究时间", r"20\d{2}\s*年"),
         cites=(("strobe", "5"),),
         sections=("methods",)),
    Item("eligibility", "eligibility criteria", True,
         (r"eligib", r"inclusion criteria", r"exclusion criteria", r"纳入标准", r"排除标准"),
         cites=(("strobe", "6a"),),
         sections=("methods",)),
    Item("variables", "outcomes, exposures and confounders defined", False,
         (r"\boutcome\b", r"\bexposure\b", r"confound", r"结局", r"暴露", r"混杂"),
         cites=(("strobe", "7"),),
         sections=("methods",)),
    Item("statistics", "statistical methods described", True,
         (r"statistical (?:method|analysis)", r"regression", r"t[- ]test", r"卡方", r"回归", r"统计方法"),
         cites=(("strobe", "12a"),),
         sections=("methods",)),
    Item("missing-data", "how missing data were handled", False,
         (r"missing data", r"imputation", r"complete[- ]case", r"缺失", r"插补"),
         cites=(("strobe", "12c"),),
         sections=("methods",)),
    Item("participants", "numbers at each stage of the study", False,
         (r"flow (?:diagram|chart)", r"\b\d+ (?:patients|participants|subjects) (?:were )?(?:enrolled|included|screened)",
          r"流程图", r"\d+\s*例"),
         cites=(("strobe", "13a"),),
         sections=("results",)),
    Item("adjusted", "confounders adjusted for", False,
         (r"adjusted for", r"multivariable", r"multivariate", r"校正", r"多因素"),
         cites=(("strobe", "16a"),),
         sections=("results",)),
)

CONSORT: tuple[Item, ...] = (
    Item("registration", "trial registration number", True,
         (r"\bNCT\d{8}\b", r"ISRCTN\d+", r"\bChiCTR[\w-]+", r"注册号", r"注册于"),
         cites=(("consort2025", "2"), ("consort2010", "23")),
         hint="A trial without a registration number cannot be assessed for "
              "selective reporting.",
         sections=("title", "abstract", "methods", "other")),
    Item("design", "trial design (parallel, factorial, non-inferiority…)", True,
         (r"randomi[sz]ed", r"randomi[sz]ation", r"平行", r"随机"),
         cites=(("consort2025", "9"), ("consort2010", "3a")),
         sections=("title", "abstract", "methods")),
    Item("randomisation", "how the sequence was generated", False,
         (r"random number", r"computer[- ]generated", r"block random", r"随机数字表", r"随机序列"),
         cites=(("consort2025", "17a"), ("consort2010", "8a")),
         sections=("methods",)),
    Item("allocation", "allocation concealment", False,
         (r"allocation (?:was |is )?conceal", r"conceal(?:ed|ment)?\s+the\s+(?:random|allocation|sequence)",
          r"sealed (?:opaque )?envelope", r"central(?:ised|ized)?\s+(?:web |computer |telephone )?randomi",
          r"分配隐藏", r"密封信封"),
         cites=(("consort2025", "18"), ("consort2010", "9")),
         sections=("methods",)),
    Item("blinding", "who was blinded", False,
         (r"\bblinding\b", r"\bblinded\b", r"double[- ]blind", r"single[- ]blind",
          r"盲法", r"双盲", r"单盲"),
         cites=(("consort2025", "20a"), ("consort2010", "11a")),
         sections=("methods",)),
    Item("sample-size", "sample size calculation", True,
         (r"sample size (?:calculation|estimate|justification)", r"\bpower\b", r"样本量", r"把握度", r"检验效能"),
         cites=(("consort2025", "16a"), ("consort2010", "7a")),
         sections=("methods",)),
    Item("outcomes", "primary and secondary outcomes defined", True,
         (r"primary (?:outcome|end ?point)", r"secondary (?:outcome|end ?point)", r"主要终点", r"次要终点"),
         cites=(("consort2025", "14"), ("consort2010", "6a")),
         sections=("methods",)),
    Item("flow", "participant flow with numbers", True,
         (r"flow (?:diagram|chart)", r"screened", r"assigned to", r"流程图", r"筛选", r"随机分组"),
         cites=(("consort2025", "22a"), ("consort2010", "13a")),
         sections=("results",)),
    Item("itt", "analysis population (ITT or per-protocol)", False,
         (r"intention[- ]to[- ]treat", r"\bITT\b", r"per[- ]protocol", r"意向性", r"符合方案"),
         cites=(("consort2025", "21b"), ("consort2010", "16")),
         sections=("methods",)),
    Item("harms", "harms or adverse events", True,
         (r"adverse event", r"\bharms?\b", r"不良事件", r"安全性"),
         cites=(("consort2025", "27"), ("consort2010", "19")),
         sections=("results",)),
)

CARE: tuple[Item, ...] = (
    Item("deidentification", "de-identification of patient details", True,
         (r"de[- ]identif", r"anonymi[sz]ed", r"no identifying", r"去标识", r"脱敏", r"匿名化"),
         cites=(("care", "5a"),),
         hint="Case reports leak identity through dates, places and rare findings; "
              "say how they were altered.",
         sections=("other",)),
    Item("demographics", "patient demographics (age, sex)", True,
         (r"\b(?:year|yr)s?[- ]old\b", r"\b\d{1,3}[- ]year", r"\b(?:male|female|man|woman)\b",
          r"\d{1,3}\s*岁", r"男|女"),
         cites=(("care", "5a"),)),
    Item("history", "clinical history and examination", False,
         (r"history", r"presented with", r"examination", r"既往史", r"主诉", r"查体"),
         cites=(("care", "5c"),)),
    Item("assessment", "diagnostic assessment and results", False,
         (r"diagnostic (?:assessment|work-?up)", r"laboratory", r"imaging", r"检查", r"化验", r"影像"),
         cites=(("care", "8a"),)),
    Item("intervention", "therapeutic intervention", False,
         (r"treat(?:ed|ment)", r"intervention", r"administered", r"治疗", r"干预", r"用药"),
         cites=(("care", "9a"),)),
    Item("outcomes", "follow-up and outcomes", True,
         (r"follow[- ]up", r"outcome", r"at \d+ (?:weeks|months)", r"随访", r"转归", r"结局"),
         cites=(("care", "10a"), ("care", "10b")),
         sections=()),
    Item("timeline", "a timeline of the episode", False,
         (r"timeline", r"day \d+", r"month \d+", r"时间轴", r"第\s*\d+\s*天"),
         cites=(("care", "7"),)),
)

STARD: tuple[Item, ...] = (
    Item("reference-standard", "the reference standard", True,
         (r"reference standard", r"gold standard", r"金标准", r"参考标准"),
         cites=(("stard", "10b"),),
         sections=("methods",)),
    Item("index-test", "the index test and its conduct", True,
         (r"index test", r"cut-?off", r"threshold", r"试验操作", r"截断值", r"临界值"),
         cites=(("stard", "10a"), ("stard", "12a")),
         sections=("methods",)),
    Item("two-by-two", "the 2x2 table (TP/FP/TN/FN or equivalents)", True,
         (r"\bTP\b[\s,;/]*\bFP\b", r"2\s*[x×]\s*2", r"true positive", r"假阳性", r"真阳性"),
         cites=(("stard", "23"),),
         sections=("results",)),
    Item("indeterminate", "indeterminate or uninterpretable results", True,
         (r"indeterminate", r"uninterpretable", r"inconclusive", r"无法判读", r"不确定结果", r"灰区"),
         cites=(("stard", "15"),),
         hint="Dropping indeterminate results inflates sensitivity; report them "
              "and how they entered the analysis.",
         sections=("methods", "results")),
    Item("accuracy", "sensitivity and specificity (with intervals)", True,
         (r"sensitivit", r"sensitivity", r"灵敏度", r"敏感度", r"特异度"),
         cites=(("stard", "24"),),
         sections=("results",)),
    Item("auc", "ROC/AUC when a continuous test is used", False,
         (r"\bAUC\b", r"ROC", r"曲线下面积"),
         cites=(("stard", "24"),),
         sections=("results",)),
    Item("flow", "participant flow through the study", False,
         (r"flow (?:diagram|chart)", r"eligible", r"included", r"流程图", r"纳入"),
         cites=(("stard", "19"),),
         sections=("results",)),
    Item("blinding", "whether readers were blinded", False,
         (r"blind", r"independent reader", r"盲法", r"独立判读"),
         cites=(("stard", "13a"),),
         sections=("methods",)),
    Item("interval", "the interval between index test and reference standard", False,
         (r"time interval", r"within \d+ (?:days|hours)", r"间隔", r"同一时间"),
         cites=(("stard", "22"),),
         sections=("methods", "results")),
)

PRISMA: tuple[Item, ...] = (
    Item("registration", "the review protocol (PROSPERO or similar)", False,
         (r"PROSPERO", r"protocol (?:was )?registered", r"注册号", r"研究方案注册"),
         cites=(("prisma", "24a"), ("prisma", "24b")),
         sections=("methods", "other")),
    Item("databases", "databases searched, with dates", True,
         (r"PubMed", r"Embase", r"Cochrane", r"Web of Science", r"CNKI", r"万方", r"数据库"),
         cites=(("prisma", "6"),),
         sections=("methods",)),
    Item("search-strategy", "the full search strategy", True,
         (r"search strategy", r"search (?:terms|string|query)", r"检索策略", r"检索式"),
         cites=(("prisma", "7"),),
         sections=("methods", "other")),
    Item("criteria", "inclusion and exclusion criteria", True,
         (r"inclusion criteria", r"exclusion criteria", r"纳入标准", r"排除标准"),
         cites=(("prisma", "5"),),
         sections=("methods",)),
    Item("selection", "numbers screened, excluded and included", True,
         (r"\d+ records", r"screened", r"excluded", r"篇文献", r"筛选", r"排除"),
         cites=(("prisma", "16a"),),
         sections=("results",)),
    Item("risk-of-bias", "risk-of-bias assessment", True,
         (r"risk of bias", r"quality assessment", r"Newcastle", r"偏倚风险", r"质量评价"),
         cites=(("prisma", "11"),),
         sections=("methods",)),
    Item("heterogeneity", "heterogeneity (I2, tau2 or a narrative account)", False,
         (r"heterogeneity", r"\bI\s*2\b", r"I\^2", r"异质性"),
         cites=(("prisma", "13d"), ("prisma", "20b")),
         sections=("methods", "results")),
    Item("publication-bias", "publication bias", False,
         (r"publication bias", r"funnel plot", r"Egger", r"发表偏倚", r"漏斗图"),
         cites=(("prisma", "14"), ("prisma", "21")),
         sections=("methods", "results")),
    Item("flow", "a PRISMA flow diagram", False,
         (r"flow (?:diagram|chart)", r"PRISMA", r"流程图"),
         cites=(("prisma", "16a"),),
         sections=("results",)),
)

DESIGNS: dict[str, tuple[Item, ...]] = {
    "strobe": STROBE,
    "consort": CONSORT,
    "care": CARE,
    "stard": STARD,
    "prisma": PRISMA,
}

DESIGN_LABEL = {
    "strobe": "STROBE 2007 (observational studies)",
    "consort": "CONSORT 2025 (randomised trials)",
    "care": "CARE 2013 (case reports)",
    "stard": "STARD 2015 (diagnostic accuracy)",
    "prisma": "PRISMA 2020 (systematic reviews)",
}

# Design detection: strongest signal first. A randomised trial also mentions
# cohorts often enough that the order matters.
_SIGNALS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("prisma", (r"systematic review", r"meta[- ]analys", r"PRISMA", r"系统评价", r"系统综述", r"荟萃分析")),
    ("consort", (r"randomi[sz]ed (?:controlled )?trial", r"randomi[sz]ation", r"随机对照", r"RCT")),
    ("care", (r"case report", r"case series", r"病例报告", r"个案报道")),
    ("stard", (r"diagnostic accuracy", r"sensitivity and specificity", r"index test",
               r"诊断准确性", r"诊断试验", r"敏感度")),
)

# Section names --sections can enforce, and the words a heading uses for each.
# An unrecognised heading leaves its body in the enclosing section, which is what
# "3.1 Study population" under Methods means.
_SECTION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("title", ("title", "标题")),
    ("abstract", ("abstract", "summary", "摘要")),
    ("intro", ("introduction", "background", "引言", "前言", "背景")),
    ("methods", ("method", "methods", "materials", "patients and methods",
                 "methodology", "study design", "study population", "participants",
                 "statistical analysis", "statistics", "方法", "资料与方法",
                 "对象与方法", "材料与方法", "研究设计", "研究对象", "统计学")),
    ("results", ("result", "results", "findings", "结果")),
    ("discussion", ("discussion", "limitations", "讨论", "局限")),
    ("other", ("other information", "declarations", "declaration", "acknowledgement",
               "acknowledgments", "funding", "conflicts of interest",
               "competing interests", "data availability", "registration",
               "consent", "ethics", "致谢", "声明", "利益冲突", "数据可用", "注册", "伦理", "知情同意")),
)

# The effect-estimate check lives in the `ci` item above and nothing else: a
# per-estimate "this OR has no interval" rule needs to parse tables and prose, and
# a regex that guesses at it would report a document with one intervaled estimate
# and one bare estimate as fine. Saying "no interval anywhere" is the honest
# version of what a pattern list can know.


@dataclass(frozen=True)
class Citation:
    """One official checklist item behind a check, resolved for this design."""
    checklist: str      # "STROBE 2007"
    number: str         # "16a"
    text: str           # official wording


@dataclass
class Finding:
    level: str          # error | warn | ok
    tag: str
    title: str
    evidence: str


@dataclass
class Report:
    path: Path
    text: str
    design: str
    findings: list[Finding] = field(default_factory=list)
    strict: bool = False
    sections_found: tuple[str, ...] = ()


def citations(item: Item, design: str) -> list[Citation]:
    """The official items behind `item` for this design (empty: no item exists)."""
    out = []
    for checklist_id, number in item.cites:
        checklist = CHECKLISTS[checklist_id]
        if checklist.design != design:
            continue
        out.append(Citation(checklist.label, number,
                            checklist.items.get(number, "")))
    return out


def basis(item: Item, design: str) -> str:
    """How a finding names its authority: "STROBE 2007 item 16a" or the rule."""
    found = citations(item, design)
    if found:
        return " · ".join(f"{c.checklist} item {c.number}" for c in found)
    return item.requirement or "no numbered checklist item"


def detect_design(text: str) -> str:
    for design, patterns in _SIGNALS:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return design
    return "strobe"


def present(text: str, item: Item) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in item.patterns)


def _canonical_section(heading: str) -> str | None:
    """Map a heading's words to a section name, or None when it is a sub-heading."""
    cleaned = heading.strip().strip("*_#:").strip().lower()
    cleaned = re.sub(r"^\d+(?:\.\d+)*[.、)]?\s*", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned or len(cleaned) > 60:
        return None
    for section, words in _SECTION_WORDS:
        for word in words:
            if cleaned == word or cleaned.startswith(word + " ") or cleaned.startswith(word + "("):
                return section
    return None


def scan_sections(text: str) -> tuple[dict[str, str], tuple[str, ...]]:
    """Split the text at recognised headings.

    Returns (section -> text, sections in document order). Markdown headings and
    plain heading lines both count; an unrecognised heading keeps its body in the
    enclosing recognised section, so sub-headings stay where they belong. A text
    with no recognised heading returns an empty mapping — --sections then says so
    instead of guessing.
    """
    buckets: dict[str, list[str]] = {}
    order: list[str] = []
    stack: list[tuple[int, str | None]] = []
    current: str | None = None
    for line in text.splitlines():
        markdown = re.match(r"^\s{0,3}(#{1,6})\s+(.*)$", line)
        plain = None
        if not markdown:
            bare = line.strip().strip("*_").strip()
            if bare and len(bare) <= 60 and not bare.endswith((".", "。", ",", "，")):
                if _canonical_section(bare) or re.match(r"^[A-Z][A-Za-z /&-]{2,58}$", bare):
                    plain = bare
        if markdown:
            level = len(markdown.group(1))
            heading = markdown.group(2).strip()
        elif plain is not None:
            level = 1
            heading = plain
        else:
            if current is not None:
                buckets.setdefault(current, []).append(line)
            continue
        section = _canonical_section(heading)
        first_heading = not order and not stack
        if section is None:
            if level == 1 and first_heading:
                # The document's own H1 is its title line, not a heading that
                # names a section; its text is content the title item can read.
                section = "title"
                title_line = True
            else:
                # A sub-heading: keep the enclosing recognised section.
                while stack and stack[-1][0] >= level:
                    stack.pop()
                current = stack[-1][1] if stack else None
                continue
        else:
            title_line = False
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, section))
        current = section
        if section not in buckets:
            buckets[section] = []
            order.append(section)
        if title_line:
            buckets[section].append(heading)
    return {k: "\n".join(v) for k, v in buckets.items()}, tuple(order)


def check(path: Path, design: str | None, strict: bool = False) -> Report:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:  # unreadable file is a finding, not a crash
        return Report(path, "", design or "strobe", [
            Finding("error", "reporting · readable", f"could not read {path.name}", str(exc)),
        ])
    chosen = design or detect_design(text)
    report = Report(path, text, chosen, strict=strict)
    if strict:
        sections, report.sections_found = scan_sections(text)
    else:
        sections = {}
    label = DESIGN_LABEL.get(chosen, chosen)

    for item in COMMON + DESIGNS.get(chosen, ()):
        where = basis(item, chosen)
        if present(text, item):
            # --sections: mentioned, but is it in the section the checklist puts
            # it in? Only when that section was actually found in this document.
            required = [s for s in item.sections if s in sections]
            if strict and required:
                placed = any(re.search(p, sections[s], re.IGNORECASE)
                             for s in required for p in item.patterns)
                if not placed:
                    wanted = " / ".join(s.capitalize() for s in required)
                    report.findings.append(Finding(
                        "warn",
                        f"reporting · {chosen} · {item.id} · section",
                        f"{label}: {where} — {item.label} appears outside {wanted}",
                        f"{where} — {path.name}: the text mentions this item, but "
                        f"not under {wanted}; the checklist puts it there. Move the "
                        f"sentence rather than adding a second one.",
                    ))
            continue
        report.findings.append(Finding(
            "error" if item.critical else "warn",
            f"reporting · {chosen} · {item.id}",
            f"{label}: no {item.label}",
            (f"{where} — {path.name}: searched for {', '.join(item.patterns[:3])}"
             + (f" — {item.hint}" if item.hint else "")),
        ))

    # Cross-cutting: nothing else. See the note above the Item list about why a
    # per-estimate interval rule is not attempted here.
    return report


def note(reports: list[Report]) -> str:
    if not reports:
        return ("Reporting-guideline gate — nothing to check: no readable manuscript "
                "was given. Absence of findings is not a claim of compliance.")
    parts = []
    for r in reports:
        total = len(COMMON) + len(DESIGNS.get(r.design, ()))
        missing = len([f for f in r.findings if " · section" not in f.tag])
        parts.append(f"{r.path.name}: {DESIGN_LABEL.get(r.design, r.design)}, "
                     f"{total - missing}/{total} items present")
    text = ("Reporting-guideline gate — a presence check against STROBE 2007/"
            "CONSORT 2025/CARE 2013/STARD 2015/PRISMA 2020 items, not a compliance "
            "verdict. " + "; ".join(parts)
            + ". A present item may still be wrong, and a missing one may be reported "
              "elsewhere in the submission package (checklist, supplement, protocol).")
    if any(r.strict for r in reports):
        judged = [r for r in reports if r.strict and r.sections_found]
        if judged:
            found = ", ".join(sorted({s for r in judged for s in r.sections_found}))
            text += (" Section positions were checked against the headings found "
                     f"({found}); a moved item is a warning, not an error.")
        else:
            text += (" Section positions were requested but no Methods/Results "
                     "heading was recognised, so placement was not judged.")
    return text


def run(paths: list[str], design: str | None, strict: bool = False) -> dict:
    targets = [Path(p) for p in paths]
    reports = [check(p, design, strict) for p in targets]
    findings = [f for r in reports for f in r.findings]
    # Most severe first, then by file, so the card list reads top-down.
    findings.sort(key=lambda f: (f.level != "error", f.tag))
    return {
        "findings": [
            {"level": f.level, "tag": f.tag, "title": f.title, "evidence": f.evidence}
            for f in findings
        ],
        "note": note(reports),
    }


def listing(design: str) -> int:
    if design not in DESIGNS:
        print(f"unknown design: {design} (one of {', '.join(DESIGNS)})", file=sys.stderr)
        return 2
    print(f"{DESIGN_LABEL[design]}")
    sources: list[str] = []
    for citation in citations_of(design):
        if citation.checklist not in sources:
            sources.append(citation.checklist)
    for source in sources:
        checklist = next(c for c in CHECKLISTS.values() if c.label == source)
        print(f"  source: {checklist.label} — {checklist.source} ({checklist.total} items)")
    for item in COMMON + DESIGNS[design]:
        mark = "required" if item.critical else "recommended"
        print(f"  [{mark:11}] {item.id:16} {item.label}")
        found = citations(item, design)
        if found:
            for c in found:
                print(f"                {c.checklist} item {c.number}: {c.text}")
        else:
            print(f"                {basis(item, design)}")
        if item.sections:
            print(f"                section: {' / '.join(item.sections)}")
    return 0


def citations_of(design: str) -> list[Citation]:
    out: list[Citation] = []
    for item in COMMON + DESIGNS.get(design, ()):
        out.extend(citations(item, design))
    return out


def main(argv: list[str]) -> int:
    # The block quotes text from the manuscript, and a Windows console is not
    # UTF-8: one unprintable character would turn a finished review into a
    # UnicodeEncodeError. Degrade it instead.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    args = list(argv)
    design: str | None = None
    strict = False
    if "--list" in args:
        args.remove("--list")
        return listing(args[0] if args else "strobe")
    if "--sections" in args:
        args.remove("--sections")
        strict = True
    if "--design" in args:
        i = args.index("--design")
        if i + 1 >= len(args):
            print("--design needs a value", file=sys.stderr)
            return 2
        design = args[i + 1].lower()
        del args[i:i + 2]
        if design not in DESIGNS:
            print(f"unknown design: {design} (one of {', '.join(DESIGNS)})", file=sys.stderr)
            return 2
    if not args:
        print(__doc__)
        return 2
    for p in args:
        if not Path(p).is_file():
            print(f"no such file: {p}", file=sys.stderr)
            return 2
    print("```review")
    print(json.dumps(run(args, design, strict), ensure_ascii=False, indent=1))
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))