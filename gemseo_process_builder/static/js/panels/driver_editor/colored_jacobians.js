// @ts-check
// The colored Jacobians of the large-scale optimizer (LSO_* algorithms): optional,
// unchecked by default (docs/LARGE_SCALE_OPTIMIZER_SPEC.md § 3.9, § 6).
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { setConfig } from "./common.js";

/**
 * @typedef {object} ColoredJacobians
 * @property {boolean} enabled
 * @property {string | null} [module_path]
 * @property {string | null} [module]
 * @property {string} function
 */

/**
 * The checkbox and, checked, the function giving the sparsity pattern.
 *
 * @param {string} id - The driver.
 * @param {ColoredJacobians} colored
 */
export function coloredJacobiansBox(id, colored) {
  /** @param {Partial<ColoredJacobians>} values */
  const save = (values) => setConfig(id, "colored_jacobians", { ...colored, ...values }).catch(() => {});
  const enabled = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: colored.enabled, name: "colored_jacobians" }));
  enabled.addEventListener("change", () => save({ enabled: enabled.checked }));
  const file = /** @type {HTMLInputElement} */ (
    el("input.input.pref-wide", { type: "text", value: colored.module_path ?? "", placeholder: "C:\\path\\to\\pattern.py", name: "pattern_file" })
  );
  file.addEventListener("change", () => save({ module_path: file.value.trim() || null, module: null }));
  const browse = el("button.button.bordered", {
    text: "Browse…",
    onClick: async () => {
      const path = await app.api.call("dialog.openFile", { title: "Python module", filter: "Python files (*.py)" });
      if (path) {
        file.value = path;
        save({ module_path: path, module: null });
      }
    },
  });
  const name = /** @type {HTMLInputElement} */ (
    el("input.input", { type: "text", value: colored.function, placeholder: "build_pattern", name: "pattern_function" })
  );
  name.addEventListener("change", () => save({ function: name.value.trim() }));
  return el("div.colored-jacobians", {}, [
    el("label.form-row.form-check", { title: "Off by default: the gradients of the constraints are then asked for one by one" }, [
      enabled,
      el("span", { text: "Colored Jacobians" }),
    ]),
    el("p.form-hint", {
      text: "When each constraint depends on a few neighbouring variables, the optimizer gets the gradients of the constraints far from activity from a few tens of directional derivatives; those close to activity are still computed exactly.",
    }),
    el("fieldset.colored-jacobians-settings", { disabled: !colored.enabled }, [
      el("div.form-row", {}, [
        el("span.form-label", { text: "Pattern file" }),
        el("div", {}, [
          el("div.input-with-button", {}, [file, browse]),
          colored.module ? el("div.form-hint", { text: `Installed module: ${colored.module}` }) : null,
        ]),
      ]),
      el("label.form-row", {}, [el("span.form-label", { text: "Pattern function" }), name]),
      el("p.form-hint", {
        text: "pattern(variables, constraints) receives the design variables and the inequality constraints as (name, size) pairs and returns a scipy.sparse boolean matrix: True where a constraint depends on a variable.",
      }),
    ]),
  ]);
}
