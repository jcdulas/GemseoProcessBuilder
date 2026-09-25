// @ts-check
// File menu actions and display of the current project.
import { app } from "../app.js";
import { showError } from "../components/errors.js";
import { showToast } from "../components/toast.js";

/**
 * Call a project method, reporting errors in a dialog.
 *
 * @param {string} method
 * @param {string} failure - Dialog title if the call fails.
 */
async function projectCall(method, failure) {
  try {
    return await app.api.call(method, {}, { timeout: 24 * 3600 * 1000 }); // Dialogs wait for the user.
  } catch (error) {
    showError(failure, error);
    return null;
  }
}

/**
 * @param {{name: string, path: string | null, dirty: boolean, read_only?: string}} state
 */
function showState(state) {
  app.projectTitle.show(state);
  app.statusBar.set("project", state.path ?? `${state.name} (not saved yet)`, state.path ?? "");
}

/**
 * The node a script runs: the selected driver or assembly, else the level shown.
 *
 * @returns {string}
 */
function exportTarget() {
  const ids = app.selection.list();
  const selected = ids.length === 1 ? app.store.node(ids[0]) : null;
  return selected?.children ? ids[0] : app.navigation.current();
}

/** @param {string} method - project.save or project.saveAs. */
async function save(method) {
  const result = await projectCall(method, "Cannot save the project");
  if (result?.saved) {
    showToast({ title: "Project saved" });
  }
}

async function exportPython() {
  try {
    // The dialog waits for the user; the export is logged in the console.
    await app.api.call("codegen.export", { target: exportTarget() }, { timeout: 24 * 3600 * 1000 });
  } catch (error) {
    showError("Cannot export the script", error);
  }
}

export async function installProjectActions() {
  const { actions, api } = app;
  actions.handle("file.new", { run: () => projectCall("project.new", "Cannot create a project") });
  actions.handle("file.open", { run: () => projectCall("project.open", "Cannot open the project") });
  actions.handle("file.save", { run: () => save("project.save") });
  actions.handle("file.saveAs", { run: () => save("project.saveAs") });
  actions.handle("file.exportPython", { run: exportPython });
  actions.handle("file.close",{ run: () => projectCall("project.close", "Cannot close the project") });
  api.on("project.changed", showState);
  showState(await api.call("project.state"));
}
