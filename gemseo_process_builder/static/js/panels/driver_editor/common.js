// @ts-check
// Helpers shared by the tabs of the driver editor.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { pickerItems } from "../../lib/driver_config.js";

/**
 * @typedef {object} Variable
 * @property {string} name - Global name.
 * @property {string} dtype
 * @property {number} size
 * @property {any} default
 * @property {string | null} unit
 *
 * @typedef {object} DriverVariables
 * @property {Variable[]} inputs - Free inputs of the driver scope.
 * @property {Variable[]} outputs - Outputs computed in the scope.
 * @property {Variable[]} couplings - Outputs also used as inputs (IDF design variables).
 * @property {Record<string, string[]>} roles
 *
 * @typedef {object} TabContext
 * @property {any} driver - The driver node of the store.
 * @property {ReturnType<typeof import("../../lib/driver_config.js").withDefaults>} config
 * @property {"model" | "bilevel" | "nested"} placement - Where the driver runs.
 * @property {() => Promise<DriverVariables>} variables - Loaded on demand.
 *
 * @typedef {object} TabView
 * @property {HTMLElement} element
 * @property {(context: TabContext) => void} [update] - Refresh in place; else the tab is rebuilt.
 */

/**
 * Change one field of the configuration of a driver (one undo step).
 *
 * @param {string} id
 * @param {string} field
 * @param {any} value
 */
export function setConfig(id, field, value) {
  return app.store.execute({ type: "setDriverConfig", id, field, value }).catch((error) => {
    showError("The driver could not be changed", error);
    throw error;
  });
}

/**
 * A button opening a menu of variables to pick.
 *
 * @param {string} label
 * @param {() => Promise<{name: string, size: number}[]>} candidates
 * @param {() => string[]} used - Names already picked (shown disabled).
 * @param {(name: string) => void} pick
 */
export function pickButton(label, candidates, used, pick) {
  const button = el("button.button.bordered", { text: label });
  button.addEventListener("click", async () => {
    const box = button.getBoundingClientRect();
    let items;
    try {
      items = pickerItems(await candidates(), used());
    } catch (error) {
      showError("The variables could not be listed", error);
      return;
    }
    openContextMenu(
      box.left,
      box.bottom,
      items.length
        ? items.map((item) => ({ label: item.label, enabled: item.enabled, run: () => pick(item.name) }))
        : [{ label: "No variable available", enabled: false, run: () => {} }],
    );
  });
  return button;
}

/**
 * The header of a tab: a title, a hint and buttons.
 *
 * @param {string} hint
 * @param {(HTMLElement | null)[]} buttons
 */
export function tabHeader(hint, buttons = []) {
  return el("div.driver-tab-header", {}, [el("p.form-hint", { text: hint }), el("div.driver-tab-buttons", {}, buttons)]);
}

/**
 * A copy of a list with one item replaced (or removed when ``item`` is null).
 *
 * @template T
 * @param {T[]} items
 * @param {number} index
 * @param {T | null} item
 * @returns {T[]}
 */
export function replaced(items, index, item) {
  const copy = [...items];
  if (item === null) {
    copy.splice(index, 1);
  } else {
    copy[index] = item;
  }
  return copy;
}
