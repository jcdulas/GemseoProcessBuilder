// @ts-check
// What the workflow canvas draws for one level of the hierarchy: the nodes of
// the level (and the children of containers expanded in place), and the
// couplings between them, as resolved by Python (`resolve.level`). Drivers are
// containers like assemblies: the nodes they drive are shown inside them.
import {
  CONTAINER_PADDING,
  HEADER_HEIGHT,
  NODE_WIDTH,
  boundingBox,
  cardAnchor,
  cardShape,
  gridPosition,
  linkPath,
  nodeShape,
  portAnchor,
  sideAnchor,
  visiblePorts,
} from "./geometry.js";
import { labelPosition, routeLink } from "./link_routing.js";

const MAX_DEPTH = 6;
/** Beyond this number of variables, the couplings of a pair are one link. */
export const MAX_LINKS_PER_PAIR = 4;
/** Diameter of the start and end circles of a workflow. */
export const TERMINAL_SIZE = 56;
/** Space between the start or end circle and the nodes of the workflow. */
export const TERMINAL_GAP = 120;
/** Beyond this number of nodes linked to the start or the end, the circles are drawn without links. */
export const MAX_TERMINAL_LINKS = 60;

/**
 * @typedef {object} WorkflowVariable - An input or output of a workflow (`workflow.io`).
 * @property {string} name
 * @property {string[]} nodes - The components using it (inputs) or computing it (outputs).
 * @property {any} value
 * @property {string | null} text
 * @property {string | null} unit
 * @property {boolean} final
 */

/**
 * @typedef {object} WorkflowIO - The inputs and outputs of the level shown (`workflow.io`).
 * @property {WorkflowVariable[]} inputs
 * @property {WorkflowVariable[]} outputs
 * @property {WorkflowVariable[]} others - Outputs that can be shown at the end too.
 */

/**
 * @typedef {object} LevelView - The result of `resolve.level`.
 * @property {string} level
 * @property {Record<string, {in: any, out: any}>} ports - Per child: for
 *   components, local name → global name; for containers, lists of global names.
 * @property {{source: string, target: string, feedback: boolean, variables: any[]}[]} edges
 * @property {string[]} free_inputs - Global names without a producer in the scope.
 */

/**
 * @typedef {object} SceneItem
 * @property {string} id
 * @property {any} node - The node entity.
 * @property {boolean} container
 * @property {boolean} expanded - A container showing its children in place.
 * @property {"start" | "end"} [terminal] - The start or the end circle of the workflow.
 * @property {number} x - Top-left corner, in canvas coordinates.
 * @property {number} y
 * @property {{x: number, y: number}} local - Position stored in the layout,
 *   relative to the container holding the node.
 * @property {number} width
 * @property {number} height
 * @property {import("./geometry.js").NodeShape} shape - Header and port rows.
 * @property {number} depth - 0 for the nodes of the level.
 * @property {string} parent - The container holding the node.
 * @property {Set<string>} freeInputs - Shown input rows without a producer.
 * @property {number} [order] - Its rank in an assembly run as a chain, from 1.
 * @property {boolean} [chainable] - In an assembly run automatically: an
 *   execution arrow drawn from it makes the assembly a chain.
 */

/**
 * @typedef {object} SceneLink
 * @property {string} id
 * @property {string} from - Scene item drawn as the source.
 * @property {string} to - Scene item drawn as the target.
 * @property {string} path
 * @property {"explicit" | "implicit" | "aggregated" | "execution" | "io"} kind - io:
 *   the inputs of the workflow going from its start, or its results going to its end;
 *   execution: the order in which an assembly runs its content (a chain, or the
 *   branches of a parallel block).
 * @property {boolean} feedback
 * @property {any[]} variables
 * @property {{x: number, y: number} | null} label - Where to write the count.
 * @property {string} sourcePort - Row name at the source ("" for side anchors).
 * @property {string} targetPort
 * @property {string} [mark] - For execution links: a filled shape (arrowhead, fork or join point).
 * @property {string} [container] - For execution links: the assembly running the nodes.
 */

/**
 * Connected ports of every component, as "in:name" / "out:name" keys.
 *
 * @param {LevelView[]} views
 * @returns {Map<string, Set<string>>}
 */
export function connectedPorts(views) {
  /** @type {Map<string, Set<string>>} */
  const connected = new Map();
  /**
   * @param {string} node
   * @param {string} key
   */
  const add = (node, key) => {
    if (!connected.has(node)) {
      connected.set(node, new Set());
    }
    connected.get(node)?.add(key);
  };
  for (const view of views) {
    for (const edge of view.edges) {
      for (const variable of edge.variables) {
        add(edge.source, `out:${variable.source_port || variable.name}`);
        add(edge.target, `in:${variable.target_port || variable.name}`);
      }
    }
  }
  return connected;
}

/**
 * The ports shown on a node: its own ports (components) or its derived ports
 * (containers), whose row names are global names.
 *
 * @param {any} node
 * @param {LevelView | undefined} view - The view of the node's parent level.
 * @returns {{local_name: string, direction: string}[]}
 */
function portsOf(node, view) {
  if (!Array.isArray(node.children)) {
    return node.ports ?? [];
  }
  const derived = view?.ports[node.id];
  if (!derived) {
    return [];
  }
  return [
    ...derived.in.map((/** @type {string} */ name) => ({ local_name: name, direction: "in" })),
    ...derived.out.map((/** @type {string} */ name) => ({ local_name: name, direction: "out" })),
  ];
}

/**
 * Build the scene of a level.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId - The container whose content is shown.
 * @param {Map<string, {x: number, y: number}>} [overrides] - Positions replacing
 *   the stored ones (nodes being dragged), in their container's coordinates.
 * @param {Map<string, LevelView>} [views] - Resolved couplings of the level and
 *   of the containers expanded in place, by container id.
 * @param {boolean} [expandAll] - Expand every container in place (image export
 *   of the whole model).
 * @param {WorkflowIO | null} [io] - The inputs and outputs of the level: drawn as
 *   the start and the end of the workflow.
 * @returns {{items: SceneItem[], links: SceneLink[], box: import("./geometry.js").Rect | null}}
 */
export function buildScene(state, levelId, overrides = new Map(), views = new Map(), expandAll = false, io = null) {
  /** @type {SceneItem[]} */
  const items = [];
  const connected = connectedPorts([...views.values()]);
  // The free inputs of each view, as a set built once: a level has thousands.
  /** @type {Map<LevelView | undefined, Set<string>>} */
  const freeSets = new Map();
  /** @param {LevelView | undefined} view */
  const freeInputsOf = (view) => {
    let free = freeSets.get(view);
    if (!free) {
      free = new Set(view?.free_inputs ?? []);
      freeSets.set(view, free);
    }
    return free;
  };

  /**
   * @param {string} containerId
   * @param {number} offsetX - Where the coordinates of the children start.
   * @param {number} offsetY
   * @param {number} depth
   * @returns {SceneItem[]}
   */
  const placeChildren = (containerId, offsetX, offsetY, depth) => {
    /** @type {SceneItem[]} */
    const placed = [];
    let unplaced = 0;
    const view = views.get(containerId);
    const holder = state.nodes[containerId];
    const chain = holder?.mode === "chain";
    const chainable = holder?.type === "assembly" && (holder.mode ?? "auto") === "auto";
    for (const [index, childId] of (state.nodes[containerId]?.children ?? []).entries()) {
      const node = state.nodes[childId];
      if (!node) {
        continue;
      }
      const layout = state.layout[childId];
      const stored = layout ? { x: layout.x, y: layout.y } : gridPosition(unplaced++);
      const position = overrides.get(childId) ?? stored;
      const item = placeNode(node, layout, offsetX + position.x, offsetY + position.y, depth, containerId, view);
      item.local = { x: position.x, y: position.y };
      if (chain) {
        item.order = index + 1;
      } else if (chainable) {
        item.chainable = true;
      }
      placed.push(item);
    }
    return placed;
  };

  /**
   * @param {any} node
   * @param {any} layout
   * @param {number} x
   * @param {number} y
   * @param {number} depth
   * @param {string} parent
   * @param {LevelView | undefined} view
   * @returns {SceneItem}
   */
  const placeNode = (node, layout, x, y, depth, parent, view) => {
    const container = Array.isArray(node.children);
    const expanded = container && (expandAll || layout?.expanded === true) && depth < MAX_DEPTH;
    const all = portsOf(node, view);
    // Nodes are cards by default; their variables can be listed on demand.
    const mode = layout?.port_display ?? "compact";
    const shape =
      mode === "compact" || mode === "none"
        ? cardShape({
            inputs: all.filter((port) => port.direction === "in").length,
            outputs: all.filter((port) => port.direction === "out").length,
          })
        : nodeShape(visiblePorts(all, mode, connected.get(node.id) ?? new Set()));
    const free = freeInputsOf(view);
    const globals = container ? null : view?.ports[node.id]?.in;
    /** @type {SceneItem} */
    const item = {
      id: node.id,
      node,
      container,
      expanded,
      x,
      y,
      local: { x: 0, y: 0 },
      width: shape.width,
      height: shape.height,
      shape,
      depth,
      parent,
      freeInputs: new Set(
        shape.inputs.map((row) => row.name).filter((name) => free.has(globals ? globals[name] : name)),
      ),
    };
    items.push(item);
    if (expanded) {
      const inner = placeChildren(node.id, x + CONTAINER_PADDING, y + HEADER_HEIGHT + CONTAINER_PADDING, depth + 1);
      const box = boundingBox(inner);
      if (box) {
        item.width = Math.max(NODE_WIDTH, box.x + box.width + CONTAINER_PADDING - x);
        item.height = Math.max(shape.height, box.y + box.height + CONTAINER_PADDING - y);
      }
    }
    return item;
  };

  const topLevel = placeChildren(levelId, 0, 0, 0);
  const byId = new Map(items.map((item) => [item.id, item]));

  /** @type {SceneLink[]} */
  const links = [];
  for (const [viewLevel, view] of views) {
    for (const edge of view.edges) {
      const from = byId.get(edge.source);
      const to = byId.get(edge.target);
      if (!from || !to || (viewLevel !== levelId && !byId.get(viewLevel)?.expanded)) {
        continue;
      }
      const bottom = Math.max(from.y + from.height, to.y + to.height);
      // One link per pair of nodes when one is a card, or when they share many variables.
      if (edge.variables.length > MAX_LINKS_PER_PAIR || from.shape.card || to.shape.card) {
        const start = from.shape.card ? cardAnchor(from, "out") : sideAnchor(from, "out");
        const end = to.shape.card ? cardAnchor(to, "in") : sideAnchor(to, "in");
        const single = edge.variables.length === 1 ? edge.variables[0] : null;
        links.push({
          id: `${viewLevel}:${edge.source}>${edge.target}`,
          from: from.id,
          to: to.id,
          path: routeLink(start, end, { feedback: edge.feedback, bottom }),
          kind: single ? (single.explicit ? "explicit" : "implicit") : "aggregated",
          feedback: edge.feedback,
          variables: edge.variables,
          label: single ? null : labelPosition(start, end),
          sourcePort: "",
          targetPort: "",
        });
        continue;
      }
      for (const variable of edge.variables) {
        const sourcePort = from.container ? variable.name : variable.source_port;
        const targetPort = to.container ? variable.name : variable.target_port;
        const start = portAnchor(from, from.shape, "out", sourcePort) ?? sideAnchor(from, "out");
        const end = portAnchor(to, to.shape, "in", targetPort) ?? sideAnchor(to, "in");
        links.push({
          id: `${viewLevel}:${edge.source}>${edge.target}:${variable.name}`,
          from: from.id,
          to: to.id,
          path: routeLink(start, end, { feedback: edge.feedback, bottom }),
          kind: variable.explicit ? "explicit" : "implicit",
          feedback: edge.feedback,
          variables: [variable],
          label: null,
          sourcePort,
          targetPort,
        });
      }
    }
  }

  links.push(...executionLinks(state, levelId, items, byId));
  if (io) {
    const terminals = terminalScene(state, levelId, io, byId, boundingBox(topLevel));
    items.push(...terminals.items);
    links.push(...terminals.links);
    topLevel.push(...terminals.items);
  }

  return { items, links, box: boundingBox(topLevel) };
}

/**
 * The start and the end of the workflow of a level: circles on its left and
 * right, linked to the nodes using its inputs and to those computing its results.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId
 * @param {WorkflowIO} io
 * @param {Map<string, SceneItem>} byId
 * @param {import("./geometry.js").Rect | null} box - The nodes of the level.
 * @returns {{items: SceneItem[], links: SceneLink[]}}
 */
function terminalScene(state, levelId, io, byId, box) {
  if (!box) {
    return { items: [], links: [] };
  }
  const y = box.y + box.height / 2 - TERMINAL_SIZE / 2;
  /**
   * @param {"start" | "end"} kind
   * @param {number} x
   * @param {WorkflowVariable[]} variables
   * @returns {SceneItem}
   */
  const circle = (kind, x, variables) => ({
    id: `${kind}:${levelId}`,
    node: { id: `${kind}:${levelId}`, type: "terminal", kind, name: kind === "start" ? "Start" : "End", variables },
    container: false,
    expanded: false,
    terminal: kind,
    x,
    y,
    local: { x, y },
    width: TERMINAL_SIZE,
    height: TERMINAL_SIZE,
    shape: {
      width: TERMINAL_SIZE,
      height: TERMINAL_SIZE,
      inputs: [],
      outputs: [],
      hidden: 0,
      card: kind === "start" ? { inputs: 0, outputs: 1 } : { inputs: 1, outputs: 0 },
    },
    depth: 0,
    parent: levelId,
    freeInputs: new Set(),
  });
  const start = circle("start", box.x - TERMINAL_SIZE - TERMINAL_GAP, io.inputs);
  const end = circle("end", box.x + box.width + TERMINAL_GAP, io.outputs);
  // A chain starts above its first node and ends under its last one.
  const children = (state.nodes[levelId]?.children ?? []).map((/** @type {string} */ id) => byId.get(id)).filter(Boolean);
  const chain = state.nodes[levelId]?.mode === "chain" && children.length > 0;
  if (chain) {
    const first = children[0];
    const last = children[children.length - 1];
    const step = TERMINAL_SIZE + TERMINAL_GAP / 2;
    Object.assign(start, { x: first.x + first.width / 2 - TERMINAL_SIZE / 2, y: first.y - step });
    Object.assign(end, { x: last.x + last.width / 2 - TERMINAL_SIZE / 2, y: last.y + last.height + step - TERMINAL_SIZE });
    start.local = { x: start.x, y: start.y };
    end.local = { x: end.x, y: end.y };
  }

  /**
   * The item drawing a component: the component, or the container around it
   * shown collapsed.
   *
   * @param {string} id
   */
  const shownItem = (id) => {
    for (let current = id; current; current = state.nodes[current]?.parent) {
      const item = byId.get(current);
      if (item) {
        return item;
      }
    }
    return undefined;
  };
  /**
   * @param {WorkflowVariable[]} variables
   * @param {string} role
   * @returns {Map<SceneItem, {name: string, role: string}[]>}
   */
  const byItem = (variables, role) => {
    const grouped = new Map();
    for (const variable of variables) {
      for (const node of variable.nodes) {
        const item = shownItem(node);
        if (item) {
          const list = grouped.get(item) ?? [];
          if (!list.some((/** @type {any} */ entry) => entry.name === variable.name)) {
            list.push({ name: variable.name, role });
          }
          grouped.set(item, list);
        }
      }
    }
    return grouped;
  };
  const inputs = byItem(io.inputs, "input");
  const outputs = byItem(io.outputs, "result");
  /** @type {SceneLink[]} */
  const links = [];
  if (inputs.size + outputs.size <= MAX_TERMINAL_LINKS) {
    /**
     * @param {SceneItem} from
     * @param {SceneItem} to
     * @param {{name: string, role: string}[]} variables
     */
    const add = (from, to, variables) => {
      const startPoint = from.shape.card ? cardAnchor(from, "out") : sideAnchor(from, "out");
      const endPoint = to.shape.card ? cardAnchor(to, "in") : sideAnchor(to, "in");
      links.push({
        id: `io:${from.id}>${to.id}`,
        from: from.id,
        to: to.id,
        // A plain curve: these links only show where the variables go.
        path: linkPath(startPoint, endPoint),
        kind: "io",
        feedback: false,
        variables,
        label: variables.length > 1 ? labelPosition(startPoint, endPoint) : null,
        sourcePort: "",
        targetPort: "",
      });
    };
    for (const [item, variables] of inputs) {
      add(start, item, variables);
    }
    for (const [item, variables] of outputs) {
      add(item, end, variables);
    }
  }
  // A chain starts at the start and ends at the end.
  if (chain) {
    const first = children[0];
    const last = children[children.length - 1];
    const bottom = (/** @type {SceneItem} */ item) => ({ x: item.x + item.width / 2, y: item.y + item.height });
    const top = (/** @type {SceneItem} */ item) => ({ x: item.x + item.width / 2, y: item.y });
    for (const [from, to] of [
      [start, first],
      [last, end],
    ]) {
      links.push({
        id: `exec:${levelId}:${from.id}>${to.id}`,
        from: from.id,
        to: to.id,
        path: executionPath(bottom(from), top(to), from, to),
        kind: "execution",
        feedback: false,
        variables: [],
        label: null,
        sourcePort: "",
        targetPort: "",
        mark: `M${top(to).x - 5},${top(to).y - 8} L${top(to).x},${top(to).y} L${top(to).x + 5},${top(to).y - 8} Z`,
        container: levelId,
      });
    }
  }
  return { items: [start, end], links };
}

/** Where an execution arrow leaves a node (the middle of its bottom side). */
function bottomOf(/** @type {SceneItem} */ item) {
  return { x: item.x + item.width / 2, y: item.y + item.height };
}

/** Where an execution arrow reaches a node (the middle of its top side). */
function topOf(/** @type {SceneItem} */ item) {
  return { x: item.x + item.width / 2, y: item.y };
}

/** How far an execution arrow goes straight out of a node before turning. */
const EXECUTION_STEP = 16;

/**
 * An execution arrow from the bottom of a node to the top of another, made of
 * vertical and horizontal segments. A node that is not below goes around
 * through the space between the two nodes, so that the arrow crosses no node.
 *
 * @param {{x: number, y: number}} start
 * @param {{x: number, y: number}} end
 * @param {import("./geometry.js").Rect} [from] - The node the arrow leaves.
 * @param {import("./geometry.js").Rect} [to] - The node it reaches.
 */
export function executionPath(start, end, from, to) {
  if (end.y >= start.y + 2 * EXECUTION_STEP || !from || !to) {
    const middle = (start.y + end.y) / 2;
    return `M${start.x},${start.y} V${middle} H${end.x} V${end.y}`;
  }
  // Between the two nodes, or on the right of both when they are one above the other.
  const lane =
    to.x >= from.x + from.width
      ? (from.x + from.width + to.x) / 2
      : from.x >= to.x + to.width
        ? (to.x + to.width + from.x) / 2
        : Math.max(from.x + from.width, to.x + to.width) + EXECUTION_STEP * 2;
  const below = start.y + EXECUTION_STEP;
  const above = end.y - EXECUTION_STEP;
  return `M${start.x},${start.y} V${below} H${lane} V${above} H${end.x} V${end.y}`;
}

/** An arrowhead pointing down, its tip at a point. */
function arrowhead(/** @type {{x: number, y: number}} */ tip) {
  return `M${tip.x - 5},${tip.y - 8} L${tip.x},${tip.y} L${tip.x + 5},${tip.y - 8} Z`;
}

/** A dot: where the branches of a parallel block part or meet. */
function dot(/** @type {{x: number, y: number}} */ center) {
  return `M${center.x - 4},${center.y} a4,4 0 1,0 8,0 a4,4 0 1,0 -8,0 Z`;
}

/**
 * The execution arrows of the assemblies shown: from each node of a chain to
 * the next one, and the fork and join of a parallel block (expanded in place).
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId
 * @param {SceneItem[]} items
 * @param {Map<string, SceneItem>} byId
 * @returns {SceneLink[]}
 */
function executionLinks(state, levelId, items, byId) {
  /** @type {SceneLink[]} */
  const links = [];
  /**
   * @param {string} container
   * @param {SceneItem} from
   * @param {SceneItem} to
   * @param {string} path
   * @param {string} mark
   */
  const add = (container, from, to, path, mark) =>
    links.push({
      id: `exec:${container}:${from.id}>${to.id}`,
      from: from.id,
      to: to.id,
      path,
      kind: "execution",
      feedback: false,
      variables: [],
      label: null,
      sourcePort: "",
      targetPort: "",
      mark,
      container,
    });
  const frames = items.filter((item) => item.expanded && item.node.type === "assembly").map((item) => item.id);
  for (const containerId of [levelId, ...frames]) {
    const container = state.nodes[containerId];
    const children = (container?.children ?? []).map((/** @type {string} */ id) => byId.get(id)).filter(Boolean);
    if (container?.mode === "chain") {
      for (let index = 0; index + 1 < children.length; index += 1) {
        const [from, to] = [children[index], children[index + 1]];
        add(containerId, from, to, executionPath(bottomOf(from), topOf(to), from, to), arrowhead(topOf(to)));
      }
    }
    const frame = byId.get(containerId);
    if (container?.mode === "parallel" && frame && children.length > 1) {
      const fork = { x: frame.x + frame.width / 2, y: frame.y + HEADER_HEIGHT + 4 };
      const join = { x: fork.x, y: frame.y + frame.height - 6 };
      for (const child of children) {
        add(containerId, frame, child, executionPath(fork, topOf(child)), `${arrowhead(topOf(child))} ${dot(fork)}`);
        add(containerId, child, frame, executionPath(bottomOf(child), join), dot(join));
      }
    }
  }
  return links;
}

/**
 * Rectangles of the nodes of the level itself (for rectangle selection).
 *
 * @param {SceneItem[]} items
 * @returns {Map<string, import("./geometry.js").Rect>}
 */
export function topLevelRects(items) {
  return new Map(items.filter((item) => item.depth === 0 && !item.terminal).map((item) => [item.id, item]));
}

/**
 * The containers whose couplings the scene needs: the level and the
 * containers expanded in place inside it.
 *
 * @param {import("./patch.js").DocumentState} state
 * @param {string} levelId
 * @param {boolean} [expandAll] - Every container is expanded in place.
 * @returns {string[]}
 */
export function levelsToResolve(state, levelId, expandAll = false) {
  const levels = [levelId];
  /**
   * @param {string} id
   * @param {number} depth
   */
  const visit = (id, depth) => {
    for (const childId of state.nodes[id]?.children ?? []) {
      const child = state.nodes[childId];
      if (child?.children && (expandAll || state.layout[childId]?.expanded) && depth < MAX_DEPTH) {
        levels.push(childId);
        visit(childId, depth + 1);
      }
    }
  };
  visit(levelId, 0);
  return levels;
}
