// @ts-check
// Pure layout of an XDSM diagram, from the XDSMjs JSON that GEMSEO writes.
//
// The components sit on the diagonal (row = column = position, the user "_U_"
// taking row and column 0). The data exchanged from A to B sits in row A and
// column B; thick data lines join the blocks of each row and column to the
// component on the diagonal. The process (workflow) is a sequence of numbered
// steps between components.

/**
 * @typedef {{id: string, name: string, type: string, subxdsm?: string}} XdsmNode
 * @typedef {{from: string, to: string, name: string}} XdsmEdge
 * @typedef {{nodes: XdsmNode[], edges: XdsmEdge[], workflow: any[]}} XdsmDiagram
 *
 * @typedef {{row: number, col: number, from: string, to: string, variables: string[]}} XdsmBlock
 * @typedef {{row1: number, col1: number, row2: number, col2: number}} XdsmSegment
 * @typedef {{from: string, to: string, step: number}} XdsmStep
 *
 * @typedef {object} XdsmLayout
 * @property {(XdsmNode & {index: number, steps: number[]})[]} nodes - On the diagonal, from index 1.
 * @property {XdsmBlock[]} blocks - Data exchanged, merged per cell.
 * @property {XdsmSegment[]} lines - Data lines, in cell coordinates.
 * @property {XdsmStep[]} steps - The process, in order.
 * @property {number} size - Rows (and columns), the user row included.
 */

export const USER = "_U_";

/**
 * The steps of a workflow: a list of node ids, where a list right after a node
 * is a loop that this node drives, and ``{"parallel": [...]}`` runs branches
 * side by side.
 *
 * @param {any[]} workflow
 * @returns {XdsmStep[]}
 */
export function processSteps(workflow) {
  /** @type {{from: string, to: string}[]} */
  const transitions = [];

  /**
   * @param {any[]} items
   * @param {string[]} previous - The nodes the next one follows.
   * @returns {string[]} The last nodes run.
   */
  const run = (items, previous) => {
    let current = previous;
    for (const item of items) {
      if (typeof item === "string") {
        for (const from of current) {
          transitions.push({ from, to: item });
        }
        current = [item];
      } else if (Array.isArray(item)) {
        // A loop driven by the node before it: back to the driver at the end.
        const drivers = current;
        for (const last of run(item, drivers)) {
          for (const driver of drivers) {
            transitions.push({ from: last, to: driver });
          }
        }
        current = drivers;
      } else if (item && Array.isArray(item.parallel)) {
        const ends = [];
        for (const branch of item.parallel) {
          ends.push(...run(Array.isArray(branch) ? branch : [branch], current));
        }
        current = ends;
      }
    }
    return current;
  };

  run(workflow, []);
  return transitions.map((transition, index) => ({ ...transition, step: index + 1 }));
}

/**
 * The layout of a diagram.
 *
 * @param {XdsmDiagram} diagram
 * @returns {XdsmLayout}
 */
export function xdsmLayout(diagram) {
  /** @type {Map<string, number>} */
  const position = new Map([[USER, 0]]);
  diagram.nodes.forEach((node, index) => position.set(node.id, index + 1));
  const steps = processSteps(diagram.workflow ?? []);
  const nodes = diagram.nodes.map((node, index) => ({
    ...node,
    index: index + 1,
    steps: steps.filter((step) => step.to === node.id).map((step) => step.step),
  }));

  /** @type {Map<string, XdsmBlock>} */
  const cells = new Map();
  for (const edge of diagram.edges) {
    const row = position.get(edge.from);
    const col = position.get(edge.to);
    if (row === undefined || col === undefined || row === col) {
      continue;
    }
    const key = `${row},${col}`;
    const names = edge.name.split(",").map((name) => name.trim()).filter(Boolean);
    const block = cells.get(key);
    if (block) {
      block.variables = [...new Set([...block.variables, ...names])];
    } else {
      cells.set(key, { row, col, from: edge.from, to: edge.to, variables: names });
    }
  }
  const blocks = [...cells.values()].sort((a, b) => a.row - b.row || a.col - b.col);

  /** @type {XdsmSegment[]} */
  const lines = [];
  for (const node of nodes) {
    const index = node.index;
    const inRow = blocks.filter((block) => block.row === index).map((block) => block.col);
    const inCol = blocks.filter((block) => block.col === index).map((block) => block.row);
    if (inRow.length) {
      lines.push({ row1: index, col1: Math.min(index, ...inRow), row2: index, col2: Math.max(index, ...inRow) });
    }
    if (inCol.length) {
      lines.push({ row1: Math.min(index, ...inCol), col1: index, row2: Math.max(index, ...inCol), col2: index });
    }
  }
  return { nodes, blocks, lines, steps, size: nodes.length + 1 };
}

/**
 * The text of a data block: at most ``count`` variables, GEMSEO's notations
 * made readable (``x^(0)`` initial value, ``y^*`` optimum).
 *
 * @param {string[]} variables
 * @param {number} [count]
 */
export function blockLabel(variables, count = 5) {
  const shown = variables.slice(0, count).map((name) => name.replace(/\^\(0\)$/, "⁰").replace(/\^\*$/, "*"));
  return variables.length > count ? `${shown.join(", ")}, …` : shown.join(", ");
}

/**
 * The text of a component: its entering steps, then its name.
 *
 * @param {{name: string, steps: number[]}} node
 * @param {number} [count] - Steps shown at most.
 */
export function nodeLabel(node, count = 3) {
  if (!node.steps.length) {
    return node.name;
  }
  const steps = node.steps.slice(0, count).join(", ") + (node.steps.length > count ? ", …" : "");
  return `${steps}: ${node.name}`;
}

/**
 * The scenario behind a sub-diagram name like ``StructureOptimizer_scn-1-3``.
 *
 * @param {string} name
 */
export function scenarioName(name) {
  return name.replace(/_scn(-\d+)+$/, "");
}
