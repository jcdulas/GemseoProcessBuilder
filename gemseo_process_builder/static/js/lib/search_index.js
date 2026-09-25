// @ts-check
// Pure search over the model (Ctrl+F): node names and variable names.

/**
 * @typedef {object} SearchEntry
 * @property {"node" | "variable"} kind
 * @property {string} name - What is matched: a node name or a variable name.
 * @property {string} node - The node to show: the node itself, or the
 *   component using the variable.
 * @property {string} detail - Shown under the name (path, role).
 * @property {"output" | "input"} [role] - For a variable: the component
 *   computing it comes first.
 *
 * @typedef {SearchEntry & {score: number}} SearchResult
 */

/** Characters starting a new word inside a name. */
const SEPARATORS = /[_.:\s-]/;

/**
 * How well a name matches a query; lower is better, ``null`` when it does not.
 *
 * @param {string} name
 * @param {string} query - Lower case.
 * @returns {number | null} 0 exact, 1 prefix, 2 prefix of a word, 3 inside.
 */
export function matchScore(name, query) {
  const text = name.toLowerCase();
  if (text === query) {
    return 0;
  }
  if (text.startsWith(query)) {
    return 1;
  }
  let index = text.indexOf(query);
  while (index > 0) {
    if (SEPARATORS.test(text[index - 1])) {
      return 2;
    }
    index = text.indexOf(query, index + 1);
  }
  return text.includes(query) ? 3 : null;
}

/**
 * Search entries, best matches first: by match quality, nodes before
 * variables, shorter names first.
 *
 * @param {SearchEntry[]} entries
 * @param {string} query
 * @param {number} [limit]
 * @returns {SearchResult[]}
 */
export function search(entries, query, limit = 50) {
  const wanted = query.trim().toLowerCase();
  if (!wanted) {
    return [];
  }
  /** @type {SearchResult[]} */
  const results = [];
  for (const entry of entries) {
    const score = matchScore(entry.name, wanted);
    if (score !== null) {
      results.push({ ...entry, score });
    }
  }
  results.sort(
    (a, b) =>
      a.score - b.score ||
      (a.kind === b.kind ? 0 : a.kind === "node" ? -1 : 1) ||
      a.name.length - b.name.length ||
      (a.role === b.role ? 0 : a.role === "output" ? -1 : 1) ||
      a.name.localeCompare(b.name) ||
      a.detail.localeCompare(b.detail),
  );
  return results.slice(0, limit);
}

/**
 * The entries of a model: every node, and every variable of every component
 * (its global name, and its local name when different).
 *
 * @param {Record<string, any>} nodes - The nodes of the store, by id.
 * @param {(id: string) => string} pathOf - Like ``Model.Optimizer.Sellar1``.
 * @param {Record<string, any>} couplings - ``resolve.couplings``: by scope, the
 *   producers and consumers of each global name.
 * @param {string} rootId
 * @returns {SearchEntry[]}
 */
export function searchEntries(nodes, pathOf, couplings, rootId) {
  /** @type {SearchEntry[]} */
  const entries = [];
  for (const node of Object.values(nodes)) {
    if (node.id !== rootId) {
      entries.push({ kind: "node", name: node.name, node: node.id, detail: pathOf(node.id) });
    }
  }
  const seen = new Set();
  /**
   * @param {string} name
   * @param {any} ref
   * @param {"output" | "input"} role
   */
  const add = (name, ref, role) => {
    const key = `${name}|${ref.node}|${role}`;
    // Drivers inside other nodes appear in couplings through their interface:
    // the components inside them are the ones to show.
    if (nodes[ref.node]?.type !== "component" || seen.has(key)) {
      return;
    }
    seen.add(key);
    entries.push({ kind: "variable", name, node: ref.node, detail: `${role} of ${pathOf(ref.node)}`, role });
  };
  for (const scope of Object.values(couplings)) {
    for (const [name, coupling] of Object.entries(scope.couplings ?? {})) {
      for (const ref of /** @type {any} */ (coupling).producers ?? []) {
        add(name, ref, "output");
        if (ref.port !== name) {
          add(ref.port, ref, "output");
        }
      }
      for (const ref of /** @type {any} */ (coupling).consumers ?? []) {
        add(name, ref, "input");
        if (ref.port !== name) {
          add(ref.port, ref, "input");
        }
      }
    }
  }
  return entries;
}
