// @ts-check
// The N2 matrix of a level (SPEC § 8.4), in a center tab.
//
// Rows and columns are the leaves of the level (components and drivers); the
// cell of row i and column j lists what i computes and j uses. Cells below the
// diagonal are feedbacks. Only the visible part is drawn: the cells as two
// paths (feed-forward and feedback), the diagonal and the labels of visible
// rows; below a zoom threshold, texts are left out (level of detail).
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { cellsByRow, collapse, reorder } from "../../lib/n2_layout.js";
import { cellsInView, visibleCells } from "../../lib/viewport_cells.js";

/** Size of a cell in matrix units (pixels at zoom 1). */
const CELL = 24;
/** Width of the row labels, in pixels. */
const HEADER_WIDTH = 190;
/** Below this size on screen (pixels), cells show no text. */
const DETAIL_SIZE = 14;
/** Below this size on screen (pixels), row labels are hidden too. */
const LABEL_SIZE = 9;
const INDENT = 12;
const TAB_ID = "n2";
const ORDER_KEY = "n2_order";

/**
 * A path drawing squares: one ``M…Z`` per cell.
 *
 * @param {{row: number, col: number}[]} cells
 */
function squares(cells) {
  return cells.map((cell) => `M${cell.col * CELL + 1},${cell.row * CELL + 1}h${CELL - 2}v${CELL - 2}h${2 - CELL}Z`).join("");
}

export class N2View {
  /** @param {HTMLElement} page */
  constructor(page) {
    const d3 = /** @type {any} */ (window).d3;
    this.page = page;
    page.classList.add("n2-view");
    this.follow = true;
    this.level = app.navigation.current();
    /** @type {Map<string, Set<string>>} - Collapsed blocks, per level. */
    this.collapsedByLevel = new Map();
    /** @type {import("../../lib/n2_layout.js").N2Data | null} */
    this.data = null;
    /** @type {import("../../lib/n2_layout.js").N2View} */
    this.view = { entries: [], blocks: [], cells: [] };
    /** @type {Map<number, import("../../lib/n2_layout.js").N2Cell[]>} */
    this.byRow = new Map();
    /** @type {{row: number, col: number} | null} */
    this.hover = null;
    /** @type {{from: number, to: number} | null} */
    this.drag = null;
    this.focusId = "";
    /** Whether to fit the matrix once it has a size (its tab may be hidden). */
    this.needsFit = false;
    this.token = 0;
    this.frame = 0;

    const followBox = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: true }));
    followBox.addEventListener("change", () => {
      this.follow = followBox.checked;
      if (this.follow) {
        this.show(app.navigation.current());
      }
    });
    this.followBox = followBox;
    this.title = el("span.n2-title");
    this.count = el("span.form-hint");
    page.replaceChildren(
      el("div.results-toolbar", {}, [
        this.title,
        el("label.form-check", { title: "Show the level open on the canvas" }, [followBox, el("span", { text: "Follow canvas" })]),
        el("span.toolbar-spacer"),
        this.count,
        el("button.button.bordered", { text: "Collapse all", onClick: () => this.setCollapsed(this.data?.blocks.map((block) => block.id) ?? []) }),
        el("button.button.bordered", { text: "Expand all", onClick: () => this.setCollapsed([]) }),
        el("button.button.bordered", { text: "Fit", onClick: () => this.fit() }),
      ]),
      el("div.n2-body", {}, [
        (this.headers = el("div.n2-headers")),
        (this.matrix = el("div.n2-matrix")),
      ]),
    );
    this.headerSvg = d3.select(this.headers).append("svg").attr("class", "n2-header-svg");
    this.svg = d3.select(this.matrix).append("svg").attr("class", "n2-svg");
    this.content = this.svg.append("g");
    this.layers = {
      blocks: this.content.append("g").attr("class", "n2-blocks"),
      bands: this.content.append("g").attr("class", "n2-bands"),
      forward: this.content.append("path").attr("class", "n2-cell"),
      feedback: this.content.append("path").attr("class", "n2-cell n2-feedback"),
      diagonal: this.content.append("g").attr("class", "n2-diagonal"),
      texts: this.content.append("g").attr("class", "n2-texts"),
      drop: this.content.append("line").attr("class", "n2-drop"),
    };
    this.zoom = d3
      .zoom()
      .scaleExtent([0.02, 4])
      // A drag starting on the diagonal reorders instead of panning.
      .filter((/** @type {any} */ event) => !event.button && !(event.type === "mousedown" && this.onDiagonal(event)))
      .on("zoom", () => this.schedule());
    this.svg.call(this.zoom).on("dblclick.zoom", null);
    this.listen();
    new ResizeObserver(() => this.schedule()).observe(this.matrix);
    this.show(this.level);
  }

  listen() {
    const node = /** @type {SVGSVGElement} */ (this.svg.node());
    node.addEventListener("mousemove", (event) => this.pointerMove(event));
    node.addEventListener("mouseleave", () => {
      this.hover = null;
      this.renderBands();
    });
    node.addEventListener("mousedown", (event) => this.dragStart(event));
    node.addEventListener("click", (event) => this.click(event));
    node.addEventListener("dblclick", (event) => this.doubleClick(event));
    app.navigation.onChange(() => {
      if (this.follow) {
        this.show(app.navigation.current());
      }
    });
    app.api.on("resolution.updated", () => this.load());
    let orderText = JSON.stringify(app.store.state.view[`extra.${ORDER_KEY}`] ?? {});
    app.store.subscribe((event) => {
      const text = JSON.stringify(app.store.state.view[`extra.${ORDER_KEY}`] ?? {});
      if (event.type === "reset") {
        this.collapsedByLevel.clear();
        this.show(app.navigation.current());
      } else if (text !== orderText) {
        this.load();
      }
      orderText = text;
    });
  }

  /**
   * Show the N2 of a level.
   *
   * @param {string} level
   * @param {string} [focus] - A node to scroll to.
   */
  show(level, focus = "") {
    const changed = level !== this.level;
    this.level = level;
    this.focusId = focus;
    this.load(changed);
  }

  /** @param {boolean} [refit] */
  async load(refit = false) {
    const token = ++this.token;
    let data;
    try {
      data = await app.api.call("n2.build", { level: this.level });
    } catch (error) {
      showError("The N2 matrix cannot be built", error);
      return;
    }
    if (token !== this.token) {
      return;
    }
    const first = this.data === null;
    this.data = data;
    this.title.textContent = `N2 of ${app.store.node(this.level)?.name ?? this.level}`;
    this.recompute();
    if (first || refit) {
      this.fit();
    }
    if (this.focusId) {
      this.reveal(this.focusId);
      this.focusId = "";
    }
    this.schedule();
  }

  collapsed() {
    let set = this.collapsedByLevel.get(this.level);
    if (!set) {
      set = new Set();
      this.collapsedByLevel.set(this.level, set);
    }
    return set;
  }

  /** @param {string[]} ids */
  setCollapsed(ids) {
    this.collapsedByLevel.set(this.level, new Set(ids));
    this.recompute();
    this.fit();
    this.schedule();
  }

  /** @param {string} id */
  toggle(id) {
    const set = this.collapsed();
    if (set.has(id)) {
      set.delete(id);
    } else {
      set.add(id);
    }
    this.recompute();
    this.schedule();
  }

  recompute() {
    if (!this.data) {
      return;
    }
    this.view = collapse(this.data, this.collapsed());
    this.byRow = cellsByRow(this.view.cells);
    const feedbacks = this.view.cells.filter((cell) => cell.feedback).length;
    this.count.textContent = `${this.view.entries.length} entries, ${this.view.cells.length} couplings, ${feedbacks} feedbacks`;
  }

  /** Zoom so that the whole matrix is visible. */
  fit() {
    const d3 = /** @type {any} */ (window).d3;
    const width = this.matrix.clientWidth;
    const height = this.matrix.clientHeight;
    if (!width || !height) {
      this.needsFit = true;
      return;
    }
    this.needsFit = false;
    const size = Math.max(1, this.view.entries.length) * CELL;
    const k = Math.min(2, Math.max(0.02, Math.min(width, height) / (size + 2 * CELL)));
    this.svg.call(this.zoom.transform, d3.zoomIdentity.translate(CELL * k, CELL * k).scale(k));
  }

  /**
   * Scroll to a node and flash it.
   *
   * @param {string} id
   */
  reveal(id) {
    const d3 = /** @type {any} */ (window).d3;
    const path = app.store.pathTo(id);
    const index = this.view.entries.findIndex((entry) => entry.id === id || path.includes(entry.id));
    if (index < 0 || !this.matrix.clientWidth) {
      return;
    }
    const k = Math.max(d3.zoomTransform(this.svg.node()).k, 1);
    const center = (index + 0.5) * CELL * k;
    const x = this.matrix.clientWidth / 2 - center;
    const y = this.matrix.clientHeight / 2 - center;
    this.svg.call(this.zoom.transform, d3.zoomIdentity.translate(x, y).scale(k));
    this.hover = { row: index, col: index };
  }

  schedule() {
    if (!this.frame) {
      this.frame = requestAnimationFrame(() => {
        this.frame = 0;
        this.render();
      });
    }
  }

  transform() {
    const d3 = /** @type {any} */ (window).d3;
    return d3.zoomTransform(this.svg.node());
  }

  render() {
    const width = this.matrix.clientWidth;
    const height = this.matrix.clientHeight;
    if (!width || !height) {
      return;
    }
    if (this.needsFit) {
      this.fit();
    }
    const t = this.transform();
    this.content.attr("transform", t.toString());
    const count = this.view.entries.length;
    const visible = visibleCells(t, width, height, CELL, count);
    const detailed = t.k * CELL >= DETAIL_SIZE;
    const cells = cellsInView(this.byRow, visible);
    this.layers.forward.attr("d", squares(cells.filter((cell) => !cell.feedback)));
    this.layers.feedback.attr("d", squares(cells.filter((cell) => cell.feedback)));
    const [firstRow, lastRow] = visible.rows;
    const [firstCol, lastCol] = visible.cols;
    // Elements are keyed by node id: indices change when blocks collapse.
    const diagonal = [];
    for (let index = Math.max(firstRow, firstCol); index <= Math.min(lastRow, lastCol); index += 1) {
      diagonal.push({ index, entry: this.view.entries[index] });
    }
    this.layers.diagonal
      .selectAll("rect")
      .data(diagonal, (/** @type {any} */ item) => item.entry.id)
      .join("rect")
      .attr("class", (/** @type {any} */ { entry }) => {
        const kind = entry.type === "driver" ? `n2-driver-${entry.kind}` : `n2-${entry.type}`;
        return `n2-entry ${kind}${entry.collapsed ? " n2-collapsed" : ""}`;
      })
      .attr("x", (/** @type {any} */ item) => item.index * CELL)
      .attr("y", (/** @type {any} */ item) => item.index * CELL)
      .attr("width", CELL)
      .attr("height", CELL);
    const texts = detailed
      ? [
          ...cells.map((cell) => ({
            key: `${cell.row},${cell.col}`,
            x: (cell.col + 0.5) * CELL,
            y: (cell.row + 0.5) * CELL,
            text: cell.variables.length > 1 ? String(cell.variables.length) : cell.variables[0].slice(0, 4),
            className: "n2-cell-text",
          })),
          ...diagonal
            .filter((item) => item.entry.collapsed)
            .map(({ index, entry }) => ({ key: `+${entry.id}`, x: (index + 0.5) * CELL, y: (index + 0.5) * CELL, text: "+", className: "n2-entry-text" })),
        ]
      : [];
    this.layers.texts
      .selectAll("text")
      .data(texts, (/** @type {any} */ item) => item.key)
      .join("text")
      .attr("class", (/** @type {any} */ item) => item.className)
      .attr("x", (/** @type {any} */ item) => item.x)
      .attr("y", (/** @type {any} */ item) => item.y)
      .text((/** @type {any} */ item) => item.text);
    const blocks = this.view.blocks.filter((block) => block.end >= Math.max(firstRow, firstCol) && block.start <= Math.min(lastRow, lastCol));
    this.layers.blocks
      .selectAll("rect")
      .data(blocks, (/** @type {any} */ block) => block.id)
      .join("rect")
      .attr("class", "n2-block")
      .attr("x", (/** @type {any} */ block) => block.start * CELL)
      .attr("y", (/** @type {any} */ block) => block.start * CELL)
      .attr("width", (/** @type {any} */ block) => (block.end - block.start + 1) * CELL)
      .attr("height", (/** @type {any} */ block) => (block.end - block.start + 1) * CELL);
    this.renderBands();
    this.renderHeaders(t, visible.rows, height);
  }

  /** The row and column bands under the pointer, and the drop line while dragging. */
  renderBands() {
    const size = this.view.entries.length * CELL;
    const bands = this.hover
      ? [
          { key: "row", x: 0, y: this.hover.row * CELL, width: size, height: CELL },
          { key: "col", x: this.hover.col * CELL, y: 0, width: CELL, height: size },
        ]
      : [];
    this.layers.bands
      .selectAll("rect")
      .data(bands, (/** @type {any} */ band) => band.key)
      .join("rect")
      .attr("class", "n2-band")
      .attr("x", (/** @type {any} */ band) => band.x)
      .attr("y", (/** @type {any} */ band) => band.y)
      .attr("width", (/** @type {any} */ band) => band.width)
      .attr("height", (/** @type {any} */ band) => band.height);
    const drop = this.drag;
    this.layers.drop
      .attr("visibility", drop ? "visible" : "hidden")
      .attr("x1", 0)
      .attr("x2", size)
      .attr("y1", drop ? (drop.to > drop.from ? drop.to + 1 : drop.to) * CELL : 0)
      .attr("y2", drop ? (drop.to > drop.from ? drop.to + 1 : drop.to) * CELL : 0);
  }

  /**
   * The labels of the visible rows, and the brackets of the blocks.
   *
   * @param {any} t
   * @param {[number, number]} rows
   * @param {number} height
   */
  renderHeaders(t, rows, height) {
    this.headerSvg.attr("width", HEADER_WIDTH).attr("height", height);
    const labelled = t.k * CELL >= LABEL_SIZE;
    const items = [];
    for (let index = rows[0]; labelled && index <= rows[1]; index += 1) {
      items.push({ index, entry: this.view.entries[index] });
    }
    const fontSize = Math.min(13, Math.max(9, t.k * CELL * 0.55));
    this.headerSvg
      .selectAll("text.n2-label")
      .data(items, (/** @type {any} */ item) => item.entry.id)
      .join((/** @type {any} */ enter) =>
        enter
          .append("text")
          .attr("class", "n2-label")
          .on("click", (/** @type {MouseEvent} */ _event, /** @type {any} */ { entry }) => {
            if (entry.collapsed) {
              this.toggle(entry.id);
            } else {
              app.selection.set([entry.id]);
            }
          }),
      )
      .attr("x", (/** @type {any} */ { entry }) => 6 + entry.depth * INDENT)
      .attr("y", (/** @type {any} */ { index }) => t.y + t.k * (index + 0.5) * CELL)
      .attr("font-size", fontSize)
      .classed("n2-label-collapsed", (/** @type {any} */ { entry }) => entry.collapsed)
      .classed("n2-label-focus", (/** @type {any} */ { index }) => this.hover?.row === index)
      .text((/** @type {any} */ { entry }) => `${entry.collapsed ? "▸ " : ""}${entry.name}`);
    // One bracket per expanded block: a click collapses it.
    const brackets = labelled ? this.view.blocks.filter((block) => block.end >= rows[0] && block.start <= rows[1]) : [];
    this.headerSvg
      .selectAll("path.n2-bracket")
      .data(brackets, (/** @type {any} */ block) => block.id)
      .join((/** @type {any} */ enter) =>
        enter
          .append("path")
          .attr("class", "n2-bracket")
          .on("click", (/** @type {MouseEvent} */ _event, /** @type {any} */ block) => this.toggle(block.id))
          .call((/** @type {any} */ path) => path.append("title")),
      )
      .attr("d", (/** @type {any} */ block) => {
        const x = 2 + block.depth * INDENT;
        const top = t.y + t.k * block.start * CELL + 2;
        const bottom = t.y + t.k * (block.end + 1) * CELL - 2;
        return `M${x + 4},${top}H${x}V${bottom}H${x + 4}`;
      })
      .select("title")
      .text((/** @type {any} */ block) => `${block.name}: click to collapse`);
  }

  /**
   * The cell under the pointer.
   *
   * @param {MouseEvent} event
   * @returns {{row: number, col: number} | null}
   */
  cellAt(event) {
    const t = this.transform();
    const box = /** @type {SVGSVGElement} */ (this.svg.node()).getBoundingClientRect();
    const col = Math.floor((event.clientX - box.left - t.x) / t.k / CELL);
    const row = Math.floor((event.clientY - box.top - t.y) / t.k / CELL);
    const count = this.view.entries.length;
    return row >= 0 && col >= 0 && row < count && col < count ? { row, col } : null;
  }

  /** @param {MouseEvent} event */
  onDiagonal(event) {
    const cell = this.cellAt(event);
    return cell !== null && cell.row === cell.col;
  }

  /**
   * @param {{row: number, col: number}} position
   * @returns {import("../../lib/n2_layout.js").N2Cell | undefined}
   */
  cellOf(position) {
    return this.byRow.get(position.row)?.find((cell) => cell.col === position.col);
  }

  /** @param {MouseEvent} event */
  pointerMove(event) {
    const position = this.cellAt(event);
    if (this.drag) {
      if (position) {
        this.drag.to = position.row;
      }
      this.renderBands();
      return;
    }
    this.hover = position;
    this.schedule();
    const svg = /** @type {SVGSVGElement} */ (this.svg.node());
    if (!position) {
      this.matrix.title = "";
      return;
    }
    const entries = this.view.entries;
    const cell = this.cellOf(position);
    const text =
      position.row === position.col
        ? `${entries[position.row].name}${entries[position.row].collapsed ? " (collapsed: click to expand)" : " (drag to reorder)"}`
        : cell
          ? `${entries[position.row].name} → ${entries[position.col].name}: ${cell.variables.join(", ")}`
          : "";
    svg.style.cursor = position.row === position.col ? "grab" : cell ? "pointer" : "";
    this.matrix.title = text;
  }

  /** @param {MouseEvent} event */
  click(event) {
    const position = this.cellAt(event);
    if (!position) {
      return;
    }
    const entries = this.view.entries;
    if (position.row === position.col) {
      if (entries[position.row].collapsed) {
        this.toggle(entries[position.row].id);
      }
      return;
    }
    const cell = this.cellOf(position);
    if (!cell) {
      return;
    }
    // The inspector lists the coupled variables, as for a link of the canvas.
    app.selection.clear();
    app.linkFocus.set({
      id: `n2:${entries[cell.row].id}>${entries[cell.col].id}`,
      from: entries[cell.row].id,
      to: entries[cell.col].id,
      path: "",
      kind: "aggregated",
      feedback: cell.feedback,
      variables: cell.links?.length ? cell.links : cell.variables.map((name) => ({ name, source_port: "", target_port: "", explicit: false })),
      label: null,
      sourcePort: "",
      targetPort: "",
    });
  }

  /** @param {MouseEvent} event */
  doubleClick(event) {
    const position = this.cellAt(event);
    if (!position) {
      return;
    }
    const entries = this.view.entries;
    if (position.row === position.col) {
      const entry = entries[position.row];
      if (entry.type === "driver" || entry.collapsed) {
        app.navigation.enter(entry.id);
      }
      return;
    }
    // Select the producer and the consumer on the canvas.
    if (this.cellOf(position)) {
      app.selection.set([entries[position.row].id, entries[position.col].id]);
    }
  }

  /** @param {MouseEvent} event */
  dragStart(event) {
    const position = this.cellAt(event);
    if (!position || position.row !== position.col || event.button !== 0) {
      return;
    }
    this.drag = { from: position.row, to: position.row };
    const up = () => {
      document.removeEventListener("mouseup", up);
      const drag = this.drag;
      this.drag = null;
      this.renderBands();
      if (drag && drag.to !== drag.from) {
        this.move(drag.from, drag.to);
      }
    };
    document.addEventListener("mouseup", up);
  }

  /**
   * Move an entry of the diagonal among its siblings.
   *
   * @param {number} from
   * @param {number} to
   */
  async move(from, to) {
    const change = reorder(this.view, from, to);
    if (!change) {
      return;
    }
    const parent = app.store.node(change.parent);
    const moved = this.view.entries[from].id;
    try {
      if (parent?.type === "assembly" && parent.mode === "chain") {
        // In a chain, the order is the execution order: an undoable change of the model.
        await app.store.execute({
          type: "reparentNodes",
          placements: [{ id: moved, parent: change.parent, index: change.ids.indexOf(moved) }],
        });
      } else {
        const orders = { ...(app.store.state.view[`extra.${ORDER_KEY}`] ?? {}), [change.parent]: change.ids };
        await app.store.execute({ type: "setLayout", extra: { [ORDER_KEY]: orders } }, { undoable: false });
      }
    } catch (error) {
      showError("The order could not be changed", error);
    }
  }
}

/** @type {N2View | null} */
let opened = null;

/**
 * Open the N2 tab (or bring it to the front).
 *
 * @param {{level?: string, focus?: string}} [options] - A level to show (the
 *   canvas stops being followed) and a node to scroll to.
 */
export function openN2({ level, focus } = {}) {
  const page = app.tabs.center.open({ id: TAB_ID, title: "N2", onClose: () => (opened = null) });
  if (!opened) {
    opened = new N2View(page);
  }
  if (level) {
    opened.follow = level === app.navigation.current();
    opened.followBox.checked = opened.follow;
    opened.show(level, focus);
  }
}

/**
 * Show a node in the N2 of the level holding it.
 *
 * @param {string} id
 */
export function showInN2(id) {
  const path = app.store.pathTo(id);
  const level = path.length > 1 ? path[path.length - 2] : id;
  openN2({ level, focus: id });
}

export function installN2() {
  app.actions.handle("view.n2", { run: () => openN2() });
}
