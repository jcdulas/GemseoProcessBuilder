// @ts-check
// Compare runs: their objective histories on one chart, their summaries side by side.
import { app } from "../../app.js";
import { formatNumber, seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";

/** @param {any} value */
function formatValue(value) {
  return Array.isArray(value) ? value.map((item) => formatNumber(item)).join(", ") : formatNumber(value);
}

/**
 * Open a tab comparing some runs.
 *
 * @param {string[]} runIds
 */
export async function openCompare(runIds) {
  const page = app.tabs.center.open({ id: `compare-${runIds.join("-")}`, title: `Compare ${runIds.length} runs` });
  page.classList.add("compare-tab");
  page.replaceChildren(el("p.placeholder", { text: "Loading…" }));
  let runs;
  try {
    const summaries = await Promise.all(runIds.map((id) => app.api.call("results.summary", { id }, { timeout: 120_000 })));
    runs = summaries.map((summary, index) => ({ ...summary, color: seriesColor(index) }));
  } catch (error) {
    showError("The runs could not be compared", error);
    page.replaceChildren();
    return;
  }
  const objectives = new Set(runs.map((run) => run.summary?.objective).filter(Boolean));
  const chartBox = el("div.compare-chart");
  page.replaceChildren(summaryTable(runs), chartBox);
  if (objectives.size !== 1) {
    chartBox.append(el("p.placeholder", { text: "These runs have different objectives: their histories cannot be overlaid." }));
    return;
  }
  const [objective] = objectives;
  const histories = await Promise.all(
    runs.map((run) => app.api.call("results.history", { id: run.id, names: [objective] }, { timeout: 120_000 })),
  );
  new LineChart(chartBox).update({
    title: `${objective} against the evaluation number`,
    xLabel: "evaluation",
    series: runs.map((run, index) => ({
      name: run.name || run.id,
      color: run.color,
      points: histories[index].evaluation.map((/** @type {number} */ x, /** @type {number} */ position) => ({
        x,
        y: histories[index].values[objective][position],
      })),
    })),
  });
}

/**
 * The summaries of the runs side by side: one column per run.
 *
 * @param {any[]} runs
 */
function summaryTable(runs) {
  const variables = [...new Set(runs.flatMap((run) => Object.keys(run.summary?.x_opt ?? {})))];
  /** @type {[string, (run: any) => string][]} */
  const rows = [
    ["Driver", (run) => run.driver_path || run.driver_name],
    ["Status", (run) => run.status],
    ["Evaluations", (run) => String(run.summary?.n_evaluations ?? "")],
    ["Algorithm", (run) => run.algorithm ?? ""],
    ["Formulation", (run) => run.formulation ?? ""],
    ["Best objective", (run) => formatValue(run.summary?.best_objective)],
    ["Feasible", (run) => (run.summary?.is_feasible === undefined || run.summary?.is_feasible === null ? "" : run.summary.is_feasible ? "yes" : "no")],
    ...variables.map((name) => /** @type {[string, (run: any) => string]} */ ([name, (run) => formatValue(run.summary?.x_opt?.[name])])),
  ];
  const header = el("tr", {}, [
    el("th"),
    ...runs.map((run) => {
      const swatch = el("span.chart-swatch");
      swatch.style.background = run.color;
      return el("th", {}, [swatch, run.name || run.id]);
    }),
  ]);
  return el("table.summary-table.compare-table", {}, [
    header,
    ...rows.map(([label, value]) => el("tr", {}, [el("th", { text: label }), ...runs.map((run) => el("td", { text: value(run) }))])),
  ]);
}
