// @ts-check
// Summary: status, optimum, constraints at the optimum and best feasible point.
import { formatNumber } from "../../charts/axis.js";
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { exportRunCsv } from "../../panels/runs.js";
import { constraintState } from "../../lib/constraints.js";
import { formatElapsed } from "../../shell/run.js";

/** @param {any} value */
function formatValue(value) {
  return Array.isArray(value) ? value.map((item) => formatNumber(item)).join(", ") : formatNumber(value);
}

/**
 * A two-column table of names and values.
 *
 * @param {[string, Node | string][]} rows
 */
function table(rows) {
  return el(
    "table.summary-table",
    {},
    rows.map(([name, value]) => el("tr", {}, [el("th", { text: name }), el("td", {}, [value])])),
  );
}

/**
 * @param {string} title
 * @param {(Node | null)[]} content
 */
function section(title, content) {
  return el("section.summary-section", {}, [el("h3.section-title", { text: title }), ...content]);
}

export class SummaryView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.root = root;
    root.classList.add("summary-view");
    this.token = 0;
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    const token = ++this.token;
    const info = source.info;
    if (!info) {
      this.root.replaceChildren(el("p.placeholder", { text: source.error || "Loading…" }));
      return;
    }
    const summary = info.summary ?? {};
    const record = app.runStates.runs.get(source.runId);
    const duration = info.duration_s != null ? formatElapsed(info.duration_s * 1000) : record ? formatElapsed(performance.now() - record.startedAt) : "";
    const evaluations = summary.n_evaluations ?? record?.data.progress?.current ?? "";
    const general = table(
      /** @type {[string, string][]} */ ([
        ["Driver", info.driver_path || info.driver_name],
        ["Status", `${info.status}${info.error ? ` — ${info.error}` : ""}`],
        ["Duration", duration],
        ["Evaluations", String(evaluations)],
        ["Algorithm", info.algorithm ?? ""],
        ["Formulation", info.formulation ?? ""],
        ["Versions", Object.entries(info.versions ?? {}).map(([name, version]) => `${name} ${version}`).join(", ")],
      ]).filter(([, value]) => value !== ""),
    );
    const sections = [section("Run", [general, this.buttons(source)])];

    if (summary.best_objective !== undefined && summary.best_objective !== null) {
      const rows = /** @type {[string, Node | string][]} */ ([[`${summary.objective} (objective)`, formatValue(summary.best_objective)]]);
      for (const [name, value] of Object.entries(summary.x_opt ?? {})) {
        rows.push([name, formatValue(value)]);
      }
      sections.push(
        section(`Optimum${summary.is_feasible === false ? " (not feasible)" : ""}`, [table(rows)]),
      );
      const types = new Map(source.columns.map((column) => [column.variable, column.constraintType ?? "ineq"]));
      const constraints = Object.entries(summary.constraints ?? {}).map(([name, value]) => {
        const { state, margin } = constraintState(/** @type {any} */ (value), /** @type {any} */ (types.get(name) ?? "ineq"));
        return /** @type {[string, Node]} */ ([
          name,
          el("span", {}, [
            el(`span.constraint-${state}`, { text: state }),
            ` ${formatValue(value)}${state === "satisfied" ? ` (margin ${formatNumber(margin)})` : ""}`,
          ]),
        ]);
      });
      if (constraints.length) {
        sections.push(section("Constraints at the optimum", [table(constraints)]));
      }
    } else if (source.live) {
      sections.push(section("Optimum", [el("p.placeholder", { text: "Known when the run ends." })]));
    }
    this.root.replaceChildren(...sections);
    if (!source.live && !source.error) {
      const best = await this.bestFeasible(source);
      if (best && token === this.token) {
        this.root.append(best);
      }
    }
  }

  /** @param {import("./source.js").ResultsSource} source */
  async bestFeasible(source) {
    const objective = source.byRole("objective")[0] ?? source.byRole("output")[0];
    if (!objective) {
      return null;
    }
    const constrained = source.columns.some((column) => column.name === "feasible");
    let page;
    try {
      page = await app.api.call("results.rows", {
        id: source.runId,
        limit: 1,
        sort: { column: objective.name },
        filters: constrained ? [{ column: "feasible", op: "==", value: 1 }] : [],
      });
    } catch (error) {
      console.error(error);
      return null;
    }
    if (!page.rows.length) {
      return section("Best feasible point", [el("p.placeholder", { text: "No evaluation satisfies the constraints." })]);
    }
    const row = page.rows[0];
    const rows = /** @type {[string, string][]} */ (
      page.columns
        .filter((/** @type {string} */ name) => name !== "feasible")
        .map((/** @type {string} */ name) => [name, formatNumber(row[page.columns.indexOf(name)])])
    );
    return section(`Best ${constrained ? "feasible " : ""}point (lowest ${objective.name})`, [table(rows)]);
  }

  /** @param {import("./source.js").ResultsSource} source */
  buttons(source) {
    /**
     * @param {string} label
     * @param {() => Promise<unknown>} action
     */
    const button = (label, action) =>
      el("button.button.bordered", { text: label, onClick: () => action().catch((error) => showError(label, error)) });
    return el("div.summary-buttons", {}, [
      button("Open the script", () => app.api.call("runs.openFile", { id: source.runId, file: "script.py" })),
      button("Open the log", () => app.api.call("runs.openFile", { id: source.runId, file: "run.log" })),
      button("Show the folder", () => app.api.call("runs.reveal", { id: source.runId })),
      source.live ? null : button("Export CSV…", () => exportRunCsv(source.runId)),
    ]);
  }
}
