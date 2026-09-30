// @ts-check
// Conversion of keyboard events into shortcut strings like "Ctrl+Shift+S".

/**
 * @typedef {object} KeyLike
 * @property {string} key
 * @property {boolean} [ctrlKey]
 * @property {boolean} [metaKey]
 * @property {boolean} [shiftKey]
 * @property {boolean} [altKey]
 */

const MODIFIER_KEYS = new Set(["Control", "Shift", "Alt", "Meta"]);

/**
 * Normalize the key part of a shortcut.
 *
 * @param {string} key
 * @returns {string}
 */
function normalizeKey(key) {
  if (key === " ") {
    return "Space";
  }
  if (key === "Del") {
    return "Delete";
  }
  return key.length === 1 ? key.toUpperCase() : key;
}

/**
 * Shortcut string of a keyboard event, or null for a lone modifier key.
 * Modifiers come in the order Ctrl, Alt, Shift; Cmd counts as Ctrl.
 *
 * @param {KeyLike} event
 * @returns {string | null}
 */
export function eventToShortcut(event) {
  if (MODIFIER_KEYS.has(event.key)) {
    return null;
  }
  const parts = [];
  if (event.ctrlKey || event.metaKey) {
    parts.push("Ctrl");
  }
  if (event.altKey) {
    parts.push("Alt");
  }
  if (event.shiftKey) {
    parts.push("Shift");
  }
  parts.push(normalizeKey(event.key));
  return parts.join("+");
}

/**
 * Normalize a shortcut written by hand ("shift+ctrl+s" → "Ctrl+Shift+S").
 *
 * @param {string} shortcut
 * @returns {string}
 */
export function normalizeShortcut(shortcut) {
  const parts = shortcut.split("+").map((part) => part.trim());
  const key = parts.pop() ?? "";
  const modifiers = new Set(parts.map((part) => part.toLowerCase()));
  return (
    eventToShortcut({
      key,
      ctrlKey: modifiers.has("ctrl") || modifiers.has("cmd"),
      altKey: modifiers.has("alt"),
      shiftKey: modifiers.has("shift"),
    }) ?? ""
  );
}

/**
 * Whether shortcuts must be ignored because the user is typing in a field.
 *
 * @param {{tagName?: string, isContentEditable?: boolean, type?: string} | null} target
 * @returns {boolean}
 */
export function isTypingTarget(target) {
  if (!target) {
    return false;
  }
  if (target.isContentEditable) {
    return true;
  }
  const tag = (target.tagName ?? "").toUpperCase();
  if (tag === "TEXTAREA" || tag === "SELECT") {
    return true;
  }
  if (tag === "INPUT") {
    return !["button", "checkbox", "radio", "range", "submit"].includes(target.type ?? "text");
  }
  return false;
}

/**
 * Text shown to the user for a shortcut ("Alt+ArrowUp" → "Alt+↑").
 *
 * @param {string} shortcut
 * @returns {string}
 */
export function displayShortcut(shortcut) {
  return shortcut
    .replace("ArrowUp", "↑")
    .replace("ArrowDown", "↓")
    .replace("ArrowLeft", "←")
    .replace("ArrowRight", "→");
}
