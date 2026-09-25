// @ts-check
// The application menu of the top bar, built from the action definitions.

/**
 * @typedef {object} AppMenuItem
 * @property {string} [id] - The action run by the item.
 * @property {string} [label]
 * @property {string} [shortcut]
 * @property {boolean} [enabled]
 * @property {boolean} [checked]
 * @property {boolean} [separator]
 * @property {string} [path] - A recent project opened by the item.
 * @property {AppMenuItem[]} [items] - A submenu.
 */

/**
 * @typedef {object} AppMenuSection
 * @property {string} title - The menu of the former menu bar: File, Edit…
 * @property {AppMenuItem[]} items
 */

/**
 * The file name of a path, for a short menu label.
 *
 * @param {string} path
 * @returns {string}
 */
export function fileName(path) {
  return path.split(/[\\/]/).filter(Boolean).pop() ?? path;
}

/**
 * The sections of the application menu, in the order of the definitions.
 *
 * @param {{id: string, menu: string, label: string, shortcuts: string[], separator_before?: boolean}[]} definitions
 * @param {{
 *   enabled: (id: string) => boolean,
 *   checked: (id: string) => boolean | undefined,
 *   recent: string[],
 *   displayShortcut?: (shortcut: string) => string,
 * }} state
 * @returns {AppMenuSection[]}
 */
export function appMenuSections(definitions, { enabled, checked, recent, displayShortcut = (text) => text }) {
  /** @type {Map<string, AppMenuItem[]>} */
  const sections = new Map();
  for (const definition of definitions) {
    let items = sections.get(definition.menu);
    if (!items) {
      items = [];
      sections.set(definition.menu, items);
    }
    if (definition.separator_before && items.length) {
      items.push({ separator: true });
    }
    const shortcut = definition.shortcuts[0];
    items.push({
      id: definition.id,
      label: definition.label,
      shortcut: shortcut ? displayShortcut(shortcut) : "",
      enabled: enabled(definition.id),
      checked: checked(definition.id),
    });
    if (definition.id === "file.open") {
      items.push({
        label: "Open recent",
        enabled: recent.length > 0,
        items: recent.map((path) => ({ label: fileName(path), path })),
      });
    }
  }
  return [...sections].map(([title, items]) => ({ title, items }));
}
