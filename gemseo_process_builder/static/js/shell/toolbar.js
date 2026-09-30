// @ts-check
// The top bar: application menu, project, and the buttons of the main actions.
import { app } from "../app.js";
import { openContextMenu } from "../components/context_menu.js";
import { el, icon } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { appMenuSections } from "../lib/app_menu.js";
import { displayShortcut } from "../lib/shortcut_keys.js";

/**
 * Buttons of the top bar: [action id, icon, text, style], or "|" for a gap.
 * Buttons with a text are labeled; the others show their action in a tooltip.
 */
const BUTTONS = [
  ["edit.undo", "undo"],
  ["edit.redo", "redo"],
  "|",
  ["view.autoLayout", "layout"],
  ["view.fit", "fit"],
  ["edit.find", "search"],
  "|",
  ["model.validate", "validate", "Validate", "bordered"],
  ["run.stop", "stop", "Stop", "danger"],
  ["run.start", "run", "Run", "primary"],
];

/** Actions whose button is hidden, not only disabled, when they cannot run. */
const HIDDEN_WHEN_DISABLED = new Set(["run.stop"]);

/** The mark of the application: three linked nodes. */
function logo() {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 28 28");
  svg.classList.add("topbar-logo");
  svg.innerHTML =
    '<rect width="28" height="28" rx="8" class="logo-back"/>' +
    '<path d="M9 10.5C14 10.5 14 17.5 19 17.5" class="logo-link"/>' +
    '<circle cx="8" cy="10.5" r="3" class="logo-node"/>' +
    '<circle cx="20" cy="17.5" r="3" class="logo-node"/>' +
    '<circle cx="20" cy="8.5" r="2" class="logo-node logo-node-small"/>';
  return svg;
}

/**
 * The application menu, below its button.
 *
 * @param {HTMLElement} button
 * @param {import("./actions.js").ActionRegistry} actions
 */
async function openAppMenu(button, actions) {
  /** @type {string[]} */
  let recent = [];
  try {
    recent = await app.api.call("project.recent");
  } catch (error) {
    console.error(error);
  }
  const sections = appMenuSections(actions.definitions, {
    enabled: (id) => actions.definitions.find((action) => action.id === id)?.native || actions.isEnabled(id),
    checked: (id) => actions.behaviors.get(id)?.checked,
    recent,
    displayShortcut,
  });
  /** @param {import("../lib/app_menu.js").AppMenuItem} item */
  const toMenuItem = (item) => ({
    ...item,
    run: item.path ? () => openRecent(/** @type {string} */ (item.path)) : item.id ? () => runAction(actions, /** @type {string} */ (item.id)) : undefined,
    items: item.items?.map(toMenuItem),
  });
  const items = sections.map((section) => ({ label: section.title, items: section.items.map(toMenuItem) }));
  const box = button.getBoundingClientRect();
  openContextMenu(box.left, box.bottom + 6, items);
}

/**
 * @param {import("./actions.js").ActionRegistry} actions
 * @param {string} id
 */
function runAction(actions, id) {
  if (actions.definitions.find((action) => action.id === id)?.native) {
    return app.api.call("actions.triggerNative", { id });
  }
  return actions.invoke(id);
}

/** @param {string} path */
async function openRecent(path) {
  try {
    await app.api.call("project.open", { path }, { timeout: 24 * 3600 * 1000 }); // May ask about unsaved changes.
  } catch (error) {
    showError("Cannot open the project", error);
  }
}

/**
 * The top bar shows the project and its state.
 *
 * @param {HTMLElement} root
 */
export class ProjectTitle {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.name = el("span.topbar-project-name");
    this.state = el("span.topbar-project-state");
    root.append(el("div.topbar-project", {}, [this.name, this.state]));
  }

  /** @param {{name: string, path: string | null, dirty: boolean, read_only?: string}} state */
  show(state) {
    /** The project shown: its name, its path… */
    this.current = state;
    this.name.textContent = state.name;
    this.name.title = state.path ?? "Not saved yet";
    const [text, kind, title] = state.read_only
      ? ["Read-only", "read-only", `Open in ${state.read_only}: save it under another name to keep your changes.`]
      : state.dirty || !state.path
        ? ["Unsaved changes", "dirty", "Save with Ctrl+S"]
        : ["Saved", "saved", state.path];
    this.state.textContent = text;
    this.state.title = title;
    this.state.className = `topbar-project-state state-${kind}`;
  }
}

/**
 * Build the top bar.
 *
 * @param {HTMLElement} root
 * @param {import("./actions.js").ActionRegistry} actions
 * @returns {ProjectTitle}
 */
export function buildToolbar(root, actions) {
  const menuButton = el("button.button.icon-button", { title: "Menu", "aria-haspopup": "menu" }, [icon("menu")]);
  menuButton.addEventListener("click", () => openAppMenu(menuButton, actions));
  const brand = el("div.topbar-brand", { title: `GEMSEO Process Builder ${app.version ?? ""}` }, [logo()]);
  root.append(menuButton, brand);
  const title = new ProjectTitle(root);
  root.append(el("div.topbar-spacer"));

  /** @type {Map<string, HTMLButtonElement>} */
  const buttons = new Map();
  for (const item of BUTTONS) {
    if (item === "|") {
      root.append(el("div.toolbar-separator"));
      continue;
    }
    const [id, iconName, text, style] = item;
    const definition = actions.definitions.find((action) => action.id === id);
    const shortcut = definition?.shortcuts[0];
    const tooltip = definition ? definition.label + (shortcut ? ` (${displayShortcut(shortcut)})` : "") : id;
    const button = /** @type {HTMLButtonElement} */ (
      el(`button.button${text ? ".labeled" : ".icon-button"}${style ? `.${style}` : ""}`, {
        title: tooltip,
        disabled: true,
        dataset: { action: id },
        onClick: () => actions.invoke(id),
      }, [icon(/** @type {any} */ (iconName)), text ? el("span", { text }) : null])
    );
    button.hidden = HIDDEN_WHEN_DISABLED.has(id);
    buttons.set(id, button);
    root.append(button);
  }
  actions.onChange((id) => {
    const button = buttons.get(id);
    if (button) {
      button.disabled = !actions.isEnabled(id);
      button.hidden = HIDDEN_WHEN_DISABLED.has(id) && button.disabled;
    }
  });
  return title;
}
