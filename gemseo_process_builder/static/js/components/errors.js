// @ts-check
// Showing errors to the user.
import { el } from "./dom.js";
import { openModal } from "./modal.js";

/**
 * Show an error returned by Python (or any exception) in a dialog.
 *
 * @param {string} title
 * @param {any} error - An ApiError or an Error.
 */
export function showError(title, error) {
  console.error(title, error);
  const details = Array.isArray(error?.details) ? error.details.join("") : "";
  openModal({
    title,
    body: el("div", {}, [
      el("p", { text: error?.message ?? String(error) }),
      details ? el("pre.console-lines", { text: details }) : null,
    ]),
  });
}
