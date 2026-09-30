// @ts-check
// A full-window image viewer: the wheel zooms around the pointer, dragging
// pans, a double click fits the image again, Escape closes.
import { el } from "./dom.js";

const MIN_SCALE = 0.1;
const MAX_SCALE = 20;

/**
 * Show images one at a time; the arrow keys go to the previous or next one.
 *
 * @param {{src: string, title: string}[]} images
 * @param {number} [start] - The index of the image shown first.
 * @returns {() => void} A function closing the viewer.
 */
export function openImageViewer(images, start = 0) {
  let index = start;
  let scale = 1;
  let x = 0;
  let y = 0;
  const image = /** @type {HTMLImageElement} */ (el("img.image-viewer-image", { draggable: "false" }));
  const title = el("span.image-viewer-title");
  const stage = el("div.image-viewer-stage", {}, [image]);
  const previous = el("button.button.bordered", { text: "‹", title: "Previous image (←)", onClick: () => go(-1) });
  const next = el("button.button.bordered", { text: "›", title: "Next image (→)", onClick: () => go(1) });
  const root = el("div.image-viewer", { role: "dialog", "aria-label": "Image viewer" }, [
    el("div.image-viewer-bar", {}, [
      previous,
      next,
      title,
      el("span.toolbar-spacer"),
      el("span.form-hint", { text: "Wheel to zoom, drag to pan, double click to fit" }),
      el("button.button.bordered", { text: "Close", onClick: () => close() }),
    ]),
    stage,
  ]);

  const apply = () => {
    image.style.transform = `translate(${x}px, ${y}px) scale(${scale})`;
  };
  // Fit the image in the stage, centered.
  const fit = () => {
    const width = image.naturalWidth || stage.clientWidth;
    const height = image.naturalHeight || stage.clientHeight;
    scale = Math.min(stage.clientWidth / width, stage.clientHeight / height, 1) * 0.95;
    x = (stage.clientWidth - width * scale) / 2;
    y = (stage.clientHeight - height * scale) / 2;
    apply();
  };
  const show = () => {
    const current = images[index];
    title.textContent = `${current.title} (${index + 1} / ${images.length})`;
    image.onload = fit;
    image.src = current.src;
    previous.toggleAttribute("disabled", index === 0);
    next.toggleAttribute("disabled", index === images.length - 1);
  };
  /** @param {number} step */
  const go = (step) => {
    const target = index + step;
    if (target >= 0 && target < images.length) {
      index = target;
      show();
    }
  };

  stage.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const box = stage.getBoundingClientRect();
      const pointerX = event.clientX - box.left;
      const pointerY = event.clientY - box.top;
      const factor = Math.exp(-event.deltaY * 0.0015);
      const target = Math.min(Math.max(scale * factor, MIN_SCALE), MAX_SCALE);
      // Keep the point under the pointer in place.
      x = pointerX - ((pointerX - x) * target) / scale;
      y = pointerY - ((pointerY - y) * target) / scale;
      scale = target;
      apply();
    },
    { passive: false },
  );
  stage.addEventListener("pointerdown", (event) => {
    const origin = { x: event.clientX - x, y: event.clientY - y };
    stage.setPointerCapture(event.pointerId);
    stage.classList.add("panning");
    const move = (/** @type {PointerEvent} */ moveEvent) => {
      x = moveEvent.clientX - origin.x;
      y = moveEvent.clientY - origin.y;
      apply();
    };
    const up = () => {
      stage.classList.remove("panning");
      stage.removeEventListener("pointermove", move);
      stage.removeEventListener("pointerup", up);
    };
    stage.addEventListener("pointermove", move);
    stage.addEventListener("pointerup", up);
  });
  stage.addEventListener("dblclick", fit);

  /** @param {KeyboardEvent} event */
  const onKey = (event) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
    } else if (event.key === "ArrowLeft") {
      go(-1);
    } else if (event.key === "ArrowRight") {
      go(1);
    }
  };
  const close = () => {
    document.removeEventListener("keydown", onKey, true);
    root.remove();
  };
  document.addEventListener("keydown", onKey, true);
  /** @type {HTMLElement} */ (document.getElementById("modal-root")).append(root);
  show();
  return close;
}
