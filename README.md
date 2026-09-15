# TxtLock

TxtLock is a DNS TXT hold escrow built on GenLayer. It allows a depositor to fund an escrow where the release of funds is gated by the presence of a specific DNS TXT record. 

The operator deploys the contract and freezes the target domain, expected TXT record, and time windows. The depositor funds the contract. After the hold period, anyone can call `resolve()`. If the DNS query exactly matches the expected TXT record, the operator is credited. Otherwise, the depositor is refunded.

## Live Deployment

- **Network:** Studio-Devnet
- **Chain ID:** `61997`
- **RPC Endpoint:** `https://studio-dev.genlayer.com/api`
- **Contract Address:** [`0x5a449a677b9F9ddcE1bB47106333FB6ebc96DcF5`](https://explorer-studio-dev.genlayer.com/address/0x5a449a677b9F9ddcE1bB47106333FB6ebc96DcF5?chain=studio-devnet)
- **Deployment Tx:** [`0x0c175a355b7aada9e8fe8a1caf1f531fe6148d8a7f1be2aa19419fdba016413a`](https://explorer-studio-dev.genlayer.com/transaction/0x0c175a355b7aada9e8fe8a1caf1f531fe6148d8a7f1be2aa19419fdba016413a?chain=studio-devnet)
- **GitHub Repository:** [edwarderlick/txtlock](https://github.com/edwarderlick/txtlock)

## Features & Constraints

- **Exact Match Only:** The contract performs a strict equality check (`observed_txt == expected_txt`). It does not use LLMs for fuzzy matching or subjective analysis.
- **Not a Court:** This contract does not mediate disputes. The DNS record is the single source of truth.
- **Size Caps:** 
  - `record_fqdn` is limited to 253 characters (standard DNS limit).
  - `expected_txt` is limited to 128 characters.

## Test Table

| Test Case | Condition | Verdict | Payout |
| :--- | :--- | :--- | :--- |
| **MATCH** | DoH lookup returns exactly the frozen token. | `MATCH` | Operator is credited. |
| **FETCH_FAILED** | DoH query fails (e.g. network error). | `FETCH_FAILED` | Depositor is refunded. |
| **MISMATCH** | TXT record exists but doesn't match exactly, or no TXT records found. | `MISMATCH` | Depositor is refunded. |

## How It Works

1. **`__init__`**: Operator deploys. Freezes `record_fqdn`, `expected_txt`, and windows. (Not payable).
2. **`fund_escrow`**: Depositor sends value > 0. A DoH fetch runs immediately. It must be a `MATCH` or the entire fund transaction reverts, ensuring the depositor isn't locking funds if the record isn't even there yet.
3. **`cancel`**: Operator (if unfunded) or depositor (if in cancel window) can cancel. Refunds depositor if funded.
4. **`resolve`**: Anyone can call after the hold period but before `resolve_deadline_ts`. Performs a DoH fetch. `MATCH` credits operator; anything else refunds depositor.
5. **`expire`**: Anyone can call after the deadline if still `FUNDED`. State becomes `EXPIRED`, depositor gets a refund.
6. **`withdraw`**: Operator can withdraw their `operator_credit`.
