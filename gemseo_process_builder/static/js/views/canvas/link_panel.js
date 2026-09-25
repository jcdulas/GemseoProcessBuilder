// @ts-check
// The floating panel of a link of the canvas (like n8n): the variables it
// carries, the output of the source on the left and the input of the target on
// the right. It also links the variables of two components at once.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { linkCompatibility } from "../../lib/link_compat.js";
import { currentMapping, mappingCommands } from "../../lib/link_mapping.js";
import { conversionToggle, storedLink } from "../../panels/inspector_link.js";

/** @type {HTMLElement | null} */
let panel = null;

export function closeLinkPanel() {
  panel?.remove();
  panel = null;
  document.removeEventListener("pointerdown", onOutside, true);
  document.removeEventListener("keydown", onKey, true);
}

/** @param {Event} event */
function onOutside(event) {
  if (panel && !panel.contains(/** @type {Node} */ (event.target))) {
    closeLinkPanel();
  }
}

/** @param {KeyboardEvent} event */
function onKey(event) {
  if (event.key === "Escape") {
    event.stopPropagation();
    closeLinkPanel();
  }
}

/**
 * Show a panel next to a point of the window, kept inside it.
 *
 * @param {HTMLElement} content
 * @param {number} x
 * @param {number} y
 */
export function show(content, x, y) {
  closeLinkPanel();
  panel = el("div.link-panel", {}, [content]);
  document.body.append(panel);
  const box = panel.getBoundingClientRect();
  panel.style.left = `${Math.max(8, Math.min(x + 12, window.innerWidth - box.width - 8))}px`;
  panel.style.top = `${Math.max(8, Math.min(y + 12, window.innerHeight - box.height - 8))}px`;
  // The click opening the panel must not close it.
  setTimeout(() => {
    document.addEventListener("pointerdown", onOutside, true);
    document.addEventListener("keydown", onKey, true);
  });
}

/**
 * A port of a node, with its unit.
 *
 * @param {any} node
 * @param {string} name
 * @param {"in" | "out"} direction
 */
function portText(node, name, direction) {
  const port = (node?.ports ?? []).find((/** @type {any} */ item) => item.local_name === name && item.direction === direction);
  return port?.unit ? `${name} [${port.unit}]` : name;
}

/**
 * @param {string} title
 * @param {Node[]} content
 */
export function frame(title, content) {
  return el("div", {}, [el("div.link-panel-title", {}, [el("span", { text: title }), el("button.link-panel-close", { text: "×", title: "Close", onClick: closeLinkPanel })]), ...content]);
}

/**
 * The panel of a link: its variables, with their actions.
 *
 * @param {import("../../lib/scene.js").SceneLink} link
 * @param {number} x - Where the link was clicked, in window coordinates.
 * @param {number} y
 */
export function openLinkPanel(link, x, y) {
  const from = app.store.node(link.from);
  const to = app.store.node(link.to);
  const components = from?.type === "component" && to?.type === "component";
  const rows = link.variables.map((/** @type {any} */ variable) => {
    const actions = [];
    const stored = variable.explicit ? storedLink(link, variable) : null;
    if (components && stored) {
      actions.push(
        el("button.table-button", {
          text: "×",
          title: "Delete this explicit link",
          onClick: () =>
            app.store
              .execute({ type: "deleteLinks", ids: [stored.id] })
              .then(closeLinkPanel)
              .catch((/** @type {unknown} */ error) => showError("The link could not be deleted", error)),
        }),
      );
    }
    const conversion = components && variable.unit?.status === "convert" ? conversionToggle(link, variable) : null;
    return el("tr", {}, [
      el("td", { text: portText(from, variable.source_port || variable.name, "out") }),
      el("td.link-panel-arrow", { text: variable.converted ? "⇢" : "→", title: variable.unit?.message ?? "" }),
      el("td", { text: portText(to, variable.target_port || variable.name, "in") }),
      el("td.form-hint", { text: variable.explicit ? "link" : "by name" }),
      el("td", {}, [conversion, ...actions]),
    ]);
  });
  const content = [
    el("table.link-panel-table", {}, [
      el("tr", {}, [el("th", { text: `Outputs of ${from?.name}` }), el("th"), el("th", { text: `Inputs of ${to?.name}` }), el("th"), el("th")]),
      ...rows,
    ]),
  ];
  if (components) {
    content.push(el("button.button.bordered", { text: "Link other variables…", onClick: () => openConnectPanel(link.from, link.to, x, y) }));
  } else {
    content.push(el("p.form-hint", { text: "Open the containers to link the variables of their components." }));
  }
  show(frame(`${from?.name} → ${to?.name}${link.feedback ? " (feedback)" : ""}`, content), x, y);
}

/**
 * The panel linking the outputs of a component to the inputs of another.
 *
 * @param {string} sourceId
 * @param {string} targetId
 * @param {number} x
 * @param {number} y
 */
export function openConnectPanel(sourceId, targetId, x, y) {
  const source = app.store.node(sourceId);
  const target = app.store.node(targetId);
  if (source?.type !== "component" || target?.type !== "component") {
    show(frame("Link variables", [el("p.form-hint", { text: "Open the containers to link the variables of their components." })]), x, y);
    return;
  }
  const outputs = (source.ports ?? []).filter((/** @type {any} */ port) => port.direction === "out");
  const inputs = (target.ports ?? []).filter((/** @type {any} */ port) => port.direction === "in");
  const links = Object.values(app.store.state.links);
  const before = currentMapping(
    links,
    sourceId,
    targetId,
    inputs.map((/** @type {any} */ port) => port.local_name),
    outputs.map((/** @type {any} */ port) => port.local_name),
  );
  /** @type {Record<string, string>} */
  const chosen = {};
  const rows = inputs.map((/** @type {any} */ input) => {
    const current = before[input.local_name];
    chosen[input.local_name] = current.output;
    const select = /** @type {HTMLSelectElement} */ (
      el("select.select", {}, [
        el("option", { value: "", text: current.other ? `(from ${app.store.node(current.other)?.name ?? current.other})` : "—" }),
        ...outputs.map((/** @type {any} */ output) => {
          const compat = linkCompatibility(output, input);
          return el("option", { value: output.local_name, text: portText(source, output.local_name, "out"), disabled: !compat.ok, title: compat.reason });
        }),
      ])
    );
    select.value = current.output;
    select.addEventListener("change", () => (chosen[input.local_name] = select.value));
    return el("tr", {}, [
      el("td", {}, [select]),
      el("td.link-panel-arrow", { text: "→" }),
      el("td", { text: portText(target, input.local_name, "in") }),
      el("td.form-hint", { text: current.explicit && !current.other ? "link" : current.output ? "by name" : "" }),
    ]);
  });
  const apply = async () => {
    const commands = mappingCommands(links, sourceId, targetId, before, chosen);
    if (!commands.length) {
      closeLinkPanel();
      return;
    }
    try {
      await app.store.executeMany(commands, "Link variables");
      closeLinkPanel();
    } catch (error) {
      showError("The variables could not be linked", error);
    }
  };
  show(
    frame(`Link ${source.name} → ${target.name}`, [
      inputs.length
        ? el("table.link-panel-table", {}, [
            el("tr", {}, [el("th", { text: `Outputs of ${source.name}` }), el("th"), el("th", { text: `Inputs of ${target.name}` }), el("th")]),
            ...rows,
          ])
        : el("p.form-hint", { text: `${target.name} has no inputs.` }),
      el("p.form-hint", { text: "An output with the name of an input feeds it without a link." }),
      el("div.link-panel-actions", {}, [
        el("button.button.bordered", { text: "Cancel", onClick: closeLinkPanel }),
        el("button.button.bordered.primary", { text: "Apply", onClick: apply }),
      ]),
    ]),
    x,
    y,
  );
}
