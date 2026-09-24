// @ts-check
// Context menus of the canvas.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { showError } from "../../components/errors.js";
import { displayShortcut } from "../../lib/shortcut_keys.js";

/**
 * A menu item running an application action.
 *
 * @param {string} id
 * @returns {import("../../components/context_menu.js").MenuItem}
 */
export function actionItem(id) {
  const definition = app.actions.definitions.find((action) => action.id === id);
  return {
    label: definition?.label ?? id,
    shortcut: definition?.shortcuts[0] ? displayShortcut(definition.shortcuts[0]) : "",
    enabled: app.actions.isEnabled(id),
    run: () => app.actions.invoke(id),
  };
}

/**
 * Items adding the built-in node types (until the library exists).
 *
 * @param {(node: object) => void} add
 * @returns {import("../../components/context_menu.js").MenuItem[]}
 */
export function addItems(add) {
  return [
    { label: "Assembly", run: () => add({ type: "assembly", name: "Assembly" }) },
    { separator: true },
    { label: "MDA driver", run: () => add({ type: "driver", kind: "mda", name: "MDA" }) },
    { label: "DOE driver", run: () => add({ type: "driver", kind: "doe", name: "DOE" }) },
    {
      label: "Optimization driver",
      run: () => add({ type: "driver", kind: "optimization", name: "Optimizer" }),
    },
    {
      label: "Parametric study",
      run: () => add({ type: "driver", kind: "parametric", name: "Parametric" }),
    },
    { separator: true },
    {
      label: "Analytic component",
      run: () => add({ type: "component", kind: "analytic", name: "Analytic" }),
    },
  ];
}

/**
 * Change view settings of nodes without an undo entry.
 *
 * @param {string[]} ids
 * @param {object} values
 */
function setNodeView(ids, values) {
  const nodes = Object.fromEntries(ids.map((id) => [id, values]));
  app.store
    .execute({ type: "setLayout", nodes }, { undoable: false })
    .catch((/** @type {any} */ error) => showError("The view could not be changed", error));
}

/**
 * Menu of a node (and of the other selected nodes).
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 * @param {string} id
 * @param {number} x
 * @param {number} y
 */
export function nodeMenu(canvas, id, x, y) {
  const node = app.store.node(id);
  const layout = app.store.layoutOf(id) ?? {};
  const ids = canvas.selection.list();
  const container = Array.isArray(node?.children);
  /** @type {import("../../components/context_menu.js").MenuItem[]} */
  const items = [];
  if (container) {
    items.push(
      { label: "Open", run: () => canvas.navigation.enter(id) },
      {
        label: layout.expanded ? "Collapse" : "Expand in place",
        run: () => setNodeView([id], { expanded: !layout.expanded }),
      },
      { separator: true },
    );
  } else {
    const display = layout.port_display ?? "all";
    items.push(
      {
        label: "Show variables",
        items: [
          { label: "All", checked: display === "all", run: () => setNodeView(ids, { port_display: "all" }) },
          {
            label: "Connected only",
            checked: display === "connected",
            run: () => setNodeView(ids, { port_display: "connected" }),
          },
          { label: "None", checked: display === "none", run: () => setNodeView(ids, { port_display: "none" }) },
        ],
      },
      { separator: true },
    );
  }
  items.push(
    actionItem("edit.rename"),
    actionItem("edit.duplicate"),
    { separator: true },
    actionItem("edit.cut"),
    actionItem("edit.copy"),
    actionItem("edit.delete"),
  );
  openContextMenu(x, y, items);
}

/**
 * Menu of the canvas background.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 * @param {{x: number, y: number}} position - Canvas coordinates of the click.
 * @param {number} x
 * @param {number} y
 */
export function backgroundMenu(canvas, position, x, y) {
  openContextMenu(x, y, [
    { label: "Add", items: addItems((node) => canvas.addNode(node, position)) },
    { separator: true },
    actionItem("edit.paste"),
    actionItem("edit.selectAll"),
    { separator: true },
    actionItem("view.fit"),
    actionItem("view.up"),
  ]);
}
