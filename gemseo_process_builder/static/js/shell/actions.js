// @ts-check
// Registry of the application actions (menus, toolbar, shortcuts).
import { normalizeShortcut } from "../lib/shortcut_keys.js";

/**
 * @typedef {object} ActionDefinition
 * @property {string} id
 * @property {string} menu
 * @property {string} label
 * @property {string[]} shortcuts
 * @property {boolean} native
 */

/**
 * @typedef {object} ActionBehavior
 * @property {() => any} run
 * @property {boolean} [enabled]
 * @property {boolean} [checked]
 */

export class ActionRegistry {
  /** @param {import("../lib/rpc.js").RpcClient} api */
  constructor(api) {
    this.api = api;
    /** @type {ActionDefinition[]} */
    this.definitions = [];
    /** @type {Map<string, ActionBehavior>} */
    this.behaviors = new Map();
    /** @type {Map<string, string>} */
    this.shortcutIndex = new Map();
    /** @type {Set<(id: string) => void>} */
    this.listeners = new Set();
    /** @type {{enabled: Record<string, boolean>, checked: Record<string, boolean>}} */
    this.pendingStates = { enabled: {}, checked: {} };
    this.flushScheduled = false;
  }

  /** Load the definitions from Python and listen to native menu clicks. */
  async load() {
    this.definitions = await this.api.call("actions.list");
    for (const definition of this.definitions) {
      for (const shortcut of definition.shortcuts) {
        this.shortcutIndex.set(normalizeShortcut(shortcut), definition.id);
      }
    }
    this.api.on("action.invoke", ({ id }) => this.invoke(id));
  }

  /**
   * Attach the behavior of an action.
   *
   * @param {string} id
   * @param {ActionBehavior} behavior
   */
  handle(id, behavior) {
    this.behaviors.set(id, { enabled: true, ...behavior });
    this.syncState(id);
  }

  /**
   * @param {string} id
   * @returns {boolean}
   */
  isEnabled(id) {
    return this.behaviors.get(id)?.enabled === true;
  }

  /**
   * @param {string} id
   * @param {boolean} enabled
   */
  setEnabled(id, enabled) {
    const behavior = this.behaviors.get(id);
    if (behavior && behavior.enabled !== enabled) {
      behavior.enabled = enabled;
      this.syncState(id);
    }
  }

  /**
   * @param {string} id
   * @param {boolean} checked
   */
  setChecked(id, checked) {
    const behavior = this.behaviors.get(id);
    if (behavior && behavior.checked !== checked) {
      behavior.checked = checked;
      this.syncState(id);
    }
  }

  /**
   * Run an action if it is enabled.
   *
   * @param {string} id
   * @returns {boolean} Whether the action ran.
   */
  invoke(id) {
    const behavior = this.behaviors.get(id);
    if (!behavior?.enabled) {
      return false;
    }
    Promise.resolve()
      .then(() => behavior.run())
      .catch((error) => console.error(`Action ${id} failed:`, error));
    return true;
  }

  /**
   * The action bound to a shortcut, if any.
   *
   * @param {string} shortcut - A normalized shortcut like "Ctrl+Shift+S".
   * @returns {string | undefined}
   */
  actionForShortcut(shortcut) {
    return this.shortcutIndex.get(shortcut);
  }

  /**
   * @param {(id: string) => void} listener - Called when an action state changes.
   * @returns {() => void}
   */
  onChange(listener) {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  /** @param {string} id */
  syncState(id) {
    const behavior = this.behaviors.get(id);
    if (!behavior) {
      return;
    }
    this.pendingStates.enabled[id] = behavior.enabled === true;
    if (behavior.checked !== undefined) {
      this.pendingStates.checked[id] = behavior.checked;
    }
    for (const listener of this.listeners) {
      listener(id);
    }
    if (!this.flushScheduled) {
      this.flushScheduled = true;
      queueMicrotask(() => this.flushStates());
    }
  }

  flushStates() {
    const states = this.pendingStates;
    this.pendingStates = { enabled: {}, checked: {} };
    this.flushScheduled = false;
    this.api.call("actions.setState", states).catch((error) => console.error(error));
  }
}
