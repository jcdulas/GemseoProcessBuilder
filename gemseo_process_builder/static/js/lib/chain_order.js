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
