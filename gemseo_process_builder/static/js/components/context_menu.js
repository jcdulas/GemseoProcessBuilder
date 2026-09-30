// @ts-check
// Context menus, with one level of submenus.
import { el } from "./dom.js";

/**
 * @typedef {object} MenuItem
 * @property {string} [label]
 * @property {() => any} [run]
 * @property {boolean} [enabled]
 * @property {boolean} [checked]
 * @property {boolean} [separator]
 * @property {string} [shortcut]
 * @property {MenuItem[]} [items] - A submenu.
 */

/** @type {HTMLElement | null} */
let openMenu = null;

export function closeContextMenu() {
  openMenu?.remove();
  openMenu = null;
  document.removeEventListener("pointerdown", onOutside, true);
  document.removeEventListener("keydown", onKey, true);
}

/** @param {Event} event */
function onOutside(event) {
  if (openMenu && !openMenu.contains(/** @type {Node} */ (event.target))) {
    closeContextMenu();
  }
}

/** @param {KeyboardEvent} event */
function onKey(event) {
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
    closeContextMenu();
  }
}

/**
 * @param {MenuItem[]} items
 * @returns {HTMLElement}
 */
function buildMenu(items) {
  const menu = el("div.context-menu", { role: "menu" });
  for (const item of items) {
    if (item.separator) {
      menu.append(el("div.context-menu-separator"));
      continue;
    }
    const enabled = item.enabled !== false;
    const row = el(
      "div.context-menu-item",
      { role: "menuitem", "aria-disabled": !enabled ? "true" : undefined },
      [
        el("span.context-menu-check", { text: item.checked ? "✓" : "" }),
        el("span.context-menu-label", { text: item.label ?? "" }),
        el("span.context-menu-shortcut", { text: item.items ? "▸" : (item.shortcut ?? "") }),
      ],
    );
    if (!enabled) {
      row.classList.add("disabled");
    } else if (item.items) {
      const submenu = buildMenu(item.items);
      submenu.classList.add("submenu");
      row.append(submenu);
      row.classList.add("has-submenu");
    } else {
      row.addEventListener("click", () => {
        closeContextMenu();
        Promise.resolve()
          .then(() => item.run?.())
          .catch((error) => console.error(`Menu item ${item.label} failed:`, error));
      });
    }
    menu.append(row);
  }
  return menu;
}

/**
 * Open a context menu at a screen position.
 *
 * @param {number} x
 * @param {number} y
 * @param {MenuItem[]} items
 */
export function openContextMenu(x, y, items) {
  closeContextMenu();
  const menu = buildMenu(items);
  document.body.append(menu);
  const { width, height } = menu.getBoundingClientRect();
  menu.style.left = `${Math.min(x, window.innerWidth - width - 4)}px`;
  menu.style.top = `${Math.min(y, window.innerHeight - height - 4)}px`;
  openMenu = menu;
  document.addEventListener("pointerdown", onOutside, true);
  document.addEventListener("keydown", onKey, true);
}
