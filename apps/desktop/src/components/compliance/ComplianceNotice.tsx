import { useState } from "react";
import { useTranslation } from "react-i18next";
import { ComplianceText } from "./ComplianceText";

/** localStorage flag: the notice is acknowledged once per install (per browser
 *  for the web client) and never shown again — but `Settings → About` always
 *  carries the same statement, so acknowledging hides the interruption, not the
 *  posture. */
export const COMPLIANCE_ACK_KEY = "ai4s.compliance.v1";

/**
 * Whether this install already acknowledged the boundary. Shared with the
 * first-run orchestration (`FirstRun`) so the setup wizard can wait until the
 * statement is behind the user instead of stacking a second dialog on it.
 */
export function hasAcknowledgedCompliance(): boolean {
  try {
    return window.localStorage.getItem(COMPLIANCE_ACK_KEY) === "1";
  } catch {
    // Storage unavailable (a locked-down webview): do not lock the user out of
    // their own app. The statement still lives in About.
    return true;
  }
}

function alreadyAcknowledged(): boolean {
  return hasAcknowledgedCompliance();
}

/**
 * First-run medical-boundary notice. Blocking on purpose: this is a research
 * tool whose output can look like clinical advice, and the one thing a user
 * must know before the first prompt is that it is not.
 */
export function ComplianceNotice({ onAcknowledged }: { onAcknowledged?: () => void } = {}) {
  const { t } = useTranslation("settings");
  const [open, setOpen] = useState(() => !alreadyAcknowledged());
  if (!open) return null;

  const accept = () => {
    try {
      window.localStorage.setItem(COMPLIANCE_ACK_KEY, "1");
    } catch {
      // Best-effort: the notice reappears next launch rather than failing.
    }
    setOpen(false);
    onAcknowledged?.();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40 p-4"
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="compliance-title"
        className="w-[520px] max-w-full rounded-card border border-border bg-surface p-5 shadow-card"
      >
        <div className="text-[11px] font-semibold uppercase tracking-wide text-accent">
          {t("compliance.badge")}
        </div>
        <h2 id="compliance-title" className="mt-1 font-serif text-xl text-text">
          {t("compliance.title")}
        </h2>
        <div className="mt-3">
          <ComplianceText />
        </div>
        <div className="mt-5 flex flex-col-reverse items-stretch gap-2 sm:flex-row sm:items-center sm:justify-between">
          <span className="text-xs leading-relaxed text-muted">{t("compliance.settingsLink")}</span>
          <button
            type="button"
            onClick={accept}
            className="shrink-0 rounded-input bg-accent px-4 py-2 text-[13px] font-medium text-white transition-opacity hover:opacity-90"
          >
            {t("compliance.ack")}
          </button>
        </div>
      </div>
    </div>
  );
}