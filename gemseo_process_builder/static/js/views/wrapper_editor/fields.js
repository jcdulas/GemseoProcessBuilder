// @ts-check
// Small form controls of the wrapper editor, committing on change.
import { el } from "../../components/dom.js";

/**
 * A labeled row.
 *
 * @param {string} label
 * @param {Node} control
 * @param {string} [hint]
 */
export function row(label, control, hint) {
  return el("div.form-row", {}, [
    el("span.form-label", { text: label }),
    el("div", {}, [control, hint ? el("div.form-hint", { text: hint }) : null]),
  ]);
}

/**
 * A text input.
 *
 * @param {string} value
 * @param {(value: string) => void} commit
 * @param {{placeholder?: string, className?: string}} [options]
 * @returns {HTMLInputElement}
 */
export function textInput(value, commit, { placeholder = "", className = "input" } = {}) {
  const input = /** @type {HTMLInputElement} */ (el(`input.${className}`, { type: "text", placeholder, spellcheck: "false" }));
  input.value = value ?? "";
  input.addEventListener("change", () => commit(input.value));
  return input;
}

/**
 * A select.
 *
 * @param {string} value
 * @param {[string, string][]} options - Values and labels.
 * @param {(value: string) => void} commit
 * @returns {HTMLSelectElement}
 */
export function selectInput(value, options, commit) {
  const select = /** @type {HTMLSelectElement} */ (
    el(
      "select.select",
      {},
      options.map(([key, label]) => el("option", { value: key, text: label })),
    )
  );
  select.value = value;
  select.addEventListener("change", () => commit(select.value));
  return select;
}

/**
 * A small button.
 *
 * @param {string} text
 * @param {() => void} onClick
 * @param {{title?: string, primary?: boolean}} [options]
 */
export function button(text, onClick, { title = "", primary = false } = {}) {
  return el(`button.button.bordered${primary ? ".primary" : ""}`, { text, title, onClick });
}

/**
 * Parse a number typed by the user; an empty text gives the fallback.
 *
 * @param {string} text
 * @param {number | null} fallback
 */
export function parseNumberInput(text, fallback) {
  const trimmed = text.trim();
  if (!trimmed) {
    return fallback;
  }
  const value = Number(trimmed);
  return Number.isFinite(value) ? value : fallback;
}

/**
 * Parse a value or a vector typed by the user: "1.5" or "1, 2, 3".
 *
 * @param {string} text
 * @returns {number | number[] | string}
 */
export function parseValueInput(text) {
  const items = text
    .split(/[\s,;]+/)
    .filter(Boolean)
    .map(Number);
  if (!items.length || items.some((item) => !Number.isFinite(item))) {
    return text.trim();
  }
  return items.length === 1 ? items[0] : items;
}

/** @param {any} value */
export function formatValueInput(value) {
  if (Array.isArray(value)) {
    return value.join(", ");
  }
  return value === null || value === undefined ? "" : String(value);
}
