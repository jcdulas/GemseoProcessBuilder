// @ts-check
// History: objective, constraints and design variables against the evaluation number.
import { seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { el } from "../../components/dom.js";
import { normalize } from "../../lib/normalize.js";

/** Curves drawn at most per chart; the filter of the results chooses them. */
const MAX_SERIES = 20;

/**
 * "Constraints", or "Constraints (20 of 3,000)".
 *
 * @param {string} title
 * @param {number} shown
 * @param {number} total
 */
function counted(title, shown, total) {
  return shown < total ? `${title} (${shown} of ${total.toLocaleString("en-US")})` : title;
}

export class HistoryView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.log = false;
    const toggle = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox" }));
    toggle.addEventListener("change", () => {
      this.log = toggle.checked;
      if (this.source) {
        this.update(this.source);
      }
    });
    this.toolbar = el("div.results-toolbar", {}, [el("label.form-check", {}, [toggle, el("span", { text: "Log scale for the objective" })])]);
    this.charts = el("div.history-charts");
    root.append(this.toolbar, this.charts);
    this.objective = new LineChart(this.charts);
    this.constraints = new LineChart(this.charts);
    this.variables = new LineChart(this.charts);
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    this.token = 0;
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    this.source = source;
    const token = ++this.token;
    const focus = await source.focus();
    const byName = new Map(source.columns.map((column) => [column.name, column]));
    const kept = (/** @type {string[]} */ names) => names.map((name) => byName.get(name)).filter((column) => column !== undefined);
    const responses = kept(focus.responses);
    const outputs = responses.filter((column) => column.role !== "constraint");
    const constraints = responses.filter((column) => column.role === "constraint");
    const designs = kept(focus.inputs);
    const shown = {
      outputs: outputs.slice(0, MAX_SERIES),
      constraints: constraints.slice(0, MAX_SERIES),
      designs: designs.slice(0, MAX_SERIES),
    };
    await source.ensure([...shown.outputs, ...shown.constraints, ...shown.designs].map((column) => column.name));
    if (token !== this.token) {
      return;
    }
    const isSample = source.byRole("objective").length === 0;
    this.objective.update({
      title: counted(isSample ? "Outputs" : "Objective", shown.outputs.length, outputs.length),
      xLabel: isSample ? "sample" : "iteration",
      log: this.log,
      series: shown.outputs.map((column, index) => ({ name: column.name, color: seriesColor(index), points: source.points(column.name) })),
    });

    this.constraints.root.hidden = !constraints.length;
    this.constraints.update({
      title: counted("Constraints (feasible below 0 for inequalities, at 0 for equalities)", shown.constraints.length, constraints.length),
      xLabel: isSample ? "sample" : "iteration",
      thresholds: [{ value: 0, label: "0" }],
      series: shown.constraints.map((column, index) => ({
        name: column.name,
        color: seriesColor(index + 1),
        dashed: column.constraintType === "eq",
        points: source.points(column.name),
      })),
    });

    const scaled = shown.designs.filter((column) => source.bounds.get(column.name)?.lower != null && source.bounds.get(column.name)?.upper != null);
    const allScaled = scaled.length === shown.designs.length;
    this.variables.root.hidden = !designs.length;
    this.variables.update({
      title: counted(allScaled ? "Design variables, scaled between their bounds" : "Design variables", shown.designs.length, designs.length),
      xLabel: isSample ? "sample" : "iteration",
      yDomain: allScaled ? [0, 1] : undefined,
      series: shown.designs.map((column, index) => {
        const bounds = source.bounds.get(column.name);
        const transform = allScaled ? (/** @type {number | null} */ value) => normalize(value, bounds?.lower, bounds?.upper) : undefined;
        return { name: column.name, color: seriesColor(index), points: source.points(column.name, transform) };
      }),
    });
  }
}
