// @ts-check
// Modal dialogs.
import { el } from "./dom.js";

/**
 * @typedef {object} ModalButton
 * @property {string} label
 * @property {boolean} [primary]
 * @property {() => (boolean | void | Promise<boolean | void>)} [onClick] - Returning
 *   false keeps the dialog open.
 */

/**
 * Open a modal dialog. Escape closes it, Enter triggers the primary button.
 *
 * @param {{title: string, body: Node | string, buttons?: ModalButton[], onClose?: () => void}} options
 *   ``onClose`` is called when the dialog closes, whatever the way.
 * @returns {() => void} A function closing the dialog.
 */
export function openModal({ title, body, buttons = [{ label: "Close", primary: true }], onClose }) {
  const root = /** @type {HTMLElement} */ (document.getElementById("modal-root"));
  const buttonBar = el("div.modal-buttons");
  const backdrop = el("div.modal-backdrop", {}, [
    el("div.modal", { role: "dialog", "aria-label": title }, [
      el("div.modal-title", { text: title }),
      el("div.modal-body", {}, [body]),
      buttonBar,
    ]),
  ]);

  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    backdrop.remove();
    onClose?.();
  };
  /** @param {ModalButton} button */
  const press = async (button) => {
    if ((await button.onClick?.()) !== false) {
      close();
    }
  };
  /** @param {KeyboardEvent} event */
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "Enter" && !(event.target instanceof HTMLTextAreaElement)) {
      const primary = buttons.find((button) => button.primary);
      if (primary) {
        event.preventDefault();
        press(primary);
      }
    }
  };

  for (const button of buttons) {
    buttonBar.append(
      el(`button.button.bordered${button.primary ? ".primary" : ""}`, {
        text: button.label,
        onClick: () => press(button),
      }),
    );
  }
  document.addEventListener("keydown", onKey, true);
  root.append(backdrop);
  /** @type {HTMLElement | null} */ (backdrop.querySelector("input, select, textarea, .primary"))?.focus();
  return close;
}

/**
 * Ask for a confirmation.
 *
 * @param {string} title
 * @param {string} message
 * @param {string} action - Label of the confirming button.
 * @returns {Promise<boolean>} Whether the user confirmed; Escape answers no.
 */
export function askConfirmation(title, message, action) {
  return new Promise((resolve) => {
    openModal({
      title,
      body: el("p", { text: message }),
      buttons: [
        { label: "Cancel", onClick: () => resolve(false) },
        { label: action, primary: true, onClick: () => resolve(true) },
      ],
      // The first answer counts: closing after a button changes nothing.
      onClose: () => resolve(false),
    });
  });
}
