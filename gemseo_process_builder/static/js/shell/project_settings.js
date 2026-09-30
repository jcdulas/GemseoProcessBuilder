// @ts-check
// Model › Project settings, and the catalog folders of the preferences.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { openModal } from "../components/modal.js";
import { preferenceSections } from "./preferences_dialog.js";

/**
 * A text area holding one folder per line.
 *
 * @param {string[]} folders
 * @returns {HTMLTextAreaElement}
 */
function foldersArea(folders) {
  const area = /** @type {HTMLTextAreaElement} */ (
    el("textarea.input.form-textarea.pref-wide", { rows: 3, placeholder: "One folder per line" })
  );
  area.value = folders.join("\n");
  return area;
}

/** @param {HTMLTextAreaElement} area */
function foldersFrom(area) {
  return area.value
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

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

export function showProjectSettings() {
  const { metadata, settings } = app.store.state.project;
  const name = /** @type {HTMLInputElement} */ (el("input.input.pref-wide", { type: "text", value: metadata.name }));
  const description = /** @type {HTMLTextAreaElement} */ (el("textarea.input.form-textarea.pref-wide", { rows: 2 }));
  description.value = metadata.description ?? "";
  const folders = foldersArea(settings.catalog_paths ?? []);
  const runs = /** @type {HTMLInputElement} */ (
    el("input.input.pref-wide", { type: "text", value: settings.runs_dir ?? "", placeholder: "<project name>.runs next to the project file" })
  );
  openModal({
    title: "Project settings",
    body: el("div.preferences", {}, [
      row("Name", name),
      row("Description", description),
      row("Catalog folders", folders, "Folders scanned for components, for this project only (absolute paths)."),
      row("Runs folder", runs),
    ]),
    buttons: [
      { label: "Cancel" },
      {
        label: "Save",
        primary: true,
        onClick: async () => {
          try {
            await app.store.execute({
              type: "setProjectSettings",
              metadata: { name: name.value.trim() || "Untitled", description: description.value },
              settings: { catalog_paths: foldersFrom(folders), runs_dir: runs.value.trim() || null },
            });
          } catch (error) {
            showError("The project settings could not be changed", error);
            return false;
          }
          return true;
        },
      },
    ],
  });
}

export function installProjectSettings() {
  app.actions.handle("model.projectSettings", { run: showProjectSettings });
  preferenceSections.push((preferences) => {
    const area = foldersArea(preferences.catalog_paths ?? []);
    return {
      element: row("Catalog folders", area, "Folders scanned for components, for every project."),
      values: () => ({ catalog_paths: foldersFrom(area) }),
    };
  });
}
