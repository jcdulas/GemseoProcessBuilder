// @ts-check
// Search (Ctrl+F): node and variable names across the whole model. Enter goes
// to the next result (Shift+Enter to the previous one): the canvas opens the
// level holding the node, centers it and highlights it. Escape closes.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { search, searchEntries } from "../../lib/search_index.js";

const SHOWN = 30;
const FLASH_MS = 1500;

export class SearchOverlay {
  /** @param {import("./canvas.js").WorkflowCanvas} canvas */
  constructor(canvas) {
    this.canvas = canvas;
    this.input = /** @type {HTMLInputElement} */ (
      el("input.input.search-input", { type: "search", placeholder: "Search nodes and variables", spellcheck: "false" })
    );
    this.count = el("span.search-count");
    this.list = el("div.search-results", { role: "listbox" });
    this.root = el("div.search-overlay", { hidden: true }, [el("div.search-bar", {}, [this.input, this.count]), this.list]);
    canvas.container.append(this.root);
    /** @type {import("../../lib/search_index.js").SearchEntry[]} */
    this.entries = [];
    /** @type {import("../../lib/search_index.js").SearchResult[]} */
    this.results = [];
    this.current = -1;
    this.input.addEventListener("input", () => this.refresh());
    this.input.addEventListener("keydown", (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        this.close();
      } else if (event.key === "Enter") {
        event.preventDefault();
        this.step(event.shiftKey ? -1 : 1);
      } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        this.step(event.key === "ArrowDown" ? 1 : -1);
      }
    });
  }

  async open() {
    this.root.hidden = false;
    this.input.focus();
    this.input.select();
    const state = app.store.state;
    const pathOf = (/** @type {string} */ id) =>
      app.store
        .pathTo(id)
        .map((nodeId) => state.nodes[nodeId]?.name ?? nodeId)
        .join(".");
    let couplings = {};
    try {
      couplings = await app.api.call("resolve.couplings");
    } catch (error) {
      console.error("The variables cannot be searched:", error);
    }
    this.entries = searchEntries(state.nodes, pathOf, couplings, app.store.rootId);
    this.refresh();
  }

  close() {
    this.root.hidden = true;
    this.canvas.svg.node().focus?.();
  }

  refresh() {
    this.results = search(this.entries, this.input.value, 500);
    this.current = -1;
    this.render();
  }

  render() {
    const query = this.input.value.trim();
    this.count.textContent = query ? `${this.current + 1 > 0 ? `${this.current + 1}/` : ""}${this.results.length}` : "";
    this.list.replaceChildren(
      ...this.results.slice(0, SHOWN).map((result, index) =>
        el(
          `div.search-result${index === this.current ? ".active" : ""}`,
          { role: "option", onClick: () => this.go(index) },
          [
            el("span.search-kind", { text: result.kind === "node" ? "node" : "var" }),
            el("span.search-name", { text: result.name }),
            el("span.search-detail", { text: result.detail }),
          ],
        ),
      ),
    );
  }

  /** @param {number} direction */
  step(direction) {
    if (!this.results.length) {
      return;
    }
    const count = this.results.length;
    this.go((this.current + direction + count) % count);
  }

  /**
   * Show a result: open its level, select, center and highlight its node.
   *
   * @param {number} index
   */
  go(index) {
    this.current = index;
    this.render();
    const nodeId = this.results[index].node;
    const path = app.store.pathTo(nodeId);
    const level = path.length > 1 ? path[path.length - 2] : app.store.rootId;
    if (app.navigation.current() !== level) {
      app.navigation.enter(level);
    }
    app.selection.set([nodeId]);
    // The level may have just been drawn: wait for the next frame.
    requestAnimationFrame(() => {
      this.canvas.render();
      this.canvas.centerOn(nodeId);
      const group = this.canvas.layers.nodes.select(`g.node[data-id="${CSS.escape(nodeId)}"]`);
      group.classed("search-flash", true);
      setTimeout(() => group.classed("search-flash", false), FLASH_MS);
    });
  }
}
