// @ts-check
// Toasts: short messages in the bottom-right corner that go away by themselves.
import { el, icon } from "./dom.js";

/** How long a toast stays, in milliseconds, unless the pointer is over it. */
const DURATION_MS = { success: 4000, info: 4000, error: 8000 };

/** @type {HTMLElement | null} */
let stack = null;

/**
 * Show a toast.
 *
 * @param {{
 *   title: string,
 *   message?: string,
 *   level?: "success" | "info" | "error",
 *   action?: {label: string, run: () => any},
 * }} options
 * @returns {() => void} Closes the toast.
 */
export function showToast({ title, message = "", level = "success", action }) {
  if (!stack) {
    stack = el("div.toast-stack", { role: "status", "aria-live": "polite" });
    document.body.append(stack);
  }
  const close = () => {
    toast.classList.add("leaving");
    setTimeout(() => toast.remove(), 180);
  };
  const toast = el(`div.toast.toast-${level}`, {}, [
    el("span.toast-icon", {}, [icon(level === "error" ? "failure" : level === "info" ? "help" : "success")]),
    el("div.toast-text", {}, [el("div.toast-title", { text: title }), message ? el("div.toast-message", { text: message }) : null]),
    action
      ? el("button.button.toast-action", {
          text: action.label,
          onClick: () => {
            close();
            action.run();
          },
        })
      : null,
    el("button.toast-close", { title: "Close", "aria-label": "Close", onClick: close }, [icon("close")]),
  ]);
  stack.append(toast);
  let timer = setTimeout(close, DURATION_MS[level]);
  toast.addEventListener("pointerenter", () => clearTimeout(timer));
  toast.addEventListener("pointerleave", () => {
    timer = setTimeout(close, DURATION_MS[level]);
  });
  return close;
}
