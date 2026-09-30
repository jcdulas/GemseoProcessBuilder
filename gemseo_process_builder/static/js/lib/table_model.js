// @ts-check
// Sorting, filtering and value parsing for editable tables.

/**
 * Parse a value typed in a cell: a number, an array like "[1, 2]", or text.
 * Empty text gives null.
 *
 * @param {string} text
 * @returns {{value: any, error: string | null}}
 */
export function parseValue(text) {
  const trimmed = text.trim();
  if (trimmed === "") {
    return { value: null, error: null };
  }
  if (trimmed.startsWith("[")) {
    try {
      const value = JSON.parse(trimmed);
      if (Array.isArray(value)) {
        return { value, error: null };
      }
    } catch {
      // Reported below.
    }
    return { value: null, error: `"${trimmed}" is not a valid array, like [1, 2.5].` };
  }
  const number = Number(trimmed);
  if (!Number.isNaN(number) && /^[-+]?(\d|\.\d)/.test(trimmed)) {
    return { value: number, error: null };
  }
  if (trimmed === "true" || trimmed === "false") {
    return { value: trimmed === "true", error: null };
  }
  return { value: trimmed, error: null };
}

/**
 * Format a value for a cell.
 *
 * @param {any} value
 * @returns {string}
 */
export function formatValue(value) {
  if (value === null || value === undefined) {
    return "";
  }
  if (Array.isArray(value) || typeof value === "object") {
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * Parse a shape: "" for a scalar, "3" for a vector, "3x4" for a matrix.
 *
 * @param {string} text
 * @returns {{value: number[], error: string | null}}
 */
export function parseShape(text) {
  const trimmed = text.trim().toLowerCase();
  if (trimmed === "" || trimmed === "scalar") {
    return { value: [], error: null };
  }
  const parts = trimmed.split(/\s*[x×,]\s*/);
  if (parts.every((part) => /^\d+$/.test(part) && Number(part) > 0)) {
    return { value: parts.map(Number), error: null };
  }
  return { value: [], error: `"${text}" is not a shape: use 3 for a vector or 3x4 for a matrix.` };
}

/**
 * @param {number[]} shape
 * @returns {string}
 */
export function formatShape(shape) {
  return shape.length === 0 ? "scalar" : shape.join("×");
}

/**
 * Sort rows by a key; the sort is stable and puts empty values last.
 *
 * @template T
 * @param {T[]} rows
 * @param {(row: T) => any} key
 * @param {"asc" | "desc"} direction
 * @returns {T[]}
 */
export function sortRows(rows, key, direction = "asc") {
  const sign = direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index, value: key(row) }))
    .sort((a, b) => {
      const emptyA = a.value === null || a.value === undefined || a.value === "";
      const emptyB = b.value === null || b.value === undefined || b.value === "";
      if (emptyA !== emptyB) {
        return emptyA ? 1 : -1;
      }
      if (a.value < b.value) {
        return -sign;
      }
      if (a.value > b.value) {
        return sign;
      }
      return a.index - b.index;
    })
    .map((entry) => entry.row);
}

/**
 * Keep the rows whose values contain a text (case-insensitive).
 *
 * @template T
 * @param {T[]} rows
 * @param {string} text
 * @param {(row: T) => string[]} values
 * @returns {T[]}
 */
export function filterRows(rows, text, values) {
  const needle = text.trim().toLowerCase();
  if (!needle) {
    return rows;
  }
  return rows.filter((row) => values(row).some((value) => value.toLowerCase().includes(needle)));
}
