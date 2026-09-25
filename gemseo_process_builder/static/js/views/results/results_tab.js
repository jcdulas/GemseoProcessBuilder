// @ts-check
// The Results tab of a run: summary, history, table and the point views.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { DataTable } from "./data_table.js";
import { HistoryView } from "./history.js";
import { ParallelCoordinates } from "./parallel_coordinates.js";
import { ParametricView } from "./parametric.js";
import { PostprocessingView } from "./postprocessing.js";
import { ScatterMatrix } from "./scatter_matrix.js";
import { ResultsSource } from "./source.js";
import { SummaryView } from "./summary.js";
import { XYPlot } from "./xy_plot.js";

const VIEWS = [
  { id: "summary", label: "Summary" },
  { id: "history", label: "History" },
  { id: "table", label: "Table" },
  { id: "scatter", label: "Scatter matrix" },
  { id: "xy", label: "XY plot" },
  { id: "parallel", label: "Parallel coordinates" },
  { id: "parametric", label: "Parametric" },
  { id: "postproc", label: "Post-processing" },
];

/** @type {Map<string, ResultsTab>} */
const opened = new Map();

class ResultsTab {
  /**
   * @param {HTMLElement} page
   * @param {string} runId
   */
  constructor(page, runId) {
    this.page = page;
    this.source = new ResultsSource(runId);
    this.view = "summary";
    this.bar = el("div.results-tabs");
    /** @type {Record<string, HTMLElement>} */
    this.pages = Object.fromEntries(VIEWS.map((view) => [view.id, el("div.results-page")]));
    page.classList.add("results-tab");
    page.replaceChildren(this.bar, ...Object.values(this.pages));
    /** @type {Record<string, {update: (source: ResultsSource) => unknown}>} */
    this.views = {
      summary: new SummaryView(this.pages.summary),
      history: new HistoryView(this.pages.history),
      table: new DataTable(this.pages.table),
      scatter: new ScatterMatrix(this.pages.scatter),
      xy: new XYPlot(this.pages.xy),
      parallel: new ParallelCoordinates(this.pages.parallel),
      parametric: new ParametricView(this.pages.parametric),
      postproc: new PostprocessingView(this.pages.postproc),
    };
    this.loading = false;
    this.show("summary");
    this.reload();
  }

  /** @param {string} view */
  show(view) {
    this.view = view;
    this.bar.replaceChildren(
      ...VIEWS.filter((item) => item.id !== "parametric" || this.isStudy()).map((item) =>
        el(`button.driver-tab-button${item.id === view ? ".active" : ""}`, { text: item.label, onClick: () => this.show(item.id) }),
      ),
    );
    for (const [id, element] of Object.entries(this.pages)) {
      element.hidden = id !== view;
    }
    this.refreshView();
  }

  /** Read the data again (live events, or the worker after the run). */
  async reload() {
    if (this.loading) {
      this.pending = true;
      return;
    }
    this.loading = true;
    try {
      await this.source.load();
    } finally {
      this.loading = false;
    }
    this.show(this.view); // The list of views depends on the results.
    if (this.pending) {
      this.pending = false;
      this.reload();
    }
  }

  /** Whether the run is a parametric study of one or two variables (a grid of values). */
  isStudy() {
    const inputs = this.source.byRole("design variable").length;
    return this.source.info?.algorithm === "CustomDOE" && inputs >= 1 && inputs <= 2;
  }

  refreshView() {
    if (!this.page.isConnected) {
      return;
    }
    this.views[this.view].update(this.source);
  }
}

/**
 * Open the Results tab of a run (or bring it to the front).
 *
 * @param {string} runId
 * @param {{view?: string, activate?: boolean}} [options]
 */
export function openResults(runId, { view, activate = true } = {}) {
  const previous = app.tabs.center.active;
  const page = app.tabs.center.open({
    id: `results-${runId}`,
    title: `Results: ${runId}`,
    onClose: () => opened.delete(runId),
  });
  let tab = opened.get(runId);
  if (!tab) {
    tab = new ResultsTab(page, runId);
    opened.set(runId, tab);
  }
  if (view) {
    tab.show(view);
  }
  if (!activate && previous) {
    app.tabs.center.activate(previous);
  }
  // Reopened with the project next time.
  app.store
    .execute({ type: "setLayout", extra: { last_results: runId } }, { undoable: false })
    .catch((/** @type {unknown} */ error) => console.error(error));
}

/** Follow the runs: live updates, then the final results. */
export function installResults() {
  app.runStates.onChange((record) => {
    const tab = opened.get(record.info.id);
    if (tab) {
      tab.reload();
    }
  });
  app.api.on("run.finished", (/** @type {any} */ info) => opened.get(info.id)?.reload());
  // Reopen the results shown last, once the project and its runs are known.
  const restore = async () => {
    const last = app.store.state.view["extra.last_results"];
    if (!last || opened.has(last)) {
      return;
    }
    const { runs } = await app.api.call("runs.list");
    if (runs.some((/** @type {any} */ run) => run.id === last && !run.missing)) {
      openResults(last, { activate: false });
    }
  };
  app.store.subscribe((event) => {
    if (event.type === "reset") {
      restore();
    }
  });
  restore();
}
