// @ts-check
// A read-only text with line numbers, highlighted ranges and a selection given
// as offsets in the text: the sample files of the wrapper editor.
import { el } from "../../components/dom.js";

/**
 * @typedef {{start: number, end: number, className: string, title?: string}} Highlight
 */

export class TextView {
  /**
   * @param {HTMLElement} container
   * @param {{onSelect?: (selection: {start: number, end: number}) => void, placeholder?: string}} [options]
   *   ``onSelect`` is called after a selection with the mouse, or a click
   *   (``start === end``).
   */
  constructor(container, { onSelect, placeholder = "" } = {}) {
    this.text = "";
    this.gutter = el("pre.wrapper-gutter");
    this.pre = el("pre.wrapper-text");
    this.placeholder = el("div.wrapper-placeholder", { text: placeholder });
    this.root = el("div.wrapper-text-view", {}, [this.gutter, this.pre, this.placeholder]);
    container.append(this.root);
    this.pre.addEventListener("mouseup", () => {
      const selection = this.selection();
      if (selection) {
        onSelect?.(selection);
      }
    });
  }

  /**
   * Show a text.
   *
   * @param {string} text
   * @param {Highlight[]} [highlights] - Ranges that do not overlap.
   */
  setText(text, highlights = []) {
    this.text = text;
    const parts = [];
    let position = 0;
    for (const highlight of [...highlights].sort((a, b) => a.start - b.start)) {
      if (highlight.start < position) {
        continue;
      }
      parts.push(document.createTextNode(text.slice(position, highlight.start)));
      parts.push(el(`span.${highlight.className}`, { text: text.slice(highlight.start, highlight.end), title: highlight.title ?? "" }));
      position = highlight.end;
    }
    parts.push(document.createTextNode(text.slice(position)));
    this.pre.replaceChildren(...parts);
    const lines = text ? text.split("\n").length : 0;
    this.gutter.textContent = Array.from({ length: lines }, (_, index) => index + 1).join("\n");
    this.placeholder.hidden = Boolean(text);
  }

  /**
   * The selection as offsets in the text, or null when it is elsewhere.
   *
   * @returns {{start: number, end: number} | null}
   */
  selection() {
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount) {
      return null;
    }
    const range = selection.getRangeAt(0);
    if (!this.pre.contains(range.startContainer) || !this.pre.contains(range.endContainer)) {
      return null;
    }
    const before = document.createRange();
    before.selectNodeContents(this.pre);
    before.setEnd(range.startContainer, range.startOffset);
    const start = before.toString().length;
    return { start, end: start + range.toString().length };
  }

  /**
   * Select a range of the text.
   *
   * @param {number} start
   * @param {number} end
   */
  select(start, end) {
    const range = document.createRange();
    const walker = document.createTreeWalker(this.pre, NodeFilter.SHOW_TEXT);
    let position = 0;
    let startSet = false;
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const length = node.textContent?.length ?? 0;
      if (!startSet && start <= position + length) {
        range.setStart(node, start - position);
        startSet = true;
      }
      if (startSet && end <= position + length) {
        range.setEnd(node, end - position);
        const selection = window.getSelection();
        selection?.removeAllRanges();
        selection?.addRange(range);
        return;
      }
      position += length;
    }
  }
}
