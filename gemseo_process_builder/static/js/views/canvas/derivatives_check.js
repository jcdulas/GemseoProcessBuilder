// @ts-check
// Check derivatives: the derivatives of a node compared with finite differences,
// as a matrix of outputs by inputs.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { openModal } from "../../components/modal.js";

const ORIGIN_TEXTS = {
  exact: "computed exactly by the disciplines",
  approximated: "approximated by finite differences in some disciplines",
  missing: "missing in some disciplines",
};

/** "2.7e-9" */
function formatError(/** @type {number} */ error) {
  return error === 0 ? "0" : error.toExponential(1);
}

/**
 * The matrix of the errors, one row per output and one column per input.
 *
 * @param {import("../../services/derivatives.js").DerivativeCheck} result
 */
function matrix(result) {
  const byPair = new Map(result.pairs.map((pair) => [`${pair.output}\u0000${pair.input}`, pair]));
  return el("table.derivatives-table", {}, [
    el("tr", {}, [el("th"), ...result.inputs.map((input) => el("th", { text: input }))]),
    ...result.outputs.map((output) =>
      el("tr", {}, [
        el("th", { text: output }),
        ...result.inputs.map((input) => {
          const pair = byPair.get(`${output}\u0000${input}`);
          if (!pair) {
            return el("td.derivatives-none", { text: "—", title: "Not differentiated" });
          }
          return el(`td.${pair.ok ? "derivatives-ok" : "derivatives-bad"}`, {
            text: `${pair.ok ? "✓" : "✗"} ${formatError(pair.error)}`,
            title: `d${output}/d${input}: largest value ${pair.size.toPrecision(3)}, error ${formatError(pair.error)} (relative, tolerance ${result.tolerance})`,
          });
        }),
      ]),
    ),
  ]);
}

/**
 * The result of a check.
 *
 * @param {import("../../services/derivatives.js").DerivativeCheck} result
 */
function report(result) {
  const bad = result.pairs.filter((pair) => !pair.ok).length;
  const verdict = result.ok
    ? `The ${result.pairs.length} derivatives match the finite differences.`
    : `${bad} of the ${result.pairs.length} derivatives differ from the finite differences.`;
  return el("div.derivatives-report", {}, [
    el(`p.derivatives-verdict.${result.ok ? "verdict-ok" : "verdict-bad"}`, { text: verdict }),
    el("p.form-hint", {
      text: `${result.discipline}: derivatives ${ORIGIN_TEXTS[/** @type {keyof ORIGIN_TEXTS} */ (result.origin)] ?? result.origin}; linearization ${result.mode || "auto"}. Compared with centered finite differences; relative tolerance ${result.tolerance}. ${result.seconds} s.`,
    }),
    el("div.derivatives-scroll", {}, [matrix(result)]),
    result.limited ? el("p.form-hint", { text: "Only the first 40 inputs and outputs are checked." }) : null,
    ...result.notes.map((note) => el("p.form-hint", { text: note })),
  ]);
}

/**
 * Check the derivatives of a node and show the result.
 *
 * @param {string} id
 */
export function openDerivativesCheck(id) {
  const node = app.store.node(id);
  const what =
    node?.type === "driver"
      ? `the objective and constraints of ${node.name} with respect to its design variables, through its whole process`
      : `the outputs of ${node?.name} with respect to its inputs`;
  const body = el("div.derivatives-body", {}, [el("p", { text: `Differentiating ${what}…` })]);
  openModal({ title: `Check derivatives — ${node?.name}`, body });
  app.derivatives
    .check(id)
    .then((result) => body.replaceChildren(report(result)))
    .catch((/** @type {any} */ error) =>
      body.replaceChildren(el("p.derivatives-verdict.verdict-bad", { text: error?.message ?? String(error) })),
    );
}
