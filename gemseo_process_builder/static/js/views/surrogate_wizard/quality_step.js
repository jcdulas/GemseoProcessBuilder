// @ts-check
// Step 3 of the surrogate wizard: train in the worker (cancellable), then show
// the quality: R² and RMSE on the training data and by cross-validation, the
// predicted-vs-observed chart and the residuals of each output.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { drawPredictedVsObserved, drawResiduals } from "../results/predicted_vs_observed.js";

/**
 * A quality value for the table.
 *
 * @param {number | null | undefined} value
 */
function formatQuality(value) {
  return value === null || value === undefined || !Number.isFinite(value) ? "–" : Number(value).toPrecision(4);
}

/**
 * The name of each component of each output: "f", or "g[0]", "g[1]"…
 *
 * @param {any} result
 * @returns {{output: string, component: number, label: string}[]}
 */
export function outputComponents(result) {
  return result.outputs.flatMap((/** @type {any} */ output) =>
    Array.from({ length: output.size }, (_, component) => ({
      output: output.name,
      component,
      label: output.size > 1 ? `${output.name}[${component}]` : output.name,
    })),
  );
}

export class QualityStep {
  /**
   * @param {HTMLElement} page
   * @param {import("./wizard.js").SurrogateWizard} wizard
   */
  constructor(page, wizard) {
    this.page = page;
    this.wizard = wizard;
    this.training = false;
    /** The output component shown in the charts. */
    this.shown = 0;
    /** Whether the charts show the cross-validated predictions. */
    this.crossValidated = true;
  }

  render() {
    const result = this.wizard.state.result;
    const train = el("button.button.bordered.primary", { text: result ? "Train again" : "Train", onClick: () => this.train() });
    train.toggleAttribute("disabled", this.training);
    const status = this.training
      ? [el("span", { text: "Training in the worker…" }), el("button.button.bordered", { text: "Cancel", onClick: () => app.api.call("surrogates.cancel") })]
      : [];
    this.page.replaceChildren(
      el("div.wizard-form.wizard-wide", {}, [
        el("div.wizard-actions", {}, [train, ...status]),
        result ? this.quality(result) : el("p.form-hint", { text: "Train the surrogate to see how well it predicts the run." }),
      ]),
    );
  }

  async train() {
    const state = this.wizard.state;
    this.training = true;
    state.result = null;
    this.render();
    try {
      state.result = await app.api.call(
        "surrogates.train",
        { run: state.run, inputs: state.inputs, outputs: state.outputs, algorithm: state.algorithm, settings: state.settings, n_folds: state.nFolds },
        { timeout: 3600_000 },
      );
      this.shown = 0;
      if (!state.name) {
        state.name = `${state.outputs.join(" ")} ${state.algorithm.replace(/Regressor$/, "")}`;
      }
    } catch (error) {
      if (/** @type {any} */ (error)?.code !== "cancelled") {
        showError("The surrogate could not be trained", error);
      }
    } finally {
      this.training = false;
      if (this.wizard.step === "quality") {
        this.wizard.show("quality");
      }
    }
  }

  /** @param {any} result */
  quality(result) {
    const components = outputComponents(result);
    const rows = components.map((item, index) => {
      const quality = result.quality[item.output];
      const cells = [quality.r2, quality.rmse, quality.r2_cv, quality.rmse_cv].map((values) => el("td.wizard-number", { text: formatQuality(values[item.component]) }));
      const row = el(`tr.wizard-row${index === this.shown ? ".selected" : ""}`, { title: "Show in the charts", onClick: () => ((this.shown = index), this.render()) }, [
        el("td", { text: item.label }),
        ...cells,
      ]);
      return row;
    });
    const item = components[this.shown] ?? components[0];
    const points = result.points[item.output][item.component];
    const predicted = this.crossValidated ? points.cross_validated : points.learned;
    const toggle = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [
        el("option", { value: "cv", text: "Cross-validated predictions" }),
        el("option", { value: "learned", text: "Predictions of the trained model" }),
      ])
    );
    toggle.value = this.crossValidated ? "cv" : "learned";
    toggle.addEventListener("change", () => {
      this.crossValidated = toggle.value === "cv";
      this.render();
    });
    const scatter = el("div.wizard-chart");
    const residuals = el("div.wizard-chart");
    drawPredictedVsObserved(scatter, { observed: points.observed, predicted, label: item.label });
    drawResiduals(residuals, { observed: points.observed, predicted, label: item.label });
    return el("div", {}, [
      el("p.form-hint", {
        text: `${result.n_samples} samples, ${result.n_folds}-fold cross-validation. R² is 1 for a perfect model; cross-validation tells how well it predicts points it was not trained on.`,
      }),
      el("table.wrapper-table.wizard-quality", {}, [
        el(
          "tr",
          {},
          ["Output", "R²", "RMSE", "R² (cross-validation)", "RMSE (cross-validation)"].map((title) => el("th", { text: title })),
        ),
        ...rows,
      ]),
      el("div.wizard-actions", {}, [el("span", { text: `Charts of ${item.label}:` }), toggle]),
      el("div.wizard-charts", {}, [scatter, residuals]),
    ]);
  }
}
