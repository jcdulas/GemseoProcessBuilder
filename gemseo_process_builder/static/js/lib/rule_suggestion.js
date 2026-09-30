/**
 * Output rules suggested from a selection in a sample output file (SPEC § 7.5).
 *
 * The rules follow runtime/parsing.py: the editor previews each suggestion
 * with it and keeps those reading the selected value. Pure: tested with node.
 */

import { numberAt, numberTokens } from "./number_selection.js";

/** How far above a value its marker line may be. */
const MAX_MARKER_DISTANCE = 3;

const NUMBER_GROUP = "([-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eEdD][-+]?\\d+)?)";

/** The lines of a text with their start offsets. */
export function lineStarts(text) {
  const starts = [0];
  for (let index = 0; index < text.length; index += 1) if (text[index] === "\n") starts.push(index + 1);
  return starts;
}

function lineIndex(starts, offset) {
  let index = 0;
  while (index + 1 < starts.length && starts[index + 1] <= offset) index += 1;
  return index;
}

/** The whitespace-separated column of the token starting at an offset of a line. */
export function columnOf(line, offset) {
  const before = line.slice(0, offset).trim();
  return before ? before.split(/\s+/).length : 0;
}

/** A regular expression matching a text literally, any run of spaces matching any other. */
export function escapeRegex(text) {
  return text
    .replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
    .replace(/\s+/g, "\\s+");
}

const hasLetter = (text) => /[A-Za-z]/.test(text);

/** The nearest line above with a label, as a marker: {index, marker} or null. */
function markerAbove(lines, index) {
  for (let above = index - 1; above >= Math.max(0, index - MAX_MARKER_DISTANCE); above -= 1) {
    const marker = lines[above].trim();
    if (hasLetter(marker)) return { index: above, marker };
  }
  return null;
}

/** Suggestions for one value. */
function scalarRules(lines, index, token, lineStart) {
  const line = lines[index];
  const offset = token.start - lineStart;
  const label = line.slice(0, offset).trim();
  const rules = [];
  for (const separator of ["=", ":"]) {
    const at = line.indexOf(separator);
    if (at < 0 || at >= offset) continue;
    const key = line.slice(0, at).trim();
    const value = line.slice(at + 1).trim();
    if (key && value === token.text) {
      rules.push({ label: `Key "${key}"`, rule: { kind: "key_value", key, ...(separator === "=" ? {} : { separator }) } });
    }
  }
  const column = columnOf(line, offset);
  if (hasLetter(label)) {
    rules.push({ label: `After "${label}"`, rule: { kind: "marker", marker: label, line: 0, column } });
  }
  const above = markerAbove(lines, index);
  if (above) {
    rules.push({
      label: `Under "${above.marker}"`,
      rule: { kind: "marker", marker: above.marker, line: index - above.index, column },
    });
  }
  if (hasLetter(label)) {
    const pattern = `${escapeRegex(label)}\\s*${NUMBER_GROUP}`;
    rules.push({ label: "Regular expression", rule: { kind: "regex", pattern } });
    rules.push({ label: "Regular expression, last match", rule: { kind: "regex", pattern, occurrence: "last" } });
  }
  return rules;
}

/** Suggestions for a column of values on consecutive lines. */
function tableRules(lines, first, last, column) {
  const above = markerAbove(lines, first);
  if (!above) return [];
  const rule = { kind: "table", marker: above.marker, column };
  if (first - above.index > 1) rule.skip = first - above.index - 1;
  const next = lines[last + 1] ?? "";
  // The table ends on an empty line by default, else on the line after it.
  if (next.trim()) {
    if (!hasLetter(next)) return [];
    rule.end = next.trim();
  }
  return [{ label: `Table under "${above.marker}"`, rule }];
}

/**
 * The rules that may read a selection: a value (a click or a selected number)
 * or a column of values (a selection over several lines).
 * @param {string} text The sample output.
 * @param {number} start The selection start (or the clicked offset).
 * @param {number} end The selection end.
 * @returns {{label: string, rule: object}[]} Rules without variable and file.
 */
export function suggestRules(text, start, end = start) {
  const lines = text.split("\n");
  const starts = lineStarts(text);
  const tokens = numberTokens(text).filter((token) => token.end > start && token.start < end);
  const firstLine = lineIndex(starts, start);
  const lastLine = lineIndex(starts, Math.max(start, end - 1));
  if (firstLine === lastLine || tokens.length <= 1) {
    const token = tokens[0] ?? numberAt(text, start);
    if (!token) return [];
    const index = lineIndex(starts, token.start);
    return scalarRules(lines, index, token, starts[index]);
  }
  // One value per line, in the column of the first one.
  const firstToken = tokens[0];
  const column = columnOf(lines[firstLine], firstToken.start - starts[firstLine]);
  return tableRules(lines, lineIndex(starts, firstToken.start), lastLine, column);
}

/** Whether a previewed value is the selected one (numbers or vectors). */
export function sameValue(read, expected, tolerance = 1e-12) {
  const close = (a, b) => typeof a === "number" && Math.abs(a - b) <= tolerance * Math.max(1, Math.abs(b));
  if (Array.isArray(expected)) {
    return Array.isArray(read) && read.length === expected.length && read.every((value, index) => close(value, expected[index]));
  }
  return close(read, expected);
}
