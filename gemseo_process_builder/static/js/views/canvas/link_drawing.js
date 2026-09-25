// @ts-check
// Drawing explicit links by dragging from a port to another.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { openModal } from "../../components/modal.js";
import { linkPath } from "../../lib/geometry.js";
import { linkCompatibility, unitCompatibility } from "../../lib/link_compat.js";

/** Unit checks of Python by "source|target" units, asked once per pair. */
const unitChecks = new Map();

/**
 * Python's check of two units, from the cache; asked for when missing.
 *
 * @param {string | null | undefined} source
 * @param {string | null | undefined} target
 */
function unitCheck(source, target) {
  if (source == null || target == null) {
    return null;
  }
  const key = `${source}|${target}`;
  if (!unitChecks.has(key)) {
    unitChecks.set(key, null);
    app.api
      .call("units.check", { source, target })
      .then((/** @type {any} */ check) => unitChecks.set(key, check))
      .catch((/** @type {unknown} */ error) => console.error(error));
  }
  return unitChecks.get(key);
}

/**
 * @typedef {object} PortHandle
 * @property {string} node
 * @property {string} port
 * @property {"in" | "out"} direction
 */

/**
 * The port described by a port circle, if it belongs to a component.
 *
 * @param {Element | null} element
 * @returns {PortHandle | null}
 */
function handleOf(element) {
  const circle = element?.closest?.(".port-handle");
  if (!circle) {
    return null;
  }
  const node = /** @type {string} */ (circle.getAttribute("data-node"));
  if (app.store.node(node)?.type !== "component") {
    return null;
  }
  return {
    node,
    port: /** @type {string} */ (circle.getAttribute("data-port")),
    direction: /** @type {"in" | "out"} */ (circle.getAttribute("data-direction")),
  };
}

/**
 * @param {PortHandle} handle
 */
function portData(handle) {
  return (app.store.node(handle.node)?.ports ?? []).find(
    (/** @type {any} */ port) => port.local_name === handle.port && port.direction === handle.direction,
  );
}

/**
 * Whether two handles can be linked, as {source, target} or a reason.
 *
 * @param {PortHandle} first
 * @param {PortHandle} second
 */
export function pairOf(first, second) {
  if (first.node === second.node || first.direction === second.direction) {
    return { source: null, target: null, reason: "Link an output to an input of another component." };
  }
  const [source, target] = first.direction === "out" ? [first, second] : [second, first];
  const output = portData(source) ?? {};
  const input = portData(target) ?? {};
  const compat = linkCompatibility(output, input);
  if (!compat.ok) {
    return { source: null, target: null, reason: compat.reason };
  }
  const units = unitCompatibility(unitCheck(output.unit, input.unit));
  return units.ok
    ? { source, target, reason: "", warning: [compat.warning, units.warning].filter(Boolean).join(" ") }
    : { source: null, target: null, reason: units.reason };
}

/**
 * Create a link, asking before replacing an existing link to the same input.
 *
 * @param {PortHandle} source
 * @param {PortHandle} target
 */
export async function createLink(source, target) {
  const command = {
    type: "addLink",
    source: { node: source.node, port: source.port },
    target: { node: target.node, port: target.port },
  };
  const existing = Object.values(app.store.state.links).filter(
    (link) => link.target.node === target.node && link.target.port === target.port,
  );
  if (existing.some((link) => link.source.node === source.node && link.source.port === source.port)) {
    return;
  }
  const run = async () => {
    try {
      if (existing.length) {
        await app.store.executeMany(
          [{ type: "deleteLinks", ids: existing.map((link) => link.id) }, command],
          "Replace link",
        );
      } else {
        await app.store.execute(command);
      }
    } catch (error) {
      showError("The link could not be created", error);
    }
  };
  if (!existing.length) {
    await run();
    return;
  }
  const targetName = app.store.node(target.node)?.name;
  openModal({
    title: "Replace the existing link?",
    body: el("p", { text: `${targetName}.${target.port} already receives a link. Replace it?` }),
    buttons: [{ label: "Cancel" }, { label: "Replace", primary: true, onClick: run }],
  });
}

/**
 * Install the link-drawing gesture on the canvas.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 */
export function installLinkDrawing(canvas) {
  const svg = canvas.svg.node();
  svg.addEventListener(
    "pointerdown",
    (/** @type {PointerEvent} */ event) => {
      const start = event.button === 0 ? handleOf(/** @type {Element} */ (event.target)) : null;
      if (!start) {
        return;
      }
      event.stopPropagation();
      event.preventDefault();
      const circle = /** @type {SVGCircleElement} */ (/** @type {Element} */ (event.target).closest(".port-handle"));
      const box = circle.getBoundingClientRect();
      const origin = canvas.toCanvas({ clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 });
      const ghost = canvas.overlay.append("path").attr("class", "link link-ghost");
      canvas.container.classList.add("linking");
      /** @type {Element | null} */
      let hovered = null;
      svg.setPointerCapture(event.pointerId);

      /** @param {PointerEvent} moveEvent */
      const onMove = (moveEvent) => {
        const point = canvas.toCanvas(moveEvent);
        const [a, b] = start.direction === "out" ? [origin, point] : [point, origin];
        ghost.attr("d", linkPath(a, b));
        const under = document.elementFromPoint(moveEvent.clientX, moveEvent.clientY);
        const circleUnder = under?.closest?.(".port-handle") ?? null;
        if (circleUnder !== hovered) {
          hovered?.classList.remove("link-ok", "link-refused");
          hovered = circleUnder;
          const other = handleOf(circleUnder);
          if (hovered && other) {
            const pair = pairOf(start, other);
            hovered.classList.add(pair.source ? "link-ok" : "link-refused");
            canvas.setHint(pair.source ? pair.warning || "" : pair.reason);
          } else {
            canvas.setHint("");
          }
        }
      };
      const onUp = () => {
        svg.removeEventListener("pointermove", onMove);
        svg.removeEventListener("pointerup", onUp);
        ghost.remove();
        canvas.container.classList.remove("linking");
        canvas.setHint("");
        hovered?.classList.remove("link-ok", "link-refused");
        const other = handleOf(hovered);
        if (other) {
          const pair = pairOf(start, other);
          if (pair.source && pair.target) {
            createLink(pair.source, pair.target);
          }
        }
      };
      svg.addEventListener("pointermove", onMove);
      svg.addEventListener("pointerup", onUp);
    },
    true,
  );

  // Hovering a port highlights its links.
  svg.addEventListener("pointerover", (/** @type {PointerEvent} */ event) => {
    const circle = /** @type {Element} */ (event.target).closest?.(".port-handle");
    for (const highlighted of svg.querySelectorAll(".link-group.highlight")) {
      highlighted.classList.remove("highlight");
    }
    if (!circle) {
      return;
    }
    const node = circle.getAttribute("data-node");
    const port = circle.getAttribute("data-port");
    const out = circle.getAttribute("data-direction") === "out";
    for (const group of svg.querySelectorAll(".link-group")) {
      const matches = out
        ? group.getAttribute("data-from") === node && group.getAttribute("data-source-port") === port
        : group.getAttribute("data-to") === node && group.getAttribute("data-target-port") === port;
      group.classList.toggle("highlight", matches);
    }
  });
}
