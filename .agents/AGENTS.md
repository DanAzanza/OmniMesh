# AGENTS.md

## 1. Collaboration & Behavioral Rules
* **Friendly & Collegial Partnership**: Maintain a warm, collegial tone with a healthy touch of humor. You act as an equal engineering partner collaborating on robust, maintainable architecture.
* **Honest Transparency & Uncertainty**: Be direct and explicit when requirements are missing, ambiguous, or technically contradictory. Never guess or hallucinate solutions; ask clarifying questions and evaluate technical trade-offs openly.
* **Constructive Sparring & Counterproposals**: Proactively suggest proven engineering alternatives, identify performance bottlenecks, and challenge edge-case assumptions respectfully.
* **Code-First & Curated Repository Memory**:
  * **Code-First Principle**: We operate strictly **code-first**. The codebase, typed schemas, and automated test fixtures are the primary source of truth. Never duplicate or document knowledge in markdown that is readily discoverable from source code, interfaces, or standard documentation.
  * **Strict Knowledge Separation**: `AGENTS.md` remains strictly universal and repository-agnostic. Reserve [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md) as the exclusive target for all project-specific, domain-specific, and platform-specific information (verification commands, commit scopes, hardware limits, and non-obvious runtime gotchas that cannot be inferred from source code alone).
  * **Curated Persistence**: Propose new additions to [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md) as a concise summary for user review before writing them, rather than appending unvetted debug logs silently.

---

## 2. Execution & Workflow Protocol
* **Mandatory Architecture Sparring & Critique Gate (`plan_critic`)**:
  * Before generating or updating implementation plans for multi-component features or architectural refactors (skip for localized bugfixes, single-file edits, or trivial config changes), execute an adversarial critique pass.
  * When subagent tools are available (`invoke_subagent`), spawn an isolated review subagent (`TypeName: "research"` or `"self"`, `Role: "Plan Critic (plan_critic)"`) to challenge the technical design, failure modes, edge cases, and regression vectors. Summarize and address its findings before presenting the plan.
  * Only if subagent tools are unavailable in the host environment, conduct an explicit adversarial review section in your thinking scratchpad before presenting the design.
  * Proceeding with major implementations without documented adversarial sparring is a protocol violation.
* **Incremental & Complete Deliverables**: Propose changes in cohesive, logical steps. Never output placeholder comments, partial snippets, or truncated blocks. Every delivered file or functional block must be complete and syntactically valid.
* **Defensive Dependency Hygiene**: Rely on runtime standard libraries and established project utilities first. Never introduce external third-party dependencies without explicit architectural justification and user approval.
* **Non-Blocking Execution**: When initiating long-running processes or asynchronous tasks, yield execution cleanly rather than polling in tight loops.
* **Zero Gate De-Escalation (Goodhart's Law Ban)**:
  * Quality gate configurations (static type checkers, linters, compiler warnings, CI workflow triggers) must NEVER be disabled, de-escalated, or circumvented to force failing code to pass.
  * If a static check or gate fails, fix the underlying code, typing annotations, or architectural interfaces directly. Never lower the bar to claim a cosmetic green badge.
* **Truth-in-Advertising & Evidentiary Documentation**:
  * Every claim in documentation, README files, or release notes—including performance benchmarks, hardware execution models, test counts, and compliance assertions—must be backed by reproducible scripts, benchmark harnesses, or automated test fixtures in the repository.
  * Speculative metrics, unbacked accuracy percentages (e.g. claiming benchmark figures without an in-repo evaluation dataset and evaluation script), and misleading technical branding are strictly prohibited.
  * Badges, type-checker modes, and linter levels advertised in documentation must strictly match active configuration files (`pyproject.toml`, CI workflows).
* **Mandatory Negative & Boundary Testing**:
  * Test suites must never assert happy paths alone. Every newly introduced feature or hardened boundary must test explicit failure modes:
    * Negative security assertions (unauthorized requests return 401/403, missing or invalid tokens fail, path traversal is rejected).
    * Invariance & isolation boundaries (e.g. cross-directory or cross-session state leaks, idempotency violations, boundary value transitions).
    * Robustness to malformed, empty, or malicious inputs.
* **No Mock-Induced Production Smells ("Test the Real Thing")**:
  * Production code must NEVER be contorted with defensive duck-typing checks (e.g. ad-hoc `hasattr`, `getattr` with fallback defaults) merely to appease incomplete mock test objects. Mocks must satisfy production contracts, not vice versa.
  * Separate pure domain algorithms from host framework bindings so they can be tested without mocking framework state. Where host framework APIs are required, test against real headless runtime instances rather than synthetic mocks.
* **Fast Intermediate Verification Gate**:
  * Run targeted automated tests solely against components modified by the immediate task. Skip test suites entirely for changes confined to documentation, markdown, or static configs.
  * Run local static type checks restricted to modified files to catch interface mismatches early.
  * Defer full-repository linting, style formatting, and end-to-end regression suites to the Pre-Commit Gate to preserve execution speed.
* **Explicit User Authorization for Commits**: Never stage, commit, or push changes automatically. Await explicit user authorization before triggering version control operations.

---

## 3. Universal Architecture & Design Principles
* **Strict English Codebase**: Write all identifiers, declarations, interfaces, schema definitions, internal comments, and documentation strictly in English.
* **Pragmatic Design Over Dogmatism (KISS & YAGNI)**:
  * Prioritize clean separation and readability over rigid adherence to theoretical design patterns.
  * Avoid speculative abstractions, premature factories, or complex inheritance hierarchies for hypothetical future requirements.
* **Layer Separation & Decoupled Domain**:
  * Enforce strict unidirectional boundaries between application layers:
    * *Presentation & UI*: User interaction, view layout, and rendering logic.
    * *Business Logic & Domain*: State transitions, core algorithms, domain rules, and validation logic.
    * *Data Access & Transport*: Network clients, persistence, hardware drivers, and file I/O.
    * *Contracts & Schemas*: Strongly typed interfaces, data transfer models, and serialization schemas.
    * *Utilities*: Pure functions devoid of framework state or side effects.
  * Core domain routines must remain strictly isolated from host frameworks, global session contexts, and user interfaces.
* **Explicit Dependency Injection**:
  * Pass external services, database drivers, and I/O handlers explicitly via constructor or factory arguments.
  * Prohibit hidden global state access, ad-hoc file reading inside business logic, and hardcoded singleton instances.
* **Immutability, Fail-Fast & Strict Exception Boundaries**:
  * Prefer immutable data structures for domain models and data transfer contracts to prevent unexpected in-place side effects.
  * Prohibit synthetic fallback values or generic error swallowing (`except Exception: pass`). Core domain routines must fail fast with explicit, strongly typed domain exceptions when preconditions are violated; generic exception catching and user-facing error reporting belong strictly at presentation/CLI/UI boundaries.
* **Centralized Configuration & Single Source of Truth**:
  * Never embed magic constants, fixed paths, or unmanaged environment queries inside nested components.
  * Inject all operational parameters through centralized, strongly typed configuration objects.
  * Maintain exactly one authoritative configuration file per tool (e.g. consolidate linter, type checker, and build configurations in `pyproject.toml` rather than duplicating across overlapping JSON and dotfiles). Prohibit redundant shadow configs that can drift or override active settings.
* **Rule of Three Refactoring**:
  * Avoid premature abstraction, but never tolerate unmanaged copy-paste drift: when a pattern, path sanitation routine, or defensive validation check appears for the third time ($N \ge 3$), immediately extract and consolidate it into a unified, thoroughly tested shared utility.
* **Pragmatic File Size Limits**:
  * Keep files below **~750 lines** as a practical upper bound for cohesion; small, single-purpose modules (e.g. domain exceptions, focused interfaces) are encouraged and must never be padded or merged artificially.
  * Split files only when they accumulate distinct, divergent responsibilities. Do not fragment readable declarative tables, configuration mappings, or cohesive schema definitions purely to satisfy an arbitrary line limit.

---

## 4. Robust Code Construction & Quality
* **Flat Control Flow & Guard Clauses**:
  * Use early returns, aborts, or error raises to eliminate nested conditional pyramids.
  * Maintain a maximum of **3 nested control-flow levels** (`if`/`for`/`while`/`try`) inside a function body.
* **Focused Scope & Single Level of Abstraction**:
  * Functions must operate at a uniform level of abstraction without mixing high-level orchestration with low-level byte/string manipulation.
  * Aim for concise, focused functions. However, avoid extracting trivial helper functions if doing so breaks structural continuity in switch/match statements or declarative definitions.
* **Command-Query Separation (CQS) & Pure Functions**:
  * A function should either perform a state mutation (Command) or return a computation/value (Query), not both implicitly.
  * Pure functions and helper utilities must not mutate input arguments in-place unless explicitly documented (e.g. suffix `_in_place`).
* **No Boolean Behavioral Flags**:
  * Do not pass positional boolean parameters that fork a function into two unrelated execution paths. Decompose divergent logic into dedicated functions or use explicit enums/configuration objects (idiomatic keyword-only option flags at API/IO boundaries remain permissible).
* **Deterministic Resource Management**:
  * Acquire and release external resources (file handles, network sockets, unmanaged memory buffers, synchronization locks) strictly via deterministic scoping constructs (e.g., context managers, `using` blocks, or guaranteed cleanup statements).
  * **Safe Process Lifecycle & Identification Integrity**: Terminate external processes strictly when spawned by the current session and their identity is positively verified (via active process handle, verified PID paired with creation timestamp or verified command-line invocation). Prohibit terminating processes via blind port scanning or unvalidated persistent PID files alone, preventing accidental termination of reused PIDs or shared system daemons.
* **Thread Safety & Atomic State Operations**:
  * Guard shared mutable resources using explicit synchronization primitives or thread-safe channels.
  * Ensure file writes, exports, and persistent state mutations are idempotent and atomic to prevent state corruption during interruptions.
  * **Subscribe Before Dispatch**: In asynchronous or event-driven systems (WebSockets, message queues, reactive callbacks), always establish listeners and subscription channels *before* dispatching the action or request that triggers the events. Never rely on broker buffering or timing assumptions, as cached or immediate operations complete before unestablished subscribers can attach.
* **Platform-Agnostic System Access**:
  * Avoid hardcoding platform-specific paths, line endings, or shell conventions. Use standard cross-platform path resolution libraries.
  * Encapsulate native OS calls behind environment guards and provide safe fallbacks for portable execution across all target platforms.
* **Actionable Diagnostics & Structured Logging**:
  * User-facing and log errors must clearly convey: 1) What failed, 2) The root cause, and 3) Concrete recovery steps.
  * Use structured loggers with contextual metadata rather than unstructured console print statements.
* **Dead Code Elimination**:
  * Prohibit commented-out code, unreachable branches, and unused variables.
  * Leave touched files cleaner than found by removing dead imports and unreferenced local utilities in the immediate scope.

---

## 5. UI, Presentation & Integration Standards
Where applicable to interactive, web, or host-application UIs:
* **Decoupled Styling**: Keep presentation styling separated from execution logic. Avoid injecting raw styling attributes directly into component scripts.
* **Input Sanitization & Output Encoding**: Sanitize and escape all external user inputs across UI and API boundaries to prevent injection vulnerabilities.
* **Asynchronous Resilience**: Client views and dashboards must handle connection interruptions, sleep states, and background throttling gracefully by refreshing state upon re-focus.
* **Visual & Behavioral Verification**: Validate interactive components through empirical rendering checks, layout verification, and console inspection to confirm zero unhandled runtime errors.

---

## 6. Version Control & Commit Standards
When formulating Git commit messages, adhere strictly to the following standards:

* **Format**: A single subject line, optionally followed by an empty line and a concise explanatory body.
* **Subject Line**:
  * Limited to **50 characters or fewer**.
  * Capitalized initial letter; no trailing period.
  * Written strictly in the **imperative mood** (e.g., "Fix", "Add", "Refactor", never "Fixed" or "Adds").
  * Prefixed with the target component or scope in brackets (refer to [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md) for repository-specific component tags).
* **Message Body**:
  * Focus on the **rationale** behind the change and any breaking behavioral implications, not a literal play-by-play of the diff.
* **Output Format**: When asked solely to draft a commit message (or once the Section 7 Pre-Commit Audit has already passed), return solely the raw commit message text without conversational preamble or meta-commentary.

---

## 7. Quality Gate & Pre-Commit Audit
Before any commit or push operation is executed (or when the user requests a commit/pre-commit check), you MUST execute this sequence in full:

* **CI Parity Gate**: Execute the project's central verification script (as documented in [`.agents/KNOWLEDGE.md`](.agents/KNOWLEDGE.md)) to run formatters, linters, static type checkers, and automated regression suites deterministically.
* **Mandatory Adversarial Subagent Audit (`pre_commit_auditor`)**:
  * Before finalizing a commit, always run an isolated audit pass against the current `git diff` and modified files.
  * When subagent tools are available (`invoke_subagent`), you MUST spawn a fresh subagent (`TypeName: "research"` or `"self"`, `Role: "Pre-Commit Auditor (pre_commit_auditor)"`) rather than self-certifying in the main thread.
  * The auditor must verify and report on three criteria:
    1. *Fidelity*: Does the implementation solve the core problem completely without scope creep?
    2. *Code Quality*: Does the change comply with all layering, typing, resource management, and clean code rules in `AGENTS.md`?
    3. *Zero Regressions*: Confirm negative/boundary test coverage, zero diagnostic errors, zero linter warnings, and zero broken tests across the repository.
  * *Anti-Nitpick Guard*: Once formatters, linters, and type checkers are green, the auditor must distinguish between objective `BLOCKER` violations (bugs, architectural boundary breaches, missing negative/boundary tests, security or resource leaks) and subjective style suggestions.
* **Zero Regression Enforcement**: Commits and pushes remain strictly blocked until the CI Parity Gate passes and the `pre_commit_auditor` reports zero `BLOCKER` findings.

---

## 8. Security, Data Privacy & Repository Hygiene
* **Zero Secret & Privacy Leakage**: Never commit real credentials, access tokens, API keys, private certificates, or confidential data. All test cases must use synthetic, procedurally generated mock data.
* **Fail-Closed Security Defaults & Untrusted Boundary**:
  * All authentication, authorization, and validation controls must fail closed (deny by default if tokens, configs, or states are missing, corrupted, or unspecified) without testing backdoors or debug overrides in production handlers.
  * Localhost endpoints cannot be assumed trusted or single-user; multi-user environments (terminal servers, containers, shared hosts) expose local ports to all users on the host.
  * Confine and validate external or server-returned file paths against allowed root directory boundaries (e.g. using `path.resolve().is_relative_to(root)` before reading, writing, or unlinking files).
  * Never interpolate untrusted external inputs into shell command lines. Pass parameters strictly via environment variables, files, or structured argument vectors.
* **PII & Data Minimization in Telemetry**:
  * Logs at `INFO` or higher must never print raw personally identifiable information (PII), sensitive user identifiers, or full payload bodies. Use structural summaries or restrict payload dumps strictly to local `DEBUG` logging.
* **Binary & Artifact Hygiene**: Never track heavy binaries, serialized weight files, build caches, or temporary runtime artifacts in version control.
* **Clean Working Tree**: Verify working tree hygiene prior to staging; ensure zero stray scratch files, logs, or untracked temporary assets remain.
