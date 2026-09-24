// @ts-check
// Help dialogs: keyboard shortcuts and About.
import { el } from "../components/dom.js";
import { openModal } from "../components/modal.js";
import { displayShortcut } from "../lib/shortcut_keys.js";

/** @param {import("./actions.js").ActionRegistry} actions */
export function showShortcuts(actions) {
  const table = el("table.shortcut-table");
  let menu = "";
  for (const action of actions.definitions) {
    if (!action.shortcuts.length) {
      continue;
    }
    if (action.menu !== menu) {
      menu = action.menu;
      table.append(el("tr", {}, [el("th", { colspan: 2, text: menu })]));
    }
    table.append(
      el("tr", {}, [
        el("td", { text: action.label }),
        el(
          "td",
          {},
          action.shortcuts.flatMap((shortcut, index) => [
            index ? " or " : "",
            el("kbd", { text: displayShortcut(shortcut) }),
          ]),
        ),
      ]),
    );
  }
  openModal({ title: "Keyboard shortcuts", body: table });
}

/** @param {string} version */
export function showAbout(version) {
  openModal({
    title: "About GEMSEO Process Builder",
    body: el("div", {}, [
      el("p", { text: `Version ${version}` }),
      el("p", { text: "Build, run and analyze GEMSEO processes graphically." }),
      el("p", { text: "Open source under the MIT license." }),
    ]),
  });
}
