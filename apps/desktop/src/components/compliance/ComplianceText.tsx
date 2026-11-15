import { useTranslation } from "react-i18next";

/**
 * The medical-boundary statement, in the user's language. One component so the
 * first-run notice and Settings → About cannot drift apart: the posture is
 * non-negotiable (AGENTS.md) and it is the same sentence in both places.
 *
 * `compact` drops the three supporting points and keeps the headline sentence —
 * for tight surfaces where the long form would be read as boilerplate.
 */
/** Supporting points, as translation-key suffixes rather than display text. */
// eslint-disable-next-line i18next/no-literal-string -- these are i18n keys
const POINTS = ["p1", "p2", "p3"] as const;

export function ComplianceText({ compact = false }: { compact?: boolean }) {
  const { t } = useTranslation("settings");
  return (
    <div className="space-y-2">
      <p className="text-[13px] leading-relaxed text-text">{t("compliance.body")}</p>
      {!compact && (
        <ul className="space-y-1.5">
          {POINTS.map((point) => (
            <li key={point} className="flex gap-2 text-[12.5px] leading-relaxed text-muted">
              <span className="mt-[7px] h-[4px] w-[4px] shrink-0 rounded-full bg-accent" />
              <span>{t(`compliance.${point}`)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}