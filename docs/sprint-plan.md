# Atlas API Sprint Plan (Draft)

Project summary:
The Atlas API backend provides strategy data to the frontend and executes trades via dHEDGE vaults on GMX V2 (Arbitrum). This plan turns the existing epics/issues into sequential, demoable sprints with atomic, testable tasks and explicit dependencies.

Assumptions:
- FastAPI + Postgres stack; ORM + migrations via SQLAlchemy/Alembic or SQLModel.
- Analytics export format is available or can be defined.
- dHEDGE vaults and GMX V2 integration are accessible on a testnet for smoke tests.
- Auth requirements are minimal for MVP (API key or internal network); expand later if needed.

Dependency graph (epics -> task IDs):
- Epic #1 Backend Infrastructure -> S1-T1..S1-T8, S1-T10
- Epic #10 Data Import -> S2-T1..S2-T8
- Epic #6 API Layer -> S3-T1..S3-T7
- Epic #13 Execution Layer -> S4-T1..S4-T9
- Epic #20 On-Chain Integration -> S5-T1..S5-T8
- Epic #23 Frontend Integration -> S6-T1..S6-T6
- Cross-cutting -> S1-T9, S3-T8, S4-T10, S5-T9, S6-T7

Sprint 1: Infrastructure MVP (Goal + Demo)
Goal: Bootstrapped FastAPI service with DB connectivity, migrations, CI, and health check.
Demo: `GET /health` returns OK; migrations run on a local Postgres; CI lints/tests.

Tasks:
- S1-T1: Repo bootstrap & FastAPI skeleton (Issue #2)
  Scope: Create app package structure, settings module, and base app instance.
  Deliverables: Running FastAPI app with OpenAPI docs enabled.
  Validation: `uvicorn` starts; `/docs` loads locally.
  Dependencies: None.
- S1-T2: Environment/config management
  Scope: Define config schema, env file templates, secrets loading pattern.
  Deliverables: `settings.py` with typed config; `.env.example` updated.
  Validation: App boots with missing/invalid config handled gracefully.
  Dependencies: S1-T1.
- S1-T3: Database connection layer
  Scope: Add DB client/engine, session lifecycle, connection check.
  Deliverables: DB module with session/engine; ping endpoint or startup check.
  Validation: Local Postgres connection succeeds/fails predictably.
  Dependencies: S1-T2.
- S1-T4: Initial schema + migrations (Issue #3)
  Scope: Baseline tables for strategies, performance, holdings, trades, vaults.
  Deliverables: Migration scripts; ORM models; schema doc snippet.
  Validation: `alembic upgrade head` (or equivalent) succeeds on empty DB.
  Dependencies: S1-T3.
- S1-T5: Health check endpoint (Issue #5)
  Scope: `/health` with DB connectivity status.
  Deliverables: Route + response schema.
  Validation: 200 OK; DB status true when connected.
  Dependencies: S1-T3.
- S1-T6: Logging + structured error handling
  Scope: JSON logging, correlation IDs, exception handlers.
  Deliverables: Log config; middleware for request IDs; error schema.
  Validation: Logs emit structured JSON for request/response and errors.
  Dependencies: S1-T1.
- S1-T7: CI pipeline setup
  Scope: Basic lint/test pipeline; pre-commit hooks if desired.
  Deliverables: CI workflow; lint/test commands documented.
  Validation: CI passes on main branch.
  Dependencies: S1-T1.
- S1-T8: Deployment scaffolding (Issue #4)
  Scope: Dockerfile, Procfile or platform config, health checks.
  Deliverables: Container build; deploy config template.
  Validation: Docker build succeeds; container starts.
  Dependencies: S1-T1.
- S1-T9: API docs baseline
  Scope: README/runbook for local setup and env vars.
  Deliverables: `README` section + setup steps.
  Validation: New dev can boot app with docs.
  Dependencies: S1-T1.
- S1-T10: Minimal smoke tests
  Scope: Add API smoke test for `/health`.
  Deliverables: Test script + CI integration.
  Validation: Test passes locally and in CI.
  Dependencies: S1-T5.

Sprint 2: Data Import Foundations (Goal + Demo)
Goal: Define import format and build ingestion pipeline from analytics exports.
Demo: Run CLI import on sample export and query data from DB.

Tasks:
- S2-T1: Define import JSON schema (Issue #11)
  Scope: Fields, types, required vs optional; versioning strategy.
  Deliverables: JSON schema file + documentation.
  Validation: Schema validates a sample export.
  Dependencies: S1-T4.
- S2-T2: Import staging tables
  Scope: Staging tables for raw analytics payloads.
  Deliverables: Migration + models for staging.
  Validation: Inserts succeed and can be queried.
  Dependencies: S1-T4.
- S2-T3: CLI import tool scaffolding (Issue #12)
  Scope: CLI entrypoint, file reading, schema validation.
  Deliverables: `atlas-import` CLI with `--file` and `--dry-run`.
  Validation: CLI validates and exits non-zero on invalid schema.
  Dependencies: S2-T1.
- S2-T4: Data transform + upsert pipeline
  Scope: Transform from staging to core tables; idempotent upserts.
  Deliverables: ETL module; conflict handling rules.
  Validation: Re-import produces no duplicates.
  Dependencies: S2-T2, S2-T3.
- S2-T5: Import observability
  Scope: Metrics/logging around import duration, counts, errors.
  Deliverables: Structured logs + summary report output.
  Validation: Logs include record counts and timing.
  Dependencies: S2-T3.
- S2-T6: Sample data fixtures
  Scope: Add fixtures that mirror analytics export.
  Deliverables: `fixtures/` sample JSON files.
  Validation: `atlas-import` succeeds on fixtures.
  Dependencies: S2-T3.
- S2-T7: Scheduled import hook
  Scope: Optional cron job entrypoint for periodic import.
  Deliverables: Script or task runner integration.
  Validation: Runs in container/local environment.
  Dependencies: S2-T4.
- S2-T8: Import tests
  Scope: Unit tests for schema validation + transforms.
  Deliverables: Test suite for import pipeline.
  Validation: Tests pass in CI.
  Dependencies: S2-T4.

Sprint 3: API Layer v1 (Goal + Demo)
Goal: Expose strategy discovery, investor reports, and historical performance endpoints.
Demo: Frontend or curl can retrieve discovery list and performance data.

Tasks:
- S3-T1: Strategy Discovery API (Issue #7)
  Scope: List/filter strategies; pagination/sorting.
  Deliverables: Endpoint + response schemas.
  Validation: Returns expected rows from imported data.
  Dependencies: S2-T4.
- S3-T2: Investor Report API (Issue #8)
  Scope: Aggregated metrics per strategy; date ranges.
  Deliverables: Endpoint + metrics calculations.
  Validation: Matches computed metrics from fixtures.
  Dependencies: S2-T4.
- S3-T3: Historical Performance API (Issue #9)
  Scope: Time-series performance endpoint.
  Deliverables: Endpoint + timeseries queries.
  Validation: Returns consistent series for known fixtures.
  Dependencies: S2-T4.
- S3-T4: API pagination/filters shared utilities
  Scope: Common query helpers and pagination responses.
  Deliverables: Shared utils + reusable schemas.
  Validation: Unit tests for filtering/sorting.
  Dependencies: S3-T1.
- S3-T5: OpenAPI tagging + examples
  Scope: Improve docs, add example responses.
  Deliverables: OpenAPI metadata improvements.
  Validation: `/docs` shows tags/examples.
  Dependencies: S3-T1.
- S3-T6: API integration tests
  Scope: Test all endpoints with fixtures.
  Deliverables: Integration test suite.
  Validation: Tests pass locally and in CI.
  Dependencies: S3-T1..S3-T3.
- S3-T7: Rate limiting/cache (optional MVP)
  Scope: Simple cache for hot reads or rate limit middleware.
  Deliverables: Cache layer or limiter config.
  Validation: Confirm cache hits/reduced DB load.
  Dependencies: S3-T1.
- S3-T8: API auth guardrails (if needed)
  Scope: API key or internal auth mechanism.
  Deliverables: Auth middleware + docs.
  Validation: Unauthorized requests rejected.
  Dependencies: S3-T1.

Sprint 4: Execution Layer (Goal + Demo)
Goal: Build core trading pipeline with simulation mode.
Demo: Simulated signals trigger trades and update positions in DB.

Tasks:
- S4-T1: Strategy loader (Issue #14)
  Scope: Load strategy configs/params from DB or config store.
  Deliverables: Strategy registry + loader interface.
  Validation: Loads known strategy definitions.
  Dependencies: S1-T4.
- S4-T2: Market data fetcher (Issue #15)
  Scope: Fetch market data via provider (mockable).
  Deliverables: Data fetch module with provider abstraction.
  Validation: Fetcher returns normalized data in tests.
  Dependencies: S4-T1.
- S4-T3: Signal generator (Issue #16)
  Scope: Generate signals from market data + strategy config.
  Deliverables: Signal engine + rules.
  Validation: Deterministic output for fixture inputs.
  Dependencies: S4-T2.
- S4-T4: Trade executor (simulated)
  Scope: Execute signals against paper account.
  Deliverables: Sim executor; trade records persisted.
  Validation: Trades created with correct sizing.
  Dependencies: S4-T3.
- S4-T5: Position tracker (Issue #18)
  Scope: Track open positions and PnL.
  Deliverables: Position model + update logic.
  Validation: Position state updates with trades.
  Dependencies: S4-T4.
- S4-T6: Scheduler/loop (Issue #19)
  Scope: Run scheduled cycles; lock to prevent overlap.
  Deliverables: Scheduler with cron/loop config.
  Validation: Cycle runs and updates positions.
  Dependencies: S4-T1..S4-T5.
- S4-T7: Execution audit logs
  Scope: Store decision logs and execution metadata.
  Deliverables: Audit table + logging integration.
  Validation: Each run emits audit row.
  Dependencies: S4-T4.
- S4-T8: Execution integration tests
  Scope: Full pipeline test in simulation mode.
  Deliverables: Integration test that runs fetch->signal->trade->positions.
  Validation: Test passes with deterministic fixtures.
  Dependencies: S4-T6.
- S4-T9: Feature flags for live vs paper
  Scope: Config gate for live execution.
  Deliverables: Config setting + guard in executor.
  Validation: Live execution blocked when disabled.
  Dependencies: S4-T4.
- S4-T10: Ops runbook for execution
  Scope: Document run cadence, failure recovery, and monitoring.
  Deliverables: Runbook doc.
  Validation: Reviewed and stored in docs.
  Dependencies: S4-T6.

Sprint 5: On-Chain Integration (Goal + Demo)
Goal: Read vault state and prepare on-chain execution pathway.
Demo: Fetch vault state from dHEDGE and execute a test trade on testnet.

Tasks:
- S5-T1: Wallet management (Issue #22)
  Scope: Secure key storage, signer abstraction, address management.
  Deliverables: Wallet module with provider injection.
  Validation: Signer loads from env/secret manager.
  Dependencies: S1-T2.
- S5-T2: Vault state reader (Issue #21)
  Scope: Read vault positions, holdings, and NAV.
  Deliverables: Chain reader module + models.
  Validation: Returns expected testnet data.
  Dependencies: S5-T1.
- S5-T3: dHEDGE trade executor (Issue #17)
  Scope: Integrate with dHEDGE vault transaction flow.
  Deliverables: Executor implementation with dry-run option.
  Validation: Simulated transaction builds successfully.
  Dependencies: S5-T1.
- S5-T4: GMX integration adapter
  Scope: Handle GMX markets, collateral, and approvals.
  Deliverables: Adapter module with approval/transfer flow.
  Validation: Smoke test on testnet.
  Dependencies: S5-T3.
- S5-T5: On-chain position reconciliation
  Scope: Compare DB positions vs vault positions.
  Deliverables: Reconciliation job + diff output.
  Validation: Reports consistent reconciliation for fixture data.
  Dependencies: S5-T2.
- S5-T6: Chain provider resiliency
  Scope: Retry/backoff, multiple RPC endpoints.
  Deliverables: Provider config with failover.
  Validation: Test with forced RPC failure.
  Dependencies: S5-T2.
- S5-T7: Security guardrails
  Scope: Transaction limits, allowlist of vaults/markets.
  Deliverables: Guardrails config + enforcement.
  Validation: Invalid trade blocked with error.
  Dependencies: S5-T3.
- S5-T8: On-chain integration tests
  Scope: Mocked or testnet integration test suite.
  Deliverables: Integration test harness.
  Validation: Tests pass in CI (mocked) or staging.
  Dependencies: S5-T2..S5-T4.
- S5-T9: Monitoring + alerting
  Scope: Alerts for failed txs, lag, or anomalous positions.
  Deliverables: Alert config + dashboards (if available).
  Validation: Alert triggers in test scenario.
  Dependencies: S5-T2.

Sprint 6: Frontend Integration (Goal + Demo)
Goal: Connect frontend to new API with stable endpoints and config.
Demo: Frontend displays live strategy list and performance using new API.

Tasks:
- S6-T1: API base config update (Issue #24)
  Scope: Update API_BASE in frontend and env config.
  Deliverables: Frontend config updated with new API URL.
  Validation: Frontend loads data from new API.
  Dependencies: S3-T1..S3-T3.
- S6-T2: Frontend API client abstraction
  Scope: Add client wrapper (fetch/axios) with error handling.
  Deliverables: API client module with typed responses.
  Validation: Unit tests for client error handling.
  Dependencies: S6-T1.
- S6-T3: Wire strategy discovery UI
  Scope: Replace mock data with live API calls.
  Deliverables: UI uses API client for discovery list.
  Validation: UI shows data from API in staging.
  Dependencies: S6-T2.
- S6-T4: Wire investor report UI
  Scope: Replace mock metrics with API calls.
  Deliverables: Report view uses API data.
  Validation: UI matches backend calculations.
  Dependencies: S6-T2.
- S6-T5: Wire historical performance UI
  Scope: Time-series charts use API data.
  Deliverables: Chart view uses backend series.
  Validation: Charts render with real data.
  Dependencies: S6-T2.
- S6-T6: Frontend E2E tests
  Scope: Add E2E tests for core flows.
  Deliverables: Playwright tests for discovery/report/history.
  Validation: E2E tests pass against staging.
  Dependencies: S6-T3..S6-T5.
- S6-T7: Release checklist + QA
  Scope: Staging deployment, smoke tests, rollback plan.
  Deliverables: Release checklist doc.
  Validation: Signed-off checklist for release.
  Dependencies: S6-T6.

Subagent review prompt:
"""
Review this sprint/task breakdown for completeness, sequencing, and test coverage. Identify missing tasks, overly large tasks, or unclear validation steps. Suggest improvements that keep sprints demoable and tasks atomic/committable.
"""
