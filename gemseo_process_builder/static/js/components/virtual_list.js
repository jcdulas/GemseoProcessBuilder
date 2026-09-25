// @ts-check
// A scrolling list rendering only its visible rows (fixed row height).
import { scrollToShow, visibleRange } from "../lib/virtual_window.js";
import { el } from "./dom.js";

export const ROW_HEIGHT = 28;

/**
 * @template T
 */
export class VirtualList {
  /**
   * @param {HTMLElement} container
   * @param {{renderRow: (row: T, index: number) => HTMLElement, rowHeight?: number}} options
   */
  constructor(container, { renderRow, rowHeight = ROW_HEIGHT }) {
    this.renderRow = renderRow;
    this.rowHeight = rowHeight;
    /** @type {T[]} */
    this.rows = [];
    this.viewport = el("div.virtual-list");
    this.spacer = el("div.virtual-list-spacer");
    this.content = el("div.virtual-list-content");
    this.spacer.append(this.content);
    this.viewport.append(this.spacer);
    container.append(this.viewport);
    this.scheduled = false;
    this.viewport.addEventListener("scroll", () => this.schedule());
    new ResizeObserver(() => this.schedule()).observe(this.viewport);
  }

  /** @param {T[]} rows */
  setRows(rows) {
    this.rows = rows;
    this.render();
  }

  schedule() {
    if (!this.scheduled) {
      this.scheduled = true;
      requestAnimationFrame(() => {
        this.scheduled = false;
        this.render();
      });
    }
  }

  render() {
    const range = visibleRange({
      scrollTop: this.viewport.scrollTop,
      viewportHeight: this.viewport.clientHeight,
      rowHeight: this.rowHeight,
      count: this.rows.length,
    });
    this.spacer.style.height = `${range.totalHeight}px`;
    this.content.style.transform = `translateY(${range.offset}px)`;
    const elements = [];
    for (let index = range.first; index < range.last; index += 1) {
      const element = this.renderRow(this.rows[index], index);
      element.style.height = `${this.rowHeight}px`;
      elements.push(element);
    }
    this.content.replaceChildren(...elements);
  }

  /** @param {number} index */
  scrollToIndex(index) {
    const top = scrollToShow(index, {
      scrollTop: this.viewport.scrollTop,
      viewportHeight: this.viewport.clientHeight,
      rowHeight: this.rowHeight,
    });
    if (top !== null) {
      this.viewport.scrollTop = top;
    }
  }
}
