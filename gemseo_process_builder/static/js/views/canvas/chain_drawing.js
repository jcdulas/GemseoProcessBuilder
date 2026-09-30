// @ts-check
// Building a chain with arrows: dragging the execution handle of a node onto
// another node of the same chain makes that node run right after it.
import { app } from "../../app.js";
import { showError } from "../../components/errors.js";
import { dependencyOrder, orderAfter } from "../../lib/chain_order.js";
import { executionPath } from "../../lib/scene.js";

/**
 * Make `next` run right after `node` in their chain. A group run automatically
 * becomes a chain, starting from the order of its dependencies.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 * @param {string} node
 * @param {string} next
 */
async function runAfter(canvas, node, next) {
  const parent = /** @type {string} */ (app.store.node(node)?.parent);
  const container = app.store.node(parent);
  const children = /** @type {string[]} */ (container?.children ?? []);
  try {
    if (container?.mode === "chain") {
      const order = orderAfter(children, node, next);
      if (order.some((id, index) => id !== children[index])) {
        await app.store.execute({ type: "reparentNodes", placements: [{ id: next, parent, index: order.indexOf(next) }] });
      }
      return;
    }
    const order = orderAfter(dependencyOrder(children, canvas.views.get(parent)?.edges ?? []), node, next);
    await app.store.executeMany(
      [
        { type: "setNodeProperties", id: parent, values: { mode: "chain" } },
        // Placed one after the other, each at its final rank.
        { type: "reparentNodes", placements: order.map((id, index) => ({ id, parent, index })) },
      ],
      "Run in order",
    );
  } catch (error) {
    showError("The order could not be changed", error);
  }
}

/**
 * Install the gesture on the canvas.
 *
 * @param {import("./canvas.js").WorkflowCanvas} canvas
 */
export function installChainDrawing(canvas) {
  const svg = canvas.svg.node();
  svg.addEventListener(
    "pointerdown",
    (/** @type {PointerEvent} */ event) => {
      const handle = event.button === 0 ? /** @type {Element} */ (event.target).closest?.(".exec-handle") : null;
      if (!handle) {
        return;
      }
      event.stopPropagation();
      event.preventDefault();
      const node = /** @type {string} */ (handle.getAttribute("data-node"));
      const parent = app.store.node(node)?.parent;
      const box = handle.getBoundingClientRect();
      const origin = canvas.toCanvas({ clientX: box.x + box.width / 2, clientY: box.y + box.height / 2 });
      const ghost = canvas.overlay.append("path").attr("class", "link link-execution link-ghost");
      canvas.container.classList.add("linking");
      /** @type {Element | null} */
      let hovered = null;
      svg.setPointerCapture(event.pointerId);

      /** @param {PointerEvent} pointer */
      const targetOf = (pointer) => {
        const group = document.elementFromPoint(pointer.clientX, pointer.clientY)?.closest?.("g.node") ?? null;
        const id = group?.getAttribute("data-id");
        return group && id && id !== node && app.store.node(id)?.parent === parent ? group : null;
      };
      /** @param {PointerEvent} moveEvent */
      const onMove = (moveEvent) => {
        ghost.attr("d", executionPath(origin, canvas.toCanvas(moveEvent)));
        const target = targetOf(moveEvent);
        if (target !== hovered) {
          hovered?.classList.remove("link-ok");
          hovered = target;
          hovered?.classList.add("link-ok");
          const name = (/** @type {string | null | undefined} */ id) => app.store.node(id)?.name;
          canvas.setHint(
            hovered
              ? `Release: ${name(hovered.getAttribute("data-id"))} will run right after ${name(node)}.`
              : "Drop on a node of the same chain.",
          );
        }
      };
      const onUp = () => {
        svg.removeEventListener("pointermove", onMove);
        svg.removeEventListener("pointerup", onUp);
        ghost.remove();
        canvas.container.classList.remove("linking");
        canvas.setHint("");
        hovered?.classList.remove("link-ok");
        const next = hovered?.getAttribute("data-id");
        if (next) {
          runAfter(canvas, node, next);
        }
      };
      svg.addEventListener("pointermove", onMove);
      svg.addEventListener("pointerup", onUp);
    },
    true,
  );
}
