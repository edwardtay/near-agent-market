# @near-js/tx-builder

Transaction construction library for NEAR Protocol. Provides a fluent, chainable API for building, signing, and sending NEAR transactions.

Built on top of `near-api-js` v7.

## Install

```bash
npm install @near-js/tx-builder
```

## Quick Start

```js
import TransactionBuilder from "@near-js/tx-builder";

const tx = new TransactionBuilder({
  signerId: "alice.testnet",
  privateKey: "ed25519:5nM...",
  network: "testnet",
});

// Send NEAR
const result = await tx.transfer("bob.testnet", "1.5").send();
```

## API

### Constructor

```js
new TransactionBuilder({
  signerId: "alice.testnet",    // Required: sender account ID
  privateKey: "ed25519:...",    // Private key for signing/sending
  publicKey: "ed25519:...",     // Public key (alternative to privateKey, for offline signing)
  rpcUrl: "https://rpc.mainnet.near.org",  // Custom RPC endpoint
  network: "testnet",          // "mainnet" or "testnet" (ignored if rpcUrl is set)
});
```

### Transfer

```js
await tx.transfer("bob.testnet", "1.5").send();
```

### Function Call

```js
await tx
  .functionCall(
    "contract.testnet",  // contract
    "set_greeting",      // method
    { greeting: "hi" },  // args
    "30",                // gas in TGas (default: "30")
    "0.1"                // deposit in NEAR (default: "0")
  )
  .send();
```

### Staking

```js
await tx.stake("100", "ed25519:validator_public_key").send();
```

### Delete Account

```js
await tx.deleteAccount("beneficiary.testnet").send();
```

### Access Keys

```js
// Add full-access key
await tx.addKey("ed25519:new_public_key").send();

// Add function-call access key
await tx
  .addKey("ed25519:new_public_key", {
    contractId: "contract.testnet",
    methodNames: ["method_a", "method_b"],
    allowance: "1", // in NEAR
  })
  .send();

// Delete a key
await tx.deleteKey("ed25519:old_public_key").send();
```

### Batch Transactions

Send multiple actions to a single receiver in one transaction:

```js
const result = await tx
  .batch("contract.testnet")
  .functionCall("init", { owner: "alice.testnet" }, "50", "5")
  .addFullAccessKey("ed25519:new_key")
  .transfer("0.5")
  .send();
```

The batch builder supports all action types:
- `.transfer(amount)`
- `.functionCall(method, args, gas, deposit)`
- `.stake(amount, publicKey)`
- `.addFullAccessKey(publicKey)`
- `.addFunctionCallAccessKey(publicKey, contractId, methodNames, allowance)`
- `.deleteKey(publicKey)`
- `.deleteAccount(beneficiaryId)`
- `.createAccount()`
- `.deployContract(wasmBytes)`

Call `.end()` to return to the parent builder, or call `.serialize()` / `.sign()` / `.send()` directly on the batch.

### Offline Signing

Build and sign transactions without sending them:

```js
// Build with only a public key (no private key needed yet)
const builder = new TransactionBuilder({
  signerId: "alice.testnet",
  publicKey: "ed25519:...",
  network: "testnet",
});

// Serialize unsigned transaction to base64
const base64Tx = await builder.transfer("bob.testnet", "1.5").serialize();

// Later, sign with a private key
const { signedTransaction, hash } = await builder
  .transfer("bob.testnet", "1.5")
  .sign("ed25519:private_key...");
```

### Sending a Signed Transaction

```js
// Sign offline, send later
const { signedTransaction } = await tx.transfer("bob.testnet", "1").sign();

// Send to a different RPC endpoint
const result = await tx.transfer("bob.testnet", "1").send("https://rpc.mainnet.near.org");
```

### Reusing the Builder

Call `.reset()` to clear pending actions and reuse the builder:

```js
const builder = new TransactionBuilder({
  signerId: "alice.testnet",
  privateKey: "ed25519:...",
  network: "testnet",
});

await builder.transfer("bob.testnet", "1").send();
builder.reset();
await builder.functionCall("contract.testnet", "do_thing", {}).send();
```

## Networks

| Network  | Default RPC                          |
|----------|--------------------------------------|
| testnet  | `https://rpc.testnet.near.org`       |
| mainnet  | `https://rpc.mainnet.near.org`       |

Pass a custom `rpcUrl` to override. Falls back to testnet if no network or URL is specified.

## License

MIT
