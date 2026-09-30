// @ts-check
// The evaluations brushed in one results view, highlighted in all the others.

export class BrushSelection {
  constructor() {
    /** @type {Map<string, Set<number>>} */
    this.byRun = new Map();
    /** @type {Set<(runId: string, origin: string) => void>} */
    this.listeners = new Set();
  }

  /**
   * The selected evaluation numbers of a run, or ``null`` when nothing is brushed.
   *
   * @param {string} runId
   */
  get(runId) {
    return this.byRun.get(runId) ?? null;
  }

  /**
   * @param {string} runId
   * @param {Set<number> | null} evaluations - ``null`` clears the selection.
   * @param {string} origin - The view that brushed, which need not redraw.
   */
  set(runId, evaluations, origin) {
    if (evaluations) {
      this.byRun.set(runId, evaluations);
    } else {
      this.byRun.delete(runId);
    }
    for (const listener of this.listeners) {
      listener(runId, origin);
    }
  }

  /** @param {(runId: string, origin: string) => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
  }
}
