export const APP_EVENTS = {
  RUN_COMPLETED: "network-agent:run-completed",
} as const;

export function notifyRunCompleted(): void {
  window.dispatchEvent(new CustomEvent(APP_EVENTS.RUN_COMPLETED));
}
