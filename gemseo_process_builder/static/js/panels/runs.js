// @ts-check
// The Runs panel: the runs of the project, with their status and best result.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { EditableTable } from "../components/editable_table.js";
import { showError } from "../components/errors.js";
import { openModal } from "../components/modal.js";
import { formatElapsed } from "../shell/run.js";
import { openResults } from "../views/results/results_tab.js";

/**
 * "2026-09-24 10:15" from an ISO date.
 *
 * @param {string | null | undefined} iso
 */
function formatDate(iso) {
  return iso ? iso.replace("T", " ").slice(0, 16) : "";
}

/** @param {any} value */
function formatObjective(value) {
  if (typeof value === "number") {
    return value.toPrecision(6);
  }
  return Array.isArray(value) ? value.map((item) => Number(item).toPrecision(4)).join(", ") : "";
}

/**
 * Ask for a confirmation.
 *
 * @param {string} title
 * @param {string} message
 * @param {string} action - Label of the confirming button.
 * @returns {Promise<boolean>}
 */
function confirm(title, message, action) {
  return new Promise((resolve) => {
    openModal({
      title,
      body: el("p", { text: message }),
      buttons: [
        { label: "Cancel", onClick: () => resolve(false) },
        { label: action, primary: true, onClick: () => resolve(true) },
      ],
    });
  });
}

/**
 * Export the results of a run to a CSV file chosen by the user.
 *
 * @param {string} runId
 */
export async function exportRunCsv(runId) {
  try {
    const folder = await app.api.call("runs.folder", { id: runId });
    const path = await app.api.call(
      "dialog.saveFile",
      { title: "Export the results", filter: "CSV files (*.csv)", start: `${folder}/${runId}.csv` },
      { timeout: 24 * 3600 * 1000 }, // The dialog waits for the user.
    );
    if (!path) {
      return;
    }
    const result = await app.api.call("runs.exportCsv", { id: runId, path }, { timeout: 120_000 });
    console.info(`Exported ${result.rows} rows to ${result.path}`);
  } catch (error) {
    showError("The results could not be exported", error);
  }
}

export class RunsPanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.notice = el("div.runs-notice");
    const container = el("div.runs-table");
    root.replaceChildren(this.notice, container);
    /** @type {any[]} */
    this.orphans = [];
    this.table = new EditableTable(container, {
      columns: [
        {
          key: "name",
          title: "Run",
          width: 150,
          get: (row) => row.name || row.id,
          editor: "text",
          editable: (row) => !row.missing,
          parse: (text) => ({ value: text.trim(), error: null }),
        },
        { key: "driver", title: "Driver", width: 110, get: (row) => row.driver_path || row.driver_name || row.driver },
        { key: "date", title: "Date", width: 115, get: (row) => formatDate(row.created) },
        {
          key: "duration",
          title: "Duration",
          width: 60,
          get: (row) => row.duration_s ?? -1,
          format: (row) => (row.duration_s == null ? "" : formatElapsed(row.duration_s * 1000)),
        },
        {
          key: "status",
          title: "Status",
          width: 75,
          get: (row) => (row.missing ? "folder missing" : row.status),
        },
        { key: "evaluations", title: "Evaluations", width: 70, get: (row) => row.summary?.n_evaluations ?? "" },
        {
          key: "best",
          title: "Best objective",
          width: 110,
          get: (row) => row.summary?.best_objective ?? null,
          format: (row) => formatObjective(row.summary?.best_objective),
        },
        { key: "open", title: "Open", width: 44, get: () => "", editor: "button", buttonText: "Open", editable: (row) => !row.missing },
        { key: "folder", title: "Folder", width: 52, get: () => "", editor: "button", buttonText: "Folder", editable: (row) => !row.missing },
        { key: "csv", title: "CSV", width: 40, get: () => "", editor: "button", buttonText: "CSV", editable: (row) => !row.missing },
        { key: "delete", title: "Delete", width: 48, get: () => "", editor: "button", buttonText: "×" },
      ],
      onEdit: (row, column, value) => this.act(row, column.key, value),
    });
    app.api.on("runs.changed", () => this.refresh());
    app.api.on("project.changed", () => this.refresh());
    this.refresh();
  }

  async refresh() {
    let listing;
    try {
      listing = await app.api.call("runs.list");
    } catch (error) {
      console.error(error);
      return;
    }
    this.orphans = listing.orphans;
    const runs = [...listing.runs].reverse(); // The latest first.
    this.table.setRows(runs.map((/** @type {any} */ run) => ({ ...run, key: run.id })));
    app.tabs.bottom.setBadge("runs", runs.length);
    this.showNotice(runs.filter((/** @type {any} */ run) => run.missing).length);
  }

  /** @param {number} missing */
  showNotice(missing) {
    const parts = [];
    if (this.orphans.length) {
      parts.push(
        el("span", { text: `${this.orphans.length} run folders on disk are not listed in the project. ` }),
        el("button.button.bordered", { text: "Add them", onClick: () => this.importOrphans() }),
      );
    }
    if (missing) {
      parts.push(
        el("span", { text: ` ${missing} runs have lost their folder. ` }),
        el("button.button.bordered", { text: "Remove them from the list", onClick: () => this.forgetMissing() }),
      );
    }
    this.notice.replaceChildren(...parts);
    this.notice.hidden = !parts.length;
  }

  async importOrphans() {
    const ids = this.orphans.map((orphan) => orphan.id);
    await app.api.call("runs.importOrphans", { ids }).catch((error) => showError("The runs could not be added", error));
  }

  async forgetMissing() {
    await app.api.call("runs.forgetMissing").catch((error) => showError("The list could not be changed", error));
  }

  /**
   * @param {any} row
   * @param {string} action
   * @param {any} value
   */
  async act(row, action, value) {
    try {
      if (action === "name") {
        await app.api.call("runs.rename", { id: row.id, name: value });
      } else if (action === "open") {
        openResults(row.id);
      } else if (action === "folder") {
        await app.api.call("runs.reveal", { id: row.id });
      } else if (action === "csv") {
        await exportRunCsv(row.id);
      } else if (action === "delete") {
        const message = row.missing
          ? `Remove ${row.id} from the list of runs?`
          : `Delete the run ${row.name || row.id} and its folder? This cannot be undone.`;
        if (await confirm("Delete the run", message, "Delete")) {
          await app.api.call("runs.delete", { id: row.id });
        }
      }
    } catch (error) {
      showError("The run could not be changed", error);
    }
  }
}
