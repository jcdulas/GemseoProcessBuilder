// @ts-check
// Configuration editors of components, by kind.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { formatExpressions, parseExpressionLines } from "../lib/expressions.js";
import { formatValue, parseValue } from "../lib/table_model.js";

const PYTHON_FILTER = "Python files (*.py)";
const TYPING_DELAY_MS = 600;

/** Component kinds whose ports are computed from their configuration. */
export const INTROSPECTED_KINDS = new Set(["analytic", "python_function", "python_class", "executable"]);

/**
 * Replace some configuration values of a component.
 *
 * @param {any} node
 * @param {object} values
 */
function setConfig(node, values) {
  const config = { ...(app.store.node(node.id)?.config ?? {}), ...values };
  return app.store
    .execute({ type: "setNodeProperties", id: node.id, values: { config }, label_text: "Change configuration" })
    .catch((error) => showError("The configuration could not be changed", error));
}

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
 * A text input committing on change.
 *
 * @param {string} value
 * @param {(value: string) => void} commit
 * @param {string} [placeholder]
 */
function textInput(value, commit, placeholder = "") {
  const input = /** @type {HTMLInputElement} */ (el("input.input.pref-wide", { type: "text", value: value ?? "", placeholder }));
  input.addEventListener("change", () => commit(input.value.trim()));
  return input;
}

/**
 * A module file field with a Browse button.
 *
 * @param {any} node
 */
function moduleFileRow(node) {
  const input = textInput(node.config.module_path ?? "", (value) => setConfig(node, { module_path: value, module: undefined }), "C:\\path\\to\\module.py");
  const browse = el("button.button.bordered", {
    text: "Browse…",
    onClick: async () => {
      const path = await app.api.call("dialog.openFile", { title: "Python module", filter: PYTHON_FILTER });
      if (path) {
        input.value = path;
        setConfig(node, { module_path: path, module: undefined });
      }
    },
  });
  return row("Module file", el("div.input-with-button", {}, [input, browse]), node.config.module ? `Installed module: ${node.config.module}` : undefined);
}

/**
 * An executable wrapper: its reusable descriptor (the graphical editor of
 * wrappers comes with plan 29).
 *
 * @param {any} node
 */
function executableEditor(node) {
  const input = textInput(node.config.descriptor_path ?? "", (value) => setConfig(node, { descriptor_path: value }), "C:\\path\\to\\wrapper.gpbwrap.json");
  const browse = el("button.button.bordered", {
    text: "Browse…",
    onClick: async () => {
      const path = await app.api.call("dialog.openFile", { title: "Wrapper descriptor", filter: "Wrapper descriptors (*.gpbwrap.json)" });
      if (path) {
        input.value = path;
        setConfig(node, { descriptor_path: path });
      }
    },
  });
  return [row("Descriptor", el("div.input-with-button", {}, [input, browse]), "The command, input templates and output rules of the external code.")];
}

/** @param {any} node */
function analyticEditor(node) {
  const area = /** @type {HTMLTextAreaElement} */ (
    el("textarea.input.form-textarea.expressions", { rows: 4, spellcheck: "false", placeholder: "y = x**2 + sin(z)" })
  );
  area.value = formatExpressions(node.config.expressions);
  const errors = el("div.form-error");
  /** @type {any} */
  let timer = null;
  const commit = () => {
    const { expressions, errors: problems } = parseExpressionLines(area.value);
    errors.textContent = problems.join(" ");
    if (!problems.length && JSON.stringify(expressions) !== JSON.stringify(app.store.node(node.id)?.config.expressions ?? {})) {
      setConfig(node, { expressions });
    }
  };
  area.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(commit, TYPING_DELAY_MS);
  });
  area.addEventListener("blur", () => {
    clearTimeout(timer);
    commit();
  });
  return [row("Expressions", el("div", {}, [area, errors]), "One output per line; the inputs are the other symbols.")];
}

/** @param {any} node */
function functionEditor(node) {
  return [
    moduleFileRow(node),
    row("Function", textInput(node.config.function ?? "", (value) => setConfig(node, { function: value }))),
  ];
}

/** @param {any} node */
function classEditor(node) {
  const argumentsBox = el("div.init-args", {}, [el("span.form-hint", { text: "Loading the constructor parameters…" })]);
  const load = async () => {
    if (!node.config.class || !(node.config.module_path || node.config.module)) {
      argumentsBox.replaceChildren(el("span.form-hint", { text: "Select a module and a class." }));
      return;
    }
    let parameters;
    try {
      parameters = await app.api.call("component.initSignature", { config: node.config }, { timeout: 90000 });
    } catch (error) {
      argumentsBox.replaceChildren(el("span.form-error", { text: /** @type {any} */ (error).message }));
      return;
    }
    if (!parameters.length) {
      argumentsBox.replaceChildren(el("span.form-hint", { text: "The constructor has no parameters." }));
      return;
    }
    const current = node.config.init_args ?? {};
    argumentsBox.replaceChildren(
      ...parameters.map((/** @type {any} */ parameter) => {
        const input = /** @type {HTMLInputElement} */ (
          el("input.input.pref-wide", {
            type: "text",
            value: parameter.name in current ? formatValue(current[parameter.name]) : "",
            placeholder: parameter.required ? "required" : `default: ${formatValue(parameter.default)}`,
          })
        );
        input.addEventListener("change", () => {
          const args = { ...(app.store.node(node.id)?.config.init_args ?? {}) };
          const parsed = parseValue(input.value);
          if (parsed.value === null) {
            delete args[parameter.name];
          } else {
            args[parameter.name] = parsed.value;
          }
          setConfig(node, { init_args: args });
        });
        return row(`${parameter.name}${parameter.annotation ? ` (${parameter.annotation})` : ""}`, input);
      }),
    );
  };
  load();
  return [
    moduleFileRow(node),
    row("Class", textInput(node.config.class ?? "", (value) => setConfig(node, { class: value }))),
    el("div.form-subtitle", { text: "Constructor arguments" }),
    argumentsBox,
  ];
}

/**
 * The configuration section of a component, or null for kinds edited elsewhere.
 *
 * @param {any} node
 * @returns {HTMLElement | null}
 */
export function componentConfigSection(node) {
  const editors = { analytic: analyticEditor, python_function: functionEditor, python_class: classEditor, executable: executableEditor };
  const editor = editors[/** @type {keyof editors} */ (node.kind)];
  if (!editor) {
    return null;
  }
  const status = el("div.component-status");
  const showStatus = () => {
    const { state, error } = app.componentStatus.get(node.id);
    status.className = `component-status status-${state}`;
    status.textContent = state === "running" ? "Reading the variables…" : state === "error" ? error : "";
  };
  showStatus();
  const stop = app.componentStatus.onChange((id) => {
    if (!status.isConnected) {
      stop();
    } else if (id === node.id) {
      showStatus();
    }
  });
  return el("div.inspector-section", {}, [
    el("div.section-header", {}, [
      el("h3.section-title", { text: "Configuration" }),
      el("button.button.bordered", {
        text: "Re-read variables",
        title: "Import the component again and update its variables",
        onClick: () => app.api.call("component.introspect", { id: node.id }),
      }),
    ]),
    ...editor(node),
    status,
  ]);
}
