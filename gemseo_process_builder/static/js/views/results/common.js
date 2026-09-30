// @ts-check
// What the point views share: choices of variables, colors and selections.
import { cssColor } from "../../charts/axis.js";
import { el } from "../../components/dom.js";
import { binRange } from "../../lib/binning.js";

/**
 * Beyond this number of evaluations, scatter cells show counts of points in
 * bins instead of the points (SPEC § 12.2, large volumes); the bins are
 * computed by the worker on every evaluation.
 */
export const BINNING_THRESHOLD = 10_000;

/** The most variables a list of choices offers. */
export const MAX_CHOICES = 500;

/**
 * The columns the point views offer, chosen by the filter of the results: the
 * design variables kept (the most important first), then the responses.
 *
 * @param {import("./source.js").ResultsSource} source
 */
export async function focusedNames(source) {
  const focus = await source.focus();
  return {
    focus,
    names: [...focus.inputs.slice(0, MAX_CHOICES), ...focus.responses.slice(0, MAX_CHOICES)],
    /** Changes when the filter does: the views choose their variables again. */
    key: JSON.stringify(source.filter),
  };
}

/**
 * A select element.
 *
 * @param {string[]} options
 * @param {string} value
 * @param {(value: string) => void} onChange
 * @param {{value: string, label: string}[]} [extra] - Options before the others.
 */
export function choice(options, value, onChange, extra = []) {
  const select = /** @type {HTMLSelectElement} */ (
    el("select.select", {}, [
      ...extra.map((item) => el("option", { value: item.value, text: item.label, selected: item.value === value })),
      ...options.map((name) => el("option", { value: name, text: name, selected: name === value })),
    ])
  );
  select.addEventListener("change", () => onChange(select.value));
  return select;
}

/**
 * A labelled control of a toolbar.
 *
 * @param {string} label
 * @param {HTMLElement} control
 */
export function labelled(label, control) {
  return el("label.toolbar-field", {}, [el("span", { text: label }), control]);
}

/**
 * The color of each point: by feasibility, by a variable, or one color.
 *
 * @param {string} mode - "feasible", "none" or a column name.
 * @param {Record<string, (number | null)[]>} columns
 * @returns {(index: number) => string}
 */
export function pointColors(mode, columns) {
  const d3 = /** @type {any} */ (window).d3;
  if (mode === "feasible") {
    const feasible = columns.feasible;
    if (!feasible) {
      return () => cssColor("--color-accent");
    }
    const good = cssColor("--color-success");
    const bad = cssColor("--color-error");
    return (index) => (feasible[index] === 1 ? good : feasible[index] === 0 ? bad : cssColor("--color-state-pending"));
  }
  if (mode !== "none" && columns[mode]) {
    const values = columns[mode];
    const scale = d3
      .scaleSequential(d3.interpolateRgb(cssColor("--color-accent-soft"), cssColor("--color-driver-optimization")))
      .domain(binRange(values));
    return (index) => (values[index] === null ? "none" : scale(values[index]));
  }
  return () => cssColor("--color-accent");
}

/**
 * The positions of the points brushed, or ``null`` when nothing is brushed.
 *
 * @param {Set<number> | null} selection - Evaluation numbers.
 * @param {number[]} evaluations
 * @returns {Set<number> | null}
 */
export function selectedPositions(selection, evaluations) {
  if (!selection) {
    return null;
  }
  const positions = new Set();
  evaluations.forEach((evaluation, index) => {
    if (selection.has(evaluation)) {
      positions.add(index);
    }
  });
  return positions;
}

/**
 * A short explanation shown instead of a view.
 *
 * @param {HTMLElement} root
 * @param {string} text
 */
export function explain(root, text) {
  root.replaceChildren(el("p.placeholder", { text }));
}
