import { beforeEach, describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { COMPLIANCE_ACK_KEY, ComplianceNotice } from "./ComplianceNotice";

beforeEach(() => window.localStorage.clear());

describe("the first-run medical boundary", () => {
  it("blocks the first launch and cannot be dismissed without acknowledging", () => {
    render(<ComplianceNotice />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(/not a medical device/i);
    expect(dialog).toHaveTextContent(/reviewed by a qualified researcher/i);
    // No close button, no escape hatch: the only way out is the acknowledgement.
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("remembers the acknowledgement, so it is a first-run notice and not a nag", () => {
    const first = render(<ComplianceNotice />);
    fireEvent.click(screen.getByRole("button", { name: /i understand/i }));
    expect(window.localStorage.getItem(COMPLIANCE_ACK_KEY)).toBe("1");
    expect(screen.queryByRole("dialog")).toBeNull();
    first.unmount();

    render(<ComplianceNotice />);
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});