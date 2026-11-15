import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { OPENCODE_VERSION } from "@ai4s/sdk";
import { useUpdateStore } from "@/lib/update";
import { ComplianceText } from "@/components/compliance/ComplianceText";
import { Section } from "./Section";

const REPO = "https://github.com/LyZheFeng/medagent-workbench";
const UPSTREAM = "https://github.com/ai4s-research/open-science";

/**
 * Settings → About: what this build is, and the medical boundary that applies
 * to everything it produces. The statement is the same component the first-run
 * notice renders, so the two can never say different things.
 */
export function AboutCard() {
  const { t } = useTranslation(["settings", "common"]);
  const version = useUpdateStore((s) => s.currentVersion);

  return (
    <>
      <Section title={t("about.title")}>
        <div className="space-y-2.5 text-[13px]">
          <Line label={t("about.version")}>
            <span className="font-mono">{version}</span>
          </Line>
          <Line label={t("about.runtime")}>
            <span className="font-mono">{`OpenCode ${OPENCODE_VERSION}`}</span>
          </Line>
          <Line label={t("about.license")}>
            <span className="text-muted">{t("about.licenseText")}</span>
          </Line>
          <div className="flex flex-wrap gap-x-4 gap-y-1 pt-0.5">
            <a className="text-accent underline-offset-2 hover:underline" href={REPO}>
              {t("about.repo")}
            </a>
            <a className="text-accent underline-offset-2 hover:underline" href={UPSTREAM}>
              {t("about.upstream")}
            </a>
          </div>
        </div>
      </Section>

      <Section title={t("about.complianceTitle")} hint={t("compliance.badge")}>
        <ComplianceText />
      </Section>
    </>
  );
}

/** One label/value row; the label column stays narrow so long values wrap. */
function Line({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex gap-4">
      <span className="w-24 shrink-0 text-muted">{label}</span>
      <span className="min-w-0 break-words">{children}</span>
    </div>
  );
}