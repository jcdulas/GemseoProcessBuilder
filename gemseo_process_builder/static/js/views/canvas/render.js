// @ts-check
// Drawing of the canvas scene with d3.
import { HEADER_HEIGHT, fitText } from "../../lib/geometry.js";

const d3 = /** @type {any} */ (window).d3;

/** Short labels shown in node headers. */
const KIND_LABELS = {
  analytic: "Analytic",
  python_function: "Function",
  python_class: "Class",
  executable: "Executable",
  surrogate: "Surrogate",
  mda: "MDA",
  doe: "DOE",
  optimization: "Optimization",
  parametric: "Parametric",
};

/**
 * CSS class of a node, from its type and kind.
 *
 * @param {any} node
 * @returns {string}
 */
export function nodeClass(node) {
  if (node.type === "driver") {
    return `node-driver node-driver-${node.kind}`;
  }
  return `node-${node.type}`;
}

/**
 * Draw the inside of one node.
 *
 * @param {any} group - d3 selection of the node group.
 * @param {import("../../lib/scene.js").SceneItem} item
 */
function drawNode(group, item) {
  const { node, width, height, shape } = item;
  group.selectAll("*").remove();
  group
    .append("rect")
    .attr("class", item.expanded ? "node-body node-body-expanded" : "node-body")
    .attr("width", width)
    .attr("height", height)
    .attr("rx", 4);
  group.append("path").attr("class", "node-header").attr("d", headerPath(width));
  group
    .append("text")
    .attr("class", "node-title")
    .attr("x", 8)
    .attr("y", HEADER_HEIGHT / 2)
    .text(fitText(node.name, width - 90));
  const kind = node.type === "assembly" ? "Assembly" : (KIND_LABELS[/** @type {keyof KIND_LABELS} */ (node.kind)] ?? "");
  group
    .append("text")
    .attr("class", "node-kind")
    .attr("x", width - 8)
    .attr("y", HEADER_HEIGHT / 2)
    .text(kind);

  if (item.container) {
    if (!item.expanded) {
      const count = node.children.length;
      group
        .append("text")
        .attr("class", "node-summary")
        .attr("x", width / 2)
        .attr("y", HEADER_HEIGHT + (height - HEADER_HEIGHT) / 2)
        .text(count === 0 ? "Empty" : `${count} item${count > 1 ? "s" : ""}`);
    }
    return;
  }

  for (const row of shape.inputs) {
    group.append("circle").attr("class", "port port-in").attr("cx", 0).attr("cy", row.y).attr("r", 4);
    group
      .append("text")
      .attr("class", "port-label")
      .attr("x", 9)
      .attr("y", row.y)
      .text(fitText(row.name, width / 2 - 12));
  }
  for (const row of shape.outputs) {
    group.append("circle").attr("class", "port port-out").attr("cx", width).attr("cy", row.y).attr("r", 4);
    group
      .append("text")
      .attr("class", "port-label port-label-out")
      .attr("x", width - 9)
      .attr("y", row.y)
      .text(fitText(row.name, width / 2 - 12));
  }
  if (shape.hidden) {
    group
      .append("text")
      .attr("class", "node-hidden-ports")
      .attr("x", width / 2)
      .attr("y", height - 12)
      .text(`${shape.hidden} hidden variable${shape.hidden > 1 ? "s" : ""}`);
  }
}

/**
 * The header shape: a rectangle with rounded top corners.
 *
 * @param {number} width
 * @returns {string}
 */
function headerPath(width) {
  const r = 4;
  return `M0,${HEADER_HEIGHT} V${r} Q0,0 ${r},0 H${width - r} Q${width},0 ${width},${r} V${HEADER_HEIGHT} Z`;
}

/**
 * Draw the whole scene.
 *
 * @param {{nodes: any, links: any}} layers - d3 selections of the layer groups.
 * @param {ReturnType<typeof import("../../lib/scene.js").buildScene>} scene
 * @param {Set<string>} selected
 */
export function drawScene(layers, scene, selected) {
  layers.nodes
    .selectAll("g.node")
    .data(scene.items, (/** @type {any} */ item) => item.id)
    .join("g")
    .attr("class", (/** @type {any} */ item) => `node ${nodeClass(item.node)}${item.expanded ? " expanded" : ""}`)
    .attr("data-id", (/** @type {any} */ item) => item.id)
    .classed("selected", (/** @type {any} */ item) => selected.has(item.id))
    .attr("transform", (/** @type {any} */ item) => `translate(${item.x},${item.y})`)
    .each(function (/** @type {any} */ item) {
      // @ts-ignore - d3 binds `this` to the group element.
      drawNode(d3.select(this), item);
    })
    .order();

  layers.links
    .selectAll("path.link")
    .data(scene.links, (/** @type {any} */ link) => link.id)
    .join("path")
    .attr("class", "link link-explicit")
    .attr("data-id", (/** @type {any} */ link) => link.id)
    .attr("d", (/** @type {any} */ link) => link.path);
}

/**
 * Only update positions (while dragging), without rebuilding the nodes.
 *
 * @param {{nodes: any, links: any}} layers
 * @param {ReturnType<typeof import("../../lib/scene.js").buildScene>} scene
 */
export function moveScene(layers, scene) {
  const byId = new Map(scene.items.map((item) => [item.id, item]));
  layers.nodes.selectAll("g.node").attr("transform", function (/** @type {any} */ item) {
    const moved = byId.get(item.id) ?? item;
    return `translate(${moved.x},${moved.y})`;
  });
  const paths = new Map(scene.links.map((link) => [link.id, link.path]));
  layers.links.selectAll("path.link").attr("d", (/** @type {any} */ link) => paths.get(link.id) ?? link.path);
}
