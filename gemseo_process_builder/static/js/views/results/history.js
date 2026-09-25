// @ts-check
// History: objective, constraints and design variables against the evaluation number.
import { seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { el } from "../../components/dom.js";
import { normalize } from "../../lib/normalize.js";

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
  }

  /** @param {import("./source.js").ResultsSource} source */
  update(source) {
    this.source = source;
    const isSample = source.byRole("objective").length === 0;
    const outputs = [...source.byRole("objective"), ...source.byRole("output"), ...source.byRole("observable")];
    this.objective.update({
      title: isSample ? "Outputs" : "Objective",
      xLabel: isSample ? "sample" : "iteration",
      log: this.log,
      series: outputs.map((column, index) => ({ name: column.name, color: seriesColor(index), points: source.points(column.name) })),
    });

    const constraints = source.byRole("constraint");
    this.constraints.root.hidden = !constraints.length;
    this.constraints.update({
      title: "Constraints (feasible below 0 for inequalities, at 0 for equalities)",
      xLabel: isSample ? "sample" : "iteration",
      thresholds: [{ value: 0, label: "0" }],
      series: constraints.map((column, index) => ({
        name: column.name,
        color: seriesColor(index + 1),
        dashed: column.constraintType === "eq",
        points: source.points(column.name),
      })),
    });

    const designs = source.byRole("design variable");
    const scaled = designs.filter((column) => source.bounds.get(column.name)?.lower != null && source.bounds.get(column.name)?.upper != null);
    this.variables.root.hidden = !designs.length;
    this.variables.update({
      title: scaled.length === designs.length ? "Design variables, scaled between their bounds" : "Design variables",
      xLabel: isSample ? "sample" : "iteration",
      yDomain: scaled.length === designs.length ? [0, 1] : undefined,
      series: designs.map((column, index) => {
        const bounds = source.bounds.get(column.name);
        const transform = scaled.length === designs.length
          ? (/** @type {number | null} */ value) => normalize(value, bounds?.lower, bounds?.upper)
          : undefined;
        return { name: column.name, color: seriesColor(index), points: source.points(column.name, transform) };
      }),
    });
  }
}
