// @ts-check
// The Cache section of the inspector (SPEC § 8.7): what GEMSEO keeps of the
// executions of a component, an assembly or a nested driver.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import {
  CACHE_CHOICES,
  cacheApplies,
  cacheChoice,
  cacheFields,
  cacheOf,
  cacheValues,
  defaultNodePath,
  entriesText,
  settingFor,
} from "../lib/cache_setting.js";

/**
 * @param {string} label
 * @param {Node} control
 * @param {string} [hint]
 */
function row(label, control, hint) {
  return el("div.form-row", {}, [
    el("span.form-label", { text: label }),
    el("div", {}, [control, hint ? el("div.form-hint", { text: hint }) : null]),
  ]);
}

/**
 * Give a node a cache setting.
 *
 * @param {any} node
 * @param {import("../lib/cache_setting.js").CacheSetting | null} setting
 */
function save(node, setting) {
  const current = app.store.node(node.id) ?? node;
  return app.store
    .execute({ type: "setNodeProperties", id: node.id, values: cacheValues(current, setting), label_text: "Change cache" })
    .catch((error) => showError("The cache could not be changed", error));
}

/**
 * The Cache section of a node, or null when the script builds no discipline of it.
 *
 * @param {any} node
 * @returns {HTMLElement | null}
 */
export function cacheSection(node) {
  const path = app.store.pathTo(node.id);
  if (!cacheApplies(node, path.length - 1)) {
    return null;
  }
  const setting = cacheOf(node);
  const choice = cacheChoice(setting);
  const fields = cacheFields(choice);
  const select = /** @type {HTMLSelectElement} */ (
    el(
      "select.input",
      {},
      CACHE_CHOICES.map((item) => el("option", { value: item.value, text: item.label, selected: item.value === choice })),
    )
  );
  select.addEventListener("change", async () => {
    const names = path.map((/** @type {string} */ id) => app.store.node(id)?.name ?? "");
    let file = "";
    if (select.value === "hdf5" && !setting?.file) {
      try {
        file = (await app.api.call("cache.defaultFile")).file;
      } catch (error) {
        showError("The default cache file is not known", error);
      }
    }
    save(node, settingFor(select.value, setting, { file, node: defaultNodePath(names) }));
  });
  const hint = CACHE_CHOICES.find((item) => item.value === choice)?.hint;
  const rows = [el("h3.section-title", { text: "Cache" }), row("Keep", select, hint)];
  if (fields.file && setting) {
    const file = /** @type {HTMLInputElement} */ (el("input.input.pref-wide", { type: "text", value: setting.file ?? "" }));
    file.addEventListener("change", () => save(node, { ...setting, file: file.value.trim() }));
    const nodePath = /** @type {HTMLInputElement} */ (el("input.input", { type: "text", value: setting.node ?? "" }));
    nodePath.addEventListener("change", () => save(node, { ...setting, node: nodePath.value.trim() }));
    rows.push(row("File", file, "An HDF5 file; several nodes may share it."), row("Node", nodePath, "Where the entries of this node are in the file."));
  }
  if (fields.tolerance && setting) {
    const tolerance = /** @type {HTMLInputElement} */ (
      el("input.input", { type: "number", min: "0", step: "any", value: String(setting.tolerance ?? 0) })
    );
    tolerance.addEventListener("change", () => {
      const value = Math.max(0, Number(tolerance.value) || 0);
      const next = { ...setting };
      if (value) {
        next.tolerance = value;
      } else {
        delete next.tolerance;
      }
      save(node, next);
    });
    rows.push(
      el("details.form-advanced", {}, [
        el("summary", { text: "Advanced" }),
        row("Tolerance", tolerance, "Inputs closer than this to cached ones are taken as equal (0: equal only)."),
      ]),
    );
  }
  if (fields.entries && setting?.file && setting?.node) {
    rows.push(entriesRow(node));
  }
  return el("div.inspector-section", {}, rows);
}

/**
 * The entries of a file cache, with Clear and, when out of date, Keep.
 *
 * @param {any} node
 */
function entriesRow(node) {
  const text = el("div.form-hint", { text: "Counting the entries…" });
  const buttons = el("div.button-row");
  const element = el("div.form-row", {}, [el("span.form-label", { text: "Entries" }), el("div", {}, [text, buttons])]);
  const refresh = () =>
    app.api
      .call("cache.inspect", { id: node.id })
      .then((/** @type {any} */ state) => {
        text.textContent = entriesText(state);
        const actions = [];
        if (state.entries) {
          actions.push(
            el("button.button.bordered", {
              text: "Clear",
              title: "Remove the entries of this node from the file",
              onClick: () => app.api.call("cache.clear", { id: node.id }).then(refresh).catch((error) => showError("The cache could not be cleared", error)),
            }),
          );
        }
        if (state.differs) {
          actions.push(
            el("button.button.bordered", {
              text: "Keep",
              title: "Keep these entries for the node as it is now",
              onClick: () => app.api.call("cache.keep", { id: node.id }).then(refresh).catch((error) => showError("The entries could not be kept", error)),
            }),
          );
        }
        buttons.replaceChildren(...actions);
      })
      .catch((/** @type {any} */ error) => {
        text.textContent = `The entries cannot be counted: ${error.message ?? error}`;
      });
  refresh();
  return element;
}
