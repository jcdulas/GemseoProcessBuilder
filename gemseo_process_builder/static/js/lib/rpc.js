// @ts-check
// Promise-based calls to Python and event dispatch, independent of QWebChannel.

/** An error returned by Python, or a local failure (timeout, bad reply). */
export class ApiError extends Error {
  /**
   * @param {string} code - One of the bridge error codes, or "timeout" / "bad_reply".
   * @param {string} message - A message meant for the user.
   * @param {unknown} [details] - Extra information (validation errors, traceback).
   */
  constructor(code, message, details = null) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.details = details;
  }
}

let counter = 0;

/** @returns {string} A unique request id. */
function defaultNewId() {
  counter += 1;
  if (globalThis.crypto?.randomUUID) {
    return globalThis.crypto.randomUUID();
  }
  return `request-${Date.now()}-${counter}`;
}

/**
 * @typedef {object} RpcOptions
 * @property {(text: string) => void} send - Sends a JSON request to Python.
 * @property {number} [timeoutMs] - Default timeout of a call.
 * @property {() => string} [newId] - Id generator.
 * @property {(fn: () => void, ms: number) => any} [setTimer]
 * @property {(handle: any) => void} [clearTimer]
 */

export class RpcClient {
  /** @param {RpcOptions} options */
  constructor({
    send,
    timeoutMs = 30000,
    newId = defaultNewId,
    setTimer = (fn, ms) => setTimeout(fn, ms),
    clearTimer = (handle) => clearTimeout(handle),
  }) {
    this.send = send;
    this.timeoutMs = timeoutMs;
    this.newId = newId;
    this.setTimer = setTimer;
    this.clearTimer = clearTimer;
    /** @type {Map<string, {resolve: (v: any) => void, reject: (e: ApiError) => void, timer: any, method: string}>} */
    this.pending = new Map();
    /** @type {Map<string, Set<(payload: any) => void>>} */
    this.listeners = new Map();
  }

  /**
   * Call a Python method.
   *
   * @param {string} method - The method name, like "project.open".
   * @param {object} [params] - The parameters.
   * @param {{timeout?: number}} [options]
   * @returns {Promise<any>} The result, or a rejection with an ApiError.
   */
  call(method, params = {}, { timeout = this.timeoutMs } = {}) {
    const id = this.newId();
    return new Promise((resolve, reject) => {
      const timer = this.setTimer(() => {
        this.pending.delete(id);
        reject(new ApiError("timeout", `${method} did not answer within ${timeout} ms.`));
      }, timeout);
      this.pending.set(id, { resolve, reject, timer, method });
      this.send(JSON.stringify({ id, method, params }));
    });
  }

  /**
   * Handle a reply received from Python.
   *
   * @param {string} text - The JSON reply.
   */
  handleReply(text) {
    let reply;
    try {
      reply = JSON.parse(text);
    } catch {
      console.error("Ignored a malformed reply:", text);
      return;
    }
    const call = this.pending.get(reply?.id);
    if (!call) {
      return;
    }
    this.pending.delete(reply.id);
    this.clearTimer(call.timer);
    if (reply.ok === true) {
      call.resolve(reply.result);
    } else if (reply.ok === false && reply.error) {
      call.reject(new ApiError(reply.error.code, reply.error.message, reply.error.details));
    } else {
      call.reject(new ApiError("bad_reply", `${call.method} sent a malformed reply.`));
    }
  }

  /**
   * Handle an event pushed by Python.
   *
   * @param {string} text - The JSON event.
   */
  handleEvent(text) {
    let event;
    try {
      event = JSON.parse(text);
    } catch {
      console.error("Ignored a malformed event:", text);
      return;
    }
    for (const listener of this.listeners.get(event?.type) ?? []) {
      try {
        listener(event.payload);
      } catch (error) {
        console.error(`Listener of ${event.type} failed:`, error);
      }
    }
  }

  /**
   * Listen to an event type.
   *
   * @param {string} type - The event type, like "document.patch".
   * @param {(payload: any) => void} listener
   * @returns {() => void} A function that stops listening.
   */
  on(type, listener) {
    if (!this.listeners.has(type)) {
      this.listeners.set(type, new Set());
    }
    this.listeners.get(type)?.add(listener);
    return () => this.listeners.get(type)?.delete(listener);
  }
}
