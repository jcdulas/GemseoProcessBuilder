// @ts-check
// Data table: every evaluation, fetched by pages, sorted and filtered by the worker.
import { formatNumber } from "../../charts/axis.js";
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { PagedRows } from "../../lib/paged_rows.js";

const ROW_HEIGHT = 22;
const COLUMN_WIDTH = 110;
const OPERATORS = ["<", "<=", ">", ">=", "==", "!="];

export class DataTable {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.runId = "";
    /** @type {string[]} */
    this.columns = [];
    /** @type {Set<string>} */
    this.hidden = new Set();
    /** @type {{column: string, descending: boolean} | null} */
    this.sort = null;
    /** @type {{column: string, op: string, value: number}[]} */
    this.filters = [];
    this.rows = new PagedRows(200);

    this.columnSelect = /** @type {HTMLSelectElement} */ (el("select.select"));
    this.operatorSelect = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, OPERATORS.map((op) => el("option", { value: op, text: op })))
    );
    this.valueInput = /** @type {HTMLInputElement} */ (el("input.input", { type: "text", placeholder: "value" }));
    this.valueInput.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        this.addFilter();
      }
    });
    this.chips = el("span.filter-chips");
    this.count = el("span.table-count");
    const toolbar = el("div.results-toolbar", {}, [
      el("span", { text: "Filter" }),
      this.columnSelect,
      this.operatorSelect,
      this.valueInput,
      el("button.button.bordered", { text: "Add", onClick: () => this.addFilter() }),
      this.chips,
      el("span.toolbar-spacer"),
      this.count,
      el("button.button.bordered", { text: "Columns…", onClick: (/** @type {MouseEvent} */ event) => this.chooseColumns(event) }),
      el("button.button.bordered", { text: "Export CSV…", onClick: () => this.exportView() }),
    ]);
    this.header = el("div.data-header");
    this.spacer = el("div.data-spacer");
    this.body = el("div.data-body", {}, [this.spacer]);
    this.scroller = el("div.data-scroll", {}, [this.header, this.body]);
    this.scroller.addEventListener("scroll", () => this.render());
    new ResizeObserver(() => this.render()).observe(this.scroller);
    root.append(toolbar, this.scroller);
  }

  /** @param {import("./source.js").ResultsSource} source */
  update(source) {
    if (source.live) {
      this.runId = "";
      this.body.replaceChildren(el("p.placeholder", { text: "The table is available when the run ends." }));
      return;
    }
    const columns = ["evaluation", ...source.columns.map((column) => column.name)];
    if (source.runId !== this.runId || columns.join() !== this.columns.join()) {
      this.runId = source.runId;
      this.columns = columns;
      this.columnSelect.replaceChildren(...columns.map((name) => el("option", { value: name, text: name })));
      this.rows.clear();
      this.body.replaceChildren(this.spacer);
    }
    this.refresh();
  }

  /** The columns shown, in their order. */
  visible() {
    return this.columns.filter((name) => !this.hidden.has(name));
  }

  queryKey() {
    return JSON.stringify([this.sort, this.filters]);
  }

  refresh() {
    this.rows.setQuery(this.queryKey());
    this.renderHeader();
    this.renderChips();
    this.render();
  }

  renderHeader() {
    const width = this.visible().length * COLUMN_WIDTH;
    this.header.style.width = `${width}px`;
    this.spacer.style.width = `${width}px`;
    this.header.replaceChildren(
      ...this.visible().map((name) => {
        const sorted = this.sort?.column === name;
        const cell = el(`div.data-cell.data-heading${sorted ? (this.sort?.descending ? ".sorted-desc" : ".sorted-asc") : ""}`, {
          text: name,
          title: "Sort",
          onClick: () => this.toggleSort(name),
        });
        return cell;
      }),
    );
  }

  /** @param {string} name */
  toggleSort(name) {
    if (this.sort?.column !== name) {
      this.sort = { column: name, descending: false };
    } else if (!this.sort.descending) {
      this.sort = { column: name, descending: true };
    } else {
      this.sort = null;
    }
    this.refresh();
  }

  addFilter() {
    const value = Number(this.valueInput.value);
    if (this.valueInput.value.trim() === "" || Number.isNaN(value)) {
      this.valueInput.setCustomValidity("Enter a number.");
      this.valueInput.reportValidity();
      return;
    }
    this.valueInput.setCustomValidity("");
    this.filters.push({ column: this.columnSelect.value, op: this.operatorSelect.value, value });
    this.valueInput.value = "";
    this.refresh();
  }

  renderChips() {
    this.chips.replaceChildren(
      ...this.filters.map((filter, index) =>
        el("span.filter-chip", {}, [
          `${filter.column} ${filter.op} ${filter.value}`,
          el("button.table-button", {
            text: "×",
            title: "Remove the filter",
            onClick: () => {
              this.filters.splice(index, 1);
              this.refresh();
            },
          }),
        ]),
      ),
    );
  }

  /** @param {MouseEvent} event */
  chooseColumns(event) {
    openContextMenu(
      event.clientX,
      event.clientY,
      this.columns.map((name) => ({
        label: name,
        checked: !this.hidden.has(name),
        run: () => {
          if (this.hidden.has(name)) {
            this.hidden.delete(name);
          } else if (this.visible().length > 1) {
            this.hidden.add(name);
          }
          this.renderHeader();
          this.render(true);
        },
      })),
    );
  }

  /** Draw the visible rows; fetch the missing pages. */
  render(force = false) {
    if (!this.runId) {
      return;
    }
    const total = this.rows.total ?? 0;
    this.spacer.style.height = `${total * ROW_HEIGHT}px`;
    const first = Math.floor(this.scroller.scrollTop / ROW_HEIGHT);
    const last = first + Math.ceil(this.scroller.clientHeight / ROW_HEIGHT);
    for (const page of this.rows.missing(first, last)) {
      this.fetch(page);
    }
    this.count.textContent = this.rows.total === null ? "" : `${total} rows`;
    const indices = this.visible().map((name) => this.columns.indexOf(name));
    const drawn = [];
    for (let index = first; index <= Math.min(last, total - 1); index += 1) {
      const row = this.rows.row(index);
      const element = el(
        "div.data-row",
        {},
        indices.map((column) => el("div.data-cell", { text: row ? formatNumber(row[column]) : "…" })),
      );
      element.style.top = `${index * ROW_HEIGHT}px`;
      drawn.push(element);
    }
    if (force || drawn.length || this.body.childElementCount > 1) {
      this.body.replaceChildren(this.spacer, ...drawn);
    }
  }

  /** @param {number} page */
  async fetch(page) {
    const key = this.queryKey();
    const runId = this.runId;
    this.rows.markLoading(page);
    try {
      const result = await app.api.call("results.rows", {
        id: runId,
        offset: page * this.rows.pageSize,
        limit: this.rows.pageSize,
        sort: this.sort,
        filters: this.filters,
      });
      if (runId === this.runId && this.rows.store(key, page, result.rows, result.total)) {
        this.render();
      }
    } catch (error) {
      showError("The results could not be read", error);
    }
  }

  async exportView() {
    try {
      const folder = await app.api.call("runs.folder", { id: this.runId });
      const path = await app.api.call(
        "dialog.saveFile",
        { title: "Export this view", filter: "CSV files (*.csv)", start: `${folder}/${this.runId}-view.csv` },
        { timeout: 24 * 3600 * 1000 },
      );
      if (path) {
        await app.api.call(
          "runs.exportCsv",
          { id: this.runId, path, names: this.visible(), sort: this.sort, filters: this.filters },
          { timeout: 120_000 },
        );
      }
    } catch (error) {
      showError("The view could not be exported", error);
    }
  }
}
