// @ts-check
// "Create an example" in the inspector of a component not set up yet: a
// working example of its kind, written where the user chooses
// (`componentExample.create`), or for a surrogate, example samples, then a
// surrogate trained on them as the Build surrogate wizard does.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";
import { showToast } from "../components/toast.js";

/** What each example is, and where it is written. */
const EXAMPLES = {
  python_function: {
    title: "Write a Python function",
    text: "Its arguments are the inputs, the names it returns the outputs. The example computes the area of a wing from its span and chord.",
    file: "wing_area.py",
    filter: "Python files (*.py)",
  },
  python_class: {
    title: "",
    text: "",
    file: "wing.py",
    filter: "Python files (*.py)",
  },
  executable: {
    title: "Wrap an external program",
    text: "The example is a small solver with its input template and its wrapper descriptor, written in the folder you choose.",
    file: "solver.gpbwrap.json",
    filter: "Wrapper descriptors (*.gpbwrap.json)",
  },
};

/** The folder of the project, to suggest where to write the example. */
function projectFolder() {
  const path = app.projectTitle.current?.path ?? "";
  return path ? path.replace(/[\\/][^\\/]*$/, "") : "";
}

/**
 * Write the example of a component in a file the user chooses.
 *
 * @param {any} node
 */
export async function createFileExample(node) {
  const example = EXAMPLES[/** @type {keyof EXAMPLES} */ (node.kind)];
  const folder = projectFolder();
  let path;
  try {
    path = await app.api.call(
      "dialog.saveFile",
      { title: "Where to write the example", filter: example.filter, start: folder ? `${folder}/${example.file}` : example.file },
      { timeout: 24 * 3600 * 1000 },
    );
    if (!path) {
      return;
    }
    const { files } = await app.api.call("componentExample.create", { id: node.id, path });
    showToast({ title: "Example created", message: files.join("\n") });
    if (node.kind !== "executable") {
      app.api.call("pythonFile.open", { id: node.id }).catch((error) => showError("The file could not be opened", error));
    }
  } catch (error) {
    showError("The example could not be created", error);
  }
}

/**
 * Example samples of a wing, a surrogate trained on them, used by the component.
 *
 * @param {any} node
 * @param {HTMLElement} status - Shows the progress.
 */
export async function createSurrogateExample(node, status) {
  try {
    status.textContent = "Writing example samples of a wing…";
    const example = await app.api.call("componentExample.samples");
    status.textContent = "Training the surrogate (radial basis functions)…";
    const result = await app.api.call(
      "surrogates.train",
      { run: example.run, inputs: example.inputs, outputs: example.outputs, algorithm: example.algorithm },
      { timeout: 600_000 },
    );
    const names = new Set((await app.api.call("surrogates.list")).map((/** @type {any} */ entry) => entry.name));
    let name = example.name;
    for (let index = 2; names.has(name); index += 1) {
      name = `${example.name} ${index}`;
    }
    await app.api.call("surrogates.save", {
      trained: result.trained,
      name,
      run: example.run,
      algorithm: example.algorithm,
      result,
      node: node.id,
    });
    status.textContent = "";
    showToast({ title: `Surrogate ${name} created`, message: "Trained on the example samples, shown in the Runs panel." });
  } catch (error) {
    status.textContent = "";
    showError("The example could not be created", error);
  }
}

/**
 * A callout offering an example, for a component not set up yet.
 *
 * @param {string} title
 * @param {string} text
 * @param {HTMLElement[]} buttons
 */
function callout(title, text, buttons) {
  return el("div.file-callout", {}, [el("div", { text: title }), el("div.form-hint", { text }), el("div.inspector-actions", {}, buttons)]);
}

/**
 * The "Create an example" callout of a component, or `null` once it is set up.
 *
 * @param {any} node
 * @returns {HTMLElement | null}
 */
export function exampleCallout(node) {
  const config = node.config ?? {};
  if (node.kind === "python_function" && !config.module_path && !config.module && !config.function) {
    const example = EXAMPLES.python_function;
    return callout(example.title, example.text, [
      el("button.button.primary.small", { text: "Create an example…", title: "Write a working example in a file you choose", onClick: () => createFileExample(node) }),
    ]);
  }
  if (node.kind === "executable" && !config.descriptor_path && !config.spec) {
    const example = EXAMPLES.executable;
    return callout(example.title, example.text, [
      el("button.button.primary.small", { text: "Create an example…", onClick: () => createFileExample(node) }),
    ]);
  }
  if (node.kind === "surrogate" && !config.surrogate_id && !config.model_path) {
    const status = el("div.form-hint");
    const box = callout(
      "Replace a costly computation by a surrogate",
      "A surrogate is trained on the results of a DOE run. The example writes samples of the area of a wing as a run of the project, trains a surrogate on them and uses it.",
      [el("button.button.primary.small", { text: "Create an example", onClick: () => createSurrogateExample(node, status) })],
    );
    box.append(status);
    return box;
  }
  return null;
}
