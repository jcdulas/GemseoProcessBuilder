// @ts-check
// A discipline class in a Python file, from the inspector: create the file and
// its class, edit its inputs and outputs in a table (the application rewrites
// their block in the class), open the file in the user's editor for the
// computation. The component follows the file when it is saved.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { openModal } from "../components/modal.js";
import { createFileExample } from "./component_examples.js";
import {
  checkVariables,
  classNameFor,
  fileNameFor,
  formatDefault,
  formatShape,
  freeName,
  parseDefault,
  parseShape,
} from "../lib/discipline_variables.js";

/** @typedef {import("../lib/discipline_variables.js").TableVariable} TableVariable */

/**
 * An editable table of inputs and outputs. An input is an array: its shape,
 * its type and its default value, one number filling it or every element.
 *
 * @param {TableVariable[]} initial
 * @param {(variables: TableVariable[]) => void} onChange - Called with valid variables only.
 */
function variablesTable(initial, onChange) {
  /** @type {TableVariable[]} */
  let variables = initial.map((variable) => ({ dtype: "float", shape: [1], values: null, fill: null, ...variable }));
  const body = el("div.file-variables-list");
  const errors = el("div.form-error");
  const changed = () => {
    const problems = checkVariables(variables);
    errors.textContent = problems.join(" ");
    if (!problems.length) {
      onChange(variables.map((variable) => ({ ...variable })));
    }
  };
  /**
   * A text field committing a parsed value.
   *
   * @param {string} value
   * @param {{placeholder?: string, title?: string, disabled?: boolean}} options
   * @param {(text: string) => string} commit - Returns an error, or "".
   */
  const field = (value, options, commit) => {
    const input = /** @type {HTMLInputElement} */ (el("input.input", { type: "text", value, spellcheck: "false", ...options }));
    input.addEventListener("change", () => {
      const error = commit(input.value.trim());
      input.setCustomValidity(error);
      input.reportValidity();
      if (!error) {
        changed();
      }
    });
    return input;
  };
  const render = () => {
    body.replaceChildren(
      ...variables.map((variable, index) => {
        const isInput = variable.direction === "in";
        const name = field(variable.name, {}, (text) => {
          variable.name = text;
          return "";
        });
        const direction = /** @type {HTMLSelectElement} */ (
          el("select.select", {}, [
            el("option", { value: "in", text: "in", selected: isInput }),
            el("option", { value: "out", text: "out", selected: !isInput }),
          ])
        );
        direction.addEventListener("change", () => {
          variable.direction = /** @type {"in" | "out"} */ (direction.value);
          if (variable.direction === "in" && !variable.values && variable.fill === null) {
            variable.fill = 0;
          }
          render();
          changed();
        });
        const shape = field(formatShape(variable.shape), { disabled: !isInput, title: "Sizes like 3, 100000 or 3x4" }, (text) => {
          const parsed = parseShape(text);
          if (!parsed.error) {
            variable.shape = /** @type {number[]} */ (parsed.value);
            // Values typed one by one no longer fit: the first one fills the array.
            if (variable.values && variable.values.length !== variable.shape.reduce((a, b) => a * b, 1)) {
              variable.fill = variable.values[0];
              variable.values = null;
              render();
            }
          }
          return parsed.error;
        });
        const dtype = /** @type {HTMLSelectElement} */ (
          el(
            "select.select",
            { disabled: !isInput },
            ["float", "int", "complex"].map((kind) => el("option", { value: kind, text: kind, selected: (variable.dtype ?? "float") === kind })),
          )
        );
        dtype.addEventListener("change", () => {
          variable.dtype = /** @type {"float" | "int" | "complex"} */ (dtype.value);
          changed();
        });
        const value = field(
          isInput ? formatDefault(variable) : "",
          {
            placeholder: "0.5, or 1, 2, 3",
            title: "One value fills the array; or one value per element",
          },
          (text) => {
            const parsed = parseDefault(text, variable.shape);
            if (!parsed.error) {
              variable.values = parsed.values;
              variable.fill = parsed.fill;
            }
            return parsed.error;
          },
        );
        const remove = el("button.table-button", {
          text: "×",
          title: "Remove",
          onClick: () => {
            variables.splice(index, 1);
            render();
            changed();
          },
        });
        // Two lines: the variable, then the array of an input.
        const caption = (/** @type {string} */ text, /** @type {HTMLElement} */ control) => el("label.mini-field", {}, [el("span", { text }), control]);
        return el("div.file-variable", {}, [
          el("div.file-variable-head", {}, [name, direction, remove]),
          isInput ? el("div.file-variable-array", {}, [caption("Shape", shape), caption("Type", dtype), caption("Default", value)]) : null,
        ]);
      }),
    );
  };
  const add = (/** @type {"in" | "out"} */ direction) => () => {
    variables.push({
      name: freeName(direction === "in" ? "x" : "y", variables),
      direction,
      dtype: "float",
      shape: [1],
      values: null,
      fill: direction === "in" ? 0 : null,
    });
    render();
    changed();
    /** @type {HTMLInputElement | null} */ (body.querySelector(".file-variable:last-child input"))?.select();
  };
  render();
  return {
    element: el("div.file-variables", {}, [
      body,
      errors,
      el("div.inspector-actions", {}, [
        el("button.button.bordered.small", { text: "+ Input", onClick: add("in") }),
        el("button.button.bordered.small", { text: "+ Output", onClick: add("out") }),
      ]),
    ]),
    /** The variables, if they are valid. */
    value: () => (checkVariables(variables).length ? null : variables.map((variable) => ({ ...variable }))),
  };
}

/** The folder of the project, to suggest where to create the file. */
function projectFolder() {
  const path = app.projectTitle.current?.path ?? "";
  return path ? path.replace(/[\\/][^\\/]*$/, "") : "";
}

/**
 * Create a Python file with a discipline class for a component.
 *
 * @param {any} node
 */
export function openNewFileDialog(node) {
  const className = /** @type {HTMLInputElement} */ (el("input.input.pref-wide", { type: "text", value: classNameFor(node.name) }));
  const description = /** @type {HTMLInputElement} */ (
    el("input.input.pref-wide", { type: "text", placeholder: "What it computes, like: The area of a wing" })
  );
  const table = variablesTable(
    [
      { name: "x", direction: "in", dtype: "float", shape: [1], values: null, fill: 1 },
      { name: "y", direction: "out" },
    ],
    () => {},
  );
  const error = el("div.form-error");
  const body = el("div.new-file", {}, [
    el("p.form-hint", {
      text: "The application writes a Python file with a GEMSEO discipline class: its inputs, with their default values, and its outputs. You then write the computation in your code editor.",
    }),
    el("div.form-row", {}, [el("span.form-label", { text: "Class" }), className]),
    el("div.form-row", {}, [el("span.form-label", { text: "Description" }), description]),
    el("div.form-subtitle", { text: "Inputs and outputs" }),
    table.element,
    error,
  ]);
  openModal({
    title: `New Python file for ${node.name}`,
    body,
    buttons: [
      { label: "Cancel" },
      {
        label: "Choose the file…",
        primary: true,
        onClick: async () => {
          const variables = table.value();
          if (!variables) {
            error.textContent = "Correct the variables first.";
            return false;
          }
          const folder = projectFolder();
          const name = fileNameFor(className.value.trim() || classNameFor(node.name));
          const path = await app.api.call(
            "dialog.saveFile",
            { title: "New Python file", filter: "Python files (*.py)", start: folder ? `${folder}/${name}` : name },
            { timeout: 24 * 3600 * 1000 },
          );
          if (!path) {
            return false;
          }
          try {
            await app.api.call("pythonFile.create", {
              id: node.id,
              path,
              class_name: className.value.trim(),
              description: description.value.trim(),
              variables,
            });
          } catch (failure) {
            error.textContent = String(/** @type {any} */ (failure)?.message ?? failure);
            return false;
          }
          app.api.call("pythonFile.open", { id: node.id }).catch((failure) => showError("The file could not be opened", failure));
          return true;
        },
      },
    ],
  });
}

/**
 * The part of the inspector of a Python class component about its file.
 *
 * @param {any} node
 * @returns {HTMLElement}
 */
export function disciplineFileSection(node) {
  const box = el("div.discipline-file");
  if (!node.config.module_path && !node.config.module) {
    box.append(
      el("div.file-callout", {}, [
        el("div", { text: "Write a new discipline in Python" }),
        el("div.form-hint", { text: "Create its file and class with its inputs and outputs here, then write the computation in your code editor." }),
        el("div.inspector-actions", {}, [
          el("button.button.primary.small", { text: "New Python file…", onClick: () => openNewFileDialog(node) }),
          el("button.button.bordered.small", {
            text: "Create an example…",
            title: "A working class computing the area of a wing, in a file you choose",
            onClick: () => createFileExample(node),
          }),
        ]),
        el("div.form-hint", { text: "Or choose an existing file and class below." }),
      ]),
    );
    return box;
  }
  if (!node.config.module_path) {
    return box; // An installed module: nothing to edit here.
  }
  const table = el("div", {}, [el("span.form-hint", { text: "Reading the file…" })]);
  const open = el("button.button.bordered.small", {
    text: "Open in editor",
    title: "Write the computation in your code editor (Tools > Preferences > Code editor)",
    onClick: () => app.api.call("pythonFile.open", { id: node.id }).catch((error) => showError("The file could not be opened", error)),
  });
  box.append(el("div.inspector-actions", {}, [open, el("span.form-hint", { text: "Saving the file updates the component." })]), table);
  const load = () =>
    app.api
      .call("pythonFile.variables", { id: node.id })
      .then((/** @type {any} */ result) => {
        if (result.error) {
          table.replaceChildren(el("div.form-error", { text: result.error }));
        } else if (!result.managed) {
          table.replaceChildren(el("div.form-hint", { text: "The inputs and outputs of this class are declared in its code." }));
        } else {
          const editor = variablesTable(result.variables, (variables) =>
            app.api
              .call("pythonFile.setVariables", { id: node.id, variables })
              .catch((error) => showError("The variables could not be written", error)),
          );
          table.replaceChildren(
            el("div.form-subtitle", { text: "Inputs and outputs" }),
            el("div.form-hint", { text: "Written in the class; read them in _run with input_data[\"name\"] and return the outputs." }),
            editor.element,
          );
        }
      })
      .catch((error) => table.replaceChildren(el("div.form-error", { text: error.message })));
  load();
  // Saved in the editor: show the variables again (unless being edited here).
  const unsubscribe = app.api.on("pythonFile.changed", (/** @type {any} */ event) => {
    if (!box.isConnected) {
      unsubscribe?.();
    } else if (event.nodes.includes(node.id) && !box.contains(document.activeElement)) {
      load();
    }
  });
  return box;
}
