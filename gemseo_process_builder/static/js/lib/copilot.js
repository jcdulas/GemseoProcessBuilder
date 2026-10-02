// @ts-check
// Pure logic of the Claude copilot (docs/CLAUDE_PILOT_SPEC.md): its settings,
// the consent to what is sent, and what a run shows of it.

/** @typedef {{id: string, label: string, hint?: string}} Choice */

/** @type {Choice[]} - The models the copilot may use. */
export const MODELS = [
  { id: "claude-opus-5-5", label: "Claude Opus 5.5" },
  { id: "claude-sonnet-5-5", label: "Claude Sonnet 5.5" },
  { id: "claude-sonnet-5", label: "Claude Sonnet 5" },
  { id: "claude-haiku-4-5", label: "Claude Haiku 4.5" },
  { id: "claude-opus-5", label: "Claude Opus 5" },
  { id: "claude-fable-5-1", label: "Claude Fable 5.1" },
];

export const DEFAULT_MODEL = "claude-opus-5-5";

/** @type {Choice[]} - How much Claude thinks at each call. */
export const EFFORTS = [
  { id: "low", label: "Low effort", hint: "Answers in seconds to a minute: the run is followed closely." },
  { id: "medium", label: "Medium effort" },
  { id: "high", label: "High effort" },
  { id: "xhigh", label: "Extra high effort" },
  { id: "max", label: "Maximum effort", hint: "Several minutes per call." },
];

/**
 * The choices of a list, with a value saved before that is not in it.
 *
 * @param {Choice[]} choices
 * @param {string | undefined} value
 * @returns {Choice[]}
 */
export function withValue(choices, value) {
  if (!value || choices.some((choice) => choice.id === value)) {
    return choices;
  }
  return [...choices, { id: value, label: value }];
}

/** @type {Choice[]} */
export const MODES = [
  { id: "observer", label: "Observer", hint: "Claude explains the run; it changes nothing." },
  { id: "advisor", label: "Advisor", hint: "Claude proposes changes; you accept or reject each one during the run." },
  { id: "pilot", label: "Pilot", hint: "Claude applies its decisions, within the limits below." },
];

/** @type {Choice[]} */
export const ACTIONS = [
  { id: "change_settings", label: "Change the algorithm settings" },
  { id: "change_design_space", label: "Narrow the design space (never beyond your bounds)" },
  { id: "switch_algorithm", label: "Switch algorithm" },
  { id: "change_sub_scenario", label: "Retune a sub-optimization (algorithm or settings)" },
  { id: "add_samples", label: "Add samples, possibly in a sub-region (never beyond your bounds)" },
  { id: "stop", label: "Stop the run" },
  { id: "restart", label: "Restart from another design (a model describing its physics)" },
  { id: "steer", label: "Steer the design toward where it heads, the optimizer going on" },
];

/**
 * The actions that apply to a driver: a DOE adds samples, an optimization
 * changes its algorithm, and a BiLevel one its sub-optimizations too.
 *
 * @param {string} kind
 * @param {string} [formulation]
 * @returns {Choice[]}
 */
export function actionsFor(kind, formulation = "") {
  if (kind === "doe") {
    return ACTIONS.filter((action) => action.id === "add_samples" || action.id === "stop");
  }
  if (kind !== "optimization") {
    return [];
  }
  return ACTIONS.filter(
    (action) => action.id !== "add_samples" && (action.id !== "change_sub_scenario" || formulation === "BiLevel"),
  );
}

/** @type {Choice[]} - From the least to the most sent. */
export const DATA_LEVELS = [
  {
    id: "anonymized",
    label: "Anonymized",
    hint: "Variables renamed x1, f1, g1…, design values scaled between their bounds; no names, no descriptions, no code.",
  },
  {
    id: "no_code",
    label: "Without code",
    hint: "The names, bounds, values and history of the optimization; never the source code of your components.",
  },
  {
    id: "full",
    label: "Full",
    hint: "The names, values and history, the descriptions of your components and their source code.",
  },
];

/**
 * @typedef {object} CopilotSettings
 * @property {boolean} enabled
 * @property {string} mode
 * @property {string[]} allowed_actions
 * @property {string} data_level
 * @property {number} max_calls
 */

/**
 * The copilot of a driver, with the defaults of the preferences for what is missing.
 *
 * @param {Record<string, any> | undefined} copilot - ``config.copilot`` of a driver.
 * @param {Record<string, any>} [preferences]
 * @returns {CopilotSettings}
 */
export function copilotSettings(copilot, preferences = {}) {
  return {
    enabled: false,
    mode: preferences.copilot_mode ?? "advisor",
    allowed_actions: ACTIONS.map((action) => action.id),
    data_level: preferences.copilot_data_level ?? "no_code",
    max_calls: preferences.copilot_max_calls ?? 30,
    ...(copilot ?? {}),
  };
}

/** @param {string} level */
function rank(level) {
  return DATA_LEVELS.findIndex((item) => item.id === level);
}

/**
 * Whether sending a data level needs the user's consent: nothing accepted yet,
 * or a level that sends more than the one accepted.
 *
 * @param {string} level
 * @param {string} accepted - The most open level accepted, or "".
 */
export function needsConsent(level, accepted) {
  return rank(level) > rank(accepted);
}

/**
 * The calls and tokens spent, and the estimated cost with an API key.
 *
 * @param {{calls?: number, input_tokens?: number, output_tokens?: number, cost_usd?: number} | null} usage
 * @param {string} backend - ``claude_code`` or ``api_key``.
 */
export function usageText(usage, backend) {
  if (!usage) {
    return "No call yet";
  }
  const number = (/** @type {number | undefined} */ value) => (value ?? 0).toLocaleString("en-US");
  const calls = usage.calls ?? 0;
  const parts = [
    `${calls} call${calls === 1 ? "" : "s"}`,
    `${number(usage.input_tokens)} tokens in`,
    `${number(usage.output_tokens)} out`,
  ];
  if (backend === "api_key" && usage.cost_usd) {
    parts.push(`about $${usage.cost_usd.toFixed(2)}`);
  }
  return parts.join(" · ");
}

/**
 * What a decision does, in a few words.
 *
 * @param {any} decision
 */
export function actionText(decision) {
  const action = decision?.action ?? { kind: "none" };
  switch (action.kind) {
    case "switch_algorithm":
      return `Switch to ${action.algo_name}`;
    case "change_settings":
      return `Set ${Object.entries(action.settings ?? {})
        .map(([name, value]) => `${name} = ${value}`)
        .join(", ")}`;
    case "change_design_space":
      return `Change ${(action.variables ?? [])
        .map((/** @type {any} */ change) => {
          const bounds = [change.lower, change.upper].map((bound) => (bound == null ? "…" : String(bound)));
          return `${change.name} to [${bounds.join(", ")}]`;
        })
        .join(", ")}`;
    case "stop":
      return `Stop the run (${action.reason})`;
    case "add_samples": {
      const region = (action.region ?? []).map(
        (/** @type {any} */ change) => `${change.name} in [${change.lower ?? "…"}, ${change.upper ?? "…"}]`,
      );
      return `Add ${action.n_samples} samples with ${action.algo_name}` + (region.length ? ` where ${region.join(", ")}` : "");
    }
    case "change_sub_scenario": {
      const changes = [
        ...(action.algo_name ? [`switch to ${action.algo_name}`] : []),
        ...Object.entries(action.settings ?? {}).map(([name, value]) => `set ${name} = ${value}`),
      ];
      return `In ${action.scenario}, ${changes.join(", ")}`;
    }
    case "restart": {
      const base = typeof action.base === "number" ? `evaluation ${action.base}` : `the ${action.base ?? "best"} design`;
      const steps = (action.transforms ?? []).map((/** @type {any} */ item) => item.kind);
      return `Restart from ${base}` + (steps.length ? `, ${steps.join(", ")}` : "") + (action.answers ? `: ${action.answers}` : "");
    }
    case "steer": {
      const moves = [
        ...(action.anticipate ? [`anticipate the trend ×${action.anticipate.factor ?? 1}`] : []),
        ...(action.transforms ?? []).map((/** @type {any} */ item) => item.kind),
        ...(action.variables ?? []).map((/** @type {any} */ change) => `set ${change.name}`),
      ];
      return `Steer the design: ${moves.join(", ")}` + (action.toward ? ` (${action.toward})` : "");
    }
    default:
      return "";
  }
}

/**
 * @typedef {object} CopilotMessage
 * @property {string} kind - diagnosis, answer, decision, proposal or report.
 * @property {string} text
 * @property {string} [id] - Of a proposal.
 * @property {string} [status] - Of a proposal: open, accepted, rejected, replaced…
 * @property {any} [decision]
 * @property {number} [evaluation]
 * @property {string} [trigger]
 * @property {string} [question] - The question an answer answers.
 */

/** What a run shows of its copilot: status, messages, segments and usage. */
export class CopilotLog {
  constructor() {
    this.state = "";
    this.mode = "";
    this.reason = "";
    /** @type {CopilotMessage[]} */
    this.messages = [];
    /** @type {any[]} */
    this.segments = [];
    /** @type {any} */
    this.usage = null;
    /** @type {any} */
    this.summary = null;
    /** @type {any[]} - The reports of the outer iterations of an LSO algorithm. */
    this.algorithm = [];
  }

  /** Whether the run had a copilot. */
  get active() {
    return Boolean(this.state || this.messages.length || this.summary);
  }

  /** The analysis Claude wrote at the end of the run, or "". */
  get report() {
    return this.messages.findLast((message) => message.kind === "report")?.text ?? "";
  }

  /** The proposal waiting for an answer, or ``null``. */
  get openProposal() {
    return this.messages.find((message) => message.kind === "proposal" && message.status === "open") ?? null;
  }

  /**
   * Apply one event of the runner.
   *
   * @param {string} event
   * @param {any} payload
   */
  apply(event, payload) {
    if (event === "copilot.status") {
      this.state = payload.state;
      this.mode = payload.mode ?? this.mode;
      this.reason = payload.reason ?? "";
    } else if (event === "copilot.message") {
      if (payload.kind === "closed") {
        this.close(payload.id, payload.how);
      } else {
        this.messages.push({
          kind: payload.kind,
          text: payload.text ?? "",
          id: payload.id,
          status: payload.kind === "proposal" ? "open" : undefined,
          decision: payload.decision,
          evaluation: payload.evaluation,
          trigger: payload.trigger,
          question: payload.question || undefined,
        });
      }
    } else if (event === "copilot.usage") {
      this.usage = payload;
    } else if (event === "copilot.segment") {
      this.segments = [...this.segments.filter((segment) => segment.index !== payload.index), payload];
    } else if (event === "copilot.algorithm") {
      // In order; a report sent again replaces the last one.
      if (this.algorithm.at(-1)?.iteration === payload.iteration) {
        this.algorithm[this.algorithm.length - 1] = payload;
      } else {
        this.algorithm.push(payload);
      }
    } else if (event === "copilot.summary") {
      this.summary = payload;
      this.segments = payload.segments ?? this.segments;
      this.usage = { calls: payload.calls, ...payload.usage };
    }
  }

  /**
   * @param {string} id
   * @param {string} how
   */
  close(id, how) {
    const proposal = this.messages.find((message) => message.kind === "proposal" && message.id === id);
    if (proposal) {
      proposal.status = how;
    }
  }

  /**
   * The log of a finished run, from the journal of its copilot.
   *
   * @param {any[]} records - Of ``copilot/journal.jsonl``.
   */
  static fromJournal(records) {
    const log = new CopilotLog();
    for (const record of records) {
      if (record.kind === "status" && record.state === "started") {
        log.mode = record.mode ?? "";
        log.state = "watching";
      } else if (record.kind === "status" && record.state === "disabled") {
        log.state = "disabled";
        log.reason = record.reason ?? "";
      } else if (record.kind === "status" && record.state === "finished") {
        log.apply("copilot.summary", record);
        log.state = "off";
        log.reason = record.stop_reason ?? "";
      } else if (record.kind === "answer" && record.trigger === "report") {
        log.messages.push({ kind: "report", text: record.text ?? "" });
      } else if (record.kind === "answer" && record.question) {
        log.messages.push({
          kind: "answer",
          text: record.text || record.decision?.diagnosis || "",
          question: record.question,
          evaluation: record.evaluation,
        });
      } else if (record.kind === "answer") {
        const acting = record.decision && record.decision.action?.kind && record.decision.action.kind !== "none";
        const text = record.decision?.diagnosis ?? record.text ?? "";
        // A decision with an action is shown by its proposal or its application.
        if (text && !(acting && log.mode !== "observer")) {
          log.messages.push({ kind: record.decision ? "diagnosis" : "answer", text, trigger: record.trigger, evaluation: record.evaluation });
        }
      } else if (record.kind === "proposal") {
        log.messages.push({
          kind: "proposal",
          id: record.id,
          status: "open",
          text: record.decision?.diagnosis ?? "",
          decision: record.decision,
          evaluation: record.evaluation,
        });
      } else if (record.kind === "proposal_closed") {
        log.close(record.id, record.how);
      } else if (record.kind === "decision") {
        log.messages.push({ kind: "decision", text: record.decision?.diagnosis ?? "", decision: record.decision });
      } else if (record.kind === "segment") {
        log.apply("copilot.segment", record);
      } else if (record.kind === "algorithm") {
        log.apply("copilot.algorithm", record);
      }
    }
    return log;
  }
}

/**
 * The working set and the rows computed at each outer iteration of an LSO
 * algorithm, as the points of two series.
 *
 * @param {any[]} reports - ``CopilotLog.algorithm``.
 * @returns {{workingSet: {x: number, y: number}[], rows: {x: number, y: number}[]}}
 */
export function workingSetSeries(reports) {
  return {
    workingSet: reports.map((report) => ({ x: report.iteration, y: report.working_set })),
    rows: reports.map((report) => ({ x: report.iteration, y: report.rows_computed })),
  };
}

/**
 * Where the History charts mark the start of the segments after the first.
 *
 * @param {any[]} segments
 * @returns {{x: number, label: string, title: string}[]} - ``x`` between the
 *   last evaluation of a segment and the first of the next (numbered from 1).
 */
export function segmentMarkers(segments) {
  return [...segments]
    .sort((a, b) => a.index - b.index)
    .slice(1)
    .map((segment) => ({ x: segment.first_evaluation + 0.5, label: segment.algo_name, title: segment.reason ?? "" }));
}
