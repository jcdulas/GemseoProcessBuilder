// @ts-check
// Shared services of the page, filled by main.js at startup and used by the
// panels and views.

/**
 * @typedef {object} AppServices
 * @property {import("./lib/rpc.js").RpcClient} api
 * @property {import("./shell/actions.js").ActionRegistry} actions
 * @property {string} version
 * @property {import("./shell/statusbar.js").StatusBar} statusBar
 * @property {import("./shell/layout.js").PanelLayout} layout
 * @property {Record<"left" | "center" | "bottom", import("./shell/tabs.js").TabGroup>} tabs
 * @property {import("./panels/console.js").ConsolePanel} console
 */

/** @type {AppServices} */
export const app = /** @type {any} */ ({});
