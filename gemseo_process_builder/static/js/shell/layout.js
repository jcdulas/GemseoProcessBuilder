// @ts-check
// Resizable and collapsible panels, persisted in the preferences.
import { PANEL_LIMITS, dragSize, normalizeLayout, toggleCollapsed } from "../lib/splitter.js";

/** Which way each splitter grows its panel, and along which axis. */
const SPLITTERS = {
  left: { axis: "x", direction: /** @type {1} */ (1) },
  right: { axis: "x", direction: /** @type {-1} */ (-1) },
  bottom: { axis: "y", direction: /** @type {-1} */ (-1) },
};

const SAVE_DELAY_MS = 500;

export class PanelLayout {
  /**
   * @param {import("../lib/rpc.js").RpcClient} api
   * @param {any} savedLayout - The `layout.panels` preference.
   */
  constructor(api, savedLayout) {
    this.api = api;
    this.state = normalizeLayout(savedLayout);
    /** @type {any} */
    this.saveTimer = null;
    /** @type {Set<() => void>} */
    this.listeners = new Set();
    for (const name of Object.keys(SPLITTERS)) {
      this.installSplitter(name);
    }
    this.apply();
  }

  /** @param {string} name */
  panel(name) {
    return /** @type {HTMLElement} */ (document.querySelector(`[data-panel="${name}"]`));
  }

  /** @param {string} name */
  splitter(name) {
    return /** @type {HTMLElement} */ (document.querySelector(`[data-splitter="${name}"]`));
  }

  apply() {
    for (const [name, { axis }] of Object.entries(SPLITTERS)) {
      const { size, collapsed } = this.state[name];
      const panel = this.panel(name);
      panel.style[axis === "x" ? "width" : "height"] = `${size}px`;
      panel.classList.toggle("collapsed", collapsed);
      this.splitter(name).classList.toggle("collapsed", collapsed);
    }
    for (const listener of this.listeners) {
      listener();
    }
  }

  /** @param {string} name */
  isVisible(name) {
    return !this.state[name].collapsed;
  }

  /** @param {string} name */
  toggle(name) {
    this.state[name] = toggleCollapsed(this.state[name]);
    this.apply();
    this.scheduleSave();
  }

  /** @param {() => void} listener */
  onChange(listener) {
    this.listeners.add(listener);
  }

  /** @param {string} name */
  installSplitter(name) {
    const { axis, direction } = SPLITTERS[/** @type {keyof SPLITTERS} */ (name)];
    const splitter = this.splitter(name);
    splitter.addEventListener("pointerdown", (event) => {
      const start = axis === "x" ? event.clientX : event.clientY;
      const startSize = this.state[name].size;
      splitter.setPointerCapture(event.pointerId);
      splitter.classList.add("dragging");
      /** @param {PointerEvent} moveEvent */
      const onMove = (moveEvent) => {
        const position = axis === "x" ? moveEvent.clientX : moveEvent.clientY;
        this.state[name].size = dragSize(startSize, position - start, direction, PANEL_LIMITS[name]);
        this.apply();
      };
      const onUp = () => {
        splitter.classList.remove("dragging");
        splitter.removeEventListener("pointermove", onMove);
        splitter.removeEventListener("pointerup", onUp);
        this.scheduleSave();
      };
      splitter.addEventListener("pointermove", onMove);
      splitter.addEventListener("pointerup", onUp);
    });
  }

  scheduleSave() {
    clearTimeout(this.saveTimer);
    this.saveTimer = setTimeout(async () => {
      const preferences = await this.api.call("prefs.get");
      const layout = { ...preferences.layout, panels: this.state };
      await this.api.call("prefs.set", { values: { layout } });
    }, SAVE_DELAY_MS);
  }
}
