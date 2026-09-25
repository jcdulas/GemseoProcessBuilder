// @ts-check
// Gradients: the size of the gradients of the objective and constraints at each
// iteration, and their last value, design variable by design variable. They are
// what a gradient-based algorithm received from GEMSEO.
import { app } from "../../app.js";
import { seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { el } from "../../components/dom.js";

/**
 * @typedef {object} FunctionGradients - One function of `results.gradients`.
 * @property {string} name
 * @property {string} role
 * @property {number[]} iterations
 * @property {number[]} norms
 * @property {(number | null)[][]} last - One row per component of the function.
 */

/** "1.2e-3", or "—" for a missing value. */
function formatValue(/** @type {number | null} */ value) {
  return value === null ? "—" : Math.abs(value) >= 1e-3 && Math.abs(value) < 1e4 ? value.toPrecision(4) : value.toExponential(2);
}

export class GradientsView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.message = el("p.placeholder");
    this.charts = el("div.history-charts");
    this.table = el("div.gradients-last");
    root.append(this.message, this.charts, this.table);
    this.norms = new LineChart(this.charts);
    this.runId = "";
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    if (source.runId === this.runId) {
      return;
    }
    let data;
    try {
      data = await app.api.call("results.gradients", { id: source.runId }, { timeout: 120_000 });
    } catch (error) {
      this.message.textContent = `The gradients could not be read: ${/** @type {any} */ (error)?.message ?? error}`;
      return;
    }
    this.runId = source.runId;
    /** @type {FunctionGradients[]} */
    const functions = data.functions;
    const any = functions.length > 0;
    this.message.textContent = any
      ? "The gradients GEMSEO gave the algorithm: their size shrinks near an optimum without active constraints."
      : "No gradients: the algorithm of this run did not use derivatives.";
    this.norms.root.hidden = !any;
    this.table.hidden = !any;
    if (!any) {
      return;
    }
    this.norms.update({
      title: "Size of the gradients (Euclidean norm)",
      xLabel: "iteration",
      log: true,
      series: functions.map((item, index) => ({
        name: item.name,
        color: seriesColor(index),
        dashed: item.role === "constraint",
        points: item.iterations.map((x, position) => ({ x, y: item.norms[position] })),
      })),
    });
    // The last gradients, one row per function (and per component of a vector).
    const rows = functions.flatMap((item) =>
      item.last.map((values, component) => ({
        name: item.last.length > 1 ? `${item.name}[${component}]` : item.name,
        role: item.role,
        values,
      })),
    );
    const largest = Math.max(1e-300, ...rows.flatMap((row) => row.values.map((value) => Math.abs(value ?? 0))));
    this.table.replaceChildren(
      el("h3.section-title", { text: "Last gradients, by design variable" }),
      el("table.gradients-table", {}, [
        el("tr", {}, [el("th"), ...data.labels.map((/** @type {string} */ label) => el("th", { text: label }))]),
        ...rows.map((row) =>
          el("tr", {}, [
            el("th", { text: row.name, title: row.role }),
            ...row.values.map((value) => {
              const cell = el("td", { text: formatValue(value) });
              // A bar behind the value shows its size among the others.
              const share = Math.abs(value ?? 0) / largest;
              cell.style.setProperty("--share", `${Math.round(share * 100)}%`);
              cell.classList.toggle("negative", (value ?? 0) < 0);
              return cell;
            }),
          ]),
        ),
      ]),
    );
  }
}
