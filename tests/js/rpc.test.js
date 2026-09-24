import assert from "node:assert/strict";
import { test } from "node:test";

import { ApiError, RpcClient } from "../../gemseo_process_builder/static/js/lib/rpc.js";

/** A client with a fake transport and manual timers. */
function makeClient() {
  const sent = [];
  const timers = new Map();
  let nextTimer = 0;
  let nextId = 0;
  const client = new RpcClient({
    send: (text) => sent.push(JSON.parse(text)),
    newId: () => `id-${++nextId}`,
    setTimer: (fn) => {
      nextTimer += 1;
      timers.set(nextTimer, fn);
      return nextTimer;
    },
    clearTimer: (handle) => timers.delete(handle),
  });
  return { client, sent, timers };
}

test("call sends a request and resolves with the result", async () => {
  const { client, sent } = makeClient();
  const promise = client.call("math.add", { a: 1, b: 2 });
  assert.deepEqual(sent[0], { id: "id-1", method: "math.add", params: { a: 1, b: 2 } });
  client.handleReply(JSON.stringify({ id: "id-1", ok: true, result: 3 }));
  assert.equal(await promise, 3);
});

test("error replies reject with an ApiError", async () => {
  const { client } = makeClient();
  const promise = client.call("nope");
  client.handleReply(
    JSON.stringify({ id: "id-1", ok: false, error: { code: "unknown_method", message: "Unknown", details: null } }),
  );
  await assert.rejects(promise, (error) => error instanceof ApiError && error.code === "unknown_method");
});

test("a call times out and its late reply is ignored", async () => {
  const { client, timers } = makeClient();
  const promise = client.call("slow");
  [...timers.values()][0]();
  await assert.rejects(promise, (error) => error.code === "timeout");
  client.handleReply(JSON.stringify({ id: "id-1", ok: true, result: 1 }));
  assert.equal(client.pending.size, 0);
});

test("a reply clears the timeout", async () => {
  const { client, timers } = makeClient();
  const promise = client.call("fast");
  client.handleReply(JSON.stringify({ id: "id-1", ok: true, result: null }));
  await promise;
  assert.equal(timers.size, 0);
});

test("malformed replies are ignored or rejected", async () => {
  const { client } = makeClient();
  const promise = client.call("x");
  client.handleReply("not json");
  assert.equal(client.pending.size, 1);
  client.handleReply(JSON.stringify({ id: "id-1" }));
  await assert.rejects(promise, (error) => error.code === "bad_reply");
});

test("events reach their listeners until they unsubscribe", () => {
  const { client } = makeClient();
  const received = [];
  const stop = client.on("document.patch", (payload) => received.push(payload));
  client.on("other", () => received.push("wrong"));
  client.handleEvent(JSON.stringify({ type: "document.patch", payload: { rev: 1 } }));
  stop();
  client.handleEvent(JSON.stringify({ type: "document.patch", payload: { rev: 2 } }));
  assert.deepEqual(received, [{ rev: 1 }]);
});

test("a failing listener does not stop the others", () => {
  const { client } = makeClient();
  const received = [];
  const originalError = console.error;
  console.error = () => {};
  client.on("e", () => {
    throw new Error("boom");
  });
  client.on("e", (payload) => received.push(payload));
  client.handleEvent(JSON.stringify({ type: "e", payload: 1 }));
  console.error = originalError;
  assert.deepEqual(received, [1]);
});

test("the default timers work when called as methods", async () => {
  const client = new RpcClient({ send: () => {}, timeoutMs: 5 });
  await assert.rejects(client.call("never"), (error) => error.code === "timeout");
});
