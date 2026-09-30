// @ts-check
// Step 2 of the surrogate wizard: the GEMSEO regression model and its settings
// (a form generated from their schema, as for the drivers), and the number of
// folds of the cross-validation.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { settingsForm } from "../../forms/schema_form.js";

/** The models offered first: they suit small DOEs. */
const COMMON = ["RBFRegressor", "GaussianProcessRegressor", "PolynomialRegressor"];

export class AlgorithmStep {
  /**
   * @param {HTMLElement} page
   * @param {import("./wizard.js").SurrogateWizard} wizard
   */
  constructor(page, wizard) {
    this.page = page;
    this.wizard = wizard;
    /** @type {any[] | null} */
    this.algorithms = null;
    this.formBox = el("div");
  }

  async render() {
    if (!this.algorithms) {
      try {
        const listed = await app.api.call("algorithms.list", { kind: "regression" }, { timeout: 120_000 });
        this.algorithms = [...listed].sort((a, b) => {
          const rank = (/** @type {any} */ item) => (COMMON.includes(item.name) ? COMMON.indexOf(item.name) : COMMON.length);
          return rank(a) - rank(b) || a.name.localeCompare(b.name);
        });
      } catch (error) {
        showError("The regression models could not be listed", error);
        return;
      }
    }
    this.draw();
  }

  draw() {
    const state = this.wizard.state;
    const algorithms = /** @type {any[]} */ (this.algorithms);
    const select = /** @type {HTMLSelectElement} */ (
      el(
        "select.select",
        {},
        algorithms.map((item) => el("option", { value: item.name, text: item.name })),
      )
    );
    select.value = state.algorithm;
    select.addEventListener("change", () => {
      state.algorithm = select.value;
      state.settings = {};
      this.wizard.changed();
    });
    const description = algorithms.find((item) => item.name === state.algorithm)?.description ?? "";
    const folds = /** @type {HTMLInputElement} */ (el("input.input", { type: "number", min: "2", max: "20", step: "1" }));
    folds.value = String(state.nFolds);
    folds.addEventListener("change", () => {
      state.nFolds = Math.max(2, Math.round(Number(folds.value) || 5));
      folds.value = String(state.nFolds);
      this.wizard.changed();
    });
    this.page.replaceChildren(
      el("div.wizard-form", {}, [
        el("h3.section-title", { text: "Regression model" }),
        el("label.form-row", {}, [el("span.form-label", { text: "Model" }), select]),
        description ? el("p.form-hint", { text: description }) : null,
        el("h3.section-title", { text: "Settings" }),
        this.formBox,
        el("h3.section-title", { text: "Cross-validation" }),
        el("label.form-row", {}, [el("span.form-label", { text: "Folds" }), folds]),
        el("p.form-hint", { text: "The samples are split in this many folds; each fold is predicted by a model trained on the others." }),
      ]),
    );
    this.drawSettings();
  }

  async drawSettings() {
    const state = this.wizard.state;
    const name = state.algorithm;
    try {
      const schema = await app.api.call("settings.schema", { kind: "regression", name }, { timeout: 120_000 });
      if (name !== state.algorithm) {
        return;
      }
      const form = settingsForm({
        schema,
        kind: "regression",
        name,
        settings: state.settings,
        onChange: async (next) => {
          state.settings = next;
          const errors = await app.api.call("settings.validate", { kind: "regression", name, settings: next });
          form.showErrors(errors);
          this.wizard.state.result = null;
        },
      });
      this.formBox.replaceChildren(form.element);
    } catch (error) {
      this.formBox.replaceChildren(el("p.form-error", { text: `The settings could not be read: ${/** @type {any} */ (error).message}` }));
    }
  }
}
