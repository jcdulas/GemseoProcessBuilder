// @ts-check
// The Problems panel: validation errors, warnings and information.
import { app } from "../app.js";
import { el } from "../components/dom.js";
import { showError } from "../components/errors.js";

const LEVEL_ICONS = { error: "✖", warning: "⚠", info: "ℹ" };

export class ProblemsPanel {
  /** @param {HTMLElement} root */
  constructor(root) {
    root.replaceChildren();
    /** @type {Set<string>} */
    this.hidden = new Set();
    this.filters = el("div.problems-filters");
    this.list = el("div.problems-list");
    root.append(this.filters, this.list);
    app.validation.onChange(() => this.render());
    app.store.subscribe(() => this.render());
    this.render();
  }

  /**
   * Show the node of a problem on the canvas.
   *
   * @param {import("../services/validation.js").Problem} problem
   */
  locate(problem) {
    if (!problem.node || !app.store.node(problem.node)) {
      return;
    }
    if (app.store.node(problem.node)?.parent) {
      app.navigation.reveal(problem.node);
      app.selection.set([problem.node]);
    } else {
      app.navigation.enter(problem.node);
    }
  }

  /**
   * @param {import("../services/validation.js").Problem} problem
   * @param {string} fix
   */
  async applyFix(problem, fix) {
    try {
      await app.api.call("validation.quickFix", { key: problem.key, fix });
    } catch (error) {
      showError("The problem could not be fixed", error);
    }
  }

  render() {
    const problems = app.validation.problems;
    const counts = { error: 0, warning: 0, info: 0 };
    for (const problem of problems) {
      counts[problem.level] += 1;
    }
    this.filters.replaceChildren(
      ...Object.entries(counts).map(([level, count]) =>
        el(`button.button.problems-filter${this.hidden.has(level) ? "" : ".active"}`, {
          text: `${LEVEL_ICONS[/** @type {keyof LEVEL_ICONS} */ (level)]} ${count} ${level}${count === 1 ? "" : "s"}`,
          onClick: () => {
            if (this.hidden.has(level)) {
              this.hidden.delete(level);
            } else {
              this.hidden.add(level);
            }
            this.render();
          },
        }),
      ),
    );
    const visible = problems.filter((problem) => !this.hidden.has(problem.level));
    this.list.replaceChildren(
      ...(visible.length
        ? visible.map((problem) => {
            const path = problem.node ? app.store.pathTo(problem.node).map((id) => app.store.node(id)?.name).join(".") : "";
            return el(`div.problem.problem-${problem.level}`, { onClick: () => this.locate(problem) }, [
              el("span.problem-icon", { text: LEVEL_ICONS[problem.level] }),
              el("span.problem-message", { text: problem.message }),
              el("span.problem-location", { text: path }),
              ...problem.quick_fixes.map((fix) =>
                el("button.button.bordered.problem-fix", {
                  text: app.validation.fixLabels[fix] ?? fix,
                  onClick: (/** @type {Event} */ event) => {
                    event.stopPropagation();
                    this.applyFix(problem, fix);
                  },
                }),
              ),
            ]);
          })
        : [el("p.placeholder", { text: problems.length ? "All problems are hidden by the filters." : "No problems found." })]),
    );
    app.tabs.bottom.setBadge("problems", counts.error + counts.warning);
  }
}

export function installValidation() {
  app.actions.handle("model.validate", {
    run: async () => {
      app.tabs.bottom.activate("problems");
      if (!app.layout.isVisible("bottom")) {
        app.layout.toggle("bottom");
      }
      await app.api.call("validation.run");
    },
  });
}
