// @ts-check
// Connects the page to the Python bridge through QWebChannel.
import { RpcClient } from "./lib/rpc.js";

export { ApiError } from "./lib/rpc.js";

/** @type {RpcClient | null} */
let client = null;

/**
 * Connect to Python. Resolves once the `bridge` object is available.
 *
 * @returns {Promise<RpcClient>} The client used to call Python and listen to events.
 */
export function connect() {
  if (client) {
    return Promise.resolve(client);
  }
  const w = /** @type {any} */ (window);
  return new Promise((resolve, reject) => {
    if (!w.qt?.webChannelTransport || !w.QWebChannel) {
      reject(new Error("QWebChannel is not available: the page must run inside the application."));
      return;
    }
    new w.QWebChannel(w.qt.webChannelTransport, (/** @type {any} */ channel) => {
      const bridge = channel.objects.bridge;
      const rpc = new RpcClient({ send: (text) => bridge.call(text) });
      bridge.reply.connect((/** @type {string} */ text) => rpc.handleReply(text));
      bridge.page_event.connect((/** @type {string} */ text) => rpc.handleEvent(text));
      client = rpc;
      w.api = rpc; // Handy from the DevTools console.
      resolve(rpc);
    });
  });
}
