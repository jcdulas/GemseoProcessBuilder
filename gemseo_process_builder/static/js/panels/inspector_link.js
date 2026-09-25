// @ts-check
// Inspector section of a link clicked on the canvas.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";

/**
 * The stored explicit link behind a coupled variable between two components.
 *
 * @param {import("../lib/scene.js").SceneLink} link
 * @param {any} variable
 */
export function storedLink(link, variable) {
  return Object.values(app.store.state.links).find(
    (candidate) =>
      candidate.source.node === link.from &&
      candidate.source.port === variable.source_port &&
      candidate.target.node === link.to &&
      candidate.target.port === variable.target_port,
  );
}

/**
 * @param {object} command
 * @param {string} failure
 */
async function execute(command, failure) {
  try {
    await app.store.execute(command);
    app.linkFocus.set(null);
  } catch (error) {
    showError(failure, error);
  }
}

/**
 * The checkbox converting a value to the unit of its input: an option of the
 * explicit link, or of the input for a coupling by name.
 *
 * @param {import("../lib/scene.js").SceneLink} link
 * @param {any} variable
 */
export function conversionToggle(link, variable) {
  const box = /** @type {HTMLInputElement} */ (el("input", { type: "checkbox", checked: Boolean(variable.converted) }));
  box.addEventListener("change", () => {
    const stored = variable.explicit ? storedLink(link, variable) : null;
    const command = stored
      ? { type: "setLinkOptions", id: stored.id, convert_units: box.checked }
      : {
          type: "setPortOptions",
          id: link.to,
          port: variable.target_port,
          direction: "in",
          values: { convert_units: box.checked },
        };
    app.store.execute(command).catch((/** @type {unknown} */ error) => showError("The option could not be changed", error));
  });
  return el("label.form-row.form-check", { title: variable.unit.message }, [
    box,
    el("span", { text: `Convert (${variable.unit.message})` }),
  ]);
}

/**
 * @param {import("../lib/scene.js").SceneLink} link
 * @returns {HTMLElement}
 */
export function linkSection(link) {
  const from = app.store.node(link.from);
  const to = app.store.node(link.to);
  const betweenComponents = from?.type === "component" && to?.type === "component";
  const rows = link.variables.map((variable) => {
    const actions = [];
    if (betweenComponents && variable.explicit) {
      const stored = storedLink(link, variable);
      if (stored) {
        actions.push(
          el("button.button.bordered", {
            text: "Delete link",
            onClick: () => execute({ type: "deleteLinks", ids: [stored.id] }, "The link could not be deleted"),
          }),
        );
      }
    } else if (betweenComponents) {
      actions.push(
        el("button.button.bordered", {
          text: "Make explicit",
          title: "Keep this coupling even if a variable is renamed",
          onClick: () =>
            execute(
              {
                type: "addLink",
                source: { node: link.from, port: variable.source_port },
                target: { node: link.to, port: variable.target_port },
              },
              "The link could not be created",
            ),
        }),
      );
    }
    if (betweenComponents && variable.unit?.status === "convert") {
      actions.push(conversionToggle(link, variable));
    }
    return el("div.link-variable", {}, [
      el("div.link-variable-name", { text: variable.name }),
      el("div.form-hint", {
        text: `${from?.name}.${variable.source_port || variable.name} → ${to?.name}.${variable.target_port || variable.name} · ${
          variable.explicit ? "explicit link" : "coupled by name"
        }`,
      }),
      ...actions,
    ]);
  });
  const hint = betweenComponents
    ? ""
    : "Open the containers to edit the links of their components. A coupling by name disappears when a variable is renamed or its component isolated.";
  return el("div.inspector-section", {}, [
    el("h3.section-title", { text: link.feedback ? "Feedback coupling" : "Coupling" }),
    el("p", { text: `${from?.name} → ${to?.name}` }),
    ...rows,
    hint ? el("p.form-hint", { text: hint }) : null,
  ]);
}
