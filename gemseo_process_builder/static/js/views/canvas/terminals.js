// @ts-check
// The start and the end of a workflow: the inputs of the level, whose values
// are typed here once for every node using them, and its results.
import { app } from "../../app.js";
import { openContextMenu } from "../../components/context_menu.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { showToast } from "../../components/toast.js";
import { formatValue, parseValue } from "../../lib/table_model.js";

/**
 * The names of nodes, for "used by" and "computed by".
 *
 * @param {string[]} ids
 */
function nodeNames(ids) {
  return ids.map((id) => app.store.node(id)?.name ?? id).join(", ");
}

/**
 * Show more outputs at the end of the level, or fewer.
 *
 * @param {string} level
 * @param {string[]} names
 */
function setExposed(level, names) {
  return app.store
    .execute({ type: "setNodeProperties", id: level, values: { exposed_outputs: names }, label_text: "Change the results" })
    .catch((/** @type {unknown} */ error) => showError("The results could not be changed", error));
}

/**
 * The input of a value, sent when it is left or on Enter.
 *
 * @param {string} level
 * @param {import("../../lib/scene.js").WorkflowVariable} variable
 */
function valueInput(level, variable) {
  const input = /** @type {HTMLInputElement} */ (el("input.input.terminal-value", { spellcheck: "false" }));
  const shown = variable.text ?? formatValue(variable.value);
  input.value = shown;
  const error = el("div.form-error");
  const send = () => {
    if (input.value === shown) {
      return;
    }
    const { value, error: message } = parseValue(input.value);
    error.textContent = message ?? "";
    if (message) {
      return;
    }
    app.api
      .call("workflow.setInput", { level, name: variable.name, value, text: input.value.trim() || null })
      .catch((/** @type {unknown} */ failure) => showError(`${variable.name} could not be changed`, failure));
  };
  input.addEventListener("change", send);
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      input.blur();
    }
  });
  return el("div", {}, [input, error]);
}

/**
 * The inspector of the start (the inputs) or the end (the results) of a level.
 *
 * @param {"start" | "end"} terminal
 * @param {string} level
 * @returns {HTMLElement}
 */
export function terminalSection(terminal, level) {
  const io = app.canvas?.io;
  if (!io) {
    return el("div.inspector-section", {}, [el("p.placeholder", { text: "Reading the variables…" })]);
  }
  if (terminal === "start") {
    return el("div.inspector-section", {}, [
      el("h3.section-title", { text: "Workflow inputs" }),
      el("p.form-hint", {
        text: "The values the workflow starts from: the inputs no node computes and no driver sets. A value typed here goes to every node using it.",
      }),
      io.inputs.length
        ? el("table.terminal-table", {}, [
            el("tr", {}, [el("th", { text: "Input" }), el("th", { text: "Value" }), el("th", { text: "Used by" })]),
            ...io.inputs.map((variable) =>
              el("tr", {}, [
                el("td.terminal-variable", { text: variable.unit ? `${variable.name} [${variable.unit}]` : variable.name }),
                el("td", {}, [valueInput(level, variable)]),
                el("td.form-hint", { text: nodeNames(variable.nodes) }),
              ]),
            ),
          ])
        : el("p.placeholder", { text: "No input: every variable is computed by a node or set by a driver." }),
    ]);
  }
  const exposed = /** @type {string[]} */ (app.store.node(level)?.exposed_outputs ?? []);
  const picker = /** @type {HTMLSelectElement} */ (
    el("select.select", {}, [
      el("option", { value: "", text: io.others.length ? "Show another output…" : "No other output" }),
      ...io.others.map((variable) => el("option", { value: variable.name, text: `${variable.name} (${nodeNames(variable.nodes)})` })),
    ])
  );
  picker.disabled = !io.others.length;
  picker.addEventListener("change", () => picker.value && setExposed(level, [...exposed, picker.value]));
  return el("div.inspector-section", {}, [
    el("h3.section-title", { text: "Workflow results" }),
    el("p.form-hint", {
      text: "The outputs no node of the workflow uses, and the ones you choose to show. Drag a node onto the end to show more of its outputs.",
    }),
    io.outputs.length
      ? el("table.terminal-table", {}, [
          el("tr", {}, [el("th", { text: "Result" }), el("th", { text: "Computed by" }), el("th")]),
          ...io.outputs.map((variable) =>
            el("tr", {}, [
              el("td.terminal-variable", { text: variable.unit ? `${variable.name} [${variable.unit}]` : variable.name }),
              el("td.form-hint", { text: nodeNames(variable.nodes) }),
              el("td", {}, [
                variable.final
                  ? el("span.form-hint", { text: "final", title: "No node of the workflow uses it" })
                  : el("button.table-button", {
                      text: "×",
                      title: "Do not show it at the end",
                      onClick: () => setExposed(level, exposed.filter((name) => name !== variable.name)),
                    }),
              ]),
            ]),
          ),
        ])
      : el("p.placeholder", { text: "No result yet." }),
    el("div.terminal-picker", {}, [picker]),
  ]);
}

/**
 * After a node is dragged onto the end: choose which of its outputs to show.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 * @param {string} node
 * @param {number} x
 * @param {number} y
 */
export function chooseOutputsForEnd(canvas, node, x, y) {
  const level = canvas.level;
  const exposed = /** @type {string[]} */ (app.store.node(level)?.exposed_outputs ?? []);
  // The node dragged may be a container: the outputs of the components inside it.
  const inside = (/** @type {string} */ id) => {
    for (let current = id; current; current = app.store.node(current)?.parent) {
      if (current === node) {
        return true;
      }
    }
    return false;
  };
  const candidates = (canvas.io?.others ?? []).filter((variable) => variable.nodes.some(inside));
  if (!candidates.length) {
    showToast({ title: `Every result of ${app.store.node(node)?.name} is at the end`, level: "info" });
    return;
  }
  openContextMenu(x, y, [
    ...candidates.map((variable) => ({
      label: `Show ${variable.name} at the end`,
      run: () => setExposed(level, [...exposed, variable.name]),
    })),
    { separator: true },
    { label: "Show all of them", run: () => setExposed(level, [...exposed, ...candidates.map((variable) => variable.name)]) },
  ]);
}
