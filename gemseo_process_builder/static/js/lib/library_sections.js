// @ts-check
// The sections of the Library given by the installed packages (SPEC § 7.6): one
// per distribution, titled with its name and version, its entries grouped.
import { searchItems } from "./builtins.js";

/**
 * @typedef {object} PackageEntry
 * @property {string} kind
 * @property {string} name
 * @property {string} module_path
 * @property {string} attribute
 * @property {string} [module]
 * @property {string} [group]
 * @property {string} [description]
 */

/**
 * @typedef {object} PackageScan
 * @property {string} name
 * @property {string} version
 * @property {PackageEntry[]} entries
 * @property {{path: string, message: string, traceback?: string}[]} [errors]
 * @property {string[]} [warnings]
 */

/**
 * @typedef {object} LibraryGroup
 * @property {string} title - Empty for the entries without a group, listed first.
 * @property {(PackageEntry & {label: string, package: {name: string, version: string}})[]} entries
 */

/**
 * @typedef {object} PackageSection
 * @property {string} key
 * @property {string} title
 * @property {LibraryGroup[]} groups
 * @property {{path: string, message: string, traceback?: string}[]} errors - Hidden while searching.
 * @property {string[]} warnings
 */

/**
 * The sections of the installed packages, filtered by a search text.
 *
 * A package keeps its section while its entries match, or, without a search,
 * when it has errors to show; groups keep the order of their first entry,
 * the entries without a group first.
 *
 * @param {PackageScan[]} packages
 * @param {string} text
 * @returns {PackageSection[]}
 */
export function packageSections(packages, text) {
  /** @type {PackageSection[]} */
  const sections = [];
  const searching = Boolean(text.trim());
  for (const scan of [...packages].sort((a, b) => a.name.localeCompare(b.name))) {
    const owner = { name: scan.name, version: scan.version };
    const items = searchItems(
      scan.entries.map((entry) => ({ ...entry, label: entry.name, package: owner })),
      text,
    );
    /** @type {Map<string, LibraryGroup>} */
    const groups = new Map();
    for (const item of items) {
      const title = item.group ?? "";
      if (!groups.has(title)) {
        groups.set(title, { title, entries: [] });
      }
      groups.get(title)?.entries.push(item);
    }
    const ordered = [...groups.values()].sort((a, b) => Number(Boolean(a.title)) - Number(Boolean(b.title)));
    const errors = searching ? [] : (scan.errors ?? []);
    if (!ordered.length && !errors.length && searching) {
      continue;
    }
    sections.push({
      key: `package:${scan.name}`,
      title: `${scan.name} ${scan.version}`.trim(),
      groups: ordered,
      errors,
      warnings: searching ? [] : (scan.warnings ?? []),
    });
  }
  return sections;
}
