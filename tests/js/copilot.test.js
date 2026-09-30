import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTIONS,
  CopilotLog,
  DEFAULT_MODEL,
  EFFORTS,
  MODELS,
  actionText,
  actionsFor,
  copilotSettings,
  needsConsent,
  segmentMarkers,
  usageText,
  withValue,
  workingSetSeries,
} from "../../gemseo_process_builder/static/js/lib/copilot.js";

test("the settings of a copilot take the defaults of the preferences", () => {
  const settings = copilotSettings(undefined, { copilot_mode: "pilot", copilot_max_calls: 10 });
  assert.deepEqual(settings, {
    enabled: false,
    mode: "pilot",
    allowed_actions: ACTIONS.map((action) => action.id),
    data_level: "no_code",
    max_calls: 10,
  });
  assert.equal(copilotSettings({ enabled: true, mode: "observer" }, { copilot_mode: "pilot" }).mode, "observer");
});

test("consent is asked for a level sending more than the one accepted", () => {
  assert.equal(needsConsent("anonymized", ""), true);
  assert.equal(needsConsent("no_code", "no_code"), false);
  assert.equal(needsConsent("anonymized", "no_code"), false);
  assert.equal(needsConsent("full", "no_code"), true);
});

test("usage by backend", () => {
  const usage = { calls: 3, input_tokens: 12400, output_tokens: 2800, cost_usd: 0.041 };
  assert.equal(usageText(usage, "claude_code"), "3 calls · 12,400 tokens in · 2,800 out");
  assert.equal(usageText(usage, "api_key"), "3 calls · 12,400 tokens in · 2,800 out · about $0.04");
  assert.equal(usageText({ calls: 1 }, "claude_code"), "1 call · 0 tokens in · 0 out");
  assert.equal(usageText(null, "claude_code"), "No call yet");
});

test("what a decision does", () => {
  assert.equal(actionText({ action: { kind: "switch_algorithm", algo_name: "NLOPT_COBYLA" } }), "Switch to NLOPT_COBYLA");
  assert.equal(actionText({ action: { kind: "change_settings", settings: { ftol_rel: 1e-8, max_iter: 40 } } }), "Set ftol_rel = 1e-8, max_iter = 40");
  assert.equal(
    actionText({ action: { kind: "change_design_space", variables: [{ name: "x", upper: 1.5 }] } }),
    "Change x to […, 1.5]",
  );
  assert.equal(actionText({ action: { kind: "stop", reason: "converged" } }), "Stop the run (converged)");
  assert.equal(actionText({ diagnosis: "Fine." }), "");
});

const SWITCH = { diagnosis: "SLSQP zigzags.", action: { kind: "switch_algorithm", algo_name: "NLOPT_COBYLA" } };

test("the log of a live run", () => {
  const log = new CopilotLog();
  assert.equal(log.active, false);
  log.apply("copilot.status", { state: "watching", mode: "advisor" });
  log.apply("copilot.message", { kind: "diagnosis", text: "Fine so far.", trigger: "start", evaluation: 0 });
  log.apply("copilot.message", { kind: "proposal", id: "p1", text: SWITCH.diagnosis, decision: SWITCH, evaluation: 6 });
  assert.equal(log.openProposal?.id, "p1");
  log.apply("copilot.message", { kind: "proposal", id: "p2", text: "Again.", decision: SWITCH, evaluation: 9 });
  log.apply("copilot.message", { kind: "closed", id: "p1", how: "replaced" });
  log.apply("copilot.message", { kind: "closed", id: "p2", how: "accepted" });
  log.apply("copilot.segment", { index: 0, algo_name: "SLSQP", first_evaluation: 0 });
  log.apply("copilot.segment", { index: 1, algo_name: "NLOPT_COBYLA", first_evaluation: 10, reason: "switch_algorithm" });
  log.apply("copilot.usage", { calls: 2, input_tokens: 10, output_tokens: 5 });
  assert.deepEqual(
    log.messages.map((message) => [message.kind, message.status]),
    [
      ["diagnosis", undefined],
      ["proposal", "replaced"],
      ["proposal", "accepted"],
    ],
  );
  assert.equal(log.openProposal, null);
  assert.equal(log.mode, "advisor");
  assert.equal(log.active, true);
  assert.deepEqual(segmentMarkers(log.segments), [{ x: 10.5, label: "NLOPT_COBYLA", title: "switch_algorithm" }]);
  log.apply("copilot.summary", { stop_reason: "completed", segments: log.segments, calls: 3, usage: { input_tokens: 20 } });
  assert.deepEqual(log.usage, { calls: 3, input_tokens: 20 });
});

test("the log of a finished run, from its journal", () => {
  const log = CopilotLog.fromJournal([
    { kind: "status", state: "started", mode: "advisor" },
    { kind: "call", trigger: "start" },
    { kind: "answer", trigger: "start", evaluation: 0, text: "", decision: { diagnosis: "Fine so far." } },
    { kind: "segment", index: 0, algo_name: "SLSQP", first_evaluation: 0 },
    { kind: "answer", trigger: "periodic", evaluation: 6, decision: SWITCH },
    { kind: "proposal", id: "p1", decision: SWITCH, evaluation: 6 },
    { kind: "user", command: "copilot.accept", params: { id: "p1" } },
    { kind: "proposal_closed", id: "p1", how: "accepted" },
    { kind: "decision", decision: SWITCH },
    { kind: "segment", index: 1, algo_name: "NLOPT_COBYLA", first_evaluation: 7 },
    { kind: "status", state: "finished", stop_reason: "completed", segments: [], calls: 2, usage: { input_tokens: 9 } },
  ]);
  assert.deepEqual(
    log.messages.map((message) => [message.kind, message.status, message.text]),
    [
      ["diagnosis", undefined, "Fine so far."],
      ["proposal", "accepted", "SLSQP zigzags."],
      ["decision", undefined, "SLSQP zigzags."],
    ],
  );
  assert.equal(log.state, "off");
  assert.equal(log.reason, "completed");
  assert.deepEqual(log.usage, { calls: 2, input_tokens: 9 });
});

test("questions, answers and the report", () => {
  const log = new CopilotLog();
  log.apply("copilot.message", { kind: "answer", text: "Because of c_1.", question: "Why?", trigger: "question", evaluation: 4 });
  log.apply("copilot.message", { kind: "report", text: "# The run" });
  assert.equal(log.messages[0].question, "Why?");
  assert.equal(log.report, "# The run");
  const finished = CopilotLog.fromJournal([
    { kind: "status", state: "started", mode: "pilot" },
    { kind: "user", command: "copilot.ask", params: { text: "Why?" } },
    { kind: "answer", trigger: "question", question: "Why?", text: "Because of c_1.", evaluation: 4 },
    { kind: "answer", trigger: "report", text: "# The run" },
    { kind: "user", command: "ask", params: { text: "And now?" } },
    { kind: "answer", trigger: "question", question: "And now?", text: "Try COBYLA." },
  ]);
  assert.deepEqual(
    finished.messages.map((message) => [message.kind, message.question, message.text]),
    [
      ["answer", "Why?", "Because of c_1."],
      ["report", undefined, "# The run"],
      ["answer", "And now?", "Try COBYLA."],
    ],
  );
  assert.equal(finished.report, "# The run");
});

test("the actions that apply to a driver", () => {
  const ids = (/** @type {string} */ kind, formulation = "") => actionsFor(kind, formulation).map((action) => action.id);
  assert.deepEqual(ids("doe"), ["add_samples", "stop"]);
  assert.deepEqual(ids("optimization"), [
    "change_settings",
    "change_design_space",
    "switch_algorithm",
    "stop",
    "restart",
    "steer",
  ]);
  assert.ok(ids("optimization", "BiLevel").includes("change_sub_scenario"));
  assert.deepEqual(ids("parametric"), []);
});

test("what a DOE or BiLevel decision does", () => {
  const more = {
    kind: "add_samples",
    algo_name: "LHS",
    n_samples: 4,
    region: [{ name: "x", lower: 0.5, upper: 1.5 }],
  };
  assert.equal(actionText({ action: more }), "Add 4 samples with LHS where x in [0.5, 1.5]");
  const retune = { kind: "change_sub_scenario", scenario: "Wing", algo_name: "COBYLA", settings: { max_iter: 5 } };
  assert.equal(actionText({ action: retune }), "In Wing, switch to COBYLA, set max_iter = 5");
});

test("what a restart or a steering does", () => {
  const restart = {
    kind: "restart",
    base: "best",
    transforms: [{ kind: "set_region" }],
    answers: "The corner concentrates the stress.",
  };
  assert.equal(actionText({ action: restart }), "Restart from the best design, set_region: The corner concentrates the stress.");
  const steer = { kind: "steer", toward: "Solid arms.", anticipate: { factor: 1.5 }, variables: [{ name: "x" }] };
  assert.equal(actionText({ action: steer }), "Steer the design: anticipate the trend ×1.5, set x (Solid arms.)");
});

test("the outer iterations of the large-scale optimizer", () => {
  const log = new CopilotLog();
  log.apply("copilot.algorithm", { iteration: 1, working_set: 400, rows_computed: 400 });
  log.apply("copilot.algorithm", { iteration: 2, working_set: 300, rows_computed: 250 });
  log.apply("copilot.algorithm", { iteration: 2, working_set: 310, rows_computed: 260 });
  assert.equal(log.algorithm.length, 2);
  assert.deepEqual(workingSetSeries(log.algorithm), {
    workingSet: [
      { x: 1, y: 400 },
      { x: 2, y: 310 },
    ],
    rows: [
      { x: 1, y: 400 },
      { x: 2, y: 260 },
    ],
  });
  const finished = CopilotLog.fromJournal([
    { kind: "status", state: "started", mode: "pilot" },
    { kind: "algorithm", iteration: 1, working_set: 400, rows_computed: 400 },
    { kind: "decision", decision: { diagnosis: "Wider margin.", action: { kind: "change_settings" } }, live: true },
  ]);
  assert.equal(finished.algorithm.length, 1);
  assert.equal(finished.messages[0].text, "Wider margin.");
});

test("the models and efforts offered", () => {
  const ids = MODELS.map((model) => model.id);
  assert.ok(ids.includes("claude-opus-5-5") && ids.includes("claude-sonnet-5"));
  assert.equal(DEFAULT_MODEL, "claude-opus-5-5");
  assert.deepEqual(
    EFFORTS.map((effort) => effort.id),
    ["low", "medium", "high", "xhigh", "max"],
  );
  // A model saved before, not in the list, stays offered.
  assert.equal(withValue(MODELS, "claude-opus-5-5"), MODELS);
  assert.deepEqual(withValue(MODELS, "my-model").at(-1), { id: "my-model", label: "my-model" });
});
