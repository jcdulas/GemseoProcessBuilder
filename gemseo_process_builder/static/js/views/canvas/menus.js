// @ts-check
// Context menus of the canvas.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { showError } from "../../components/errors.js";
import { BUILTIN_ITEMS } from "../../lib/builtins.js";
import { displayShortcut } from "../../lib/shortcut_keys.js";
import { openDriverEditor } from "../../panels/driver_editor/index.js";
import { showInN2 } from "../n2/n2_view.js";
import { openXdsm } from "../xdsm/xdsm_view.js";
import { roleMenuItems } from "../../services/driver_roles.js";

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
  /** @type {import("../../components/context_menu.js").MenuItem[]} */
  const items = [];
  let group = "";
  for (const item of BUILTIN_ITEMS) {
    if (group && item.group !== group) {
      items.push({ separator: true });
    }
    group = item.group;
    items.push({ label: item.label, run: () => add(item.node) });
  }
  return items;
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
 * @param {{name: string, direction: "in" | "out"} | null} [port] - The port clicked, if any.
 */
export function nodeMenu(canvas, id, x, y, port = null) {
  const node = app.store.node(id);
  const layout = app.store.layoutOf(id) ?? {};
  const ids = canvas.selection.list();
  const container = Array.isArray(node?.children);
  /** @type {import("../../components/context_menu.js").MenuItem[]} */
  const items = [];
  const roles = port ? roleMenuItems(id, port.name, port.direction) : [];
  if (roles.length) {
    items.push(...roles, { separator: true });
  }
  if (node?.type === "driver") {
    items.push({ label: "Edit driver…", run: () => openDriverEditor(id) });
    if (node.kind !== "mda") {
      items.push({ label: "Show XDSM", run: () => openXdsm(id) });
    }
    items.push({ separator: true });
  }
  if (container) {
    items.push(
      { label: "Open", run: () => canvas.navigation.enter(id) },
      {
        label: layout.expanded ? "Collapse" : "Expand in place",
        run: () => setNodeView([id], { expanded: !layout.expanded }),
      },
      variablesMenu(ids, layout),
      { separator: true },
    );
  } else {
    items.push(variablesMenu(ids, layout), { separator: true });
  }
  if (node && (node.type === "component" || node.type === "assembly")) {
    items.push({
      label: "Isolate variable names",
      checked: Boolean(node.isolated),
      run: () =>
        app.store
          .execute({ type: "setNodeProperties", id, values: { isolated: !node.isolated } })
          .catch((error) => showError("The node could not be changed", error)),
    });
  }
  items.push({ label: "Show in N2", run: () => showInN2(id) }, { separator: true });
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
 * How nodes show their variables: counted on a card (the default), or listed.
 *
 * @param {string[]} ids
 * @param {any} layout
 */
function variablesMenu(ids, layout) {
  const display = layout.port_display === "none" ? "compact" : (layout.port_display ?? "compact");
  return {
    label: "Variables",
    items: [
      { label: "Card (counted)", checked: display === "compact", run: () => setNodeView(ids, { port_display: "compact" }) },
      { label: "Listed: all", checked: display === "all", run: () => setNodeView(ids, { port_display: "all" }) },
      {
        label: "Listed: connected only",
        checked: display === "connected",
        run: () => setNodeView(ids, { port_display: "connected" }),
      },
    ],
  };
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
    actionItem("view.n2"),
    actionItem("view.xdsm"),
    { separator: true },
    actionItem("file.exportImage"),
    { separator: true },
    actionItem("tools.devTools"),
  ]);
}
