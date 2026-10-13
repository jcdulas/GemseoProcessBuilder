// @ts-check
// The Cache setting of the inspector (SPEC § 8.7): what GEMSEO keeps of the
// executions of a discipline. Pure functions, tested with node --test.

/** @typedef {{type: "none" | "memory" | "hdf5", tolerance?: number, file?: string, node?: string}} CacheSetting */

/** The choices of the field, GEMSEO's default first. */
export const CACHE_CHOICES = [
  { value: "default", label: "Last execution (default)", hint: "GEMSEO's default: right for most components." },
  { value: "none", label: "None", hint: "Runs each time: for a discipline with side effects." },
  { value: "memory", label: "All executions, in memory", hint: "Inputs met again are not computed again, during the run." },
  { value: "hdf5", label: "All executions, in a file", hint: "Kept across runs and crashes: for expensive evaluations." },
];

/**
 * The cache setting of a node: in the config of a component or a driver, in
 * the field ``cache`` of an assembly; ``null`` for GEMSEO's default.
 *
 * @param {any} node
 * @returns {CacheSetting | null}
 */
export function cacheOf(node) {
  const data = node.type === "assembly" ? node.cache : node.config?.cache;
  return data && data.type ? data : null;
}

/**
 * The choice of the field for a setting.
 *
 * @param {CacheSetting | null} setting
 */
export function cacheChoice(setting) {
  return setting ? setting.type : "default";
}

/**
 * The fields shown for a choice.
 *
 * @param {string} choice
 */
export function cacheFields(choice) {
  return {
    tolerance: choice === "memory" || choice === "hdf5",
    file: choice === "hdf5",
    node: choice === "hdf5",
    entries: choice === "hdf5",
  };
}

/**
 * The default node of a file cache: the names from the model down.
 *
 * @param {string[]} names - The names of the ancestors and of the node, the model first.
 */
export function defaultNodePath(names) {
  return names.slice(1).join("/");
}

/**
 * The setting after a choice, keeping what still applies of the current one.
 *
 * @param {string} choice
 * @param {CacheSetting | null} current
 * @param {{file: string, node: string}} defaults - The default file and node.
 * @returns {CacheSetting | null}
 */
export function settingFor(choice, current, defaults) {
  if (choice === "default") {
    return null;
  }
  /** @type {CacheSetting} */
  const setting = { type: /** @type {any} */ (choice) };
  if (choice !== "none" && current?.tolerance) {
    setting.tolerance = current.tolerance;
  }
  if (choice === "hdf5") {
    setting.file = current?.file || defaults.file;
    setting.node = current?.node || defaults.node;
  }
  return setting;
}

/**
 * The properties of a ``setNodeProperties`` command giving a node a setting.
 *
 * @param {any} node
 * @param {CacheSetting | null} setting
 */
export function cacheValues(node, setting) {
  if (node.type === "assembly") {
    return { cache: setting ?? {} };
  }
  const config = { ...(node.config ?? {}) };
  delete config.cache;
  if (setting) {
    config.cache = setting;
  }
  return { config };
}

/**
 * Whether the script builds a node as a discipline its cache is set on:
 * components, assemblies that are not transparent, drivers inside another node.
 *
 * @param {any} node
 * @param {number} depth - Its ancestors: 0 for the model, 1 for its children.
 */
export function cacheApplies(node, depth) {
  if (depth === 0) {
    return false;
  }
  if (node.type === "component") {
    return true;
  }
  if (node.type === "assembly") {
    return !node.transparent;
  }
  return node.type === "driver" && depth > 1;
}

/**
 * The line describing the entries of a file cache.
 *
 * @param {{exists: boolean, entries: number, differs: boolean}} state
 */
export function entriesText(state) {
  if (!state.exists) {
    return "No entries yet: the file or its node is created by the first run.";
  }
  const count = `${state.entries} ${state.entries === 1 ? "entry" : "entries"}`;
  return state.differs
    ? `${count}, computed by another version of this node: clear them, or keep them.`
    : `${count} kept in the file.`;
}
