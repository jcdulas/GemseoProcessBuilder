// @ts-check
// The workflow canvas: one level of the model drawn as an SVG flow diagram.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { HEADER_HEIGHT, NODE_WIDTH, fitTransform } from "../../lib/geometry.js";
import { rectFromCorners, selectInRect } from "../../lib/hit_test.js";
import { isTypingTarget } from "../../lib/shortcut_keys.js";
import { openDriverEditor } from "../../panels/driver_editor/index.js";
import { NEW_NODE_TYPE } from "../../panels/library.js";
import { buildScene, levelsToResolve, topLevelRects } from "../../lib/scene.js";
import { Breadcrumb } from "./breadcrumb.js";
import { installLinkDrawing } from "./link_drawing.js";
import { backgroundMenu, nodeMenu } from "./menus.js";
import { drawScene, moveScene } from "./render.js";

const d3 = /** @type {any} */ (window).d3;
const SAVE_ZOOM_DELAY_MS = 600;

export class WorkflowCanvas {
  /**
   * @param {HTMLElement} root - The page of the Workflow tab.
   * @param {import("../../services/selection.js").Selection} selection
   * @param {import("../../services/navigation.js").Navigation} navigation
   */
  constructor(root, selection, navigation) {
    this.store = app.store;
    this.selection = selection;
    this.navigation = navigation;
    /** @type {Map<string, {x: number, y: number}>} */
    this.dragPositions = new Map();
    /** @type {ReturnType<typeof buildScene>} */
    this.scene = { items: [], links: [], box: null };
    this.renderScheduled = false;
    this.spaceDown = false;
    /** @type {{x: number, y: number} | null} */
    this.lastPointer = null;
    /** @type {any} */
    this.saveZoomTimer = null;
    this.restoringZoom = false;

    /** @type {Map<string, import("../../lib/scene.js").LevelView>} */
    this.views = new Map();
    this.viewsRequest = 0;

    root.replaceChildren();
    root.classList.add("canvas-page");
    this.breadcrumb = new Breadcrumb(root, navigation);
    this.container = el("div.canvas-container");
    this.hint = el("div.canvas-hint");
    this.container.append(this.hint);
    root.append(this.container);

    this.svg = d3.select(this.container).append("svg").attr("class", "canvas");
    this.background = this.svg.append("rect").attr("class", "canvas-background").attr("width", "100%").attr("height", "100%");
    this.viewport = this.svg.append("g").attr("class", "viewport");
    // Links are drawn under the nodes; expanded containers have a translucent
    // body so that the links of their children stay visible.
    this.layers = {
      links: this.viewport.append("g").attr("class", "links-layer"),
      nodes: this.viewport.append("g").attr("class", "nodes-layer"),
    };
    this.overlay = this.viewport.append("g").attr("class", "overlay-layer");

    this.zoom = d3
      .zoom()
      .scaleExtent([0.1, 4])
      .filter((/** @type {any} */ event) => {
        if (event.type === "wheel") {
          return true;
        }
        return event.button === 1 || (event.button === 0 && this.spaceDown);
      })
      .on("zoom", (/** @type {any} */ event) => {
        this.viewport.attr("transform", event.transform);
        this.scheduleZoomSave();
      });
    this.svg.call(this.zoom).on("dblclick.zoom", null);

    this.installPointerHandlers();
    this.installKeyboard();
    this.installDrop();
    installLinkDrawing(this);
    this.store.subscribe(() => this.onDocumentChange());
    selection.onChange(() => this.scheduleRender());
    app.componentStatus.onChange(() => this.scheduleRender());
    app.validation.onChange(() => this.scheduleRender());
    navigation.onChange(() => this.onLevelChange());
    this.onLevelChange();
  }

  // Rendering ----------------------------------------------------------------

  get level() {
    return this.navigation.current();
  }

  onDocumentChange() {
    this.dragPositions.clear();
    this.selection.prune((id) => Boolean(this.store.node(id)) && id !== this.store.rootId);
    this.breadcrumb.render();
    this.scheduleRender();
    this.refreshViews();
  }

  /** Ask Python for the couplings of the level and of the expanded containers. */
  async refreshViews() {
    const request = ++this.viewsRequest;
    const levels = levelsToResolve(this.store.state, this.level);
    try {
      const { views } = await this.store.api.call("resolve.levels", { levels });
      if (request === this.viewsRequest) {
        this.views = new Map(Object.entries(views));
        this.scheduleRender();
      }
    } catch (error) {
      console.error("The couplings could not be resolved:", error);
    }
  }

  /** @param {string} text - A message shown at the bottom of the canvas. */
  setHint(text) {
    this.hint.textContent = text;
    this.hint.classList.toggle("visible", Boolean(text));
  }

  onLevelChange() {
    this.selection.clear();
    app.linkFocus.set(null);
    this.breadcrumb.render();
    this.views = new Map();
    this.refreshViews();
    this.render();
    const saved = this.store.state.levels[this.level];
    if (saved) {
      this.restoreTransform(saved);
    } else {
      this.fit();
    }
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
    this.scene = buildScene(this.store.state, this.level, this.dragPositions, this.views);
    drawScene(
      this.layers,
      this.scene,
      this.selection.ids,
      (id) => app.componentStatus.get(id),
      (id) => ({
        level: app.validation.levelOf(id),
        messages: (app.validation.byNode.get(id) ?? [])
          .filter((problem) => problem.level !== "info")
          .map((problem) => problem.message),
      }),
    );
  }

  // Zoom ---------------------------------------------------------------------

  /** @returns {{width: number, height: number}} */
  viewportSize() {
    return { width: this.container.clientWidth, height: this.container.clientHeight };
  }

  fit() {
    const box = this.scene.box;
    const { x, y, k } = fitTransform(box, this.viewportSize());
    this.svg.transition().duration(200).call(this.zoom.transform, d3.zoomIdentity.translate(x, y).scale(k));
  }

  /** @param {{x: number, y: number, k: number}} transform */
  restoreTransform({ x, y, k }) {
    this.restoringZoom = true;
    this.svg.call(this.zoom.transform, d3.zoomIdentity.translate(x, y).scale(k));
    this.restoringZoom = false;
  }

  scheduleZoomSave() {
    if (this.restoringZoom) {
      return;
    }
    clearTimeout(this.saveZoomTimer);
    const level = this.level;
    this.saveZoomTimer = setTimeout(() => {
      const { x, y, k } = d3.zoomTransform(this.svg.node());
      this.store
        .execute({ type: "setLayout", levels: { [level]: { x, y, k } } }, { undoable: false })
        .catch((/** @type {any} */ error) => console.error(error));
    }, SAVE_ZOOM_DELAY_MS);
  }

  /**
   * Canvas coordinates of a pointer event.
   *
   * @param {any} event
   * @returns {{x: number, y: number}}
   */
  toCanvas(event) {
    const [px, py] = d3.pointer(event, this.svg.node());
    const [x, y] = d3.zoomTransform(this.svg.node()).invert([px, py]);
    return { x, y };
  }

  // Pointer interactions ------------------------------------------------------

  /** @param {string} id */
  itemById(id) {
    return this.scene.items.find((item) => item.id === id);
  }

  installPointerHandlers() {
    const svgNode = this.svg.node();
    svgNode.addEventListener("pointermove", (/** @type {PointerEvent} */ event) => {
      this.lastPointer = this.toCanvas(event);
    });

    // Rectangle selection on the background.
    svgNode.addEventListener("pointerdown", (/** @type {PointerEvent} */ event) => {
      if (event.button !== 0 || this.spaceDown || event.target !== this.background.node()) {
        return;
      }
      const start = this.toCanvas(event);
      const additive = event.ctrlKey || event.metaKey;
      const initial = additive ? this.selection.list() : [];
      const rect = this.overlay.append("rect").attr("class", "selection-rect");
      let moved = false;
      svgNode.setPointerCapture(event.pointerId);
      /** @param {PointerEvent} moveEvent */
      const onMove = (moveEvent) => {
        const area = rectFromCorners(start, this.toCanvas(moveEvent));
        moved = moved || area.width > 3 || area.height > 3;
        rect.attr("x", area.x).attr("y", area.y).attr("width", area.width).attr("height", area.height);
        if (moved) {
          this.selection.set([...initial, ...selectInRect(area, topLevelRects(this.scene.items))]);
        }
      };
      const onUp = () => {
        rect.remove();
        svgNode.removeEventListener("pointermove", onMove);
        svgNode.removeEventListener("pointerup", onUp);
        if (!moved && !additive) {
          this.selection.clear();
        }
      };
      svgNode.addEventListener("pointermove", onMove);
      svgNode.addEventListener("pointerup", onUp);
    });

    // Dragging nodes.
    const drag = d3
      .drag()
      .container(this.viewport.node())
      .filter(
        (/** @type {any} */ event) =>
          event.button === 0 && !this.spaceDown && !event.target.closest?.(".port-handle"),
      )
      .on("start", (/** @type {any} */ event, /** @type {any} */ item) => {
        const additive = event.sourceEvent.ctrlKey || event.sourceEvent.metaKey;
        this.dragState = { moved: false, additive, wasSelected: this.selection.has(item.id), dx: 0, dy: 0 };
        if (additive && !this.dragState.wasSelected) {
          this.selection.add([item.id]);
        } else if (!additive && !this.dragState.wasSelected) {
          this.selection.set([item.id]);
        }
      })
      .on("drag", (/** @type {any} */ event) => {
        const state = /** @type {any} */ (this.dragState);
        state.dx += event.dx;
        state.dy += event.dy;
        state.moved = state.moved || Math.abs(state.dx) + Math.abs(state.dy) > 2;
        if (!state.moved) {
          return;
        }
        this.dragPositions.clear();
        for (const id of this.selection.ids) {
          const item = this.itemById(id);
          if (item) {
            this.dragPositions.set(id, { x: item.local.x + state.dx, y: item.local.y + state.dy });
          }
        }
        moveScene(this.layers, buildScene(this.store.state, this.level, this.dragPositions, this.views));
      })
      .on("end", (/** @type {any} */ event, /** @type {any} */ item) => {
        const state = /** @type {any} */ (this.dragState);
        if (!state.moved) {
          if (state.additive && state.wasSelected) {
            this.selection.toggle(item.id);
          } else if (!state.additive) {
            this.selection.set([item.id]);
          }
          return;
        }
        const positions = Object.fromEntries(this.dragPositions);
        this.store.execute({ type: "moveNodes", positions }).catch((/** @type {any} */ error) => {
          this.dragPositions.clear();
          this.render();
          showError("The nodes could not be moved", error);
        });
      });

    const nodesLayer = this.layers.nodes.node();
    const observer = new MutationObserver(() => {
      this.layers.nodes.selectAll("g.node").call(drag);
    });
    observer.observe(nodesLayer, { childList: true });

    nodesLayer.addEventListener("dblclick", (/** @type {MouseEvent} */ event) => {
      const group = /** @type {Element} */ (event.target).closest("g.node");
      const item = group && this.itemById(/** @type {string} */ (group.getAttribute("data-id")));
      if (!item) {
        return;
      }
      const onTitle = /** @type {Element} */ (event.target).classList.contains("node-title");
      if (onTitle && this.store.node(item.id)?.type === "driver") {
        openDriverEditor(item.id);
      } else if (item.container && !onTitle) {
        this.navigation.enter(item.id);
      } else {
        this.startRename(item.id);
      }
    });

    this.layers.links.node().addEventListener("click", (/** @type {MouseEvent} */ event) => {
      const group = /** @type {Element} */ (event.target).closest("g.link-group");
      const link = this.scene.links.find((candidate) => candidate.id === group?.getAttribute("data-id"));
      if (link) {
        this.selection.clear();
        app.linkFocus.set(link);
      }
    });

    svgNode.addEventListener("contextmenu", (/** @type {MouseEvent} */ event) => {
      event.preventDefault();
      const group = /** @type {Element} */ (event.target).closest("g.node");
      const id = group?.getAttribute("data-id");
      if (id) {
        if (!this.selection.has(id)) {
          this.selection.set([id]);
        }
        const handle = /** @type {Element} */ (event.target).closest("[data-port]");
        const direction = handle?.classList.contains("port-in") ? "in" : "out";
        const port = handle ? { name: /** @type {string} */ (handle.getAttribute("data-port")), direction } : null;
        nodeMenu(this, id, event.clientX, event.clientY, /** @type {any} */ (port));
      } else {
        backgroundMenu(this, this.toCanvas(event), event.clientX, event.clientY);
      }
    });
  }

  installKeyboard() {
    document.addEventListener("keydown", (event) => {
      if (event.key === " " && !isTypingTarget(/** @type {any} */ (event.target))) {
        this.spaceDown = true;
        this.container.classList.add("panning");
      }
      if (
        event.key === "Escape" &&
        !isTypingTarget(/** @type {any} */ (event.target)) &&
        !document.querySelector(".modal-backdrop, .context-menu")
      ) {
        this.selection.clear();
      }
    });
    document.addEventListener("keyup", (event) => {
      if (event.key === " ") {
        this.spaceDown = false;
        this.container.classList.remove("panning");
      }
    });
  }

  // Editing ------------------------------------------------------------------

  /**
   * Show a text field over the title of a node to rename it.
   *
   * @param {string} id
   */
  startRename(id) {
    const item = this.itemById(id);
    if (!item) {
      return;
    }
    const transform = d3.zoomTransform(this.svg.node());
    const [left, top] = transform.apply([item.x, item.y]);
    const input = /** @type {HTMLInputElement} */ (
      el("input.input.canvas-rename", { type: "text", value: item.node.name, spellcheck: "false" })
    );
    input.style.left = `${left}px`;
    input.style.top = `${top}px`;
    input.style.width = `${Math.max(120, NODE_WIDTH * transform.k)}px`;
    input.style.height = `${Math.max(20, HEADER_HEIGHT * transform.k)}px`;
    this.container.append(input);
    input.focus();
    input.select();
    let done = false;
    /** @param {boolean} commit */
    const finish = (commit) => {
      if (done) {
        return;
      }
      done = true;
      input.remove();
      const name = input.value.trim();
      if (commit && name && name !== item.node.name) {
        this.store
          .execute({ type: "renameNode", id, name })
          .catch((/** @type {any} */ error) => showError("The node could not be renamed", error));
      }
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
   * Add a node at a canvas position of the current level.
   *
   * @param {object} node - At least type, name and kind.
   * @param {{x: number, y: number}} position
   */
  async addNode(node, position) {
    try {
      await this.store.execute({ type: "addNode", parent: this.level, node, position });
    } catch (error) {
      showError("The node could not be added", error);
    }
  }

  /**
   * Add a node in the middle of the visible area.
   *
   * @param {object} node
   */
  addNodeAtCenter(node) {
    const { width, height } = this.viewportSize();
    const [x, y] = d3.zoomTransform(this.svg.node()).invert([width / 2 - NODE_WIDTH / 2, height / 3]);
    this.addNode(node, { x, y });
  }

  /** Accept nodes dropped from the Library. */
  installDrop() {
    this.container.addEventListener("dragover", (event) => {
      if (event.dataTransfer?.types.includes(NEW_NODE_TYPE)) {
        event.preventDefault();
        event.dataTransfer.dropEffect = "copy";
      }
    });
    this.container.addEventListener("drop", (event) => {
      const data = event.dataTransfer?.getData(NEW_NODE_TYPE);
      if (!data) {
        return;
      }
      event.preventDefault();
      const position = this.toCanvas(event);
      this.addNode(JSON.parse(data), { x: position.x - NODE_WIDTH / 2, y: position.y - HEADER_HEIGHT / 2 });
    });
  }
}
