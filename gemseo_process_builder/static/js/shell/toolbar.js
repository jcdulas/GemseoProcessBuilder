// @ts-check
// The toolbar: buttons bound to actions, disabled when their action is.
import { el, icon } from "../components/dom.js";
import { displayShortcut } from "../lib/shortcut_keys.js";

/** Toolbar content: action ids with their icon, or "|" for a separator. */
const TOOLBAR = [
  ["file.new", "new"],
  ["file.open", "open"],
  ["file.save", "save"],
  "|",
  ["edit.undo", "undo"],
  ["edit.redo", "redo"],
  "|",
  ["model.validate", "validate", "Validate"],
  ["run.start", "run", "Run"],
  ["run.stop", "stop", "Stop"],
  "|",
  ["view.autoLayout", "layout"],
  ["view.fit", "fit"],
  ["edit.find", "search"],
];

/**
 * Build the toolbar.
 *
 * @param {HTMLElement} root
 * @param {import("./actions.js").ActionRegistry} actions
 */
export function buildToolbar(root, actions) {
  /** @type {Map<string, HTMLButtonElement>} */
  const buttons = new Map();
  for (const item of TOOLBAR) {
    if (item === "|") {
      root.append(el("div.toolbar-separator"));
      continue;
    }
    const [id, iconName, text] = item;
    const definition = actions.definitions.find((action) => action.id === id);
    const shortcut = definition?.shortcuts[0];
    const title = definition ? definition.label + (shortcut ? ` (${displayShortcut(shortcut)})` : "") : id;
    const button = /** @type {HTMLButtonElement} */ (
      el("button.button", { title, disabled: true, dataset: { action: id }, onClick: () => actions.invoke(id) }, [
        icon(/** @type {any} */ (iconName)),
        text ? el("span", { text }) : null,
      ])
    );
    buttons.set(id, button);
    root.append(button);
  }
  actions.onChange((id) => {
    const button = buttons.get(id);
    if (button) {
      button.disabled = !actions.isEnabled(id);
    }
  });
}
