// @ts-check
// Rectangle selection on the canvas.

/**
 * Normalize a rectangle given by two corners.
 *
 * @param {{x: number, y: number}} a
 * @param {{x: number, y: number}} b
 * @returns {import("./geometry.js").Rect}
 */
export function rectFromCorners(a, b) {
  return {
    x: Math.min(a.x, b.x),
    y: Math.min(a.y, b.y),
    width: Math.abs(a.x - b.x),
    height: Math.abs(a.y - b.y),
  };
}

/**
 * @param {import("./geometry.js").Rect} a
 * @param {import("./geometry.js").Rect} b
 */
export function intersects(a, b) {
  return a.x < b.x + b.width && b.x < a.x + a.width && a.y < b.y + b.height && b.y < a.y + a.height;
}

/**
 * @param {import("./geometry.js").Rect} outer
 * @param {import("./geometry.js").Rect} inner
 */
export function contains(outer, inner) {
  return (
    inner.x >= outer.x &&
    inner.y >= outer.y &&
    inner.x + inner.width <= outer.x + outer.width &&
    inner.y + inner.height <= outer.y + outer.height
  );
}

/**
 * The ids of the rectangles selected by a selection rectangle.
 *
 * @param {import("./geometry.js").Rect} selection
 * @param {Map<string, import("./geometry.js").Rect>} rects
 * @param {"intersect" | "contain"} [mode]
 * @returns {string[]}
 */
export function selectInRect(selection, rects, mode = "intersect") {
  const test = mode === "contain" ? contains : intersects;
  return [...rects].filter(([, rect]) => test(selection, rect)).map(([id]) => id);
}
