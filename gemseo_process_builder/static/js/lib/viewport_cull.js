/**
 * Viewport culling and level of detail of the canvas (SPEC § 14.1).
 *
 * Only the nodes and links near the visible area are put in the DOM: the area
 * drawn is the view with a margin, so that panning does not redraw at every
 * frame. Below zoom thresholds, details that cannot be read are left out.
 * Pure: tested with node.
 */

/** Zoom below which port labels and link counts are left out. */
export const REDUCED_ZOOM = 0.55;
/** Zoom below which ports are left out too. */
export const OUTLINE_ZOOM = 0.3;

/**
 * The detail drawn at a zoom.
 * @param {number} k
 * @returns {"full" | "reduced" | "outline"}
 */
export function detailLevel(k) {
  if (k < OUTLINE_ZOOM) return "outline";
  return k < REDUCED_ZOOM ? "reduced" : "full";
}

/**
 * The area of the scene shown by a view, in scene coordinates.
 * @param {{x: number, y: number, k: number}} transform - Screen = scene × k + (x, y).
 * @param {number} width - Of the view, in pixels.
 * @param {number} height
 * @returns {{x: number, y: number, width: number, height: number}}
 */
export function visibleArea(transform, width, height) {
  return { x: -transform.x / transform.k, y: -transform.y / transform.k, width: width / transform.k, height: height / transform.k };
}

/**
 * A rectangle grown by a share of its size on each side.
 * @param {{x: number, y: number, width: number, height: number}} rect
 * @param {number} share
 */
export function grow(rect, share) {
  const dx = rect.width * share;
  const dy = rect.height * share;
  return { x: rect.x - dx, y: rect.y - dy, width: rect.width + 2 * dx, height: rect.height + 2 * dy };
}

/** Whether a rectangle is inside another one. */
export function contains(outer, inner) {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  );
}

function intersects(a, b) {
  return a.x <= b.x + b.width && b.x <= a.x + a.width && a.y <= b.y + b.height && b.y <= a.y + a.height;
}

/**
 * The part of a scene to draw in an area: the items crossing it (with the
 * containers holding them), and the links with an end among them or crossing
 * the area.
 * @template {{id: string, x: number, y: number, width: number, height: number, parent?: string}} Item
 * @template {{from: string, to: string}} Link
 * @param {{items: Item[], links: Link[]}} scene
 * @param {{x: number, y: number, width: number, height: number}} area
 * @returns {{items: Item[], links: Link[]}}
 */
export function cullScene(scene, area) {
  const byId = new Map(scene.items.map((item) => [item.id, item]));
  const kept = new Set();
  for (const item of scene.items) {
    if (intersects(item, area)) {
      // A drawn item needs the containers around it (expanded in place).
      for (let current = item; current && !kept.has(current.id); current = byId.get(current.parent ?? "")) {
        kept.add(current.id);
      }
    }
  }
  const links = scene.links.filter((link) => {
    if (kept.has(link.from) || kept.has(link.to)) return true;
    const from = byId.get(link.from);
    const to = byId.get(link.to);
    if (!from || !to) return false;
    // A link between two items out of the area may still cross it.
    const x = Math.min(from.x, to.x);
    const y = Math.min(from.y, to.y);
    const box = { x, y, width: Math.max(from.x + from.width, to.x + to.width) - x, height: Math.max(from.y + from.height, to.y + to.height) - y };
    return intersects(box, area);
  });
  return { items: scene.items.filter((item) => kept.has(item.id)), links };
}
