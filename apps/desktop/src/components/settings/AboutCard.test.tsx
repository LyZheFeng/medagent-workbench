import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AboutCard } from "./AboutCard";

describe("Settings → About", () => {
  it("names the build and keeps the medical boundary reachable after first run", () => {
    render(<AboutCard />);

    expect(screen.getByText("About")).toBeInTheDocument();
    expect(screen.getByText("Version")).toBeInTheDocument();
    // The statement is the same copy the first-run notice shows; it must not
    // drift into a softer promise here.
    expect(screen.getByText(/gives no diagnosis, treatment or prescribing advice/i)).toBeInTheDocument();
    expect(screen.getByText(/Not for clinical decisions/i)).toBeInTheDocument();
    // Both home pages are real links (AppShell opens them externally).
    expect(screen.getByRole("link", { name: "Project home" })).toHaveAttribute(
      "href",
      "https://github.com/LyZheFeng/medagent-workbench",
    );
    expect(screen.getByRole("link", { name: "Upstream project" })).toHaveAttribute(
      "href",
      "https://github.com/ai4s-research/open-science",
    );
  });
});