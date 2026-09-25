// @ts-check
// Drawing of the canvas scene with d3.
import { HEADER_HEIGHT, fitText } from "../../lib/geometry.js";
import { conversionNotes } from "../../lib/link_compat.js";
import { NODE_ICON_PATHS, nodeAppearance } from "../../lib/node_icons.js";

const d3 = /** @type {any} */ (window).d3;

/** Size of the icon tile of a card, and of a header. */
const CARD_TILE = 36;
const HEADER_TILE = 26;
const RADIUS = 12;
/** Width of the characters of titles over that of subtitles (13 px and 11 px). */
const SUBTITLE_SCALE = 13 / 11;

/**
 * CSS class of a node, from its type and kind.
 *
 * @param {any} node
 * @returns {string}
 */
export function nodeClass(node) {
  const tone = `tone-${nodeAppearance(node).tone}`;
  if (node.type === "driver") {
    return `node-driver node-driver-${node.kind} ${tone}`;
  }
  return `node-${node.type} ${tone}`;
}

/**
 * The icon of a node in a rounded tile tinted with the color of its type.
 *
 * @param {any} group
 * @param {any} node
 * @param {number} x
 * @param {number} y
 * @param {number} size
 */
function drawTile(group, node, x, y, size) {
  const tile = group.append("g").attr("class", "node-tile").attr("transform", `translate(${x},${y})`);
  tile.append("rect").attr("class", "node-tile-back").attr("width", size).attr("height", size).attr("rx", size / 4);
  const scale = (size * 0.62) / 24;
  const offset = (size - 24 * scale) / 2;
  tile
    .append("path")
    .attr("class", "node-tile-icon")
    .attr("transform", `translate(${offset},${offset}) scale(${scale})`)
    .attr("d", NODE_ICON_PATHS[nodeAppearance(node).icon]);
}

/**
 * The status of the introspection of a component: reading, or failed.
 *
 * @param {any} group
 * @param {{state: string, error: string}} status
 * @param {number} x
 * @param {number} y
 */
function drawIntrospection(group, status, x, y) {
  if (status.state !== "running" && status.state !== "error") {
    return;
  }
  group
    .append("text")
    .attr("class", `node-status node-status-${status.state}`)
    .attr("x", x)
    .attr("y", y)
    .text(status.state === "error" ? "⚠" : "…")
    .append("title")
    .text(status.state === "error" ? status.error : "Reading the variables…");
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
  if (item.terminal) {
    drawTerminal(group, item);
    return;
  }
  // The ring shows the selection and the running state around the node.
  group
    .append("rect")
    .attr("class", "node-ring")
    .attr("x", -4)
    .attr("y", -4)
    .attr("width", width + 8)
    .attr("height", height + 8)
    .attr("rx", RADIUS + 4);
  if (!item.expanded) {
    group
      .append("rect")
      .attr("class", "node-shadow")
      .attr("y", 2)
      .attr("width", width)
      .attr("height", height)
      .attr("rx", RADIUS);
  }
  group
    .append("rect")
    .attr("class", item.expanded ? "node-body node-body-expanded" : "node-body")
    .attr("width", width)
    .attr("height", height)
    .attr("rx", RADIUS);

  if (item.order) {
    // Its rank in a chain: the order in which the disciplines run.
    const badge = group.append("g").attr("class", "node-order").attr("transform", "translate(2,2)");
    badge.append("circle").attr("r", 9);
    badge.append("text").text(item.order).append("title").text(`Runs in position ${item.order} of the chain`);
  }
  if (item.order || item.chainable) {
    // Dragged onto another node of the chain, it makes that node run next.
    // In a group run automatically, it shows on hover and makes a chain.
    group
      .append("circle")
      .attr("class", item.order ? "exec-handle" : "exec-handle latent")
      .attr("data-node", node.id)
      .attr("cx", width / 2)
      .attr("cy", height)
      .attr("r", 5.5)
      .append("title")
      .text("Drag to the node that runs next");
  }
  if (shape.card && !item.expanded) {
    drawCard(group, item, status);
    return;
  }
  if (item.container && !item.expanded && !shape.inputs.length && !shape.outputs.length) {
    const count = node.children.length;
    const card = { ...item, shape: { ...shape, card: { inputs: 0, outputs: 0 } } };
    drawCard(group, card, status, count === 0 ? "empty" : `${count} item${count > 1 ? "s" : ""}`);
    return;
  }

  // A header (icon, name and kind), and the variables listed below it.
  const kind = nodeAppearance(node).label;
  const middle = HEADER_HEIGHT / 2;
  drawTile(group, node, 10, middle - HEADER_TILE / 2, HEADER_TILE);
  group
    .append("text")
    .attr("class", "node-title")
    .attr("x", 44)
    .attr("y", middle)
    .text(fitText(node.name, width - 60 - kind.length * 6));
  group
    .append("text")
    .attr("class", "node-kind")
    .attr("x", width - 12)
    .attr("y", middle)
    .text(kind);
  drawIntrospection(group, status, width - 20 - kind.length * 6.5, middle);
  if (item.expanded) {
    return;
  }
  group.append("path").attr("class", "node-divider").attr("d", `M0,${HEADER_HEIGHT}H${width}`);

  for (const row of shape.inputs) {
    group
      .append("circle")
      .attr("class", `port port-in port-handle${item.freeInputs.has(row.name) ? " port-free" : ""}`)
      .attr("data-node", node.id)
      .attr("data-port", row.name)
      .attr("data-direction", "in")
      .attr("cx", 0)
      .attr("cy", row.y)
      .attr("r", 4.5)
      .append("title")
      .text(item.freeInputs.has(row.name) ? `${row.name}: free input (no component computes it)` : row.name);
    group
      .append("text")
      .attr("class", "port-label")
      .attr("x", 11)
      .attr("y", row.y)
      .text(fitText(row.name, width / 2 - 14));
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
      .attr("r", 4.5)
      .append("title")
      .text(row.name);
    group
      .append("text")
      .attr("class", "port-label port-label-out")
      .attr("x", width - 11)
      .attr("y", row.y)
      .text(fitText(row.name, width / 2 - 14));
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

/** Glyphs of the start (play) and the end (stop), centered on 0. */
const TERMINAL_GLYPHS = { start: "M-5,-8 L9,0 L-5,8 Z", end: "M-7,-7 H7 V7 H-7 Z" };

/**
 * The start or the end of the workflow: a circle, its name, and the number of
 * its inputs or results under it.
 *
 * @param {any} group
 * @param {import("../../lib/scene.js").SceneItem} item
 */
function drawTerminal(group, item) {
  const radius = item.width / 2;
  const variables = item.node.variables ?? [];
  group.append("circle").attr("class", "node-ring").attr("cx", radius).attr("cy", radius).attr("r", radius + 4);
  group
    .append("circle")
    .attr("class", `terminal terminal-${item.terminal}`)
    .attr("cx", radius)
    .attr("cy", radius)
    .attr("r", radius);
  group
    .append("path")
    .attr("class", "terminal-glyph")
    .attr("transform", `translate(${radius},${radius})`)
    .attr("d", TERMINAL_GLYPHS[/** @type {"start" | "end"} */ (item.terminal)]);
  group.append("text").attr("class", "terminal-name").attr("x", radius).attr("y", item.height + 16).text(item.node.name);
  const count = variables.length;
  const noun = item.terminal === "start" ? "input" : "result";
  group
    .append("text")
    .attr("class", "terminal-count")
    .attr("x", radius)
    .attr("y", item.height + 31)
    .text(count ? `${count} ${noun}${count > 1 ? "s" : ""}` : `no ${noun}`);
  group
    .append("title")
    .text(
      `${item.terminal === "start" ? "The inputs of the workflow" : "The results of the workflow"}: click to see them\n` +
        variables.map((/** @type {any} */ variable) => variable.name).join(", "),
    );
  if (item.terminal === "end") {
    // Dragging a node onto the end shows more of its outputs.
    group
      .append("circle")
      .attr("class", "port port-in node-handle terminal-handle")
      .attr("data-node", item.id)
      .attr("data-port", "")
      .attr("data-direction", "in")
      .attr("cx", 0)
      .attr("cy", radius)
      .attr("r", 5);
  }
}

/**
 * A card: the icon, the name, a subtitle with the kind and the count of the
 * variables (and of the children of a container), and one link point on each side.
 *
 * @param {any} group
 * @param {import("../../lib/scene.js").SceneItem} item
 * @param {{state: string, error: string}} status
 * @param {string} [summary] - Replaces the count of the variables.
 */
function drawCard(group, item, status, summary) {
  const { node, width, height, shape } = item;
  const counts = /** @type {{inputs: number, outputs: number}} */ (shape.card);
  const middle = height / 2;
  drawTile(group, node, 12, middle - CARD_TILE / 2, CARD_TILE);
  const parts = [nodeAppearance(node).label];
  if (summary) {
    parts.push(summary);
  } else {
    if (item.container) {
      const count = node.children.length;
      parts.push(count === 0 ? "empty" : `${count} item${count > 1 ? "s" : ""}`);
    }
    parts.push(`${counts.inputs} in · ${counts.outputs} out`);
  }
  group
    .append("text")
    .attr("class", "node-title")
    .attr("x", 58)
    .attr("y", middle - 8)
    .text(fitText(node.name, width - 76));
  group
    .append("text")
    .attr("class", "node-subtitle")
    .attr("x", 58)
    .attr("y", middle + 10)
    // Smaller than the titles fitText is tuned for: more characters fit.
    .text(fitText(parts.join(" · "), (width - 70) * SUBTITLE_SCALE));
  drawIntrospection(group, status, width - 12, 14);
  for (const direction of /** @type {const} */ (["in", "out"])) {
    if (!counts[direction === "in" ? "inputs" : "outputs"]) {
      continue;
    }
    group
      .append("circle")
      .attr("class", `port port-${direction} port-handle node-handle`)
      .attr("data-node", node.id)
      .attr("data-port", "")
      .attr("data-direction", direction)
      .attr("cx", direction === "in" ? 0 : width)
      .attr("cy", middle)
      .attr("r", 6.5)
      .append("title")
      .text(
        direction === "in" ? "Inputs: drop a link here" : "Outputs: drag to another node to link variables",
      );
  }
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
    .attr("class", (/** @type {any} */ item) => {
      const level = problemsOf(item.id).level;
      const problem = level === "error" || level === "warning" ? ` problem-${level}` : "";
      return `node ${nodeClass(item.node)}${item.expanded ? " expanded" : ""}${problem}`;
    })
    .attr("data-id", (/** @type {any} */ item) => item.id)
    .classed("selected", (/** @type {any} */ item) => selected.has(item.id))
    .attr("transform", (/** @type {any} */ item) => `translate(${item.x},${item.y})`)
    .each(function (/** @type {any} */ item) {
      const status = statusOf(item.id);
      const problems = problemsOf(item.id);
      // A node is drawn again only when what it shows changed (the store
      // replaces the data of the nodes a change touches).
      const key = [
        item.width,
        item.height,
        item.expanded,
        item.shape.inputs.length,
        item.shape.outputs.length,
        item.freeInputs.size,
        item.order,
        item.chainable,
        item.node.mode,
        status.state,
        status.error,
        problems.level,
        problems.messages.join("|"),
      ].join(";");
      // @ts-ignore - the node data and key drawn are kept on the element.
      if (this.__drawnNode === item.node && this.__drawnKey === key) {
        return;
      }
      // @ts-ignore
      this.__drawnNode = item.node;
      // @ts-ignore
      this.__drawnKey = key;
      // @ts-ignore - d3 binds `this` to the group element.
      const group = d3.select(this);
      drawNode(group, item, status);
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
      // Links are drawn again only when they moved or carry other variables.
      // @ts-ignore - the path and variables drawn are kept on the element.
      if (this.__drawnPath === link.path && this.__drawnVariables === link.variables) {
        return;
      }
      // @ts-ignore
      this.__drawnPath = link.path;
      // @ts-ignore
      this.__drawnVariables = link.variables;
      // @ts-ignore - d3 binds `this` to the group element.
      const group = d3.select(this);
      group.select("path.link-hit").attr("d", link.path);
      group
        .select("path.link")
        .attr(
          "class",
          `link link-${link.kind}${link.feedback ? " link-feedback" : ""}${
            link.variables.some((/** @type {any} */ variable) => variable.converted) ? " link-converted" : ""
          }`,
        )
        .attr("d", link.path);
      group.select("title").text(linkTooltip(link));
      group.selectAll("path.link-mark").remove();
      if (link.mark) {
        group.append("path").attr("class", "link-mark").attr("d", link.mark);
      }
      group.selectAll(".link-count").remove();
      if (link.label) {
        const text = String(link.variables.length);
        const badgeWidth = 12 + text.length * 7;
        const badge = group
          .append("g")
          .attr("class", "link-count")
          .attr("transform", `translate(${link.label.x},${link.label.y})`);
        badge.append("rect").attr("x", -badgeWidth / 2).attr("y", -9).attr("width", badgeWidth).attr("height", 18).attr("rx", 9);
        badge.append("text").text(text);
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
  if (link.kind === "io") {
    return link.variables.map((variable) => variable.name).join("\n");
  }
  if (link.kind === "execution") {
    return "Execution order";
  }
  if (link.kind === "control") {
    return "Driven: runs within its driver, without exchanging variables with it";
  }
  if (link.kind === "driver") {
    return link.variables.map((variable) => `${variable.name} (${variable.role})`).join("\n");
  }
  const names = link.variables.map((variable) => variable.name).join(", ");
  const kind =
    link.kind === "aggregated"
      ? `${link.variables.length} variables`
      : link.kind === "explicit"
        ? "explicit link"
        : "coupled by name";
  const notes = conversionNotes(link.variables);
  return `${names} (${kind}${link.feedback ? ", feedback" : ""})${notes.length ? `\nUnits: ${notes.join("; ")}` : ""}`;
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
  const marks = new Map(scene.links.map((link) => [link.id, link.mark]));
  layers.links
    .selectAll("g.link-group")
    .selectAll("path.link-mark")
    .attr("d", function () {
      // @ts-ignore - d3 binds `this` to the path element.
      return marks.get(this.parentNode.getAttribute("data-id")) ?? this.getAttribute("d");
    });
  layers.links
    .selectAll("g.link-group")
    .selectAll("path.link, path.link-hit")
    .attr("d", function () {
      // @ts-ignore - d3 binds `this` to the path element.
      const id = this.parentNode.getAttribute("data-id");
      // @ts-ignore
      return paths.get(id) ?? this.getAttribute("d");
    });
}
