// @ts-check
// File menu actions and display of the current project.
import { app } from "../app.js";
import { showError } from "../components/errors.js";

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
 * @param {{name: string, path: string | null, dirty: boolean}} state
 */
function showState(state) {
  app.statusBar.set("project", state.path ?? `${state.name} (not saved yet)`, state.path ?? "");
  app.statusBar.set("modified", state.dirty ? "Modified" : "");
}

export async function installProjectActions() {
  const { actions, api } = app;
  actions.handle("file.new", { run: () => projectCall("project.new", "Cannot create a project") });
  actions.handle("file.open", { run: () => projectCall("project.open", "Cannot open the project") });
  actions.handle("file.save", { run: () => projectCall("project.save", "Cannot save the project") });
  actions.handle("file.saveAs", { run: () => projectCall("project.saveAs", "Cannot save the project") });
  actions.handle("file.close", { run: () => projectCall("project.close", "Cannot close the project") });
  api.on("project.changed", showState);
  showState(await api.call("project.state"));
}
