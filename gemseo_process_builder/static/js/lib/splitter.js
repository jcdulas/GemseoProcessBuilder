// @ts-check
// Panel sizes and collapsed states of the application frame.

/**
 * @typedef {object} PanelLimits
 * @property {number} min
 * @property {number} max
 * @property {number} initial
 * @property {boolean} [collapsed] - Whether the panel starts collapsed.
 */

/**
 * @typedef {object} PanelState
 * @property {number} size - Width (side panels) or height (bottom panel), in pixels.
 * @property {boolean} collapsed
 */

/** @type {Record<string, PanelLimits>} */
export const PANEL_LIMITS = {
  left: { min: 160, max: 600, initial: 260 },
  right: { min: 200, max: 700, initial: 320 },
  // The canvas comes first: the console, problems and runs open on demand.
  bottom: { min: 80, max: 700, initial: 220, collapsed: true },
};

/**
 * Keep a size inside the panel limits.
 *
 * @param {number} size
 * @param {PanelLimits} limits
 * @returns {number}
 */
export function clampSize(size, limits) {
  return Math.round(Math.min(limits.max, Math.max(limits.min, size)));
}

/**
 * Size of a panel after dragging its splitter.
 *
 * @param {number} startSize - The size when the drag started.
 * @param {number} delta - The mouse movement since the drag started.
 * @param {1 | -1} direction - 1 when moving the mouse towards positive
 *   coordinates grows the panel (left panel), -1 otherwise (right and bottom panels).
 * @param {PanelLimits} limits
 * @returns {number}
 */
export function dragSize(startSize, delta, direction, limits) {
  return clampSize(startSize + direction * delta, limits);
}

/**
 * Merge a saved layout with the defaults, dropping invalid values.
 *
 * @param {any} saved - The layout stored in the preferences, possibly empty or invalid.
 * @returns {Record<string, PanelState>}
 */
export function normalizeLayout(saved) {
  /** @type {Record<string, PanelState>} */
  const layout = {};
  for (const [name, limits] of Object.entries(PANEL_LIMITS)) {
    const panel = saved && typeof saved === "object" ? saved[name] : undefined;
    const size = Number.isFinite(panel?.size) ? panel.size : limits.initial;
    const collapsed = typeof panel?.collapsed === "boolean" ? panel.collapsed : limits.collapsed === true;
    layout[name] = { size: clampSize(size, limits), collapsed };
  }
  return layout;
}

/**
 * Collapse an expanded panel or expand a collapsed one; the size is kept, so
 * expanding restores the previous size.
 *
 * @param {PanelState} state
 * @returns {PanelState}
 */
export function toggleCollapsed(state) {
  return { ...state, collapsed: !state.collapsed };
}
