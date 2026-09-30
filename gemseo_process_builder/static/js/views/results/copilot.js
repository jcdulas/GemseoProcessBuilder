// @ts-check
// Copilot: what Claude said and did during a piloted run, its proposals to
// accept or reject while it runs, the mode and the usage (docs/CLAUDE_PILOT_SPEC.md § 10.1).
import { app } from "../../app.js";
import { el } from "../../components/dom.js";
import { showError } from "../../components/errors.js";
import { seriesColor } from "../../charts/axis.js";
import { LineChart } from "../../charts/line_chart.js";
import { CopilotLog, MODES, actionText, usageText, workingSetSeries } from "../../lib/copilot.js";

/** What the states of the copilot mean for the user. */
const STATES = {
  watching: "Watching the run",
  thinking: "Claude is thinking",
  waiting: "Waiting for your answer",
  disabled: "Off for this run",
  off: "Finished",
};

/** How a proposal ended, for the user. */
const CLOSED = {
  accepted: "Accepted",
  rejected: "Rejected",
  replaced: "Replaced by a newer proposal",
  expired: "Too old to be applied",
  unanswered: "Not answered in time",
  "run ended": "The run ended first",
};

/**
 * Whether a run had a copilot, from its live events or its summary.
 *
 * @param {import("./source.js").ResultsSource} source
 */
export function isPiloted(source) {
  const live = app.runStates.runs.get(source.runId);
  return Boolean(live?.data.copilot.active || Object.keys(source.info?.summary?.copilot ?? {}).length);
}

/**
 * The segments of a piloted run, for the markers of the History charts.
 *
 * @param {import("./source.js").ResultsSource} source
 * @returns {any[]}
 */
export function segmentsOf(source) {
  const live = source.liveRecord();
  return live ? live.data.copilot.segments : (source.info?.summary?.copilot?.segments ?? []);
}

export class CopilotView {
  /** @param {HTMLElement} root */
  constructor(root) {
    this.root = root;
    root.classList.add("copilot-view");
    /** @type {Map<string, Promise<CopilotLog>>} - Journals of finished runs. */
    this.journals = new Map();
    /** @type {import("./source.js").ResultsSource | null} */
    this.source = null;
    // Built once: the view is redrawn at each event of the run, not the question typed.
    this.question = /** @type {HTMLTextAreaElement} */ (
      el("textarea.input.copilot-question", { rows: 2, placeholder: "Ask Claude about this run…" })
    );
    this.asking = el("span.form-hint");
    this.askBox = el("div.copilot-ask", {}, [
      this.question,
      el("button.button.bordered.primary", { text: "Ask", onClick: () => this.ask() }),
      this.asking,
    ]);
    // Built once too: a chart observes its size.
    this.chartBox = el("div.copilot-chart");
    this.chart = new LineChart(this.chartBox);
  }

  /** Send the question typed; a running run answers through its events. */
  async ask() {
    const source = this.source;
    const question = this.question.value.trim();
    if (!source || !question) {
      return;
    }
    const live = source.live;
    this.question.disabled = true;
    this.asking.textContent = live ? "Sent: Claude answers at the next iteration." : "Claude is reading the run…";
    try {
      const answer = await app.api.call("copilot.ask", { run_id: source.runId, question }, { timeout: 600_000 });
      if (!live && answer.text) {
        (await this.log(source)).messages.push({ kind: "answer", text: answer.text, question });
      }
      this.question.value = "";
      this.asking.textContent = live ? this.asking.textContent : "";
      this.update(source);
    } catch (error) {
      this.asking.textContent = "";
      showError("Claude could not answer", error);
    } finally {
      this.question.disabled = false;
    }
  }

  /**
   * @param {import("./source.js").ResultsSource} source
   * @returns {Promise<CopilotLog>}
   */
  log(source) {
    const live = source.liveRecord();
    if (live) {
      return Promise.resolve(live.data.copilot);
    }
    if (!this.journals.has(source.runId)) {
      const journal = app.api
        .call("copilot.journal", { run_id: source.runId })
        .then((/** @type {any[]} */ records) => CopilotLog.fromJournal(records));
      journal.catch(() => this.journals.delete(source.runId));
      this.journals.set(source.runId, journal);
    }
    return /** @type {Promise<CopilotLog>} */ (this.journals.get(source.runId));
  }

  /** @param {import("./source.js").ResultsSource} source */
  async update(source) {
    this.source = source;
    let log;
    try {
      log = await this.log(source);
    } catch (error) {
      this.root.replaceChildren(el("p.placeholder", { text: `The journal of the copilot could not be read: ${error}` }));
      return;
    }
    const live = source.live;
    this.root.replaceChildren(
      this.header(source.runId, log, live),
      el(
        "div.copilot-timeline",
        {},
        log.messages.length
          ? log.messages.map((message) => this.message(source.runId, message, live))
          : [el("p.placeholder", { text: live ? "Claude has not said anything yet." : "Claude said nothing during this run." })],
      ),
      this.askBox,
      this.chartBox,
      this.segments(log),
    );
    this.workingSet(log);
  }

  /**
   * The working set and the rows per iteration of an LSO algorithm, if any.
   *
   * @param {CopilotLog} log
   */
  workingSet(log) {
    this.chartBox.hidden = !log.algorithm.length;
    if (!log.algorithm.length) {
      return;
    }
    const { workingSet, rows } = workingSetSeries(log.algorithm);
    this.chart.update({
      title: "Working set and rows per iteration",
      xLabel: "outer iteration",
      xName: "Iteration",
      series: [
        { name: "Working set", color: seriesColor(0), points: workingSet },
        { name: "Rows computed", color: seriesColor(1), points: rows },
      ],
    });
  }

  /**
   * @param {string} runId
   * @param {CopilotLog} log
   * @param {boolean} live
   */
  header(runId, log, live) {
    const state = /** @type {Record<string, string>} */ (STATES)[log.state] ?? log.state;
    const reason = log.reason && log.state !== "watching" ? ` (${log.reason})` : "";
    const cost = log.usage?.cost_usd ? "api_key" : "claude_code";
    const children = [
      el(`span.copilot-state.${log.state || "off"}`, { text: `${state}${reason}` }),
      el("span.copilot-usage", { text: usageText(log.usage, cost) }),
    ];
    if (live && log.state !== "off" && log.state !== "disabled") {
      const mode = /** @type {HTMLSelectElement} */ (
        el(
          "select.input",
          { title: "The mode of the copilot for the rest of the run" },
          MODES.map((choice) => el("option", { value: choice.id, text: choice.label, selected: choice.id === log.mode })),
        )
      );
      mode.addEventListener("change", () => command(runId, { command: "mode", mode: mode.value }));
      children.push(el("label.copilot-mode", {}, [el("span", { text: "Mode" }), mode]));
    } else if (log.mode) {
      children.push(el("span.copilot-mode", { text: `Mode: ${log.mode}` }));
    }
    return el("div.results-toolbar.copilot-header", {}, children);
  }

  /**
   * @param {string} runId
   * @param {import("../../lib/copilot.js").CopilotMessage} message
   * @param {boolean} live
   */
  message(runId, message, live) {
    const when = message.evaluation != null ? `evaluation ${message.evaluation}` : (message.trigger ?? "");
    const action = actionText(message.decision);
    const children = [
      el("div.copilot-message-head", {}, [
        el(`span.copilot-kind.${message.kind}`, { text: message.kind }),
        el("span.copilot-when", { text: when }),
      ]),
      message.question ? el("p.copilot-question", { text: `You: ${message.question}` }) : null,
      el(`${message.kind === "report" ? "div.copilot-report" : "p.copilot-text"}`, { text: message.text }),
      action ? el("p.copilot-action", { text: action }) : null,
      message.decision?.rationale ? el("p.form-hint", { text: message.decision.rationale }) : null,
    ];
    if (message.kind === "proposal") {
      if (message.status === "open" && live) {
        children.push(
          el("div.copilot-answer", {}, [
            el("button.button.bordered.primary", {
              text: "Accept",
              onClick: () => command(runId, { command: "accept", id: message.id }),
            }),
            el("button.button.bordered", { text: "Reject", onClick: () => command(runId, { command: "reject", id: message.id }) }),
          ]),
        );
      } else {
        const status = /** @type {Record<string, string>} */ (CLOSED)[message.status ?? ""] ?? "Open";
        children.push(el("p.copilot-status", { text: status }));
      }
    }
    return el(`div.copilot-message.${message.kind}`, {}, children);
  }

  /** @param {CopilotLog} log */
  segments(log) {
    if (!log.segments.length) {
      return el("div");
    }
    return el("table.copilot-segments", {}, [
      el("thead", {}, [el("tr", {}, ["Segment", "Algorithm", "From evaluation", "Why"].map((text) => el("th", { text })))]),
      el(
        "tbody",
        {},
        log.segments.map((segment) =>
          el("tr", {}, [
            el("td", { text: String(segment.index + 1) }),
            el("td", { text: segment.algo_name }),
            el("td", { text: String(segment.first_evaluation + 1) }),
            el("td", { text: segment.reason ?? "" }),
          ]),
        ),
      ),
    ]);
  }
}

/**
 * Send a command of the user to the copilot of a running run.
 *
 * @param {string} runId
 * @param {{command: string, id?: string, mode?: string}} params
 */
function command(runId, params) {
  app.api.call("run.copilot", { run_id: runId, ...params }).catch((error) => showError("The copilot did not get the answer", error));
}
