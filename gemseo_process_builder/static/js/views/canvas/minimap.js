// @ts-check
// The minimap in the corner of the canvas: the nodes of the level as plain
// rectangles and the visible area; click or drag to move the view. Hidden
// while the whole level fits in the canvas.
import { el } from "../../components/dom.js";
import { boundingBox } from "../../lib/geometry.js";

const WIDTH = 180;
const HEIGHT = 120;
const PADDING = 6;
/** Below this number of nodes, the minimap is not worth its place. */
const MIN_NODES = 6;

export class Minimap {
  /** @param {import("./canvas.js").WorkflowCanvas} canvas */
  constructor(canvas) {
    const d3 = /** @type {any} */ (window).d3;
    this.canvas = canvas;
    this.root = el("div.minimap", { title: "Click or drag to move the view" });
    canvas.container.append(this.root);
    this.svg = d3.select(this.root).append("svg").attr("width", WIDTH).attr("height", HEIGHT);
    this.nodes = this.svg.append("g");
    this.frame = this.svg.append("rect").attr("class", "minimap-view");
    /** @type {{x: number, y: number, k: number} | null} - Canvas → minimap. */
    this.scale = null;
    this.root.addEventListener("pointerdown", (event) => {
      this.root.setPointerCapture(event.pointerId);
      this.moveTo(event);
      const move = (/** @type {PointerEvent} */ moveEvent) => this.moveTo(moveEvent);
      const up = () => {
        this.root.removeEventListener("pointermove", move);
        this.root.removeEventListener("pointerup", up);
      };
      this.root.addEventListener("pointermove", move);
      this.root.addEventListener("pointerup", up);
    });
  }

  /** The visible area of the canvas, in canvas coordinates. */
  visibleArea() {
    const d3 = /** @type {any} */ (window).d3;
    const t = d3.zoomTransform(this.canvas.svg.node());
    const { width, height } = this.canvas.viewportSize();
    return { x: -t.x / t.k, y: -t.y / t.k, width: width / t.k, height: height / t.k };
  }

  update() {
    const items = this.canvas.scene.items.filter((item) => item.depth === 0);
    const box = boundingBox(items);
    const view = this.visibleArea();
    const fits =
      box !== null &&
      box.x >= view.x &&
      box.y >= view.y &&
      box.x + box.width <= view.x + view.width &&
      box.y + box.height <= view.y + view.height;
    this.root.hidden = !box || items.length < MIN_NODES || fits;
    if (this.root.hidden || !box) {
      return;
    }
    const all = /** @type {import("../../lib/geometry.js").Rect} */ (boundingBox([box, view]));
    const k = Math.min((WIDTH - 2 * PADDING) / all.width, (HEIGHT - 2 * PADDING) / all.height);
    this.scale = { x: PADDING - all.x * k, y: PADDING - all.y * k, k };
    const { x, y } = this.scale;
    this.nodes
      .selectAll("rect")
      .data(items, (/** @type {any} */ item) => item.id)
      .join("rect")
      .attr("class", (/** @type {any} */ item) => `minimap-node minimap-${item.node.type}`)
      .attr("x", (/** @type {any} */ item) => x + item.x * k)
      .attr("y", (/** @type {any} */ item) => y + item.y * k)
      .attr("width", (/** @type {any} */ item) => Math.max(1, item.width * k))
      .attr("height", (/** @type {any} */ item) => Math.max(1, item.height * k));
    this.frame
      .attr("x", x + view.x * k)
      .attr("y", y + view.y * k)
      .attr("width", view.width * k)
      .attr("height", view.height * k);
  }

  /**
   * Center the canvas on the point of the minimap under the pointer.
   *
   * @param {PointerEvent} event
   */
  moveTo(event) {
    if (!this.scale) {
      return;
    }
    const d3 = /** @type {any} */ (window).d3;
    const box = this.root.getBoundingClientRect();
    const cx = (event.clientX - box.left - this.scale.x) / this.scale.k;
    const cy = (event.clientY - box.top - this.scale.y) / this.scale.k;
    const t = d3.zoomTransform(this.canvas.svg.node());
    const { width, height } = this.canvas.viewportSize();
    this.canvas.svg.call(this.canvas.zoom.transform, d3.zoomIdentity.translate(width / 2 - cx * t.k, height / 2 - cy * t.k).scale(t.k));
  }
}
