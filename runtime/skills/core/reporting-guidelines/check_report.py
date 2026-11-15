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

Output: one ```review fenced JSON block on stdout, the app's reviewer contract
(`level` error|warn|ok, `tag`, `title`, `evidence`, plus a `note`).

Usage:
    python check_report.py report.md                 # detect the design
    python check_report.py --design stard report.md  # force one
    python check_report.py --list stard              # print the checklist
    python check_report.py --design consort *.md     # several files
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Checklist items
#
# Patterns are searched case-insensitively; the first hit makes the item present.
# Both languages are covered on purpose: this workbench is Chinese-first, and a
# Chinese manuscript reporting "伦理审批" satisfies STROBE as well as one that says
# "ethics approval".
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class Item:
    id: str
    label: str
    basis: str
    critical: bool
    patterns: tuple[str, ...]
    hint: str = ""


COMMON: tuple[Item, ...] = (
    Item(
        "ethics", "ethics approval or a waiver", "human-subjects research",
        True,
        (r"ethic", r"\bIRB\b", r"institutional review", r"伦理", r"审查批件"),
        "Name the approving body and the approval number.",
    ),
    Item(
        "consent", "informed consent or a documented waiver", "human-subjects research",
        True,
        (r"informed consent", r"consent waiv", r"written consent",
         r"知情同意", r"免除知情同意"),
        "State whether consent was written or oral, or why it was waived.",
    ),
    Item(
        "limitations", "a limitations section", "all designs",
        False,
        (r"limitation", r"局限", r"局限性与不足"),
    ),
    Item(
        "funding", "funding or a statement that there was none", "all designs",
        False,
        (r"funding", r"funded by", r"grant", r"资金", r"资助", r"无资助"),
    ),
    Item(
        "conflicts", "conflicts of interest", "all designs",
        False,
        (r"conflicts? of interest", r"competing interests?", r"declaration of interests?",
         r"利益冲突", r"无利益冲突"),
    ),
    Item(
        "data-availability", "data availability", "all designs",
        False,
        (r"data availability", r"available (?:on|from) request", r"数据可用", r"数据可向"),
    ),
    Item(
        "ci", "confidence intervals on the effect estimates", "all designs",
        True,
        (r"95\s*%\s*(?:CI|confidence interval)", r"confidence interval",
         r"95\s*%\s*(?:置信区间|可信区间)", r"置信区间", r"可信区间"),
        "Report every headline estimate with its interval; a bare point estimate "
        "hides the precision the reader needs.",
    ),
)

STROBE: tuple[Item, ...] = (
    Item("design", "the study design is named", "STROBE item 4", True,
         (r"cohort", r"case[- ]control", r"cross[- ]sectional", r"队列", r"病例对照", r"横断面")),
    Item("setting", "setting, locations and dates", "STROBE item 5", False,
         (r"\bsetting\b", r"conducted (?:at|in|between)", r"研究现场", r"研究时间", r"20\d{2}\s*年")),
    Item("eligibility", "eligibility criteria", "STROBE item 6a", True,
         (r"eligib", r"inclusion criteria", r"exclusion criteria", r"纳入标准", r"排除标准")),
    Item("variables", "outcomes, exposures and confounders defined", "STROBE item 7", False,
         (r"\boutcome\b", r"\bexposure\b", r"confound", r"结局", r"暴露", r"混杂")),
    Item("statistics", "statistical methods described", "STROBE item 12a", True,
         (r"statistical (?:method|analysis)", r"regression", r"t[- ]test", r"卡方", r"回归", r"统计方法")),
    Item("missing-data", "how missing data were handled", "STROBE item 12c", False,
         (r"missing data", r"imputation", r"complete[- ]case", r"缺失", r"插补")),
    Item("participants", "numbers at each stage of the study", "STROBE item 13", False,
         (r"flow (?:diagram|chart)", r"\b\d+ (?:patients|participants|subjects) (?:were )?(?:enrolled|included|screened)",
          r"流程图", r"\d+\s*例")),
    Item("adjusted", "confounders adjusted for", "STROBE item 14a", False,
         (r"adjusted for", r"multivariable", r"multivariate", r"校正", r"多因素")),
)

CONSORT: tuple[Item, ...] = (
    Item("registration", "trial registration number", "CONSORT item 2b", True,
         (r"\bNCT\d{8}\b", r"ISRCTN\d+", r"\bChiCTR[\w-]+", r"注册号", r"注册于"),
         "A trial without a registration number cannot be assessed for selective reporting."),
    Item("design", "trial design (parallel, factorial, non-inferiority…)", "CONSORT item 3a", True,
         (r"randomi[sz]ed", r"randomi[sz]ation", r"平行", r"随机")),
    Item("randomisation", "how the sequence was generated", "CONSORT item 8a", False,
         (r"random number", r"computer[- ]generated", r"block random", r"随机数字表", r"随机序列")),
    Item("allocation", "allocation concealment", "CONSORT item 9", False,
         (r"allocation conceal", r"sealed (?:opaque )?envelope", r"central randomi", r"分配隐藏", r"密封信封")),
    Item("blinding", "who was blinded", "CONSORT item 11a", False,
         (r"blinding", r"double[- ]blind", r"single[- ]blind", r"盲法", r"双盲", r"单盲")),
    Item("sample-size", "sample size calculation", "CONSORT item 7a", True,
         (r"sample size (?:calculation|estimate|justification)", r"\bpower\b", r"样本量", r"把握度", r"检验效能")),
    Item("outcomes", "primary and secondary outcomes defined", "CONSORT item 6a", True,
         (r"primary (?:outcome|end ?point)", r"secondary (?:outcome|end ?point)", r"主要终点", r"次要终点")),
    Item("flow", "participant flow with numbers", "CONSORT item 13a", True,
         (r"flow (?:diagram|chart)", r"screened", r"assigned to", r"流程图", r"筛选", r"随机分组")),
    Item("itt", "analysis population (ITT or per-protocol)", "CONSORT item 16", False,
         (r"intention[- ]to[- ]treat", r"\bITT\b", r"per[- ]protocol", r"意向性", r"符合方案")),
    Item("harms", "harms or adverse events", "CONSORT item 19", True,
         (r"adverse event", r"\bharms?\b", r"不良事件", r"安全性")),
)

CARE: tuple[Item, ...] = (
    Item("deidentification", "de-identification of patient details", "CARE item 1 / 13", True,
         (r"de[- ]identif", r"anonymi[sz]ed", r"no identifying", r"去标识", r"脱敏", r"匿名化"),
         "Case reports leak identity through dates, places and rare findings; say how "
         "they were altered."),
    Item("demographics", "patient demographics (age, sex)", "CARE item 3", True,
         (r"\b(?:year|yr)s?[- ]old\b", r"\b\d{1,3}[- ]year", r"\b(?:male|female|man|woman)\b",
          r"\d{1,3}\s*岁", r"男|女")),
    Item("history", "clinical history and examination", "CARE item 5", False,
         (r"history", r"presented with", r"examination", r"既往史", r"主诉", r"查体")),
    Item("assessment", "diagnostic assessment and results", "CARE item 6", False,
         (r"diagnostic (?:assessment|work-?up)", r"laboratory", r"imaging", r"检查", r"化验", r"影像")),
    Item("intervention", "therapeutic intervention", "CARE item 7", False,
         (r"treat(?:ed|ment)", r"intervention", r"administered", r"治疗", r"干预", r"用药")),
    Item("outcomes", "follow-up and outcomes", "CARE item 8 / 9", True,
         (r"follow[- ]up", r"outcome", r"at \d+ (?:weeks|months)", r"随访", r"转归", r"结局")),
    Item("timeline", "a timeline of the episode", "CARE item 4", False,
         (r"timeline", r"day \d+", r"month \d+", r"时间轴", r"第\s*\d+\s*天")),
)

STARD: tuple[Item, ...] = (
    Item("reference-standard", "the reference standard", "STARD item 7", True,
         (r"reference standard", r"gold standard", r"金标准", r"参考标准")),
    Item("index-test", "the index test and its conduct", "STARD item 10a", True,
         (r"index test", r"cut-?off", r"threshold", r"试验操作", r"截断值", r"临界值")),
    Item("two-by-two", "the 2x2 table (TP/FP/TN/FN or equivalents)", "STARD item 21", True,
         (r"\bTP\b[\s,;/]*\bFP\b", r"2\s*[x×]\s*2", r"true positive", r"假阳性", r"真阳性")),
    Item("indeterminate", "indeterminate or uninterpretable results", "STARD item 16", True,
         (r"indeterminate", r"uninterpretable", r"inconclusive", r"无法判读", r"不确定结果", r"灰区"),
         "Dropping indeterminate results inflates sensitivity; report them and how "
         "they entered the analysis."),
    Item("accuracy", "sensitivity and specificity (with intervals)", "STARD item 24", True,
         (r"sensitivit", r"sensitivity", r"灵敏度", r"敏感度", r"特异度")),
    Item("auc", "ROC/AUC when a continuous test is used", "STARD item 24", False,
         (r"\bAUC\b", r"ROC", r"曲线下面积")),
    Item("flow", "participant flow through the study", "STARD item 19", False,
         (r"flow (?:diagram|chart)", r"eligible", r"included", r"流程图", r"纳入")),
    Item("blinding", "whether readers were blinded", "STARD item 11", False,
         (r"blind", r"independent reader", r"盲法", r"独立判读")),
    Item("interval", "the interval between index test and reference standard", "STARD item 12", False,
         (r"time interval", r"within \d+ (?:days|hours)", r"间隔", r"同一时间")),
)

PRISMA: tuple[Item, ...] = (
    Item("registration", "the review protocol (PROSPERO or similar)", "PRISMA item 5", False,
         (r"PROSPERO", r"protocol (?:was )?registered", r"注册号", r"研究方案注册")),
    Item("databases", "databases searched, with dates", "PRISMA item 8", True,
         (r"PubMed", r"Embase", r"Cochrane", r"Web of Science", r"CNKI", r"万方", r"数据库")),
    Item("search-strategy", "the full search strategy", "PRISMA item 7", True,
         (r"search strategy", r"search (?:terms|string|query)", r"检索策略", r"检索式")),
    Item("criteria", "inclusion and exclusion criteria", "PRISMA item 6", True,
         (r"inclusion criteria", r"exclusion criteria", r"纳入标准", r"排除标准")),
    Item("selection", "numbers screened, excluded and included", "PRISMA item 16a", True,
         (r"\d+ records", r"screened", r"excluded", r"篇文献", r"筛选", r"排除")),
    Item("risk-of-bias", "risk-of-bias assessment", "PRISMA item 11", True,
         (r"risk of bias", r"quality assessment", r"Newcastle", r"偏倚风险", r"质量评价")),
    Item("heterogeneity", "heterogeneity (I2, tau2 or a narrative account)", "PRISMA item 13", False,
         (r"heterogeneity", r"\bI\s*2\b", r"I\^2", r"异质性")),
    Item("publication-bias", "publication bias", "PRISMA item 15", False,
         (r"publication bias", r"funnel plot", r"Egger", r"发表偏倚", r"漏斗图")),
    Item("flow", "a PRISMA flow diagram", "PRISMA item 16", False,
         (r"flow (?:diagram|chart)", r"PRISMA", r"流程图")),
)

DESIGNS: dict[str, tuple[Item, ...]] = {
    "strobe": STROBE,
    "consort": CONSORT,
    "care": CARE,
    "stard": STARD,
    "prisma": PRISMA,
}

DESIGN_LABEL = {
    "strobe": "STROBE (observational studies)",
    "consort": "CONSORT (randomised trials)",
    "care": "CARE (case reports)",
    "stard": "STARD (diagnostic accuracy)",
    "prisma": "PRISMA (systematic reviews)",
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

# The effect-estimate check lives in the `ci` item above and nothing else: a
# per-estimate "this OR has no interval" rule needs to parse tables and prose, and
# a regex that guesses at it would report a document with one intervaled estimate
# and one bare estimate as fine. Saying "no interval anywhere" is the honest
# version of what a pattern list can know.


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


def detect_design(text: str) -> str:
    for design, patterns in _SIGNALS:
        for pattern in patterns:
            if re.search(pattern, text, re.IGNORECASE):
                return design
    return "strobe"


def present(text: str, item: Item) -> bool:
    return any(re.search(p, text, re.IGNORECASE) for p in item.patterns)


def check(path: Path, design: str | None) -> Report:
    try:
        text = path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError as exc:  # unreadable file is a finding, not a crash
        return Report(path, "", design or "strobe", [
            Finding("error", "reporting · readable", f"could not read {path.name}", str(exc)),
        ])
    chosen = design or detect_design(text)
    report = Report(path, text, chosen)
    label = DESIGN_LABEL.get(chosen, chosen)

    for item in COMMON + DESIGNS.get(chosen, ()):
        if present(text, item):
            continue
        report.findings.append(Finding(
            "error" if item.critical else "warn",
            f"reporting · {chosen} · {item.id}",
            f"{label}: no {item.label}",
            (f"{path.name}: searched for {', '.join(item.patterns[:3])}"
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
        missing = len(r.findings)
        parts.append(f"{r.path.name}: {DESIGN_LABEL.get(r.design, r.design)}, "
                     f"{total - missing}/{total} items present")
    return ("Reporting-guideline gate — a presence check against STROBE/CONSORT/CARE/"
            "STARD/PRISMA items, not a compliance verdict. " + "; ".join(parts)
            + ". A present item may still be wrong, and a missing one may be reported "
              "elsewhere in the submission package (checklist, supplement, protocol).")


def run(paths: list[str], design: str | None) -> dict:
    targets = [Path(p) for p in paths]
    reports = [check(p, design) for p in targets]
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
    for item in COMMON + DESIGNS[design]:
        mark = "required" if item.critical else "recommended"
        print(f"  [{mark:11}] {item.id:16} {item.label}  ({item.basis})")
    return 0


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
    if "--list" in args:
        args.remove("--list")
        return listing(args[0] if args else "strobe")
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
    print(json.dumps(run(args, design), ensure_ascii=False, indent=1))
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))