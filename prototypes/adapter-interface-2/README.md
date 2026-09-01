# Adapter interface spike (issue #2)

Question: does one `Adapter` interface cover both the in-memory mock adapter and a real,
Stripe-shaped integration, without the interface itself ever knowing what Stripe is?

Built against the contract already locked in [ADR-0005](../../docs/adr/0005-exactly-once-boundary.md)
(the `is_idempotent` flag, the core-generated idempotency key, the two-exception retry taxonomy)
plus the interface-shape decisions grilled in issue #2 (async, a `revalidate` step before
`execute`, a generic `Effect` return type).

Run it:

```bash
python3 spike.py
```

See [RESULTS.md](RESULTS.md) for what it found. This code is throwaway - the real interface
lands in `ephor/src/ephor/effects.py` once #10-#12 extract it for real; nothing here is imported
by the package.
