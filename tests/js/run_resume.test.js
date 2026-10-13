import assert from "node:assert/strict";
import { test } from "node:test";

import { canResume, statusText } from "../../gemseo_process_builder/static/js/lib/run_resume.js";

test("only runs that ended without completing can be resumed", () => {
  assert.deepEqual(
    ["completed", "running", "failed", "stopped", "killed"].map((status) => canResume({ status })),
    [false, false, true, true, true],
  );
  assert.equal(canResume({ status: "killed", missing: true }), false);
});

test("a resumed run names the run it resumes", () => {
  assert.equal(statusText({ status: "running" }), "running");
  assert.equal(statusText({ status: "completed", resumed_from: "r-1" }), "completed (resumes r-1)");
});
