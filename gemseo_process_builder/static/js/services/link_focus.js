// @ts-check
// The link shown in the inspector after a click on the canvas.

export class LinkFocus {
  constructor() {
    /** @type {import("../lib/scene.js").SceneLink | null} */
    this.link = null;
    /** @type {Set<() => void>} */
    this.listeners = new Set();
  }

  /** @param {import("../lib/scene.js").SceneLink | null} link */
  set(link) {
    this.link = link;
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** @param {() => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}
