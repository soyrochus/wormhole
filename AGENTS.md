# Build Prompt — Integrate **Prepper** as Wormhole’s config mechanism

## Mission

Refactor Wormhole’s configuration to use **Prepper** as the single configuration loader while **preserving** current behavior:

* Keep support for **`.env`** and **direct environment variables** (current implementation).
* **Add** support for reading a **local config file in the user’s home directory**.
* No env namespace/prefix filtering: **accept flat env variable names exactly as written**.

These characateristics will be provoded by Pepper. They DO NOT HAVE TO BE IMPLEMENTED. 

The agent must read **Prepper’s API and usage details** from:

* `<project_root>/docs/prepper-readme.md`



## Scope & Requirements

### 1) Dependency & wiring

* Verify that  **Prepper** has been added as a dependecy

* REmove the existing `python-dotenv`/manual `os.environ` 

### 2) Sources & precedence (exact)

* Use yaml as the **one file format** chosen for Wormhole 

### 3) Variables to support (flat names, type-safe)

The agent must support and validate the following fields (exact names; no renaming; no prefixing):

* `LLM_PROVIDER` — string; allowed values include `"azure_openai"`, `"openai"`
* `AZURE_OPENAI_API_KEY` — string (secret)
* `AZURE_OPENAI_ENDPOINT` — string (URL)
* `AZURE_OPENAI_API_VERSION` — string (e.g., `2024-12-01-preview`)
* `AZURE_OPENAI_DEPLOYMENT_NAME` — string
* `OPENAI_API_KEY` — string (secret)

Behavioral notes:

* If `LLM_PROVIDER="azure_openai"`, then **Azure** fields must be present and valid.
* If `LLM_PROVIDER="openai"`, then **`OPENAI_API_KEY`** must be present and valid; Azure fields may be ignored.


### 4) Schema & validation

* Define a **schema object** (type-safe; use modern Python typing) that declares the fields above, types, defaults (if any), and validation rules (cross-field rules for provider-specific requirements).
* Ensure aggregated validation errors (fail fast with a single, readable report listing all issues and their sources).


### 7) Public API impact

* Retreive from Pepper the small function or object (consistent with current app structure) that returns the **typed, validated, immutable** config for the rest of Wormhole.
* The rest of the codebase should **not** directly read `os.environ` nor parse `.env`; it should consume the new config object exclusively.

### 8) Docs

* Keep the developer documentation in the repo up to date.
* Reference   Prepper doc at https://github.com/soyrochus/prepper
* Update Wormhole’s README or internal docs to state the **new precedence** and how to provide user-home config.

