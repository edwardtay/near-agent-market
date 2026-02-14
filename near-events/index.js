"use strict";

const DEFAULT_POLL_INTERVAL_MS = 1000;
const DEFAULT_RPC_URL = "https://rpc.mainnet.near.org";

/**
 * Parse NEP-297 standard events from NEAR transaction logs.
 *
 * NEP-297 format: EVENT_JSON:{"standard":"...","version":"...","event":"...","data":[...]}
 *
 * @param {string[]} logs - Array of log strings from a receipt outcome
 * @returns {object[]} Parsed event objects
 */
function parseNep297Logs(logs) {
  const events = [];
  for (const log of logs) {
    if (!log.startsWith("EVENT_JSON:")) continue;
    try {
      const json = JSON.parse(log.slice("EVENT_JSON:".length));
      if (json.event) {
        events.push(json);
      }
    } catch {
      // Not valid JSON - skip
    }
  }
  return events;
}

/**
 * Make a JSON-RPC call to a NEAR RPC node.
 */
async function rpcCall(url, method, params) {
  const res = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: "events", method, params }),
  });
  if (!res.ok) {
    throw new Error(`RPC request failed: ${res.status} ${res.statusText}`);
  }
  const body = await res.json();
  if (body.error) {
    throw new Error(`RPC error: ${body.error.message || JSON.stringify(body.error)}`);
  }
  return body.result;
}

class NearEventListener {
  /**
   * @param {object} [options]
   * @param {string} [options.rpcUrl] - NEAR RPC endpoint
   * @param {number} [options.pollIntervalMs] - Polling interval in milliseconds
   * @param {string} [options.network] - "mainnet" | "testnet" (sets default RPC URL)
   */
  constructor(options = {}) {
    const network = options.network || "mainnet";
    if (options.rpcUrl) {
      this._rpcUrl = options.rpcUrl;
    } else if (network === "testnet") {
      this._rpcUrl = "https://rpc.testnet.near.org";
    } else {
      this._rpcUrl = DEFAULT_RPC_URL;
    }

    this._pollIntervalMs = options.pollIntervalMs || DEFAULT_POLL_INTERVAL_MS;
    this._running = false;
    this._timer = null;
    this._lastBlockHeight = null;

    // Map<contractId, Map<eventName | "*", Set<callback>>>
    this._listeners = new Map();

    // Accumulated errors for diagnostics
    this._consecutiveErrors = 0;
    this._maxConsecutiveErrors = 10;
  }

  /**
   * Listen for a specific NEP-297 event from a contract.
   *
   * @param {string} contractId - The NEAR account ID of the contract
   * @param {string} eventName - The event name to match (the "event" field in NEP-297)
   * @param {function} callback - Called with (event, context) where context includes receiptId, blockHeight, contractId
   * @returns {function} Unsubscribe function
   */
  on(contractId, eventName, callback) {
    if (typeof callback !== "function") {
      throw new TypeError("callback must be a function");
    }
    if (!this._listeners.has(contractId)) {
      this._listeners.set(contractId, new Map());
    }
    const contractMap = this._listeners.get(contractId);
    if (!contractMap.has(eventName)) {
      contractMap.set(eventName, new Set());
    }
    contractMap.get(eventName).add(callback);

    return () => {
      const cMap = this._listeners.get(contractId);
      if (!cMap) return;
      const eSet = cMap.get(eventName);
      if (!eSet) return;
      eSet.delete(callback);
      if (eSet.size === 0) cMap.delete(eventName);
      if (cMap.size === 0) this._listeners.delete(contractId);
    };
  }

  /**
   * Listen for all events from a contract.
   *
   * @param {string} contractId - The NEAR account ID of the contract
   * @param {function} callback - Called with (event, context)
   * @returns {function} Unsubscribe function
   */
  onAll(contractId, callback) {
    return this.on(contractId, "*", callback);
  }

  /**
   * Start polling for new blocks and processing events.
   *
   * @param {string} [rpcUrl] - Override the RPC URL (optional, uses constructor value otherwise)
   * @returns {Promise<void>}
   */
  async start(rpcUrl) {
    if (rpcUrl) {
      this._rpcUrl = rpcUrl;
    }
    if (this._running) return;
    this._running = true;
    this._consecutiveErrors = 0;

    // Get the current block height as starting point
    if (this._lastBlockHeight === null) {
      const status = await rpcCall(this._rpcUrl, "status", []);
      this._lastBlockHeight = status.sync_info.latest_block_height;
    }

    this._poll();
  }

  /**
   * Stop polling.
   */
  stop() {
    this._running = false;
    if (this._timer) {
      clearTimeout(this._timer);
      this._timer = null;
    }
  }

  /**
   * Whether the listener is currently running.
   * @returns {boolean}
   */
  get running() {
    return this._running;
  }

  /**
   * Fetch historical events for a contract within a block range.
   *
   * @param {string} contractId - The contract account ID
   * @param {object} [options]
   * @param {number} [options.fromBlock] - Start block height (inclusive)
   * @param {number} [options.toBlock] - End block height (inclusive, defaults to latest)
   * @param {string} [options.eventName] - Filter by event name
   * @param {number} [options.limit] - Max number of events to return (default 100)
   * @returns {Promise<object[]>} Array of { event, context } objects
   */
  async getHistory(contractId, options = {}) {
    const limit = options.limit || 100;
    const eventName = options.eventName || null;

    // Determine block range
    const status = await rpcCall(this._rpcUrl, "status", []);
    const latestHeight = status.sync_info.latest_block_height;
    const toBlock = options.toBlock || latestHeight;
    const fromBlock = options.fromBlock || Math.max(toBlock - 999, 0);

    const results = [];

    for (let height = fromBlock; height <= toBlock && results.length < limit; height++) {
      try {
        const events = await this._processBlockForContract(height, contractId, eventName);
        for (const item of events) {
          results.push(item);
          if (results.length >= limit) break;
        }
      } catch {
        // Block may not exist or chunk unavailable - skip
      }
    }

    return results;
  }

  // ---- Internal methods ----

  /**
   * Main poll loop.
   * @private
   */
  async _poll() {
    if (!this._running) return;

    try {
      const status = await rpcCall(this._rpcUrl, "status", []);
      const latestHeight = status.sync_info.latest_block_height;

      // Process any blocks we missed
      while (this._lastBlockHeight < latestHeight && this._running) {
        this._lastBlockHeight++;
        try {
          await this._processBlock(this._lastBlockHeight);
        } catch {
          // Individual block failures are non-fatal (block may have been GC'd)
        }
      }

      this._consecutiveErrors = 0;
    } catch (err) {
      this._consecutiveErrors++;
      if (this._consecutiveErrors >= this._maxConsecutiveErrors) {
        this.stop();
        throw new Error(
          `Stopped after ${this._maxConsecutiveErrors} consecutive RPC errors. Last error: ${err.message}`
        );
      }
    }

    if (this._running) {
      this._timer = setTimeout(() => this._poll(), this._pollIntervalMs);
    }
  }

  /**
   * Process a single block: fetch the block, iterate chunks, extract matching receipts.
   * @private
   */
  async _processBlock(blockHeight) {
    const block = await rpcCall(this._rpcUrl, "block", { block_id: blockHeight });

    // Collect all watched contract IDs
    const watchedContracts = new Set(this._listeners.keys());
    if (watchedContracts.size === 0) return;

    for (const chunk of block.chunks) {
      if (chunk.height_included !== blockHeight) continue;

      let chunkDetail;
      try {
        chunkDetail = await rpcCall(this._rpcUrl, "chunk", { chunk_id: chunk.chunk_hash });
      } catch {
        continue;
      }

      // Process transactions in this chunk
      for (const tx of chunkDetail.transactions || []) {
        const receiverId = tx.receiver_id;
        if (!watchedContracts.has(receiverId)) continue;

        // Fetch the full transaction outcome to get logs
        let txOutcome;
        try {
          txOutcome = await rpcCall(this._rpcUrl, "EXPERIMENTAL_tx_status", {
            tx_hash: tx.hash,
            sender_account_id: tx.signer_id,
            wait_until: "EXECUTED",
          });
        } catch {
          continue;
        }

        this._extractEventsFromOutcome(txOutcome, watchedContracts, blockHeight);
      }
    }
  }

  /**
   * Extract NEP-297 events from a transaction outcome and dispatch to listeners.
   * @private
   */
  _extractEventsFromOutcome(txOutcome, watchedContracts, blockHeight) {
    const allOutcomes = [];

    // The transaction outcome itself
    if (txOutcome.transaction_outcome) {
      allOutcomes.push(txOutcome.transaction_outcome);
    }

    // Receipt outcomes (cross-contract calls, etc.)
    if (txOutcome.receipts_outcome) {
      allOutcomes.push(...txOutcome.receipts_outcome);
    }

    for (const outcome of allOutcomes) {
      const executorId = outcome.outcome?.executor_id;
      if (!executorId || !watchedContracts.has(executorId)) continue;

      const logs = outcome.outcome.logs || [];
      const events = parseNep297Logs(logs);

      for (const event of events) {
        const context = {
          receiptId: outcome.id,
          blockHeight,
          contractId: executorId,
          standard: event.standard,
          version: event.version,
        };

        this._dispatch(executorId, event, context);
      }
    }
  }

  /**
   * Dispatch a parsed event to matching listeners.
   * @private
   */
  _dispatch(contractId, event, context) {
    const contractMap = this._listeners.get(contractId);
    if (!contractMap) return;

    // Exact event name match
    const exactSet = contractMap.get(event.event);
    if (exactSet) {
      for (const cb of exactSet) {
        try {
          cb(event, context);
        } catch {
          // Listener errors should not crash the poller
        }
      }
    }

    // Wildcard listeners
    const wildcardSet = contractMap.get("*");
    if (wildcardSet) {
      for (const cb of wildcardSet) {
        try {
          cb(event, context);
        } catch {
          // Listener errors should not crash the poller
        }
      }
    }
  }

  /**
   * Process a single block looking for events from a specific contract (used by getHistory).
   * @private
   */
  async _processBlockForContract(blockHeight, contractId, eventNameFilter) {
    const block = await rpcCall(this._rpcUrl, "block", { block_id: blockHeight });
    const results = [];

    for (const chunk of block.chunks) {
      if (chunk.height_included !== blockHeight) continue;

      let chunkDetail;
      try {
        chunkDetail = await rpcCall(this._rpcUrl, "chunk", { chunk_id: chunk.chunk_hash });
      } catch {
        continue;
      }

      for (const tx of chunkDetail.transactions || []) {
        if (tx.receiver_id !== contractId) continue;

        let txOutcome;
        try {
          txOutcome = await rpcCall(this._rpcUrl, "EXPERIMENTAL_tx_status", {
            tx_hash: tx.hash,
            sender_account_id: tx.signer_id,
            wait_until: "EXECUTED",
          });
        } catch {
          continue;
        }

        const allOutcomes = [];
        if (txOutcome.transaction_outcome) allOutcomes.push(txOutcome.transaction_outcome);
        if (txOutcome.receipts_outcome) allOutcomes.push(...txOutcome.receipts_outcome);

        for (const outcome of allOutcomes) {
          if (outcome.outcome?.executor_id !== contractId) continue;
          const logs = outcome.outcome.logs || [];
          const events = parseNep297Logs(logs);

          for (const event of events) {
            if (eventNameFilter && event.event !== eventNameFilter) continue;
            results.push({
              event,
              context: {
                receiptId: outcome.id,
                blockHeight,
                contractId,
                standard: event.standard,
                version: event.version,
              },
            });
          }
        }
      }
    }

    return results;
  }
}

module.exports = { NearEventListener, parseNep297Logs };
