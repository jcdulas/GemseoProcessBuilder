// @ts-check
// The order of the nodes of a chain, changed by drawing execution arrows.

/**
 * The children of a chain once `next` is moved right after `node`.
 *
 * @param {string[]} children
 * @param {string} node
 * @param {string} next
 * @returns {string[]}
 */
export function orderAfter(children, node, next) {
  const others = children.filter((id) => id !== next);
  others.splice(others.indexOf(node) + 1, 0, next);
  return others;
}

/**
 * The children in an order where each one comes after the nodes whose results
 * it uses, keeping their order otherwise. The nodes of a loop keep their order.
 *
 * @param {string[]} children
 * @param {{source: string, target: string}[]} edges - The couplings between them.
 * @returns {string[]}
 */
export function dependencyOrder(children, edges) {
  const waiting = new Map(children.map((id) => [id, new Set()]));
  for (const { source, target } of edges) {
    if (source !== target && waiting.has(source) && waiting.has(target)) {
      waiting.get(target)?.add(source);
    }
  }
  /** @type {string[]} */
  const order = [];
  while (order.length < children.length) {
    const ready = children.find((id) => !order.includes(id) && [...(waiting.get(id) ?? [])].every((source) => order.includes(source)));
    // A loop: its first node goes first.
    order.push(ready ?? /** @type {string} */ (children.find((id) => !order.includes(id))));
  }
  return order;
}
