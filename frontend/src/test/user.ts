import userEvent, { PointerEventsCheckLevel } from "@testing-library/user-event";

/**
 * user-event configured for Radix: open menus/dialogs set `pointer-events:
 * none` on the body, which user-event would otherwise refuse to click through.
 */
export function setupUser() {
  return userEvent.setup({ pointerEventsCheck: PointerEventsCheckLevel.Never });
}
