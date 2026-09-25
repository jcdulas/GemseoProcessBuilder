// @ts-check
// Tools › Preferences.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { openModal } from "../components/modal.js";

/**
 * @param {string} label
 * @param {HTMLElement} control
 * @param {string} [hint]
 */
function row(label, control, hint) {
  return el("div.pref-row", {}, [
    el("label.form-label", { text: label }),
    el("div", {}, [control, hint ? el("div.form-hint", { text: hint }) : null]),
  ]);
}

/**
 * Extra sections added by later plans (catalog folders…).
 *
 * @type {((preferences: any) => {element: HTMLElement, values: () => object})[]}
 */
export const preferenceSections = [];

export async function showPreferences() {
  const preferences = await app.api.call("prefs.get");
  const interpreter = /** @type {HTMLInputElement} */ (
    el("input.input.pref-wide", {
      type: "text",
      value: preferences.python_interpreter,
      placeholder: "The application's own Python",
    })
  );
  const editor = /** @type {HTMLInputElement} */ (
    el("input.input.pref-wide", {
      type: "text",
      value: preferences.code_editor ?? "",
      placeholder: "Visual Studio Code if installed (code or vscode), else the text editor",
    })
  );
  const maxUndo = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "number", min: 1, max: 10000, value: preferences.max_undo })
  );
  const stopTimeout = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "number", min: 1, step: 1, value: preferences.stop_timeout_s })
  );
  const concurrent = /** @type {HTMLInputElement} */ (
    el("input", { type: "checkbox", checked: preferences.allow_concurrent_runs })
  );
  const extra = preferenceSections.map((section) => section(preferences));
  const body = el("div.preferences", {}, [
    row(
      "Python interpreter",
      interpreter,
      "Runs GEMSEO and your disciplines. It needs GEMSEO 6 and Pydantic 2. Leave empty to use the application's Python.",
    ),
    row(
      "Code editor",
      editor,
      'Opens the Python files of your disciplines, like "code" or "C:\Program Files\Notepad++\notepad++.exe"; {file} stands for the file.',
    ),
    row("Undo steps", maxUndo, "Applies to the next opened project."),
    row("Stop timeout (s)", stopTimeout, "Delay before a run that does not stop is killed."),
    row("Concurrent runs", concurrent, "Allow several runs at the same time."),
    ...extra.map((section) => section.element),
  ]);
  openModal({
    title: "Preferences",
    body,
    buttons: [
      { label: "Cancel" },
      {
        label: "Save",
        primary: true,
        onClick: async () => {
          const values = {
            python_interpreter: interpreter.value.trim(),
            code_editor: editor.value.trim(),
            max_undo: Number(maxUndo.value),
            stop_timeout_s: Number(stopTimeout.value),
            allow_concurrent_runs: concurrent.checked,
            ...Object.assign({}, ...extra.map((section) => section.values())),
          };
          try {
            await app.api.call("prefs.set", { values });
          } catch (error) {
            showError("The preferences could not be saved", error);
            return false;
          }
          return true;
        },
      },
    ],
  });
}
