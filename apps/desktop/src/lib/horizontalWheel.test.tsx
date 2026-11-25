// The model-picker's filter chips hide their scrollbar at rest, so a desktop
// mouse had no way to reach the providers past the right edge: no bar to drag,
// and a wheel with no `deltaX` did nothing. These pin the wheel mapping —
// and that it stays out of the way when there is nothing to reveal.

import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { useHorizontalWheel } from "./horizontalWheel";

function Strip() {
  const ref = useHorizontalWheel();
  return <div ref={ref} data-testid="strip" />;
}

function stripWith(contentWidth: number, viewWidth: number) {
  const el = render(<Strip />).getByTestId("strip") as HTMLElement;
  Object.defineProperty(el, "scrollWidth", { value: contentWidth, configurable: true });
  Object.defineProperty(el, "clientWidth", { value: viewWidth, configurable: true });
  el.scrollLeft = 0;
  return el;
}

function wheel(el: HTMLElement, init: WheelEventInit) {
  const event = new WheelEvent("wheel", { bubbles: true, cancelable: true, ...init });
  el.dispatchEvent(event);
  return event;
}

describe("useHorizontalWheel", () => {
  it("scrolls a overflowing strip with a plain vertical wheel", () => {
    const el = stripWith(400, 100);
    const event = wheel(el, { deltaY: 120 });
    expect(el.scrollLeft).toBe(120);
    expect(event.defaultPrevented).toBe(true);
  });

  it("leaves the gesture alone when everything already fits", () => {
    const el = stripWith(100, 100);
    const event = wheel(el, { deltaY: 120 });
    expect(el.scrollLeft).toBe(0);
    expect(event.defaultPrevented).toBe(false);
  });

  it("leaves a horizontal gesture and a pinch-zoom to the browser", () => {
    const el = stripWith(400, 100);
    const sideways = wheel(el, { deltaX: 120, deltaY: 10 });
    expect(el.scrollLeft).toBe(0);
    expect(sideways.defaultPrevented).toBe(false);

    const pinch = wheel(el, { deltaY: 120, ctrlKey: true });
    expect(el.scrollLeft).toBe(0);
    expect(pinch.defaultPrevented).toBe(false);
  });
});