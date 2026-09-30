// @ts-check
// Keyboard shortcuts, handled by the page because the web view has the focus.
import { eventToShortcut, isTypingTarget } from "../lib/shortcut_keys.js";

/**
 * Route key presses to actions, except while the user types in a field.
 *
 * @param {import("./actions.js").ActionRegistry} actions
 */
export function installShortcuts(actions) {
  document.addEventListener("keydown", (event) => {
    if (document.querySelector(".modal-backdrop")) {
      return; // Dialogs handle their own keys.
    }
    if (isTypingTarget(/** @type {any} */ (event.target))) {
      return;
    }
    const shortcut = eventToShortcut(event);
    const id = shortcut && actions.actionForShortcut(shortcut);
    if (id && actions.invoke(id)) {
      event.preventDefault();
    }
  });
}
