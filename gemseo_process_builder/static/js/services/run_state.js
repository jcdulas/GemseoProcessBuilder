// @ts-check
// The runs of the session as the page sees them: status, events and logs.
import { RunAccumulator } from "../lib/run_accumulator.js";
import { nodeStates } from "../lib/status_aggregation.js";

/**
 * @typedef {object} RunRecord
 * @property {any} info - ``run.json`` content (id, driver, driver_name, status…).
 * @property {RunAccumulator} data
 * @property {number} startedAt - ``performance.now()`` when the page saw it start.
 * @property {number | null} finishedAt
 */

const ACTIVE = new Set(["preparing", "running"]);

export class RunStates {
  /**
   * @param {import("../lib/rpc.js").RpcClient} api
   * @param {import("../store.js").DocumentStore} store
   */
  constructor(api, store) {
    this.store = store;
    /** @type {Map<string, RunRecord>} */
    this.runs = new Map();
    /** @type {string | null} */
    this.currentId = null;
    /** @type {Set<(record: RunRecord) => void>} */
    this.listeners = new Set();
    /** @type {Set<(runId: string, line: import("../lib/log_buffer.js").LogLine) => void>} */
    this.logListeners = new Set();
    /** @type {Set<string>} */
    this.changed = new Set();
    /** @type {Map<string, import("../lib/status_aggregation.js").RunState>} */
    this.cachedStates = new Map();

    api.on("run.started", (/** @type {any} */ info) => {
      this.runs.set(info.id, {
        info,
        data: new RunAccumulator(),
        startedAt: performance.now(),
        finishedAt: null,
      });
      this.currentId = info.id;
      this.touch(info.id);
    });
    const updated = (/** @type {any} */ info) => {
      const record = this.runs.get(info.id);
      if (record) {
        record.info = info;
        if (!ACTIVE.has(info.status)) {
          record.finishedAt ??= performance.now();
        }
        this.touch(info.id);
      }
    };
    api.on("run.updated", updated);
    api.on("run.finished", updated);
    api.on("run.event", (/** @type {any} */ message) => {
      const record = this.runs.get(message.run_id);
      if (record) {
        record.data.apply(message.event, message.payload);
        this.touch(message.run_id);
      }
    });
    api.on("run.log", (/** @type {any} */ message) => {
      const line = {
        time: Date.now() / 1000,
        level: message.level,
        source: `run:${message.run_id}`,
        logger: "run",
        message: message.message,
      };
      for (const listener of this.logListeners) {
        listener(message.run_id, line);
      }
    });
  }

  /** @param {string} runId */
  touch(runId) {
    if (!this.changed.size) {
      requestAnimationFrame(() => this.notify());
    }
    this.changed.add(runId);
  }

  notify() {
    const changed = [...this.changed];
    this.changed.clear();
    this.cachedStates = this.computeStates();
    for (const runId of changed) {
      const record = this.runs.get(runId);
      if (record) {
        for (const listener of this.listeners) {
          listener(record);
        }
      }
    }
  }

  /** The run shown on the canvas: the last one started. */
  current() {
    return this.currentId ? (this.runs.get(this.currentId) ?? null) : null;
  }

  /** @param {RunRecord} record */
  isActive(record) {
    return ACTIVE.has(record.info.status);
  }

  computeStates() {
    const record = this.current();
    if (!record) {
      return new Map();
    }
    return nodeStates(
      this.store.rootId,
      (id) => {
        const node = this.store.node(id);
        return Array.isArray(node?.children) ? node.children : null;
      },
      record.data.states,
    );
  }

  /**
   * The execution state of a node in the current run, or ``null``.
   *
   * @param {string} id
   */
  stateOf(id) {
    return this.cachedStates.get(id) ?? null;
  }

  /** @param {(record: RunRecord) => void} listener - Called at most once per frame and run. */
  onChange(listener) {
    this.listeners.add(listener);
  }

  /** @param {(runId: string, line: import("../lib/log_buffer.js").LogLine) => void} listener */
  onLog(listener) {
    this.logListeners.add(listener);
  }
}
