// @ts-check
// Sets up the Workflow tab: the canvas and the selection-based actions.
import { app } from "../../app.js";
import { showError } from "../../components/errors.js";
import { isTile } from "../../lib/scene.js";
import { autoLayout } from "./auto_layout.js";
import { WorkflowCanvas } from "./canvas.js";
import { fileStem, registerImageSource } from "../../services/export.js";

/**
 * Call Python for an edit action, reporting errors.
 *
 * @param {string} method
 * @param {object} params
 * @param {string} failure
 * @returns {Promise<any>}
 */
async function editCall(method, params, failure) {
  try {
    return await app.api.call(method, params);
  } catch (error) {
    showError(failure, error);
    return null;
  }
}

export function installWorkflow() {
  const page = /** @type {HTMLElement} */ (app.tabs.center.page("workflow"));
  const canvas = new WorkflowCanvas(page, app.selection, app.navigation);
  app.canvas = canvas;
  registerImageSource("workflow", {
    get name() {
      return fileStem(app.store.node(app.store.rootId)?.name ?? "model");
    },
    produce: (options) => canvas.picture(options),
    fullChoice: true,
  });
  const { actions, selection, navigation, store } = app;

  const selectedIds = () => selection.list().filter((id) => id !== store.rootId);

  actions.handle("edit.delete", {
    run: () =>
      store
        .execute({ type: "deleteNodes", ids: selectedIds() })
        .catch((error) => showError("The nodes could not be deleted", error)),
  });
  actions.handle("edit.rename", { run: () => canvas.startRename(selectedIds()[0]) });
  actions.handle("edit.selectAll", {
    run: () => selection.set(shownNodes(navigation.current())),
  });
  actions.handle("edit.copy", {
    run: () => editCall("doc.copy", { ids: selectedIds() }, "The nodes could not be copied"),
  });
  actions.handle("edit.cut", {
    run: () => editCall("doc.cut", { ids: selectedIds() }, "The nodes could not be cut"),
  });
  actions.handle("edit.paste", {
    run: async () => {
      const position = canvas.lastPointer ?? {};
      const result = await editCall(
        "doc.paste",
        { parent: navigation.current(), ...position },
        "The clipboard could not be pasted",
      );
      if (result) {
        selection.set(result.ids);
      }
    },
  });
  actions.handle("edit.duplicate", {
    run: async () => {
      const result = await editCall("doc.duplicate", { ids: selectedIds() }, "The nodes could not be duplicated");
      if (result) {
        selection.set(result.ids);
      }
    },
  });
  actions.handle("view.fit", { run: () => canvas.fit() });
  actions.handle("view.up", { run: () => navigation.up() });
  actions.handle("view.autoLayout", { run: () => autoLayout(canvas) });
  actions.handle("edit.find", { run: () => canvas.search.open() });
  actions.handle("model.group", {
    run: async () => {
      const ids = selectedIds();
      try {
        const before = new Set(store.children(navigation.current()).map((child) => child.id));
        await store.execute({ type: "groupNodes", ids });
        const group = store.children(navigation.current()).find((child) => !before.has(child.id));
        if (group) {
          selection.set([group.id]);
        }
      } catch (error) {
        showError("The nodes could not be grouped", error);
      }
    },
  });
  actions.handle("model.ungroup", {
    run: async () => {
      const [id] = selectedIds();
      const children = store.node(id)?.children ?? [];
      try {
        await store.execute({ type: "ungroupNode", id });
        selection.set(children);
      } catch (error) {
        showError("The assembly could not be ungrouped", error);
      }
    },
  });

  /**
   * The nodes a level shows: its children, and the nodes their drivers drive.
   *
   * @param {string} levelId
   * @returns {string[]}
   */
  const shownNodes = (levelId) =>
    (store.node(levelId)?.children ?? []).flatMap((/** @type {string} */ id) =>
      isTile(store.node(id)) ? [id, ...shownNodes(id)] : [id],
    );

  const updateStates = () => {
    const count = selectedIds().length;
    for (const id of ["edit.delete", "edit.copy", "edit.cut", "edit.duplicate"]) {
      actions.setEnabled(id, count > 0);
    }
    actions.setEnabled("edit.rename", count === 1);
    actions.setEnabled("model.group", count > 0);
    const single = count === 1 ? store.node(selectedIds()[0]) : null;
    actions.setEnabled("model.ungroup", single?.type === "assembly");
    const shown = shownNodes(navigation.current()).length;
    actions.setEnabled("view.autoLayout", shown > 1);
    actions.setEnabled("edit.selectAll", shown > 0);
    actions.setEnabled("view.up", navigation.current() !== store.rootId);
  };
  selection.onChange(updateStates);
  navigation.onChange(updateStates);
  store.subscribe(updateStates);
  updateStates();
}
