// @ts-check
// Bounded storage and filtering of Console lines.

/** Numeric severity of each level, as in Python's logging module. */
export const LEVELS = { DEBUG: 10, INFO: 20, WARNING: 30, ERROR: 40, CRITICAL: 50 };

/**
 * @typedef {object} LogLine
 * @property {number} time - Seconds since the epoch.
 * @property {string} level - DEBUG, INFO, WARNING, ERROR or CRITICAL.
 * @property {string} source - "app", "worker" or "run:<id>".
 * @property {string} message
 * @property {string} [logger]
 */

export class LogBuffer {
  /** @param {number} capacity - The maximum number of lines kept. */
  constructor(capacity = 10000) {
    this.capacity = capacity;
    /** @type {LogLine[]} */
    this.lines = [];
  }

  /** @param {LogLine} line */
  push(line) {
    this.lines.push(line);
    if (this.lines.length > this.capacity) {
      this.lines.splice(0, this.lines.length - this.capacity);
    }
  }

  clear() {
    this.lines = [];
  }

  /**
   * Lines at or above a level whose message, logger or source contains a text.
   *
   * @param {{minLevel?: string, text?: string, source?: string}} [filter]
   * @returns {LogLine[]}
   */
  filtered({ minLevel = "DEBUG", text = "", source = "" } = {}) {
    const threshold = LEVELS[/** @type {keyof LEVELS} */ (minLevel)] ?? 0;
    const needle = text.toLowerCase();
    return this.lines.filter(
      (line) =>
        (LEVELS[/** @type {keyof LEVELS} */ (line.level)] ?? 0) >= threshold &&
        (!source || line.source === source) &&
        (!needle ||
          line.message.toLowerCase().includes(needle) ||
          (line.logger ?? "").toLowerCase().includes(needle)),
    );
  }
}

/**
 * Format a line for display and copying.
 *
 * @param {LogLine} line
 * @returns {string}
 */
export function formatLine(line) {
  const date = new Date(line.time * 1000);
  const time = [date.getHours(), date.getMinutes(), date.getSeconds()]
    .map((part) => String(part).padStart(2, "0"))
    .join(":");
  return `${time} ${line.level.padEnd(7)} [${line.source}] ${line.message}`;
}
