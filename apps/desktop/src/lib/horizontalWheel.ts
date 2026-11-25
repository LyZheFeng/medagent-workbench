import { useCallback, useRef } from "react";

/**
 * Let a plain mouse wheel scroll a horizontal strip.
 *
 * The strips that scroll sideways in this app (the model-picker filter chips,
 * the Screen bar) hide their scrollbar at rest, which leaves a mouse user with
 * no way to reach anything past the right edge: there is no visible bar to
 * drag, and a wheel that carries no `deltaX` never reaches them. A trackpad's
 * two-finger swipe works; a desktop mouse does not.
 *
 * So the strip claims a mostly-vertical wheel: when it actually has content to
 * the right, that gesture moves it sideways instead of doing nothing. A real
 * horizontal gesture (`|deltaX| >= |deltaY|`) is left alone, and so is a
 * ctrl+wheel pinch-zoom.
 *
 * Returns a callback ref, like `useTransientScrollbar`, so a strip that mounts
 * later is still wired up.
 */
export function useHorizontalWheel(): (el: HTMLElement | null) => void {
  const cleanup = useRef<(() => void) | null>(null);
  return useCallback((el: HTMLElement | null) => {
    cleanup.current?.();
    cleanup.current = null;
    if (!el) return;
    const onWheel = (event: WheelEvent) => {
      if (event.defaultPrevented || event.ctrlKey) return;
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      // Nothing to reveal: leave the gesture to the picker's own scrolling.
      if (el.scrollWidth - el.clientWidth <= 1) return;
      event.preventDefault();
      el.scrollLeft += event.deltaY;
    };
    // React's synthetic wheel listener is passive, where preventDefault() is a
    // no-op — this has to be a native one.
    el.addEventListener("wheel", onWheel, { passive: false });
    cleanup.current = () => el.removeEventListener("wheel", onWheel);
  }, []);
}