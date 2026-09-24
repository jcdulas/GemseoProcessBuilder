// @ts-check
// Which rows of a long list are visible, for rendering only those.

/**
 * @param {{scrollTop: number, viewportHeight: number, rowHeight: number, count: number, overscan?: number}} options
 * @returns {{first: number, last: number, offset: number, totalHeight: number}}
 *   Rows [first, last) are rendered, starting at `offset` pixels.
 */
export function visibleRange({ scrollTop, viewportHeight, rowHeight, count, overscan = 10 }) {
  const totalHeight = count * rowHeight;
  if (count === 0 || rowHeight <= 0) {
    return { first: 0, last: 0, offset: 0, totalHeight };
  }
  const top = Math.max(0, Math.min(scrollTop, totalHeight));
  const first = Math.max(0, Math.floor(top / rowHeight) - overscan);
  const last = Math.min(count, Math.ceil((top + Math.max(viewportHeight, 0)) / rowHeight) + overscan);
  return { first, last, offset: first * rowHeight, totalHeight };
}

/**
 * The scroll position showing a row, or null when it is already visible.
 *
 * @param {number} index
 * @param {{scrollTop: number, viewportHeight: number, rowHeight: number}} options
 * @returns {number | null}
 */
export function scrollToShow(index, { scrollTop, viewportHeight, rowHeight }) {
  const top = index * rowHeight;
  if (top < scrollTop) {
    return top;
  }
  if (top + rowHeight > scrollTop + viewportHeight) {
    return top + rowHeight - viewportHeight;
  }
  return null;
}
