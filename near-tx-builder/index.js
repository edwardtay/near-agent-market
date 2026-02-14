import {
  Account,
  JsonRpcProvider,
  KeyPairSigner,
  KeyPair,
  actions,
  nearToYocto,
  teraToGas,
} from "near-api-js";

const DEFAULT_GAS = teraToGas("30");
const DEFAULT_DEPOSIT = "0";
const MAINNET_RPC = "https://rpc.mainnet.near.org";
const TESTNET_RPC = "https://rpc.testnet.near.org";

/**
 * Fluent transaction builder for NEAR Protocol.
 *
 * Wraps near-api-js v7 to provide a chainable API for constructing,
 * signing, and sending transactions.
 */
class TransactionBuilder {
  #signerId;
  #provider;
  #privateKey;
  #publicKey;
  #pendingActions = [];
  #receiverId = null;
  #batchMode = false;

  /**
   * @param {object} opts
   * @param {string} opts.signerId   - The signer's NEAR account ID.
   * @param {string} opts.rpcUrl     - RPC endpoint URL.
   * @param {string} [opts.privateKey] - ed25519 private key string (e.g. "ed25519:5nM...").
   * @param {string} [opts.publicKey]  - Public key string, required if privateKey is omitted (offline signing).
   * @param {string} [opts.network]    - "mainnet" or "testnet". Ignored when rpcUrl is provided.
   */
  constructor({ signerId, rpcUrl, privateKey, publicKey, network } = {}) {
    if (!signerId) throw new Error("signerId is required");

    this.#signerId = signerId;

    const resolvedRpc =
      rpcUrl ||
      (network === "mainnet" ? MAINNET_RPC : null) ||
      (network === "testnet" ? TESTNET_RPC : null) ||
      TESTNET_RPC;

    this.#provider = new JsonRpcProvider({ url: resolvedRpc });

    if (privateKey) {
      this.#privateKey = privateKey;
      const kp = KeyPair.fromString(privateKey);
      this.#publicKey = kp.getPublicKey().toString();
    } else if (publicKey) {
      this.#publicKey = publicKey;
    }
  }

  // ---------------------------------------------------------------------------
  // Single-action convenience methods
  // ---------------------------------------------------------------------------

  /**
   * Build a NEAR transfer transaction.
   *
   * @param {string} receiverId - Recipient account ID.
   * @param {string} amount     - Amount in NEAR (e.g. "1.5").
   * @returns {TransactionBuilder}
   */
  transfer(receiverId, amount) {
    this.#receiverId = receiverId;
    this.#pendingActions.push(actions.transfer(nearToYocto(amount)));
    return this;
  }

  /**
   * Build a function call transaction.
   *
   * @param {string} receiverId - Contract account ID.
   * @param {string} methodName - Method to call.
   * @param {object} args       - JSON-serializable arguments.
   * @param {string} [gas]      - Gas in TGas (default "30").
   * @param {string} [deposit]  - Attached deposit in NEAR (default "0").
   * @returns {TransactionBuilder}
   */
  functionCall(receiverId, methodName, args = {}, gas = "30", deposit = "0") {
    this.#receiverId = receiverId;
    this.#pendingActions.push(
      actions.functionCall(
        methodName,
        args,
        teraToGas(gas),
        nearToYocto(deposit)
      )
    );
    return this;
  }

  /**
   * Build a staking transaction.
   *
   * @param {string} amount    - Amount in NEAR to stake.
   * @param {string} publicKey - Validator public key string.
   * @returns {TransactionBuilder}
   */
  stake(amount, publicKey) {
    this.#receiverId = this.#signerId;
    this.#pendingActions.push(actions.stake(nearToYocto(amount), publicKey));
    return this;
  }

  /**
   * Build a delete-account transaction.
   *
   * @param {string} beneficiaryId - Account that receives remaining balance.
   * @returns {TransactionBuilder}
   */
  deleteAccount(beneficiaryId) {
    this.#receiverId = this.#signerId;
    this.#pendingActions.push(actions.deleteAccount(beneficiaryId));
    return this;
  }

  /**
   * Add a full-access key to the signer account.
   *
   * @param {string} publicKey - Public key to add.
   * @param {object} [accessKey] - Optional access key permissions.
   * @param {string} [accessKey.contractId] - If set, creates a function-call access key.
   * @param {string[]} [accessKey.methodNames] - Allowed methods (empty = all).
   * @param {string} [accessKey.allowance] - Allowance in NEAR.
   * @returns {TransactionBuilder}
   */
  addKey(publicKey, accessKey) {
    this.#receiverId = this.#signerId;
    if (accessKey && accessKey.contractId) {
      this.#pendingActions.push(
        actions.addFunctionCallAccessKey(
          publicKey,
          accessKey.contractId,
          accessKey.methodNames || [],
          accessKey.allowance ? nearToYocto(accessKey.allowance) : undefined
        )
      );
    } else {
      this.#pendingActions.push(actions.addFullAccessKey(publicKey));
    }
    return this;
  }

  /**
   * Delete an access key from the signer account.
   *
   * @param {string} publicKey - Public key to remove.
   * @returns {TransactionBuilder}
   */
  deleteKey(publicKey) {
    this.#receiverId = this.#signerId;
    this.#pendingActions.push(actions.deleteKey(publicKey));
    return this;
  }

  // ---------------------------------------------------------------------------
  // Batch transaction support
  // ---------------------------------------------------------------------------

  /**
   * Start a batch transaction. Chain action methods after this,
   * then call .serialize(), .sign(), or .send().
   *
   * @param {string} receiverId - Target account for all actions.
   * @returns {BatchBuilder}
   */
  batch(receiverId) {
    return new BatchBuilder(this, receiverId);
  }

  // ---------------------------------------------------------------------------
  // Internal: accept batch actions
  // ---------------------------------------------------------------------------

  /** @internal */
  _applyBatch(receiverId, batchActions) {
    this.#receiverId = receiverId;
    this.#pendingActions.push(...batchActions);
    return this;
  }

  // ---------------------------------------------------------------------------
  // Serialize / Sign / Send
  // ---------------------------------------------------------------------------

  /**
   * Create the unsigned transaction object.
   *
   * @returns {Promise<object>} The unsigned NEAR transaction.
   */
  async buildTransaction() {
    if (!this.#receiverId) {
      throw new Error("No actions added. Call transfer(), functionCall(), etc. first.");
    }
    if (!this.#publicKey) {
      throw new Error("publicKey or privateKey is required to build a transaction.");
    }

    const account = new Account(this.#signerId, this.#provider);
    const tx = await account.createTransaction({
      receiverId: this.#receiverId,
      actions: this.#pendingActions,
      publicKey: this.#publicKey,
    });
    return tx;
  }

  /**
   * Serialize the unsigned transaction to a base64 string.
   *
   * @returns {Promise<string>} Base64-encoded transaction bytes.
   */
  async serialize() {
    const tx = await this.buildTransaction();
    const bytes = tx.encode();
    return Buffer.from(bytes).toString("base64");
  }

  /**
   * Sign the transaction with the configured private key.
   *
   * @param {string} [keyPair] - Optional private key override (ed25519 string).
   * @returns {Promise<object>} Object with { signedTransaction, hash }.
   */
  async sign(keyPair) {
    const key = keyPair || this.#privateKey;
    if (!key) {
      throw new Error("Private key is required. Pass it to the constructor or sign().");
    }

    const tx = await this.buildTransaction();
    const signer = KeyPairSigner.fromSecretKey(key);
    const result = await signer.signTransaction(tx);
    return result;
  }

  /**
   * Sign and send the transaction to the network.
   *
   * @param {string} [rpcUrl] - Optional RPC endpoint override.
   * @returns {Promise<object>} The transaction outcome from the RPC.
   */
  async send(rpcUrl) {
    if (!this.#privateKey) {
      throw new Error("Private key is required to send transactions.");
    }

    const provider = rpcUrl
      ? new JsonRpcProvider({ url: rpcUrl })
      : this.#provider;

    const account = new Account(this.#signerId, provider, this.#privateKey);

    const result = await account.signAndSendTransaction({
      receiverId: this.#receiverId,
      actions: this.#pendingActions,
    });

    return result;
  }

  /**
   * Reset all pending actions so the builder can be reused.
   *
   * @returns {TransactionBuilder}
   */
  reset() {
    this.#pendingActions = [];
    this.#receiverId = null;
    return this;
  }
}

/**
 * Helper for constructing batch transactions with multiple actions
 * sent to a single receiver.
 */
class BatchBuilder {
  #parent;
  #receiverId;
  #actions = [];

  /** @internal */
  constructor(parent, receiverId) {
    this.#parent = parent;
    this.#receiverId = receiverId;
  }

  /**
   * Add a transfer action.
   * @param {string} amount - Amount in NEAR.
   * @returns {BatchBuilder}
   */
  transfer(amount) {
    this.#actions.push(actions.transfer(nearToYocto(amount)));
    return this;
  }

  /**
   * Add a function call action.
   * @param {string} methodName
   * @param {object} args
   * @param {string} [gas="30"]
   * @param {string} [deposit="0"]
   * @returns {BatchBuilder}
   */
  functionCall(methodName, args = {}, gas = "30", deposit = "0") {
    this.#actions.push(
      actions.functionCall(
        methodName,
        args,
        teraToGas(gas),
        nearToYocto(deposit)
      )
    );
    return this;
  }

  /**
   * Add a stake action.
   * @param {string} amount
   * @param {string} publicKey
   * @returns {BatchBuilder}
   */
  stake(amount, publicKey) {
    this.#actions.push(actions.stake(nearToYocto(amount), publicKey));
    return this;
  }

  /**
   * Add a full-access key.
   * @param {string} publicKey
   * @returns {BatchBuilder}
   */
  addFullAccessKey(publicKey) {
    this.#actions.push(actions.addFullAccessKey(publicKey));
    return this;
  }

  /**
   * Add a function-call access key.
   * @param {string} publicKey
   * @param {string} contractId
   * @param {string[]} [methodNames=[]]
   * @param {string} [allowance]
   * @returns {BatchBuilder}
   */
  addFunctionCallAccessKey(publicKey, contractId, methodNames = [], allowance) {
    this.#actions.push(
      actions.addFunctionCallAccessKey(
        publicKey,
        contractId,
        methodNames,
        allowance ? nearToYocto(allowance) : undefined
      )
    );
    return this;
  }

  /**
   * Add a delete-key action.
   * @param {string} publicKey
   * @returns {BatchBuilder}
   */
  deleteKey(publicKey) {
    this.#actions.push(actions.deleteKey(publicKey));
    return this;
  }

  /**
   * Add a delete-account action.
   * @param {string} beneficiaryId
   * @returns {BatchBuilder}
   */
  deleteAccount(beneficiaryId) {
    this.#actions.push(actions.deleteAccount(beneficiaryId));
    return this;
  }

  /**
   * Add a create-account action.
   * @returns {BatchBuilder}
   */
  createAccount() {
    this.#actions.push(actions.createAccount());
    return this;
  }

  /**
   * Add a deploy-contract action.
   * @param {Uint8Array} code - WASM bytes.
   * @returns {BatchBuilder}
   */
  deployContract(code) {
    this.#actions.push(actions.deployContract(code));
    return this;
  }

  /**
   * Finalize the batch and return the parent builder, ready for
   * .serialize(), .sign(), or .send().
   *
   * @returns {TransactionBuilder}
   */
  end() {
    if (this.#actions.length === 0) {
      throw new Error("Batch has no actions. Add at least one action before calling end().");
    }
    return this.#parent._applyBatch(this.#receiverId, this.#actions);
  }

  /** Shortcut: finalize and serialize. */
  async serialize() {
    return this.end().serialize();
  }

  /** Shortcut: finalize and sign. */
  async sign(keyPair) {
    return this.end().sign(keyPair);
  }

  /** Shortcut: finalize and send. */
  async send(rpcUrl) {
    return this.end().send(rpcUrl);
  }
}

export { TransactionBuilder, BatchBuilder };
export default TransactionBuilder;
