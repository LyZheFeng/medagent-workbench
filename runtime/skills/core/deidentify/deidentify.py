#!/usr/bin/env python3
"""De-identification gate for case reports and clinical text — stdlib only.

Reads a document, replaces pattern-matched direct identifiers with stable
tokens, shifts every date by one consistent offset, and writes a de-identified
copy. Emits exactly one ```review fenced JSON block, the app's reviewer
contract, with counts only — never the identifiers themselves.

It is a rule-based first pass, never a guarantee of anonymity: it does not read
images or DICOM metadata, an unlabelled name can survive, and unusual free-text
identifiers are outside what a fixed pattern list can see. The block says so.

Usage:
    python deidentify.py case.md                     # writes case.deid.md
    python deidentify.py case.md --out clean.md --mapping map.json
    python deidentify.py case.md --shift-days 30     # fixed, reproducible shift
    python deidentify.py --check case.md             # report only, write nothing
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

# --------------------------------------------------------------------------- #
# Patterns
#
# Each rule is a documented convention, not a guessed heuristic:
#   - an 18/15-digit mainland ID has a fixed layout
#   - a mobile number starts 1, then 3-9
#   - each identifier kind is either unlabelled (email, ID, phone) or requires
#     its label (住院号, 姓名, 地址), because a bare Chinese name cannot be told
#     apart from ordinary words without a model
#   - the one bare-name rule is the CARE convention "患者张三，男": a 2-4
#     character run right before a gender marker
# --------------------------------------------------------------------------- #

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")

ID18 = re.compile(
    r"(?<!\d)[1-9]\d{5}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[\dXx](?!\d)"
)
ID15 = re.compile(
    r"(?<!\d)[1-9]\d{7}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}(?!\d)"
)
PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")

# A label may be followed by a colon or just whitespace: "住院号：A123456" and
# "住院号 A123456" are both real. Requiring one of them keeps "姓名学" from
# being read as a name field.
_SEP = r"(?:\s*[:：]\s*|\s+)"

PHONE_LABELED = re.compile(
    r"(?:电话|手机|联系方式|联系电话|Tel|Phone|Mobile)" + _SEP + r"(\+?[0-9][0-9\-\s()]{6,18}[0-9])",
    re.IGNORECASE,
)

# A label may be followed by a colon or just whitespace: "住院号：A123456" and
# "住院号 A123456" are both real. Requiring one of them keeps "姓名学" from
# being read as a name field.
MRN = re.compile(
    r"(?:住院号|门诊号|病历号|病案号|就诊号|登记号|检查号|检验号|医保卡号|医保号|社保号|"
    r"MRN|Medical Record(?: Number)?)" + _SEP + r"([A-Za-z0-9][A-Za-z0-9\-]{2,})",
    re.IGNORECASE,
)

NAME_ZH_LABELED = re.compile(
    r"(?:姓名|患者姓名|病人姓名|真实姓名)" + _SEP + r"([\u4e00-\u9fff·]{2,6})"
)
NAME_ZH_PATIENT = re.compile(
    r"(?:患者|病人)" + _SEP + r"([\u4e00-\u9fff·]{2,4})"
)
NAME_ZH_GENDER = re.compile(
    r"(?:患者|病人)\s*([\u4e00-\u9fff·]{2,4})(?=\s*[，,]\s*(?:男|女))"
)
NAME_EN_LABELED = re.compile(
    r"(?:Name|Patient name)" + _SEP + r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2})"
)
NAME_EN_TITLED = re.compile(
    r"\b(?:Patient|Mr|Mrs|Ms|Miss|Dr)\.?\s+"
    r"([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,2})"
)
# What a Chinese name field catches that is not a name. A fixed list beats a
# guess here: wrongly redacting "男性" hides a clinical fact.
NAME_STOPWORDS = frozenset(
    {"男性", "女性", "患儿", "成人", "老年", "儿童", "孕妇", "患者", "病人", "家属", "本人",
     "不明", "未知", "匿名", "未提供"}
)

ADDRESS = re.compile(
    r"(?:住址|家庭住址|现住址|联系地址|地址|Address)" + _SEP + r"([^\n，,。；;]{2,60})",
    re.IGNORECASE,
)

INSTITUTION_ZH = re.compile(
    r"(?:(?:就诊于|入住|转入|转至|转院至|来自|就诊|于|在|到|至|住)\s*)?"
    r"([\u4e00-\u9fff]{2,20}?"
    r"(?:人民医院|中心医院|附属医院|医院|医科大学|医学院|研究院|卫生服务中心|"
    r"社区卫生服务中心|卫生院|疾病预防控制中心|疾控中心))"
)
INSTITUTION_EN = re.compile(
    r"\b([A-Z][A-Za-z.'\-]+(?:\s+[A-Z][A-Za-z.'\-]+){0,5}\s+"
    r"(?:University(?:\s+Hospital)?|Hospital|Medical\s+Center|Medical\s+School|"
    r"Institute|Clinic))\b"
)

AGE = re.compile(
    r"(?<!\d)(\d{1,3})\s*(?:岁|years?\s*old|year-old|y/o)(?![A-Za-z])",
    re.IGNORECASE,
)
AGE_AGED = re.compile(r"\b(?:aged|age)\s+(\d{2,3})\b", re.IGNORECASE)

DATE_ISO = re.compile(r"(?<!\d)((?:19|20)\d{2})-(\d{1,2})-(\d{1,2})(?!\d)")
DATE_SLASH = re.compile(r"(?<!\d)((?:19|20)\d{2})/(\d{1,2})/(\d{1,2})(?!\d)")
DATE_ZH = re.compile(
    r"((?:19|20)\d{2})\s*年\s*(\d{1,2})\s*月(?:\s*(\d{1,2})\s*日)?"
    r"|(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)

KIND_LABEL = {
    "NAME": ("name", "names"),
    "ID": ("national ID", "national IDs"),
    "PHONE": ("phone number", "phone numbers"),
    "EMAIL": ("email address", "email addresses"),
    "MRN": ("record number", "record numbers"),
    "ADDRESS": ("address", "addresses"),
    "INSTITUTION": ("institution", "institutions"),
    "AGE": ("age grouped as ≥90", "ages grouped as ≥90"),
}


# --------------------------------------------------------------------------- #
# Replacement machinery
# --------------------------------------------------------------------------- #


class _Tokens:
    """One token per distinct value, stable within a document: the same name
    reads `[NAME-1]` everywhere, so the prose stays readable and the mapping can
    re-identify it."""

    def __init__(self) -> None:
        self.counts: dict[str, int] = {}
        self.by_value: dict[tuple[str, str], str] = {}
        self.map: dict[str, str] = {}

    def get(self, kind: str, value: str) -> str:
        key = (kind, value)
        if key in self.by_value:
            return self.by_value[key]
        number = self.counts.get(kind, 0) + 1
        self.counts[kind] = number
        token = f"[{kind}-{number}]"
        self.by_value[key] = token
        self.map[token] = value
        return token


def _replace_group(
    text: str,
    pattern: re.Pattern[str],
    kind: str,
    tokens: _Tokens,
    group: int = 1,
    skip: frozenset[str] = frozenset(),
    trim=None,
) -> str:
    """Replace one capture group in every match, leaving the label (or the verb
    before an institution) in place. `trim(value) -> int` may strip a prefix
    the pattern had to consume to find the match; the stripped characters stay
    in the text."""
    out: list[str] = []
    last = 0
    for match in pattern.finditer(text):
        start, end = match.span(group)
        if start < last:  # cannot happen within one pattern; guards a future edit
            continue
        value = text[start:end]
        keep = trim(value) if trim is not None else 0
        if len(value) - keep < 2:
            continue
        out.append(text[last:start + keep])
        out.append(value if value in skip else tokens.get(kind, value[keep:]))
        last = end
    out.append(text[last:])
    return "".join(out)


# Institutions in running Chinese text arrive with a genre's worth of prefixes:
# "患者于2024年3月入住北京协和医院" starts its Chinese run at 月. Trim the date
# unit (only when a movement verb follows) and the verb itself, and tokenise
# what remains. Over-redacting an unusual run is the safe failure; leaking the
# ward is not.
_INSTITUTION_LEAD_DATE = "年月日后"
_INSTITUTION_VERBS = (
    "就诊于", "转院至", "转入", "转至", "入住", "来自", "就诊", "于", "在", "到", "至", "住",
)


def _trim_institution_prefix(value: str) -> int:
    trimmed = 0
    while True:
        rest = value[trimmed:]
        for lead in _INSTITUTION_VERBS:
            if rest.startswith(lead) and len(rest) - len(lead) >= 2:
                trimmed += len(lead)
                break
        else:
            if rest[:1] in _INSTITUTION_LEAD_DATE:
                after = rest[1:]
                if len(after) >= 2 and after.startswith(_INSTITUTION_VERBS):
                    trimmed += 1
                    continue
            break
    return trimmed


def _replace_whole(text: str, pattern: re.Pattern[str], kind: str, tokens: _Tokens) -> str:
    return _replace_group(text, pattern, kind, tokens, group=0)


@dataclass
class Scan:
    text: str
    shift_days: int
    tokens: _Tokens = field(default_factory=_Tokens)
    dates: dict[str, str] = field(default_factory=dict)
    ages: dict[str, str] = field(default_factory=dict)

    @property
    def counts(self) -> dict[str, int]:
        counts = dict(self.tokens.counts)
        if self.ages:
            counts["AGE"] = len(self.ages)
        return counts


def _deterministic_shift(raw: bytes) -> int:
    """Same file, same shift — and different files almost never share one. A
    fixed offset per document keeps interval lengths intact while breaking the
    calendar link to the real admission dates."""
    digest = hashlib.sha256(raw).digest()
    magnitude = 1 + int.from_bytes(digest[:2], "big") % 364
    return magnitude if digest[2] % 2 else -magnitude


def _shift_date(year: str, month: str, day: str, days: int) -> tuple[int, int, int] | None:
    try:
        moved = date(int(year), int(month), int(day)) + timedelta(days=days)
    except ValueError:
        return None
    return moved.year, moved.month, moved.day


def _shift_dates(text: str, days: int, scan: Scan) -> str:
    def iso(match: re.Match[str]) -> str:
        moved = _shift_date(match.group(1), match.group(2), match.group(3), days)
        if not moved:
            return match.group(0)
        out = f"{moved[0]:04d}-{moved[1]:02d}-{moved[2]:02d}"
        scan.dates[match.group(0)] = out
        return out

    def slash(match: re.Match[str]) -> str:
        moved = _shift_date(match.group(1), match.group(2), match.group(3), days)
        if not moved:
            return match.group(0)
        out = f"{moved[0]:04d}/{moved[1]:02d}/{moved[2]:02d}"
        scan.dates[match.group(0)] = out
        return out

    def chinese(match: re.Match[str]) -> str:
        if match.group(1) is None:
            # "3月18日": a timeline often names the year once and then writes
            # month-day. Anchor it on a leap year so the arithmetic is valid,
            # and print month-day back — the offset still moves it.
            try:
                moved = date(2000, int(match.group(4)), int(match.group(5))) + timedelta(days=days)
            except ValueError:
                return match.group(0)
            out = f"{moved.month}月{moved.day}日"
            scan.dates[match.group(0)] = out
            return out
        day = match.group(3) or "1"
        moved = _shift_date(match.group(1), match.group(2), day, days)
        if not moved:
            return match.group(0)
        if match.group(3) is None:  # year-month only: keep the month granularity
            out = f"{moved[0]}年{moved[1]}月"
        else:
            out = f"{moved[0]}年{moved[1]}月{moved[2]}日"
        scan.dates[match.group(0)] = out
        return out

    text = DATE_ISO.sub(iso, text)
    text = DATE_SLASH.sub(slash, text)
    return DATE_ZH.sub(chinese, text)


def _group_ages(text: str, scan: Scan) -> str:
    """CARE and most journals group ages over 89; below that an age is clinical
    information, not an identifier."""

    def replace(match: re.Match[str]) -> str:
        if int(match.group(1)) < 90:
            return match.group(0)
        scan.ages[match.group(1)] = "≥90"
        return match.group(0).replace(match.group(1), "≥90", 1)

    text = AGE.sub(replace, text)
    return AGE_AGED.sub(replace, text)


def scan_text(text: str, shift_days: int) -> Scan:
    """Apply every rule in a fixed order: unlabelled numeric identifiers first
    (so a date inside an ID is never shifted), then labelled fields, then ages,
    then dates last."""
    scan = Scan(text=text, shift_days=shift_days)
    tokens = scan.tokens
    text = _replace_whole(text, EMAIL, "EMAIL", tokens)
    text = _replace_whole(text, ID18, "ID", tokens)
    text = _replace_whole(text, ID15, "ID", tokens)
    text = _replace_whole(text, PHONE, "PHONE", tokens)
    text = _replace_group(text, PHONE_LABELED, "PHONE", tokens)
    text = _replace_group(text, MRN, "MRN", tokens)
    text = _replace_group(text, NAME_ZH_LABELED, "NAME", tokens)
    text = _replace_group(text, NAME_ZH_PATIENT, "NAME", tokens, skip=NAME_STOPWORDS)
    text = _replace_group(text, NAME_ZH_GENDER, "NAME", tokens, skip=NAME_STOPWORDS)
    text = _replace_group(text, NAME_EN_LABELED, "NAME", tokens)
    text = _replace_group(text, NAME_EN_TITLED, "NAME", tokens)
    text = _replace_group(text, ADDRESS, "ADDRESS", tokens)
    text = _replace_group(text, INSTITUTION_ZH, "INSTITUTION", tokens, trim=_trim_institution_prefix)
    text = _replace_group(text, INSTITUTION_EN, "INSTITUTION", tokens)
    text = _group_ages(text, scan)
    text = _shift_dates(text, shift_days, scan)
    scan.text = text
    return scan


# --------------------------------------------------------------------------- #
# Review block
# --------------------------------------------------------------------------- #


def findings(scan: Scan) -> list[dict[str, str]]:
    counts = scan.counts
    out: list[dict[str, str]] = []
    for kind in sorted(counts):
        number = counts[kind]
        singular, plural = KIND_LABEL.get(kind, (kind.lower(), kind.lower()))
        tokens = [f"[{kind}-{i}]" for i in range(1, number + 1)] if kind != "AGE" else []
        evidence = (
            f"{number} distinct {'value' if number == 1 else 'values'} replaced"
            + (f"; tokens {', '.join(tokens)}" if tokens else "")
        )
        out.append(
            {
                "level": "warn",
                "tag": f"deidentify · {kind.lower()}",
                "title": f"{number} {singular if number == 1 else plural} replaced",
                "evidence": evidence,
            }
        )
    if scan.dates:
        out.append(
            {
                "level": "warn",
                "tag": "deidentify · date",
                "title": f"{len(scan.dates)} distinct dates shifted by {scan.shift_days:+d} days",
                "evidence": "one offset for the whole document, so intervals inside it are preserved",
            }
        )
    if not out:
        out.append(
            {
                "level": "ok",
                "tag": "deidentify · identifiers",
                "title": "No direct identifiers matched the rules",
                "evidence": "labelled names/record numbers, ID numbers, phones, emails, addresses, institutions, dates",
            }
        )
    return out


def note(scan: Scan, source: Path, out: Path | None, mapping: Path | None) -> str:
    where = (
        "report only — no file was written; run it without --check to write the copy"
        if out is None
        else f"de-identified copy written to {out.name}"
    )
    kept = (
        f"; {mapping.name} re-identifies it and contains the originals"
        if mapping is not None
        else "; no mapping file was written, so the originals are gone from the copy"
    )
    return (
        f"De-identification pass on {source.name}: {where}{kept}. "
        "This is a rule-based first pass, not a guarantee of anonymity — it does not "
        "read images or DICOM metadata, an unlabelled name can survive, and dates were "
        "shifted by one offset (including any citation or lookup date). Review the copy "
        "before sharing it."
    )


def report(
    scan: Scan,
    source: Path,
    out: Path | None,
    mapping: Path | None,
) -> dict:
    return {"findings": findings(scan), "note": note(scan, source, out, mapping)}


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def read_text(path: Path) -> tuple[str, str]:
    """UTF-8 first, then GB18030 (the usual Chinese-Windows fallback). A byte
    sequence that is neither is decoded with replacement and labelled as such
    rather than crashing the gate."""
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return raw.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace"), "utf-8 (replaced)"


def default_out(path: Path) -> Path:
    return path.with_name(f"{path.stem}.deid{path.suffix}")


def mapping_document(scan: Scan, source: Path) -> dict:
    return {
        "notice": (
            f"Identifiers removed from {source.name}. This file re-identifies the "
            "de-identified copy — keep it where patient data belongs, never in the "
            "workspace or an export."
        ),
        "source": source.name,
        "dateShiftDays": scan.shift_days,
        "tokens": scan.tokens.map,
        "dates": scan.dates,
        "ages": scan.ages,
    }


def main(argv: list[str]) -> int:
    # The block can quote a path, and a Chinese Windows console is not UTF-8:
    # degrade unprintable characters instead of failing a finished review.
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(
        prog="deidentify.py",
        description="Replace pattern-matched identifiers and shift dates.",
    )
    parser.add_argument("file", help="document to de-identify (Markdown or plain text)")
    parser.add_argument("--out", help="de-identified copy (default: <name>.deid<suffix>)")
    parser.add_argument("--mapping", help="write the token → original mapping here")
    parser.add_argument(
        "--shift-days",
        type=int,
        default=None,
        help="fixed date offset; default: derived from the file's hash, stable per file",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report only; write neither the copy nor the mapping",
    )
    args = parser.parse_args(argv)
    if args.check and (args.out or args.mapping):
        print("--check writes nothing, so --out/--mapping make no sense with it", file=sys.stderr)
        return 2

    source = Path(args.file)
    if not source.is_file():
        print(f"no such file: {source}", file=sys.stderr)
        return 2
    text, _encoding = read_text(source)
    shift = args.shift_days if args.shift_days is not None else _deterministic_shift(
        source.read_bytes()
    )

    out_path: Path | None = None
    mapping_path: Path | None = None
    if not args.check:
        out_path = Path(args.out) if args.out else default_out(source)
        if out_path.resolve() == source.resolve():
            print("refusing to overwrite the source file; use --out", file=sys.stderr)
            return 2
        if args.mapping:
            mapping_path = Path(args.mapping)
            if mapping_path.resolve() == source.resolve():
                print("refusing to write the mapping over the source file", file=sys.stderr)
                return 2
            if mapping_path.resolve() == out_path.resolve():
                print("refusing to write the mapping over the de-identified copy", file=sys.stderr)
                return 2

    scan = scan_text(text, shift)

    if out_path is not None:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(scan.text, encoding="utf-8", newline="\n")
    if mapping_path is not None:
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(
            json.dumps(mapping_document(scan, source), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )

    print("```review")
    print(
        json.dumps(
            report(scan, source, out_path, mapping_path),
            ensure_ascii=False,
            indent=1,
        )
    )
    print("```")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))