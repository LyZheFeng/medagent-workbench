#!/usr/bin/env python3
"""Sample size and power for clinical studies, stdlib-only.

Five designs, each with the formula named in the output so a reader can check
it against a textbook:

  two-proportions   superiority, two independent proportions (Fleiss)
  non-inferiority   one-sided margin on a risk difference (equal allocation)
  means             two independent means, mean difference and pooled SD
  accuracy          sensitivity/specificity CI precision (Buderer), given prevalence
  survival          number of events for a log-rank comparison (Schoenfeld)

Every design reports the rounded-up sample size AND the power actually achieved
at that size, because "n = 93" is a rounded number and the achieved power is the
number the protocol should quote. `--dropout` inflates the size for anticipated
losses; the review block keeps both values.

Usage:
    python stats_power.py two-proportions --p1 0.50 --p2 0.30 --power 0.80
    python stats_power.py non-inferiority --p1 0.50 --p2 0.50 --margin 0.10
    python stats_power.py means --delta 5 --sd 10 --power 0.80
    python stats_power.py accuracy --sensitivity 0.90 --specificity 0.85 \
        --half-width 0.05 --prevalence 0.30
    python stats_power.py survival --hr 0.70 --event-rate 0.60 --power 0.80

Defaults: alpha 0.05 (two-sided except non-inferiority, which is one-sided),
power 0.80, allocation ratio 1, no dropout.

Exit codes: 0 computed; 2 bad input. Output is one human summary plus one
```review JSON block, matching the other medical-stats gates.

(Console text is deliberately ASCII: this runs on a Chinese Windows console,
where an en dash or a multiplication sign raises UnicodeEncodeError.)
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from statistics import NormalDist

NORMAL = NormalDist()


class PowerError(Exception):
    """An input this design cannot use (a proportion outside 0-1, p1 == p2...)."""


def _z(alpha: float, two_sided: bool) -> float:
    return NORMAL.inv_cdf(1 - alpha / 2 if two_sided else 1 - alpha)


def _check_fraction(name: str, value: float) -> float:
    if not (0.0 < value < 1.0):
        raise PowerError(f"{name} must be between 0 and 1 (exclusive), got {value:g}")
    return value


def _check_alpha(alpha: float) -> float:
    return _check_fraction("alpha", alpha)


def _check_power(power: float) -> float:
    return _check_fraction("power", power)


def _check_ratio(ratio: float) -> float:
    if not (ratio > 0.0):
        raise PowerError(f"ratio must be positive, got {ratio:g}")
    return ratio


def _check_dropout(dropout: float) -> float:
    if not (0.0 <= dropout < 1.0):
        raise PowerError(f"dropout must be in [0, 1), got {dropout:g}")
    return dropout


def _inflate(n: float, dropout: float) -> int:
    return math.ceil(n / (1.0 - dropout))


def _two_proportions(p1: float, p2: float, alpha: float, power: float,
                     ratio: float) -> dict:
    _check_fraction("p1", p1)
    _check_fraction("p2", p2)
    if p1 == p2:
        raise PowerError("two-proportions needs p1 != p2; a zero difference has "
                         "no finite sample size")
    za = _z(alpha, two_sided=True)
    zb = NORMAL.inv_cdf(power)
    pbar = (p1 + ratio * p2) / (1.0 + ratio)
    n1 = ((za * math.sqrt((1.0 + 1.0 / ratio) * pbar * (1.0 - pbar))
           + zb * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2) / ratio)) ** 2
          / (p1 - p2) ** 2)
    n1 = math.ceil(n1)
    n2 = math.ceil(n1 * ratio)
    achieved = NORMAL.cdf((math.sqrt(n1) * abs(p1 - p2)
                           - za * math.sqrt((1.0 + 1.0 / ratio)
                                            * pbar * (1.0 - pbar)))
                          / math.sqrt(p1 * (1.0 - p1)
                                      + p2 * (1.0 - p2) / ratio))
    return {"n1": n1, "n2": n2, "total": n1 + n2,
            "achieved_power": achieved}


def _non_inferiority(p1: float, p2: float, margin: float, alpha: float,
                     power: float) -> dict:
    _check_fraction("p1", p1)
    _check_fraction("p2", p2)
    if not (margin > 0.0):
        raise PowerError(f"margin must be positive, got {margin:g}")
    expected = p1 - p2
    effect = margin - expected
    if not (effect > 0.0):
        raise PowerError(
            f"margin ({margin:g}) must exceed the expected difference "
            f"({expected:g}); otherwise the alternative is not non-inferior")
    za = _z(alpha, two_sided=True)
    zb = NORMAL.inv_cdf(power)
    n1 = ((za + zb) ** 2 * (p1 * (1.0 - p1) + p2 * (1.0 - p2))
          / effect ** 2)
    n1 = math.ceil(n1)
    achieved = NORMAL.cdf(
        math.sqrt(n1) * effect
        / math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2)) - za)
    return {"n1": n1, "n2": n1, "total": 2 * n1, "achieved_power": achieved}


def _means(delta: float, sd: float, alpha: float, power: float,
           ratio: float) -> dict:
    if not (delta > 0.0):
        raise PowerError(f"delta must be positive, got {delta:g}")
    if not (sd > 0.0):
        raise PowerError(f"sd must be positive, got {sd:g}")
    za = _z(alpha, two_sided=True)
    zb = NORMAL.inv_cdf(power)
    n1 = math.ceil((za + zb) ** 2 * sd ** 2 * (1.0 + 1.0 / ratio) / delta ** 2)
    n2 = math.ceil(n1 * ratio)
    achieved = NORMAL.cdf(
        math.sqrt(n1) * delta / math.sqrt(sd ** 2 * (1.0 + 1.0 / ratio)) - za)
    return {"n1": n1, "n2": n2, "total": n1 + n2,
            "achieved_power": achieved}


def _accuracy(sensitivity: float, specificity: float, half_width: float,
              prevalence: float, alpha: float) -> dict:
    _check_fraction("sensitivity", sensitivity)
    _check_fraction("specificity", specificity)
    _check_fraction("prevalence", prevalence)
    if not (half_width > 0.0):
        raise PowerError(f"half-width must be positive, got {half_width:g}")
    z = _z(alpha, two_sided=True)
    diseased = math.ceil(z * z * sensitivity * (1.0 - sensitivity)
                         / half_width ** 2)
    non_diseased = math.ceil(z * z * specificity * (1.0 - specificity)
                             / half_width ** 2)
    for_sensitivity = math.ceil(diseased / prevalence)
    for_specificity = math.ceil(non_diseased / (1.0 - prevalence))
    total = max(for_sensitivity, for_specificity)
    warnings = []
    if min(diseased, non_diseased) < 20:
        warnings.append("fewer than 20 participants in one group; the normal "
                        "approximation behind Buderer's method is unreliable "
                        "there")
    return {
        "n_diseased": diseased,
        "n_non_diseased": non_diseased,
        "n_for_sensitivity": for_sensitivity,
        "n_for_specificity": for_specificity,
        "n1": total, "n2": 0, "total": total,
        "achieved_power": None,
        "binding": ("sensitivity" if for_sensitivity >= for_specificity
                    else "specificity"),
    }, warnings


def _survival(hr: float, event_rate: float, alpha: float, power: float,
              ratio: float) -> dict:
    if not (hr > 0.0) or hr == 1.0:
        raise PowerError("hr must be positive and not 1; a hazard ratio of 1 "
                         "has no finite event count")
    _check_fraction("event-rate", event_rate)
    za = _z(alpha, two_sided=True)
    zb = NORMAL.inv_cdf(power)
    events = math.ceil((za + zb) ** 2 * (1.0 + ratio) ** 2
                       / (ratio * math.log(hr) ** 2))
    achieved = NORMAL.cdf(math.sqrt(events * ratio / (1.0 + ratio) ** 2)
                          * abs(math.log(hr)) - za)
    n_total = math.ceil(events / event_rate)
    n1 = math.ceil(n_total / (1.0 + ratio))
    n2 = n_total - n1
    return {"events": events, "n1": n1, "n2": n2, "total": n_total,
            "achieved_power": achieved}


def _emit(design: str, inputs: dict, result: dict, method: str,
          warnings: list[str]) -> None:
    print("```review")
    print(json.dumps({"gate": "medical-stats/stats_power", "design": design,
                      "inputs": inputs, "result": result, "method": method,
                      "warnings": warnings}, ensure_ascii=False, indent=1))
    print("```")


def _common(ns) -> dict:
    return {"alpha": ns.alpha, "power": ns.power, "ratio": ns.ratio,
            "dropout": ns.dropout}


def _report(design: str, inputs: dict, result: dict, method: str,
            warnings: list[str]) -> None:
    if result["n2"]:
        print(f"  n per group: {result['n1']} / {result['n2']} "
              f"(total {result['total']})")
    else:
        print(f"  n required: {result['total']}")
    if result.get("events"):
        print(f"  events required: {result['events']}")
    if result.get("achieved_power") is not None:
        print(f"  power at n: {result['achieved_power']:.4f}")
    for warning in warnings:
        print(f"  warning: {warning}")
    _emit(design, inputs, result, method, warnings)


def _apply_dropout(result: dict, dropout: float) -> dict:
    if dropout == 0.0:
        return result
    inflated = dict(result)
    if result["n2"]:
        inflated["n1"] = math.ceil(result["n1"] / (1.0 - dropout))
        inflated["n2"] = math.ceil(result["n2"] / (1.0 - dropout))
        inflated["total"] = inflated["n1"] + inflated["n2"]
    else:
        inflated["total"] = _inflate(result["total"], dropout)
        inflated["n1"] = inflated["total"]
    return inflated


def cmd_two_proportions(ns) -> int:
    _check_alpha(ns.alpha)
    _check_power(ns.power)
    _check_ratio(ns.ratio)
    _check_dropout(ns.dropout)
    result = _two_proportions(ns.p1, ns.p2, ns.alpha, ns.power, ns.ratio)
    warnings = []
    if min(result["n1"], result["n2"]) < 20:
        warnings.append("fewer than 20 per group; the normal approximation is "
                        "unreliable there")
    method = ("Fleiss normal approximation for two independent proportions, "
              "allocation ratio n2/n1")
    inputs = {"p1": ns.p1, "p2": ns.p2, **_common(ns)}
    print(f"two-proportions: p1={ns.p1:g}, p2={ns.p2:g}, "
          f"alpha={ns.alpha:g} (two-sided), power={ns.power:g}, "
          f"ratio={ns.ratio:g}")
    if ns.dropout:
        print(f"  dropout {ns.dropout:.0%}: inflating n")
        result = _apply_dropout(result, ns.dropout)
    _report("two-proportions", inputs, result, method, warnings)
    return 0


def cmd_non_inferiority(ns) -> int:
    _check_alpha(ns.alpha)
    _check_power(ns.power)
    _check_ratio(ns.ratio)
    _check_dropout(ns.dropout)
    if ns.ratio != 1.0:
        raise PowerError("non-inferiority is implemented for equal allocation "
                         "(ratio 1); unequal allocation needs a different formula")
    result = _non_inferiority(ns.p1, ns.p2, ns.margin, ns.alpha, ns.power)
    warnings = []
    if result["n1"] < 20:
        warnings.append("fewer than 20 per group; the normal approximation is "
                        "unreliable there")
    method = ("one-sided normal approximation at alpha/2 for a risk-difference "
              "margin; the alternative effect is margin minus the expected "
              "difference")
    inputs = {"p1": ns.p1, "p2": ns.p2, "margin": ns.margin, **_common(ns)}
    print(f"non-inferiority: p1={ns.p1:g}, p2={ns.p2:g}, margin={ns.margin:g}, "
          f"alpha={ns.alpha:g} (one-sided at alpha/2), power={ns.power:g}")
    if ns.dropout:
        print(f"  dropout {ns.dropout:.0%}: inflating n")
        result = _apply_dropout(result, ns.dropout)
    _report("non-inferiority", inputs, result, method, warnings)
    return 0


def cmd_means(ns) -> int:
    _check_alpha(ns.alpha)
    _check_power(ns.power)
    _check_ratio(ns.ratio)
    _check_dropout(ns.dropout)
    result = _means(ns.delta, ns.sd, ns.alpha, ns.power, ns.ratio)
    warnings = []
    if min(result["n1"], result["n2"]) < 20:
        warnings.append("fewer than 20 per group; the normal approximation is "
                        "unreliable there")
    method = "two-sample z approximation for a mean difference and pooled SD"
    inputs = {"delta": ns.delta, "sd": ns.sd, **_common(ns)}
    print(f"means: delta={ns.delta:g}, sd={ns.sd:g}, alpha={ns.alpha:g} "
          f"(two-sided), power={ns.power:g}, ratio={ns.ratio:g}")
    if ns.dropout:
        print(f"  dropout {ns.dropout:.0%}: inflating n")
        result = _apply_dropout(result, ns.dropout)
    _report("means", inputs, result, method, warnings)
    return 0


def cmd_accuracy(ns) -> int:
    _check_alpha(ns.alpha)
    _check_dropout(ns.dropout)
    result, warnings = _accuracy(ns.sensitivity, ns.specificity,
                                 ns.half_width, ns.prevalence, ns.alpha)
    if ns.dropout:
        print(f"  dropout {ns.dropout:.0%}: inflating n")
        result = _apply_dropout(result, ns.dropout)
    method = ("Buderer precision method: n = z^2 p(1-p) / half-width^2 per "
              "group, divided by prevalence (or 1 - prevalence) for the total")
    inputs = {"sensitivity": ns.sensitivity, "specificity": ns.specificity,
              "half_width": ns.half_width, "prevalence": ns.prevalence,
              "alpha": ns.alpha, "dropout": ns.dropout}
    print(f"accuracy: sensitivity={ns.sensitivity:g}, "
          f"specificity={ns.specificity:g}, half-width={ns.half_width:g}, "
          f"prevalence={ns.prevalence:g}, alpha={ns.alpha:g} (two-sided)")
    print(f"  diseased needed: {result['n_diseased']} "
          f"(total {result['n_for_sensitivity']} at this prevalence)")
    print(f"  non-diseased needed: {result['n_non_diseased']} "
          f"(total {result['n_for_specificity']})")
    print(f"  binding constraint: {result['binding']}")
    _report("accuracy", inputs, result, method, warnings)
    return 0


def cmd_survival(ns) -> int:
    _check_alpha(ns.alpha)
    _check_power(ns.power)
    _check_ratio(ns.ratio)
    _check_dropout(ns.dropout)
    result = _survival(ns.hr, ns.event_rate, ns.alpha, ns.power, ns.ratio)
    warnings = []
    if result["events"] < 20:
        warnings.append("fewer than 20 events; the log-rank approximation is "
                        "unreliable there")
    method = ("Schoenfeld: events = (z_alpha/2 + z_beta)^2 (1+r)^2 / "
              "(r (ln HR)^2), then N = events / event proportion")
    inputs = {"hr": ns.hr, "event_rate": ns.event_rate, **_common(ns)}
    print(f"survival: hr={ns.hr:g}, event-rate={ns.event_rate:g}, "
          f"alpha={ns.alpha:g} (two-sided), power={ns.power:g}, "
          f"ratio={ns.ratio:g}")
    if ns.dropout:
        print(f"  dropout {ns.dropout:.0%}: inflating N (events unchanged)")
        result = _apply_dropout(result, ns.dropout)
    _report("survival", inputs, result, method, warnings)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="stats_power.py",
        description="Sample size and power: two proportions, non-inferiority, "
                    "means, diagnostic accuracy precision, survival events. "
                    "Stdlib only.")
    sub = parser.add_subparsers(dest="design", required=True)

    def common(p):
        p.add_argument("--alpha", type=float, default=0.05,
                       help="type I error (default 0.05)")
        p.add_argument("--power", type=float, default=0.80,
                       help="desired power (default 0.80)")
        p.add_argument("--ratio", type=float, default=1.0,
                       help="allocation ratio n2/n1 (default 1)")
        p.add_argument("--dropout", type=float, default=0.0,
                       help="anticipated loss to follow-up, 0-1 (default 0)")

    two = sub.add_parser("two-proportions",
                         help="superiority test for two independent proportions")
    common(two)
    two.add_argument("--p1", type=float, required=True, help="proportion in arm 1")
    two.add_argument("--p2", type=float, required=True, help="proportion in arm 2")
    two.set_defaults(func=cmd_two_proportions)

    ni = sub.add_parser("non-inferiority",
                        help="non-inferiority margin on a risk difference")
    common(ni)
    ni.add_argument("--p1", type=float, required=True)
    ni.add_argument("--p2", type=float, required=True)
    ni.add_argument("--margin", type=float, required=True,
                    help="non-inferiority margin (positive)")
    ni.set_defaults(func=cmd_non_inferiority)

    means = sub.add_parser("means", help="two independent means")
    common(means)
    means.add_argument("--delta", type=float, required=True,
                       help="mean difference to detect")
    means.add_argument("--sd", type=float, required=True, help="pooled SD")
    means.set_defaults(func=cmd_means)

    acc = sub.add_parser("accuracy",
                         help="sensitivity/specificity CI precision (Buderer)")
    acc.add_argument("--sensitivity", type=float, required=True)
    acc.add_argument("--specificity", type=float, required=True)
    acc.add_argument("--half-width", type=float, required=True,
                     help="desired 95% CI half-width (absolute)")
    acc.add_argument("--prevalence", type=float, required=True)
    acc.add_argument("--alpha", type=float, default=0.05)
    acc.add_argument("--dropout", type=float, default=0.0)
    acc.set_defaults(func=cmd_accuracy)

    surv = sub.add_parser("survival",
                          help="events for a log-rank comparison (Schoenfeld)")
    common(surv)
    surv.add_argument("--hr", type=float, required=True,
                      help="hazard ratio to detect (not 1)")
    surv.add_argument("--event-rate", type=float, required=True,
                      help="expected proportion of participants with an event")
    surv.set_defaults(func=cmd_survival)
    return parser


def main(argv: list[str]) -> int:
    try:
        sys.stdout.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass
    parser = build_parser()
    try:
        ns = parser.parse_args(argv)
    except SystemExit as exit_:
        return int(exit_.code) if isinstance(exit_.code, int) else 2
    try:
        return ns.func(ns)
    except PowerError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))