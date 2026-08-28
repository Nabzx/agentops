# Adapter credentials — how Adapters should hold secrets

_Wayfinder research for issue #5. Terms (Adapter, Effect, the core) are used as defined in
[CONTEXT.md](../../CONTEXT.md)._

## Question

An **Adapter** carries out a class of **Effects** against one external system (the first is a
Stripe adapter, Stripe **test mode** first). Each Adapter needs credentials for its system. We
need **one** credential model for how Adapters hold those credentials, judged against:

- **sandbox / test-mode by default** — the safe path is the default; touching live money is a
  deliberate, explicit act;
- **scoped** — each Adapter sees only its own credentials, ideally least-privilege at the
  provider too;
- **secrets never committed** — nothing sensitive lands in the repo or an image;
- **dead-simple for a self-hosted OSS user** — clone, set a couple of variables, run;
- **clean with many Adapters** — the pattern does not rot as detectors and Adapters multiply.

The `wayfinder:map` framing is a "secrets / credential model: how Adapters hold scoped,
sandbox-first credentials"
([ROADMAP.md](../../ROADMAP.md), Open decisions).

## Approaches compared

| Approach | How it works | Strengths | Weaknesses |
| --- | --- | --- | --- |
| **Environment variables (12-factor)** | Each secret is an env var read at runtime | Zero deps; never in code; language/OS-agnostic; standard for OSS | Flat namespace; no typing/validation; no per-Adapter grouping on its own; no test-vs-live logic on its own |
| **`.env` file via python-dotenv** | `load_dotenv()` reads a git-ignored `.env` into `os.environ` | One-file local dev; matches the env-var model; trivial to run | Just a loader — no validation or structure; must be git-ignored or secrets leak |
| **Per-Adapter config object (pydantic-settings)** | A typed `BaseSettings` subclass per Adapter, env-prefixed, `.env`-aware | Typed + validated at startup; per-Adapter namespace via `env_prefix`; `SecretStr` masks values; fails fast on missing/bad config; still just env vars underneath | One small class per Adapter (this is the point, not overhead) |
| **Pluggable secret-provider interface** | Core defines a `SecretProvider` seam; env-var provider default, Vault/cloud later | Future-proof; supports managed secret stores | Premature for v0.1–v0.3; adds a seam before there is a second implementation to justify it |
| **OS keychain (keyring)** | Secrets held in macOS Keychain / libsecret | Nothing on disk in plaintext | Interactive/desktop-shaped; awkward in Docker/CI/headless servers — the OSS deployment target; extra dep |

### How a resolver decides test vs live

Two families exist, and Stripe hands us the cleaner one for free:

- **Key-encodes-mode (recommended).** The Stripe secret key prefix *is* the mode: `sk_test_` /
  `rk_test_` are sandbox, `sk_live_` / `rk_live_` are live, and "objects in one mode aren't
  accessible to the other"
  ([Stripe: API keys — sandbox vs live](https://docs.stripe.com/keys#sandbox-versus-live-mode)).
  So mode is a property of the credential, not a separate flag to keep in sync.
- **Explicit `mode` flag.** A separate `test`/`live` field the resolver reads. Redundant with
  the key prefix for Stripe and adds a way to disagree with reality (a `live` flag next to an
  `sk_test_` key). Its only value is as a **guard**: refuse to start if a key's prefix and the
  declared mode disagree, and default the flag to `test` so live is never the accident.

Recommendation below uses the key prefix as the source of truth, defaults to test, and treats a
live key as an explicit opt-in that must be asserted.

## How comparable tools do it (each claim cited)

- **Stripe Python SDK** — the API key is the whole configuration. Legacy global
  `stripe.api_key = "sk_test_..."` or the modern client `StripeClient("sk_test_...")`, with an
  optional per-request `options={"api_key": ...}` override
  ([stripe/stripe-python README](https://github.com/stripe/stripe-python)). The SDK does not
  read env vars for you — the app supplies the key — so test-vs-live is decided entirely by
  *which key string* you hand it. Idempotency is automatic: "Idempotency keys are automatically
  generated and added to requests, when not given, to guarantee that retries are safe"
  ([stripe/stripe-python README](https://github.com/stripe/stripe-python)) — relevant because
  the core already owns an Idempotency key, so the Adapter should pass that stable key through
  rather than rely on the SDK's per-process random one.
- **Stripe key model** — keys are typed and scoped: publishable `pk_`, **restricted `rk_`**
  (permissions you control — "Create as many RAKs as you want and assign them to different parts
  of your application"), and unrestricted secret `sk_`, with Stripe recommending RAKs over `sk_`
  for new use cases. Guidance is explicit: "Don't put keys in source code or configuration files
  checked into version control"; use a secrets vault "or … an environment variable"
  ([Stripe: API keys](https://docs.stripe.com/keys)). This directly supports env-var + a
  least-privilege restricted key per Adapter.
- **Airbyte** separates **configuration** (non-secret settings) from **credentials** (API keys,
  OAuth tokens), stores credentials server-side, "never returns them in API responses after
  creation", and — when an external manager is configured — persists only a *pointer to the
  secret* rather than the secret itself, injecting the real value into each execution
  ([Airbyte: Secret Management](https://docs.airbyte.com/platform/deploying-airbyte/integrations/secrets),
  [Airbyte: Connectors and credentials](https://docs.airbyte.com/ai-agents/concepts/architecture/connectors-and-credentials)).
  Takeaway: split secret from config, and keep a seam for an external store — but their default
  DB storage is plaintext, which we should avoid emulating.
- **n8n** stores credentials as **separate entities**, referenced by a node via **ID** so the
  secret is never embedded in the workflow, and encrypts them at rest with a single instance
  key, `N8N_ENCRYPTION_KEY` (a 32-char string; lose it and every stored credential is
  unrecoverable)
  ([n8n docs: credentials](https://docs.n8n.io/integrations/builtin/credentials/),
  [n8n docs: securing / encryption key rotation](https://docs.n8n.io/hosting/securing/encryption-key-rotation/)).
  Takeaway: reference-not-embed and encrypt-at-rest are the right instincts for a *hosted*
  product; for a self-hosted OSS core they are heavier than env vars and better deferred.
- **Dagster** configures a **resource** with `dg.EnvVar("NAME")`, which populates a string
  config field from an environment variable, is read **at run launch (runtime), not at code-load
  time**, and — unlike `os.getenv()` — is **not displayed in the UI**
  ([Dagster: configuring resources](https://docs.dagster.io/guides/build/external-resources/configuring-resources)).
  This is the closest match to what we want: a typed per-component config object whose secret
  fields are env-backed and non-printing. Their `ConfigurableResource` is essentially a
  pydantic settings object.
- **LangChain** integration packages default to reading a provider env var — for Anthropic,
  "set the `ANTHROPIC_API_KEY` environment variable"
  ([LangChain: ChatAnthropic](https://docs.langchain.com/oss/python/integrations/chat/anthropic))
  — while still allowing an explicit `api_key=` argument to the constructor. Same shape as
  Stripe: env var as the default, constructor override for tests/multi-tenant.
- **Foundations.** 12-factor Config mandates "strict separation of config from code" and storing
  config (DB creds, API keys) in **environment variables**, precisely so a codebase can be open
  sourced "without compromising any credentials"
  ([12factor.net/config](https://12factor.net/config)). `python-dotenv` reads a `.env` into
  `os.environ` for local dev and its own guidance is to add `.env` to `.gitignore`
  ([python-dotenv on PyPI](https://pypi.org/project/python-dotenv/)). `pydantic-settings`
  `BaseSettings` reads fields from the environment, supports a per-object `env_prefix`, loads a
  `.env` via `SettingsConfigDict(env_file=...)`, masks secrets with `SecretStr`, and validates
  on instantiation
  ([pydantic-settings docs](https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/)).

The consistent pattern across every tool a self-hosted user would recognise: **environment
variables are the substrate; a typed per-component config object is the ergonomic layer; an
external secret store is an optional seam, not the default.**

## Recommendation — one model

**A per-Adapter, typed config object built on `pydantic-settings`, env-var backed, `.env` for
local dev, sandbox-by-default, with a small resolver that refuses to run live unless explicitly
told to.** This is Dagster's `ConfigurableResource` shape and LangChain/Stripe's
"env-var-default, constructor-override" ergonomics, expressed once per Adapter.

Concretely:

1. **One `BaseSettings` subclass per Adapter**, namespaced by `env_prefix` (e.g.
   `AGENTOPS_STRIPE_`). The Adapter declares its own fields; the core never enumerates them.
   Secrets are `SecretStr` so they never print in logs or `repr`.
2. **Env vars are the source of truth**; a git-ignored `.env` (shipped as a committed
   `.env.example` with `sk_test_...` placeholders) makes local dev one file. `.env` is in
   `.gitignore`, per python-dotenv's own guidance.
3. **Sandbox is the default and is enforced.** The resolver reads the key, infers mode from the
   `_test_` / `_live_` prefix, and **only permits live when the Adapter is explicitly constructed
   with `allow_live=True`** (which a Detector/CLI sets from an operator action, never a default).
   A live key with `allow_live` unset is a startup error — you cannot reach live by omission.
4. **No secret store in v0.1–v0.3, but leave the seam.** Resolution goes through one function so
   a `SecretProvider` (Vault, cloud manager, n8n-style encrypted-at-rest) can be slotted in
   later without touching Adapters — matching Airbyte's pointer-to-secret model when someone
   needs it.
5. **Idempotency comes from the core, not the SDK.** The Adapter passes the core's Idempotency
   key into the Stripe call rather than relying on the SDK's auto-generated per-process key, so
   exactly-once survives worker restarts.

### Config / resolver sketch

```python
# core/adapters/config.py — provided by the core, shared by every Adapter
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AdapterSettings(BaseSettings):
    """Base for every Adapter's config. Subclasses set their own env_prefix."""
    model_config = SettingsConfigDict(
        env_file=".env",          # local dev; .env is git-ignored
        extra="ignore",
        case_sensitive=False,
    )


class Mode(str):  # illustrative
    TEST = "test"
    LIVE = "live"


def resolve_mode(secret_key: str) -> str:
    """Mode is a property of the credential, not a separate flag (Stripe key prefix)."""
    if "_test_" in secret_key:
        return Mode.TEST
    if "_live_" in secret_key:
        return Mode.LIVE
    raise ValueError("Unrecognised key: cannot determine test vs live mode")
```

```python
# adapters/stripe/config.py — lives with the Stripe Adapter
from pydantic import SecretStr
from pydantic_settings import SettingsConfigDict
from core.adapters.config import AdapterSettings, resolve_mode, Mode


class StripeAdapterSettings(AdapterSettings):
    model_config = SettingsConfigDict(env_prefix="AGENTOPS_STRIPE_")

    # AGENTOPS_STRIPE_API_KEY  (use a restricted key, rk_test_… — least privilege)
    api_key: SecretStr

    def build(self, *, allow_live: bool = False) -> "StripeAdapter":
        mode = resolve_mode(self.api_key.get_secret_value())
        if mode == Mode.LIVE and not allow_live:
            raise RuntimeError(
                "Refusing to start a live Stripe Adapter. "
                "Pass allow_live=True to opt in; default is sandbox/test mode."
            )
        return StripeAdapter(api_key=self.api_key, mode=mode)
```

A self-hosted user's entire setup: `cp .env.example .env`, paste an `rk_test_…` restricted key,
run. Adding an Adapter means adding one `*AdapterSettings` subclass with a new `env_prefix` —
nothing central changes, so the pattern stays clean across many Adapters.

## Consequences / what it unblocks

- **Unblocks #2 (Action/Effect Adapter interface).** The interface can require each Adapter to
  expose a `Settings` type and a `build(*, allow_live=False)` factory. The core depends on that
  contract, never on Stripe specifics — consistent with "the core knows nothing about any
  specific system" (CONTEXT.md, Adapter). Credential handling becomes part of the Adapter
  contract, not ad-hoc per Adapter.
- **Unblocks #9 (scaffold).** The scaffold ships `pydantic-settings` + `python-dotenv` as deps,
  a committed `.env.example` (test-mode placeholders only), `.env` in `.gitignore`, and an
  `AdapterSettings` base + `resolve_mode`. A new-Adapter template is "copy this settings class,
  change the `env_prefix`."
- **Keeps the roadmap's determinism promise.** Sandbox-by-default with an enforced live opt-in
  operationalises "the flagship talks to Stripe test mode only … nothing touches real money"
  (ROADMAP.md, Ground rules): reaching live requires an explicit `allow_live=True`, so it can
  never happen by default or by a stray env var.
- **Least-privilege at the provider, for free.** Because a scoped **restricted key** (`rk_…`) is
  just a different string in the same field, adopting least privilege costs nothing in code
  (Stripe: API keys).
- **Deferred, not foreclosed:** an encrypted-at-rest store (n8n) or external secret manager
  (Airbyte) attaches at the single resolver seam later, without changing any Adapter — so the
  simple default does not paint us into a corner. The main residual risk is the usual one for
  env-var models — a `.env` accidentally committed — mitigated by shipping only `.env.example`
  and git-ignoring `.env` from the first commit.

_Note: issue #5 asks for the write-up as an ADR. This file is the research finding; the settled
decision should be recorded as an ADR under `docs/adr/` once accepted._
