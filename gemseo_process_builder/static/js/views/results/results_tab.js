// @ts-check
// The Results tab of a run: Summary, History and Table, live during the run.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { DataTable } from "./data_table.js";
import { HistoryView } from "./history.js";
import { ResultsSource } from "./source.js";
import { SummaryView } from "./summary.js";

const VIEWS = [
  { id: "summary", label: "Summary" },
  { id: "history", label: "History" },
  { id: "table", label: "Table" },
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
    this.pages = {
      summary: el("div.results-page"),
      history: el("div.results-page"),
      table: el("div.results-page"),
    };
    page.classList.add("results-tab");
    page.replaceChildren(this.bar, ...Object.values(this.pages));
    this.summary = new SummaryView(this.pages.summary);
    this.history = new HistoryView(this.pages.history);
    this.table = new DataTable(this.pages.table);
    this.loading = false;
    this.show("summary");
    this.reload();
  }

  /** @param {string} view */
  show(view) {
    this.view = view;
    this.bar.replaceChildren(
      ...VIEWS.map((item) =>
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
    this.refreshView();
    if (this.pending) {
      this.pending = false;
      this.reload();
    }
  }

  refreshView() {
    if (!this.page.isConnected) {
      return;
    }
    if (this.view === "summary") {
      this.summary.update(this.source);
    } else if (this.view === "history") {
      this.history.update(this.source);
    } else {
      this.table.update(this.source);
    }
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
