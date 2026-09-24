// @ts-check
// Console panel: application, worker and run logs.
import { el } from "../components/dom.js";
import { LogBuffer, formatLine } from "../lib/log_buffer.js";

/** Lines rendered at most; older matching lines stay in the buffer. */
const MAX_RENDERED_LINES = 2000;

export class ConsolePanel {
  /**
   * @param {HTMLElement} root
   * @param {import("../lib/rpc.js").RpcClient} api
   */
  constructor(root, api) {
    this.buffer = new LogBuffer(10000);
    this.renderScheduled = false;

    this.levelSelect = /** @type {HTMLSelectElement} */ (
      el("select.select", { title: "Minimum level", onChange: () => this.render() }, [
        el("option", { value: "DEBUG", text: "Debug" }),
        el("option", { value: "INFO", text: "Info", selected: true }),
        el("option", { value: "WARNING", text: "Warning" }),
        el("option", { value: "ERROR", text: "Error" }),
      ])
    );
    this.searchInput = /** @type {HTMLInputElement} */ (
      el("input.input", { type: "search", placeholder: "Filter…", onInput: () => this.render() })
    );
    this.lines = el("pre.console-lines");
    root.append(
      el("div.console-toolbar", {}, [
        this.levelSelect,
        this.searchInput,
        el("button.button", { text: "Copy", title: "Copy the visible lines", onClick: () => this.copy() }),
        el("button.button", { text: "Clear", onClick: () => this.clear() }),
      ]),
      this.lines,
    );

    api.on("app.log", (line) => this.add(line));
    api.call("app.logs").then((/** @type {any[]} */ history) => {
      for (const line of history) {
        this.buffer.push(line);
      }
      this.scheduleRender();
    });
  }

  /** @param {import("../lib/log_buffer.js").LogLine} line */
  add(line) {
    this.buffer.push(line);
    this.scheduleRender();
  }

  visibleLines() {
    return this.buffer
      .filtered({ minLevel: this.levelSelect.value, text: this.searchInput.value })
      .slice(-MAX_RENDERED_LINES);
  }

  scheduleRender() {
    if (!this.renderScheduled) {
      this.renderScheduled = true;
      requestAnimationFrame(() => {
        this.renderScheduled = false;
        this.render();
      });
    }
  }

  render() {
    const atBottom = this.lines.scrollHeight - this.lines.scrollTop - this.lines.clientHeight < 20;
    this.lines.replaceChildren(
      ...this.visibleLines().map((line) =>
        el(`div.console-line.level-${line.level}`, { text: formatLine(line) }),
      ),
    );
    if (atBottom) {
      this.lines.scrollTop = this.lines.scrollHeight;
    }
  }

  copy() {
    navigator.clipboard?.writeText(this.visibleLines().map(formatLine).join("\n"));
  }

  clear() {
    this.buffer.clear();
    this.render();
  }
}
