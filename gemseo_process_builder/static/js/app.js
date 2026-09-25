// @ts-check
// Shared services of the page, filled by main.js at startup and used by the
// panels and views.

/**
 * @typedef {object} AppServices
 * @property {import("./lib/rpc.js").RpcClient} api
 * @property {import("./shell/actions.js").ActionRegistry} actions
 * @property {string} version
 * @property {import("./shell/statusbar.js").StatusBar} statusBar
 * @property {import("./shell/toolbar.js").ProjectTitle} projectTitle - The project in the top bar.
 * @property {import("./shell/layout.js").PanelLayout} layout
 * @property {Record<"left" | "center" | "bottom", import("./shell/tabs.js").TabGroup>} tabs
 * @property {import("./panels/console.js").ConsolePanel} console
 * @property {import("./store.js").DocumentStore} store - The document mirror.
 * @property {import("./services/selection.js").Selection} selection - Selected nodes.
 * @property {import("./services/navigation.js").Navigation} navigation - Canvas level.
 * @property {import("./views/canvas/canvas.js").WorkflowCanvas} canvas
 * @property {import("./services/component_status.js").ComponentStatus} componentStatus
 * @property {import("./services/derivatives.js").DerivativeState} derivatives - Origins and checks of the derivatives.
 * @property {import("./services/link_focus.js").LinkFocus} linkFocus
 * @property {import("./services/validation.js").ValidationState} validation
 * @property {import("./services/driver_roles.js").DriverRoles} driverRoles - Roles of variables in drivers.
 * @property {import("./services/run_state.js").RunStates} runStates - Runs of the session and their events.
 * @property {import("./services/brush_selection.js").BrushSelection} brushSelection - Evaluations brushed in the results views.
 * @property {{state: string, detail: string, versions: Record<string, string>}} workerStatus
 */

/** @type {AppServices} */
export const app = /** @type {any} */ ({});
