// @ts-check
// The path of the level shown by the canvas, with clickable ancestors.
import { app } from "../../app.js";
import { el } from "../../components/dom.js";

export class Breadcrumb {
  /**
   * @param {HTMLElement} root
   * @param {import("../../services/navigation.js").Navigation} navigation
   */
  constructor(root, navigation) {
    this.navigation = navigation;
    this.element = el("div.canvas-breadcrumb");
    root.append(this.element);
  }

  render() {
    const path = app.store.pathTo(this.navigation.current());
    const parts = [];
    for (const [index, id] of path.entries()) {
      if (index) {
        parts.push(el("span.breadcrumb-separator", { text: "›" }));
      }
      const last = index === path.length - 1;
      parts.push(
        el(last ? "span.breadcrumb-current" : "button.breadcrumb-link", {
          text: app.store.node(id)?.name ?? "?",
          onClick: last ? undefined : () => this.navigation.enter(id),
        }),
      );
    }
    this.element.replaceChildren(...parts);
  }
}
