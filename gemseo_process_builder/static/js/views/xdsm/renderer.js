// @ts-check
// Draw XDSM diagrams with d3 (SPEC § 8.5): components on the diagonal, data
// blocks off the diagonal, grey data lines and numbered process lines.
//
// This module only needs d3 and ``lib/xdsm_layout.js``: the standalone HTML
// export inlines both (``app/xdsm_export.py``), so it must not import the
// rest of the application.
import { USER, blockLabel, nodeLabel, scenarioName, xdsmLayout } from "../../lib/xdsm_layout.js";

const CELL_WIDTH = 170;
const CELL_HEIGHT = 56;
const NODE_WIDTH = 150;
const NODE_HEIGHT = 36;
const BLOCK_WIDTH = 140;
const BLOCK_HEIGHT = 30;
const SKEW = 8;
const CHAR_WIDTH = 6.6;

/**
 * A text cut to fit a width.
 *
 * @param {string} text
 * @param {number} width
 */
function fit(text, width) {
  const max = Math.max(3, Math.floor(width / CHAR_WIDTH));
  return text.length <= max ? text : `${text.slice(0, max - 1)}…`;
}

/** @param {number} col */
const cx = (col) => col * CELL_WIDTH + CELL_WIDTH / 2;
/** @param {number} row */
const cy = (row) => row * CELL_HEIGHT + CELL_HEIGHT / 2;

/**
 * @typedef {object} XdsmOptions
 * @property {(event: {diagram: string, node: import("../../lib/xdsm_layout.js").XdsmNode}) => void} [onNodeClick]
 */

/**
 * Show a set of XDSM diagrams (``root`` and one per sub-scenario) in an element.
 *
 * @param {HTMLElement} root
 * @param {Record<string, import("../../lib/xdsm_layout.js").XdsmDiagram>} diagrams
 * @param {XdsmOptions} [options]
 */
export function mountXdsm(root, diagrams, options = {}) {
  const d3 = /** @type {any} */ (window).d3;
  const bar = document.createElement("div");
  bar.className = "xdsm-bar";
  const stage = document.createElement("div");
  stage.className = "xdsm-stage";
  root.replaceChildren(bar, stage);
  const svg = d3.select(stage).append("svg").attr("class", "xdsm-svg");
  const defs = svg.append("defs");
  defs
    .append("marker")
    .attr("id", "xdsm-arrow")
    .attr("viewBox", "0 0 10 10")
    .attr("refX", 9)
    .attr("refY", 5)
    .attr("markerWidth", 7)
    .attr("markerHeight", 7)
    .attr("orient", "auto-start-reverse")
    .append("path")
    .attr("class", "xdsm-arrow")
    .attr("d", "M0,0L10,5L0,10Z");
  const content = svg.append("g");
  const zoom = d3
    .zoom()
    .scaleExtent([0.1, 4])
    .on("zoom", (/** @type {any} */ event) => content.attr("transform", event.transform));
  svg.call(zoom).on("dblclick.zoom", null);
  /** @type {string[]} - The diagrams opened, from the root. */
  let path = ["root"];

  const breadcrumb = () => {
    bar.replaceChildren(
      ...path.flatMap((name, index) => {
        const button = document.createElement("button");
        button.className = "xdsm-crumb";
        button.textContent = index === 0 ? "Process" : scenarioName(name);
        button.disabled = index === path.length - 1;
        button.addEventListener("click", () => {
          path = path.slice(0, index + 1);
          draw();
        });
        const separator = document.createElement("span");
        separator.className = "xdsm-separator";
        separator.textContent = "›";
        return index ? [separator, button] : [button];
      }),
    );
  };

  const fitView = () => {
    const box = /** @type {SVGGElement} */ (content.node()).getBBox();
    const width = stage.clientWidth;
    const height = stage.clientHeight;
    if (!width || !height || !box.width) {
      return;
    }
    const k = Math.min(1.5, (width - 40) / box.width, (height - 40) / box.height);
    svg.call(zoom.transform, d3.zoomIdentity.translate((width - k * box.width) / 2 - k * box.x, (height - k * box.height) / 2 - k * box.y).scale(k));
  };

  const draw = () => {
    const name = path[path.length - 1];
    const diagram = diagrams[name];
    content.selectAll("*").remove();
    breadcrumb();
    if (!diagram) {
      return;
    }
    const layout = xdsmLayout(diagram);
    // Data lines, under everything.
    content
      .append("g")
      .attr("class", "xdsm-lines")
      .selectAll("line")
      .data(layout.lines)
      .join("line")
      .attr("x1", (/** @type {any} */ line) => cx(line.col1))
      .attr("y1", (/** @type {any} */ line) => cy(line.row1))
      .attr("x2", (/** @type {any} */ line) => cx(line.col2))
      .attr("y2", (/** @type {any} */ line) => cy(line.row2));
    // Process: from a component along its row, then down its column.
    const byId = new Map(layout.nodes.map((node) => [node.id, node.index]));
    const process = layout.steps.filter((step) => step.from !== USER && step.to !== USER);
    content
      .append("g")
      .attr("class", "xdsm-process")
      .selectAll("path")
      .data(process)
      .join("path")
      .attr("marker-end", "url(#xdsm-arrow)")
      .attr("d", (/** @type {any} */ step) => {
        const from = /** @type {number} */ (byId.get(step.from));
        const to = /** @type {number} */ (byId.get(step.to));
        const offset = from < to ? -6 : 6;
        const endY = cy(to) + (from < to ? -NODE_HEIGHT / 2 : NODE_HEIGHT / 2);
        return `M${cx(from) + offset},${cy(from)}H${cx(to) + offset}V${endY}`;
      });
    // Data blocks: parallelograms.
    const blocks = content
      .append("g")
      .attr("class", "xdsm-blocks")
      .selectAll("g")
      .data(layout.blocks)
      .join("g")
      .attr("class", (/** @type {any} */ block) => `xdsm-block${block.row === 0 || block.col === 0 ? " xdsm-block-user" : ""}`)
      .attr("transform", (/** @type {any} */ block) => `translate(${cx(block.col)},${cy(block.row)})`);
    blocks
      .append("path")
      .attr("d", `M${-BLOCK_WIDTH / 2 + SKEW},${-BLOCK_HEIGHT / 2}H${BLOCK_WIDTH / 2}L${BLOCK_WIDTH / 2 - SKEW},${BLOCK_HEIGHT / 2}H${-BLOCK_WIDTH / 2}Z`);
    blocks
      .append("text")
      .attr("class", "xdsm-block-text")
      .text((/** @type {any} */ block) => fit(blockLabel(block.variables), BLOCK_WIDTH - 2 * SKEW));
    blocks.append("title").text((/** @type {any} */ block) => block.variables.join(", "));
    // Components on the diagonal.
    const nodes = content
      .append("g")
      .attr("class", "xdsm-nodes")
      .selectAll("g")
      .data(layout.nodes)
      .join("g")
      .attr("class", (/** @type {any} */ node) => `xdsm-node xdsm-${node.type}${node.subxdsm ? " xdsm-has-sub" : ""}`)
      .attr("transform", (/** @type {any} */ node) => `translate(${cx(node.index)},${cy(node.index)})`)
      .on("click", (/** @type {MouseEvent} */ _event, /** @type {any} */ node) => {
        options.onNodeClick?.({ diagram: name, node });
      })
      .on("dblclick", (/** @type {MouseEvent} */ _event, /** @type {any} */ node) => {
        if (node.subxdsm && diagrams[node.subxdsm]) {
          path = [...path, node.subxdsm];
          draw();
        }
      });
    nodes
      .filter((/** @type {any} */ node) => node.subxdsm)
      .append("rect")
      .attr("class", "xdsm-shadow")
      .attr("x", -NODE_WIDTH / 2 + 4)
      .attr("y", -NODE_HEIGHT / 2 + 4)
      .attr("width", NODE_WIDTH)
      .attr("height", NODE_HEIGHT);
    nodes
      .append("rect")
      .attr("class", "xdsm-shape")
      .attr("x", -NODE_WIDTH / 2)
      .attr("y", -NODE_HEIGHT / 2)
      .attr("width", NODE_WIDTH)
      .attr("height", NODE_HEIGHT)
      .attr("rx", (/** @type {any} */ node) => (node.type === "analysis" || node.type === "function" ? 2 : 12));
    nodes
      .append("text")
      .attr("class", "xdsm-node-text")
      .text((/** @type {any} */ node) => fit(nodeLabel({ ...node, name: scenarioName(node.name) }), NODE_WIDTH - 10));
    nodes
      .append("title")
      .text((/** @type {any} */ node) => (node.subxdsm ? `${scenarioName(node.name)}: double-click to open its XDSM` : node.name));
    fitView();
  };

  new ResizeObserver(() => {
    if (!content.select("g").empty()) {
      fitView();
    }
  }).observe(stage);
  draw();
  return {
    /** Show the XDSM of the process again (after a new build). */
    reset() {
      path = path.filter((name) => name === "root" || name in diagrams);
      draw();
    },
    fit: fitView,
    /** @returns {SVGSVGElement} */
    svg: () => svg.node(),
  };
}
