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
 * @param {{state: string, error: string}} status - Introspection status.
 */
function drawNode(group, item, status) {
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
  if (status.state === "running" || status.state === "error") {
    group
      .append("text")
      .attr("class", `node-status node-status-${status.state}`)
      .attr("x", width - 8 - kind.length * 6 - 8)
      .attr("y", HEADER_HEIGHT / 2)
      .text(status.state === "error" ? "⚠" : "…")
      .append("title")
      .text(status.state === "error" ? status.error : "Reading the variables…");
  }

  if (item.container && !item.expanded && !shape.inputs.length && !shape.outputs.length) {
    const count = node.children.length;
    group
      .append("text")
      .attr("class", "node-summary")
      .attr("x", width / 2)
      .attr("y", HEADER_HEIGHT + (height - HEADER_HEIGHT) / 2)
      .text(count === 0 ? "Empty" : `${count} item${count > 1 ? "s" : ""}`);
    return;
  }
  if (item.expanded) {
    return;
  }

  for (const row of shape.inputs) {
    group
      .append("circle")
      .attr("class", `port port-in port-handle${item.freeInputs.has(row.name) ? " port-free" : ""}`)
      .attr("data-node", node.id)
      .attr("data-port", row.name)
      .attr("data-direction", "in")
      .attr("cx", 0)
      .attr("cy", row.y)
      .attr("r", 4)
      .append("title")
      .text(item.freeInputs.has(row.name) ? `${row.name}: free input (no component computes it)` : row.name);
    group
      .append("text")
      .attr("class", "port-label")
      .attr("x", 9)
      .attr("y", row.y)
      .text(fitText(row.name, width / 2 - 12));
  }
  for (const row of shape.outputs) {
    group
      .append("circle")
      .attr("class", "port port-out port-handle")
      .attr("data-node", node.id)
      .attr("data-port", row.name)
      .attr("data-direction", "out")
      .attr("cx", width)
      .attr("cy", row.y)
      .attr("r", 4)
      .append("title")
      .text(row.name);
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
 * @param {(id: string) => {state: string, error: string}} statusOf
 * @param {(id: string) => {level: string | null, messages: string[]}} [problemsOf]
 */
export function drawScene(layers, scene, selected, statusOf, problemsOf = () => ({ level: null, messages: [] })) {
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
      const group = d3.select(this);
      drawNode(group, item, statusOf(item.id));
      const problems = problemsOf(item.id);
      group
        .classed("problem-error", problems.level === "error")
        .classed("problem-warning", problems.level === "warning");
      if (problems.messages.length) {
        group.select("rect.node-body").append("title").text(problems.messages.join("\n"));
      }
    })
    .order();

  layers.links
    .selectAll("g.link-group")
    .data(scene.links, (/** @type {any} */ link) => link.id)
    .join((/** @type {any} */ enter) => {
      const group = enter.append("g").attr("class", "link-group");
      group.append("path").attr("class", "link-hit");
      group.append("path").attr("class", "link");
      group.append("title");
      return group;
    })
    .attr("data-id", (/** @type {any} */ link) => link.id)
    .attr("data-from", (/** @type {any} */ link) => link.from)
    .attr("data-to", (/** @type {any} */ link) => link.to)
    .attr("data-source-port", (/** @type {any} */ link) => link.sourcePort)
    .attr("data-target-port", (/** @type {any} */ link) => link.targetPort)
    .each(function (/** @type {any} */ link) {
      // @ts-ignore - d3 binds `this` to the group element.
      const group = d3.select(this);
      group.select("path.link-hit").attr("d", link.path);
      group
        .select("path.link")
        .attr("class", `link link-${link.kind}${link.feedback ? " link-feedback" : ""}`)
        .attr("d", link.path);
      group.select("title").text(linkTooltip(link));
      group.selectAll("text.link-count").remove();
      if (link.label) {
        group
          .append("text")
          .attr("class", "link-count")
          .attr("x", link.label.x)
          .attr("y", link.label.y)
          .text(link.variables.length);
      }
    });
}

/**
 * The tooltip of a link.
 *
 * @param {import("../../lib/scene.js").SceneLink} link
 * @returns {string}
 */
export function linkTooltip(link) {
  const names = link.variables.map((variable) => variable.name).join(", ");
  const kind =
    link.kind === "aggregated"
      ? `${link.variables.length} variables`
      : link.kind === "explicit"
        ? "explicit link"
        : "coupled by name";
  return `${names} (${kind}${link.feedback ? ", feedback" : ""})`;
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
  layers.links
    .selectAll("g.link-group")
    .selectAll("path")
    .attr("d", function () {
      // @ts-ignore - d3 binds `this` to the path element.
      const id = this.parentNode.getAttribute("data-id");
      // @ts-ignore
      return paths.get(id) ?? this.getAttribute("d");
    });
}
