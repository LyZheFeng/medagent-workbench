import { useState } from "react";
import { isTauri } from "@/lib/tauri";
import { isGatewayWeb } from "@/lib/webMode";
import { ComplianceNotice, hasAcknowledgedCompliance } from "@/components/compliance/ComplianceNotice";
import { OnboardingWizard } from "@/components/onboarding/OnboardingWizard";

/**
 * The two first-run surfaces, in the only order that makes sense: the medical
 * boundary is a statement the user must acknowledge, the setup wizard is an
 * on-ramp. Rendering both at once would stack two blocking dialogs and make the
 * second one's dismissal ambiguous, so the wizard is mounted only after the
 * statement is acknowledged — whether that happened just now or in an earlier
 * launch.
 *
 * Both are desktop/on-ramp surfaces: the gateway web client cannot write
 * provider configuration (the gateway refuses it by design), so the wizard is
 * not rendered there.
 */
export function FirstRun({
  desktop = isTauri,
  web = isGatewayWeb,
}: {
  desktop?: boolean;
  web?: boolean;
} = {}) {
  const [acknowledged, setAcknowledged] = useState(() => hasAcknowledgedCompliance());
  return (
    <>
      <ComplianceNotice onAcknowledged={() => setAcknowledged(true)} />
      {acknowledged && <OnboardingWizard desktop={desktop} web={web} />}
    </>
  );
}