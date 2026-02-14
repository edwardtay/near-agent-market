# @near-js/events

Contract event listener for NEAR Protocol. Parses [NEP-297](https://nomicon.io/Standards/EventsFormat) standard events from on-chain transaction logs in real time.

## Install

```bash
npm install @near-js/events
```

Requires Node.js 18+ (uses native `fetch`).

## Quick Start

```js
const { NearEventListener } = require("@near-js/events");

const listener = new NearEventListener({
  network: "mainnet",       // or "testnet"
  pollIntervalMs: 1000,     // how often to check for new blocks
});

// Listen for a specific event
listener.on("wrap.near", "ft_transfer", (event, ctx) => {
  console.log("Transfer:", event.data);
  console.log("Block:", ctx.blockHeight, "Receipt:", ctx.receiptId);
});

// Listen for all events from a contract
listener.onAll("ref-finance-101.onboard-dao.near", (event, ctx) => {
  console.log(`${event.event}:`, event.data);
});

await listener.start();

// Later...
listener.stop();
```

## API

### `new NearEventListener(options?)`

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `rpcUrl` | `string` | (derived from network) | Custom NEAR RPC endpoint |
| `network` | `string` | `"mainnet"` | `"mainnet"` or `"testnet"` |
| `pollIntervalMs` | `number` | `1000` | Block polling interval in ms |

### `.on(contractId, eventName, callback)`

Subscribe to a specific NEP-297 event from a contract. Returns an unsubscribe function.

```js
const unsub = listener.on("contract.near", "nft_mint", (event, ctx) => {
  // event.standard, event.version, event.event, event.data
  // ctx.contractId, ctx.blockHeight, ctx.receiptId
});

// Stop listening for this event
unsub();
```

### `.onAll(contractId, callback)`

Subscribe to all events from a contract. Returns an unsubscribe function.

### `.start(rpcUrl?)`

Start polling for new blocks. Optionally override the RPC URL. Returns a promise that resolves once the initial block height is determined.

### `.stop()`

Stop polling.

### `.running`

Boolean indicating whether the listener is actively polling.

### `.getHistory(contractId, options?)`

Fetch historical events from past blocks.

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `fromBlock` | `number` | `toBlock - 999` | Start block height (inclusive) |
| `toBlock` | `number` | latest | End block height (inclusive) |
| `eventName` | `string` | all | Filter by event name |
| `limit` | `number` | `100` | Max events to return |

```js
const events = await listener.getHistory("wrap.near", {
  fromBlock: 100000000,
  toBlock: 100001000,
  eventName: "ft_transfer",
  limit: 50,
});
```

### `parseNep297Logs(logs)`

Low-level utility. Parse an array of log strings and return any valid NEP-297 event objects.

```js
const { parseNep297Logs } = require("@near-js/events");

const events = parseNep297Logs([
  'EVENT_JSON:{"standard":"nep171","version":"1.0.0","event":"nft_mint","data":[{"owner_id":"alice.near"}]}',
  "Some other log line",
]);
// => [{ standard: "nep171", version: "1.0.0", event: "nft_mint", data: [{ owner_id: "alice.near" }] }]
```

## NEP-297 Event Format

Events follow the [NEP-297 standard](https://nomicon.io/Standards/EventsFormat):

```
EVENT_JSON:{"standard":"nep171","version":"1.0.0","event":"nft_mint","data":[...]}
```

Common standards:
- `nep141` - Fungible tokens (ft_transfer, ft_mint, ft_burn)
- `nep171` - Non-fungible tokens (nft_mint, nft_transfer, nft_burn)
- `nep245` - Multi-token (mt_mint, mt_transfer, mt_burn)

## License

MIT
