// @ts-check
// A virtualized table whose cells can be edited in place.
import { filterRows, sortRows } from "../lib/table_model.js";
import { el } from "./dom.js";
import { VirtualList } from "./virtual_list.js";

/**
 * @typedef {object} Column
 * @property {string} key
 * @property {string} title
 * @property {number} width - In pixels.
 * @property {(row: any) => any} get - The value shown (and sorted on).
 * @property {(row: any) => string} [format] - Text shown; defaults to String(get).
 * @property {"text" | "select" | "checkbox" | "button"} [editor]
 * @property {string[] | ((row: any) => string[])} [options] - For "select".
 * @property {(text: string, row: any) => {value: any, error: string | null}} [parse]
 * @property {(row: any) => boolean} [editable]
 * @property {string} [buttonText] - For "button".
 * @property {string} [datalist] - For "text": the id of a ``<datalist>`` of suggestions.
 */

export class EditableTable {
  /**
   * @param {HTMLElement} container
   * @param {{
   *   columns: Column[],
   *   onEdit: (row: any, column: Column, value: any) => Promise<void> | void,
   *   filterable?: boolean,
   * }} options
   */
  constructor(container, { columns, onEdit, filterable = true }) {
    this.columns = columns;
    this.onEdit = onEdit;
    /** @type {any[]} */
    this.rows = [];
    /** @type {{key: string, direction: "asc" | "desc"} | null} */
    this.sort = null;
    this.filterText = "";
    /** @type {Map<string, string>} */
    this.errors = new Map();

    this.root = el("div.editable-table");
    if (filterable) {
      this.root.append(
        el("input.input.table-filter", {
          type: "search",
          placeholder: "Filter…",
          onInput: (/** @type {Event} */ event) => {
            this.filterText = /** @type {HTMLInputElement} */ (event.target).value;
            this.refresh();
          },
        }),
      );
    }
    this.header = el("div.table-row.table-header");
    for (const column of columns) {
      const cell = el("div.table-cell", {
        text: column.title,
        title: "Sort",
        onClick: () => this.toggleSort(column.key),
      });
      cell.style.width = `${column.width}px`;
      this.header.append(cell);
    }
    // Header and body scroll horizontally together; the body scrolls vertically.
    const totalWidth = columns.reduce((sum, column) => sum + column.width, 0) + 2;
    const scroller = el("div.table-scroll");
    const inner = el("div.table-inner");
    inner.style.width = `${totalWidth}px`;
    const body = el("div.table-body");
    inner.append(this.header, body);
    scroller.append(inner);
    this.root.append(scroller);
    this.list = new VirtualList(body, { renderRow: (row) => this.renderRow(row) });
    container.append(this.root);
  }

  /** @param {any[]} rows */
  setRows(rows) {
    this.rows = rows;
    this.refresh();
  }

  refresh() {
    let rows = filterRows(this.rows, this.filterText, (row) =>
      this.columns.filter((column) => column.editor !== "button").map((column) => this.text(column, row)),
    );
    if (this.sort) {
      const column = this.columns.find((candidate) => candidate.key === this.sort?.key);
      if (column) {
        rows = sortRows(rows, column.get, this.sort.direction);
      }
    }
    for (const cell of this.header.children) {
      cell.classList.remove("sorted-asc", "sorted-desc");
    }
    if (this.sort) {
      const index = this.columns.findIndex((column) => column.key === this.sort?.key);
      this.header.children[index]?.classList.add(`sorted-${this.sort.direction}`);
    }
    this.list.setRows(rows);
  }

  /** @param {string} key */
  toggleSort(key) {
    if (this.sort?.key !== key) {
      this.sort = { key, direction: "asc" };
    } else if (this.sort.direction === "asc") {
      this.sort = { key, direction: "desc" };
    } else {
      this.sort = null;
    }
    this.refresh();
  }

  /**
   * @param {Column} column
   * @param {any} row
   */
  text(column, row) {
    if (column.format) {
      return column.format(row);
    }
    const value = column.get(row);
    return value === null || value === undefined ? "" : String(value);
  }

  /** @param {any} row */
  renderRow(row) {
    const element = el("div.table-row");
    for (const column of this.columns) {
      const editable = column.editor && (column.editable?.(row) ?? true);
      const cell = el("div.table-cell", {}, []);
      cell.style.width = `${column.width}px`;
      const errorKey = `${row.key}:${column.key}`;
      if (this.errors.has(errorKey)) {
        cell.classList.add("cell-error");
        cell.title = this.errors.get(errorKey) ?? "";
      }
      if (column.editor === "checkbox") {
        const box = /** @type {HTMLInputElement} */ (
          el("input", { type: "checkbox", disabled: !editable, checked: Boolean(column.get(row)) })
        );
        box.addEventListener("change", () => this.commit(row, column, box.checked));
        cell.append(box);
      } else if (column.editor === "button") {
        cell.append(
          el("button.table-button", {
            text: column.buttonText ?? "…",
            title: column.title,
            disabled: !editable,
            onClick: () => this.commit(row, column, null),
          }),
        );
      } else {
        cell.textContent = this.text(column, row);
        cell.title ||= cell.textContent;
        if (editable) {
          cell.classList.add("editable");
          cell.addEventListener("dblclick", () => this.startEdit(cell, row, column));
        }
      }
      element.append(cell);
    }
    return element;
  }

  /**
   * @param {HTMLElement} cell
   * @param {any} row
   * @param {Column} column
   */
  startEdit(cell, row, column) {
    const current = this.text(column, row);
    /** @type {HTMLInputElement | HTMLSelectElement} */
    let input;
    if (column.editor === "select") {
      const options = typeof column.options === "function" ? column.options(row) : (column.options ?? []);
      input = /** @type {HTMLSelectElement} */ (
        el(
          "select.select.cell-editor",
          {},
          options.map((option) => el("option", { value: option, text: option, selected: option === current })),
        )
      );
      input.addEventListener("change", () => finish(true));
    } else {
      input = /** @type {HTMLInputElement} */ (
        el("input.input.cell-editor", { type: "text", value: current, list: column.datalist })
      );
    }
    cell.replaceChildren(input);
    input.focus();
    if (input instanceof HTMLInputElement) {
      input.select();
    }
    let done = false;
    /** @param {boolean} commit */
    const finish = (commit) => {
      if (done) {
        return;
      }
      done = true;
      if (!commit || input.value === current) {
        this.list.render();
        return;
      }
      const parsed = column.parse ? column.parse(input.value, row) : { value: input.value, error: null };
      const errorKey = `${row.key}:${column.key}`;
      if (parsed.error) {
        this.errors.set(errorKey, parsed.error);
        this.list.render();
        return;
      }
      this.commit(row, column, parsed.value);
    };
    input.addEventListener("keydown", (event) => {
      event.stopPropagation();
      if (event.key === "Enter") {
        finish(true);
      } else if (event.key === "Escape") {
        finish(false);
      }
    });
    input.addEventListener("blur", () => finish(true));
  }

  /**
   * @param {any} row
   * @param {Column} column
   * @param {any} value
   */
  async commit(row, column, value) {
    const errorKey = `${row.key}:${column.key}`;
    try {
      await this.onEdit(row, column, value);
      this.errors.delete(errorKey);
    } catch (/** @type {any} */ error) {
      this.errors.set(errorKey, error?.message ?? String(error));
    }
    this.list.render();
  }
}
