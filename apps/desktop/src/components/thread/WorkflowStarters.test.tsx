import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import i18n from "@/i18n";
import { WORKFLOW_STARTERS, WorkflowStarters, promptForLocale } from "./WorkflowStarters";

// Plain closures instead of vi.fn: tinyspy's result tracking derives an extra
// promise from a rejecting spy, which vitest then reports as unhandled.
const installCalls: string[] = [];
let failInstall = false;
vi.mock("@/lib/tauri", () => ({
  isTauri: true,
  installExample: async (name: string) => {
    installCalls.push(name);
    if (failInstall) throw new Error("resource missing");
    return name;
  },
}));

describe("WorkflowStarters", () => {
  beforeEach(() => {
    installCalls.length = 0;
    failInstall = false;
  });

  it("renders one card per starter workflow, including the clinical example", () => {
    render(<WorkflowStarters onPick={() => {}} />);
    // Titles are i18n-translated (session:starters.<id>.title); WORKFLOW_STARTERS
    // itself no longer carries display copy, only ids/prompts — assert the
    // rendered English text directly.
    expect(screen.getByText("Run a demo diagnostic-accuracy analysis, end to end")).toBeInTheDocument();
    expect(screen.getByText("Analyze my clinical data")).toBeInTheDocument();
    expect(screen.getByText("Audit a medical report for traceability")).toBeInTheDocument();
    expect(screen.getByText("Explore an example: diagnostic-accuracy study")).toBeInTheDocument();
    expect(WORKFLOW_STARTERS).toHaveLength(4);
  });

  it("sends the full-workflow prompt on click", async () => {
    const onPick = vi.fn();
    render(<WorkflowStarters onPick={onPick} />);
    await userEvent.click(screen.getByText("Run a demo diagnostic-accuracy analysis, end to end"));
    await waitFor(() => expect(onPick).toHaveBeenCalledWith(expect.stringContaining("figure1.png")));
    expect(onPick.mock.calls[0][0]).toContain("report.md");
    expect(installCalls).toHaveLength(0);
  });

  it("installs the example files before sending the clinical prompt", async () => {
    const onPick = vi.fn();
    render(<WorkflowStarters onPick={onPick} />);

    await userEvent.click(screen.getByText("Explore an example: diagnostic-accuracy study"));
    await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
    expect(installCalls).toEqual(["clinical-diagnostics"]);
    expect(onPick.mock.calls[0][0]).toContain("diagnostic_test.csv");
  });

  it("does not send the prompt when the example install fails", async () => {
    failInstall = true;
    const onPick = vi.fn();
    render(<WorkflowStarters onPick={onPick} />);

    await userEvent.click(screen.getByText("Explore an example: diagnostic-accuracy study"));
    await waitFor(() => expect(installCalls).toHaveLength(1));
    expect(onPick).not.toHaveBeenCalled();
  });
});

describe("workflow prompt language", () => {
  // The instruction is what the agent reads, so a Chinese UI must not send an
  // English request: that is why every answer came back in English.
  it("picks the Chinese instruction for a Chinese UI and English otherwise", () => {
    const demo = WORKFLOW_STARTERS.find((s) => s.id === "demo")!;
    expect(promptForLocale(demo, "zh-Hans")).toContain("端到端");
    expect(promptForLocale(demo, "zh-CN")).toContain("端到端");
    expect(promptForLocale(demo, "en")).toContain("end to end");
    expect(promptForLocale(demo, "ja")).toContain("end to end");
  });

  it("sends the Chinese prompt when the interface is Chinese", async () => {
    const onPick = vi.fn();
    await i18n.changeLanguage("zh-Hans");
    try {
      render(<WorkflowStarters onPick={onPick} />);
      await userEvent.click(screen.getByText("运行一次诊断试验演示分析"));
      await waitFor(() => expect(onPick).toHaveBeenCalledTimes(1));
      expect(onPick.mock.calls[0][0]).toContain("demo_analysis/figure1.png");
      expect(onPick.mock.calls[0][0]).toContain("端到端");
    } finally {
      await i18n.changeLanguage("en");
    }
  });
});
