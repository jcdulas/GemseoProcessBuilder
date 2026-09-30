/**
 * Numbers in the sample input file of a wrapper (SPEC § 7.5): which numbers a
 * selection covers, how they are written, and the template marker replacing
 * them. Pure: tested with node.
 */

/** A number, also in Fortran notation (1.5D+03). */
const NUMBER = /[-+]?(?:\d+\.?\d*|\.\d+)(?:[eEdD][-+]?\d+)?/g;

/** The value of a number token; NaN when it is not one. */
export function parseNumber(text) {
  const cleaned = text.trim().replace(/[dD]/, "e");
  if (!/^[-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?$/i.test(cleaned)) return NaN;
  return Number(cleaned);
}

/**
 * The number tokens of a text, with their offsets. Digits inside words
 * (x1, run_2) are not numbers.
 * @returns {{start: number, end: number, text: string, value: number}[]}
 */
export function numberTokens(text) {
  const tokens = [];
  for (const match of text.matchAll(NUMBER)) {
    const start = match.index;
    const end = start + match[0].length;
    const before = text[start - 1] ?? "";
    const after = text[end] ?? "";
    if (/[\w.]/.test(before) || /[A-Za-z_]/.test(after)) continue;
    tokens.push({ start, end, text: match[0], value: parseNumber(match[0]) });
  }
  return tokens;
}

/** The number token under an offset (a click), or null. */
export function numberAt(text, offset) {
  return numberTokens(text).find((token) => token.start <= offset && offset <= token.end) ?? null;
}

/**
 * The Python format writing numbers like this one, so that the input file keeps
 * its layout: `.6e` for 1.234560e+00, `12.4f` for a field of width 12, `.0f`
 * for an integer. The field is the token with the spaces selected before it.
 */
export function guessFormat(field) {
  const token = field.trim();
  const padded = field.replace(/\s+$/, "");
  const width = padded.length > token.length ? String(padded.length) : "";
  const exponent = token.match(/^[-+]?\d*\.?(\d*)([eEdD])/);
  if (exponent) {
    // Python writes no Fortran D: E keeps the look of the file.
    const letter = exponent[2] === "e" ? "e" : "E";
    return `${width}.${exponent[1].length}${letter}`;
  }
  const decimals = token.includes(".") ? token.split(".")[1].length : 0;
  return `${width}.${decimals}f`;
}

/**
 * The numbers a selection covers and how they are separated.
 * @returns {{values: number[], separator: string, format: string} | null} null
 *   when the selection holds no number, or text other than numbers.
 */
export function selectionNumbers(selected) {
  const tokens = numberTokens(selected);
  if (!tokens.length) return null;
  let rest = selected;
  for (const token of [...tokens].reverse()) rest = rest.slice(0, token.start) + rest.slice(token.end);
  if (!/^[\s,;]*$/.test(rest)) return null;
  let separator = " ";
  if (tokens.length > 1) {
    const between = selected.slice(tokens[0].end, tokens[1].start);
    if (between.includes("\n")) separator = "\n";
    else if (between.includes(",")) separator = between.replace(/ +$/, " ").replace(/^ +/, "");
    else if (between.includes(";")) separator = between.trim() + " ";
  }
  const first = selected.slice(0, tokens[0].end);
  const field = tokens.length === 1 ? first.slice(first.lastIndexOf("\n") + 1) : tokens[0].text;
  return { values: tokens.map((token) => token.value), separator, format: guessFormat(field) };
}

/** The template marker of an input: {{x}} or {{x:.6e}}. */
export function markerText(name, format = "") {
  return format ? `{{${name}:${format}}}` : `{{${name}}}`;
}

/**
 * Replace a selection of the sample by the marker of an input.
 * @param {{format?: string}} [options] The format of the marker: guessed from
 *   the selection when undefined, none when empty.
 * @returns {{text: string, port: {name: string, size: number, default: number | number[]}, separator: string} | null}
 *   the new template, the input it declares and the vector separator it needs.
 */
export function replaceByMarker(text, start, end, name, { format } = {}) {
  const found = selectionNumbers(text.slice(start, end));
  if (!found) return null;
  // Spaces selected before a number belong to its field, written by the format.
  const marker = markerText(name, format ?? found.format);
  const values = found.values;
  const port = { name, size: values.length, default: values.length === 1 ? values[0] : values };
  return { text: text.slice(0, start) + marker + text.slice(end), port, separator: found.separator };
}

/** The markers of a template, as runtime/templates.py reads them. */
const MARKER = /(?<!\\)\{\{\s*([A-Za-z_][\w.:-]*?)\s*(?::([^{}]*))?\}\}/g;

/**
 * The markers of a template.
 * @returns {{start: number, end: number, name: string, format: string}[]}
 */
export function templateMarkers(text) {
  return [...text.matchAll(MARKER)].map((match) => ({
    start: match.index,
    end: match.index + match[0].length,
    name: match[1],
    format: (match[2] ?? "").trim(),
  }));
}

/** Rename the markers of an input. */
export function renameMarkers(text, oldName, newName) {
  let result = text;
  for (const marker of templateMarkers(text).reverse()) {
    if (marker.name === oldName) {
      result = result.slice(0, marker.start) + markerText(newName, marker.format) + result.slice(marker.end);
    }
  }
  return result;
}

/**
 * A number written with a Python format of the kinds guessed here: `.6e`,
 * `12.4f`, `.0f` (other formats write the number as it is).
 */
export function formatNumber(value, format = "") {
  const found = format.match(/^(\d*)\.(\d+)([efE])$/);
  if (!found) return String(value);
  const [, width, precision, kind] = found;
  let text = kind === "f" ? value.toFixed(Number(precision)) : value.toExponential(Number(precision));
  if (kind !== "f") {
    // Python writes two exponent digits at least: 1.5e+03, 1.5e-07.
    text = text.replace(/e([+-])(\d)$/, (_, sign, digit) => `e${sign}0${digit}`);
    if (kind === "E") text = text.toUpperCase();
  }
  return text.padStart(Number(width || 0));
}

/** The text of a marker written back with a value (when a marker is removed). */
export function markerValueText(value, format = "", separator = " ") {
  const values = Array.isArray(value) ? value : [value ?? 0];
  return values.map((item) => formatNumber(Number(item), format)).join(separator);
}
