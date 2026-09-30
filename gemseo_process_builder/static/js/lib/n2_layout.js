// @ts-check
// Pure helpers of the N2 view: collapsed blocks, positions and reordering.

/**
 * @typedef {object} N2Entry - A leaf of the diagonal, from ``core/n2.py``.
 * @property {string} id
 * @property {string} name
 * @property {string} type - component, driver or assembly (an empty one).
 * @property {string} kind
 * @property {string} parent - The container holding it.
 * @property {number} depth
 *
 * @typedef {object} N2Block - An assembly around a range of leaves.
 * @property {string} id
 * @property {string} name
 * @property {string} mode
 * @property {string} parent
 * @property {number} depth
 * @property {number} start - First leaf.
 * @property {number} end - Last leaf.
 *
 * @typedef {{name: string, source_port: string, target_port: string, explicit: boolean}} N2Link
 * @typedef {{row: number, col: number, variables: string[], feedback: boolean, links?: N2Link[]}} N2Cell
 *
 * @typedef {{level: string, entries: N2Entry[], blocks: N2Block[], cells: N2Cell[]}} N2Data
 *
 * @typedef {object} N2Item - An entry of the displayed diagonal.
 * @property {string} id
 * @property {string} name
 * @property {string} type
 * @property {string} kind
 * @property {string} parent
 * @property {number} depth
 * @property {boolean} collapsed - A collapsed block standing for its leaves.
 *
 * @typedef {{entries: N2Item[], blocks: N2Block[], cells: N2Cell[]}} N2View
 */

/**
 * The matrix with some blocks collapsed: the rows and columns of the leaves of
 * a collapsed block merge into one, and the couplings inside it disappear.
 *
 * @param {N2Data} data
 * @param {Set<string>} collapsed - Ids of the collapsed blocks.
 * @returns {N2View} Expanded blocks keep their range, in displayed indices.
 */
export function collapse(data, collapsed) {
  /** @type {(N2Block | null)[]} - The outermost collapsed block of each leaf. */
  const hiddenBy = data.entries.map(() => null);
  // Blocks come outer first: an inner block of a collapsed block is ignored.
  for (const block of data.blocks) {
    if (collapsed.has(block.id) && hiddenBy[block.start] === null) {
      for (let leaf = block.start; leaf <= block.end; leaf += 1) {
        hiddenBy[leaf] = block;
      }
    }
  }
  /** @type {N2Item[]} */
  const entries = [];
  /** @type {number[]} */
  const position = [];
  data.entries.forEach((entry, leaf) => {
    const block = hiddenBy[leaf];
    if (block && leaf !== block.start) {
      position.push(entries.length - 1);
      return;
    }
    position.push(entries.length);
    entries.push(
      block
        ? { id: block.id, name: block.name, type: "assembly", kind: block.mode, parent: block.parent, depth: block.depth, collapsed: true }
        : { ...entry, collapsed: false },
    );
  });
  const blocks = data.blocks
    .filter((block) => hiddenBy[block.start] === null)
    .map((block) => ({ ...block, start: position[block.start], end: position[block.end] }));
  /** @type {Map<string, N2Cell>} */
  const merged = new Map();
  for (const cell of data.cells) {
    const row = position[cell.row];
    const col = position[cell.col];
    if (row === col) {
      continue; // Inside a collapsed block.
    }
    const key = `${row},${col}`;
    const existing = merged.get(key);
    if (existing) {
      existing.variables = [...new Set([...existing.variables, ...cell.variables])].sort();
      // Merged cells join several nodes: their ports mean nothing any more.
      existing.links = [];
    } else {
      merged.set(key, { row, col, variables: [...cell.variables], feedback: row > col, links: cell.links ?? [] });
    }
  }
  const cells = [...merged.values()].sort((a, b) => a.row - b.row || a.col - b.col);
  return { entries, blocks, cells };
}

/**
 * The cells of each row, sorted by column, to find the visible ones quickly.
 *
 * @param {N2Cell[]} cells
 * @returns {Map<number, N2Cell[]>}
 */
export function cellsByRow(cells) {
  /** @type {Map<number, N2Cell[]>} */
  const rows = new Map();
  for (const cell of cells) {
    const row = rows.get(cell.row);
    if (row) {
      row.push(cell);
    } else {
      rows.set(cell.row, [cell]);
    }
  }
  for (const row of rows.values()) {
    row.sort((a, b) => a.col - b.col);
  }
  return rows;
}

/**
 * The children of a container in displayed order: its leaves and collapsed
 * blocks, and its expanded blocks, each with the displayed range it covers.
 *
 * @param {N2View} view
 * @param {string} parent
 * @returns {{id: string, start: number, end: number}[]}
 */
export function siblings(view, parent) {
  const items = view.entries.map((entry, index) => ({ id: entry.id, parent: entry.parent, start: index, end: index }));
  for (const block of view.blocks) {
    items.push({ id: block.id, parent: block.parent, start: block.start, end: block.end });
  }
  return items
    .filter((item) => item.parent === parent)
    .sort((a, b) => a.start - b.start)
    .map(({ id, start, end }) => ({ id, start, end }));
}

/**
 * The new order of a container after dropping one of its children on another
 * position of the diagonal.
 *
 * @param {N2View} view
 * @param {number} from - Displayed index of the dragged entry.
 * @param {number} to - Displayed index where it is dropped.
 * @returns {{parent: string, ids: string[]} | null} ``null`` when the drop
 *   position is outside the container, or changes nothing.
 */
export function reorder(view, from, to) {
  const entry = view.entries[from];
  if (!entry) {
    return null;
  }
  const items = siblings(view, entry.parent);
  const target = items.find((item) => item.start <= to && to <= item.end);
  if (!target || target.id === entry.id) {
    return null;
  }
  const ids = items.map((item) => item.id).filter((id) => id !== entry.id);
  const index = ids.indexOf(target.id) + (to > from ? 1 : 0);
  ids.splice(index, 0, entry.id);
  return { parent: entry.parent, ids };
}
