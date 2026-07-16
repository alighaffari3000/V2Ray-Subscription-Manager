# Final Integration Plan: V2RayDAR & v2raysub

This plan establishes a clean separation of concerns by keeping the Rust scan engine (**V2RayDAR**) completely stateless, removing all internal HTTP endpoints, and exchanging data strictly via standard input/output streams (stdin/stdout) using a synchronous, versioned request/response protocol.

---

## Final Architecture Overview

```
                                Admin Panel UI
                                      │
                                      ▼
                                Python Backend
                                      │
           ┌──────────────────────────┴──────────────────────────┐
           ▼                                                     ▼
     Database Layer                                      AutomationService
 (auto_sources, configs,                                 (Orchestrator Layer)
    scan_history tables)                                         │
                                   ┌──────────────┬──────────────┼──────────────┬──────────────┐
                                   ▼              ▼              ▼              ▼              ▼
                                 Runner     ResultParser  ConfigImporter  HealthManager  MetricsRecorder
                                   │
                                   ▼ (Subprocess: standard stream exchange via subprocess.run)
                                V2RayDAR Worker Subcommand
                                   ├── CLI Subcommands: `v2raydar worker discovery` / `v2raydar worker health`
                                   ├── Module: `src/worker.rs` (stateless, stdout ONLY for JSON, stderr for logs)
                                   └── Executed by: `sing-box` (parallel Active Probing)
```

---

## User Review Required

> [!IMPORTANT]
> **Subprocess Execution Path:**
> The Python runner will invoke the `v2raydar` executable as a subprocess.
> A custom path configuration will be added to the `.env` file to allow overriding this location:
> `V2RAYDAR_PATH=F:/Telegram Bots/v2ray-sub-auto/V2RayDAR-main/target/debug/v2raydar.exe`

---

## Protocol Versioning Rules

We define explicit versioning policies to ensure long-term stability and forward/backward compatibility:

* **`worker_version` (String):** Identifies the build/release version of the V2RayDAR executable (e.g., `"0.5.4"`). This changes with every release or bug fix.
* **`schema_version` (Integer):** Identifies the structural JSON protocol interface (e.g., `1`).
* **Independent Versioning:** A new `worker_version` does **not** require a new `schema_version`.
* **Changes & Increments:**
  * The `schema_version` is only incremented for **breaking changes** to the protocol schema (e.g., removing required fields or changing value types).
  * **Backward-compatible additions** (such as new optional output fields) will retain the same `schema_version`.

This guarantees that the Python backend can safely interact with any future V2RayDAR release as long as the reported `schema_version` is supported.

---

## Detailed Specifications of Revisions

### 1. Completely Stateless Rust Worker
* The worker code will **never** open or connect to any rusqlite database.
* Probing functions `load_candidates_with_cache` and `probe_candidates` do not require a database connection and will be called directly in the stateless worker module.

### 2. Dedicated Worker Module (`src/worker.rs`)
* A new file [worker.rs](file:///f:/Telegram%20Bots/v2ray-sub-auto/V2RayDAR-main/src/worker.rs) will contain all worker logic:
  * Structs for input/output JSON schemas.
  * Function `run(mode: WorkerMode, config: AppConfig) -> Result<()>` (dispatched from `main.rs`).

### 3. stdout Reserved Exclusively for JSON
* In worker mode, tracing/logging is initialized to target `std::io::stderr`.
* The final structured output payload is written directly to `std::io::stdout()`.

### 4. Versioned JSON Protocol (Schema Version 1)
* **Discovery Input Schema (stdin):**
  ```json
  {
    "schema_version": 1,
    "mode": "discovery",
    "sources": [
      {
        "name": "source-1",
        "url": "https://example.com/sub",
        "priority": 100
      }
    ]
  }
  ```
* **Health Check Input Schema (stdin):**
  ```json
  {
    "schema_version": 1,
    "mode": "health_check",
    "configs": [
      {
        "uri": "vmess://...",
        "protocol": "vmess"
      }
    ]
  }
  ```
* **Unified Output Schema (stdout):**
  ```json
  {
    "schema_version": 1,
    "success": true,
    "worker_version": "0.5.4",
    "duration_ms": 1420,
    "results": [
      {
        "uri": "vmess://...",
        "protocol": "vmess",
        "reachable": true,
        "latency_ms": 120,
        "country_code": "DE",
        "validation": "Success",
        "error": null
      }
    ]
  }
  ```

### 5. Return Complete Probe Results
* The Rust worker returns results for all probed items, including those that failed.
* Detailed error messages (`timeout`, `connection refused`, etc.) will be populated in the `"error"` field for Python to process.

### 6. Monotonic Scheduler Timing
* The background scheduler will use `time.monotonic()` in Python instead of `time.time()` to protect against manual system clock changes.

### 7. Extended `scan_history` Schema
* Schema definition for the `scan_history` table:
  ```sql
  CREATE TABLE IF NOT EXISTS scan_history (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      scan_type TEXT NOT NULL,
      started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
      finished_at TIMESTAMP,
      duration_ms INTEGER,
      discovered_count INTEGER DEFAULT 0,
      added_count INTEGER DEFAULT 0,
      disabled_count INTEGER DEFAULT 0,
      deleted_count INTEGER DEFAULT 0,
      status TEXT NOT NULL, -- 'success' or 'failed'
      error_message TEXT,
      worker_version TEXT,
      engine_version TEXT
  )
  ```

### 8. Decomposed Python Automation Components
* We will decouple the `AutomationService` by introducing 5 helper classes:
  1. **Runner**: Formulates CLI arguments, invokes the subprocess synchronously using `subprocess.run()` with `input=`, `capture_output=True`, `text=True`, and a configurable `timeout`, and handles exit status check.
  2. **ResultParser**: Validates schema version (aborts if version mismatch), parses JSON, and logs structural parse warnings/errors.
  3. **ConfigImporter**: Performs duplicate checking using local normalization criteria, evaluates `max_active_configs` constraints, and writes new discovered items to the DB.
  4. **HealthManager**: Modifies configurations based on check outcomes, counts consecutive failures, and triggers cleanup policies.
  5. **MetricsRecorder**: Commits records to the `scan_history` table and updates `auto_sources` metadata.
* `AutomationService` itself coordinates these sub-components.

### 9. Version Compatibility Checks
* The `ResultParser` checks the output JSON's `schema_version`. If the version does not match `1`, it aborts immediately, preventing corrupted inputs and recording the version mismatch error into `scan_history`.

### 10. CLI Subcommands in clap
* The CLI layout is updated to clap subcommands:
  * `v2raydar worker discovery`
  * `v2raydar worker health`

---

## Proposed Changes (Phase 2)

### Python Backend: v2raysub

#### [MODIFY] [database.py](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/database.py)
* Update `init_db()` to implement new tables and migration logic:
  * Create `auto_sources` table including `last_scan`, `last_success`, `last_error`, `failure_count`.
  * Create `scan_history` table with extended metadata.
  * Add configuration columns to the `configs` table.
  * Populate default parameters in `settings`.

#### [NEW] [automation_service.py](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/services/automation_service.py)
* Implement `AutomationService` orchestrating the decomposed classes:
  * `Runner` (using synchronous `subprocess.run()`)
  * `ResultParser`
  * `ConfigImporter`
  * `HealthManager`
  * `MetricsRecorder`
* Unified orchestrator function: `run_scan(mode)`. Uses a `threading.Lock` to avoid concurrent runs.

#### [NEW] [scheduler.py](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/services/scheduler.py)
* Spawns a background thread ticking every 10 seconds.
* Tracks timing dynamically using `time.monotonic()` relative to configured intervals.

#### [MODIFY] [admin_api.py](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/routes/admin_api.py) & [admin_pages.py](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/routes/admin_pages.py)
* Expose endpoints for:
  * Auto Sources CRUD
  * Automation Settings update
  * Manual triggers
* Pass stats, source listings, and scan history logs to templates.

#### [MODIFY] [admin.html](file:///f:/Telegram%20Bots/v2ray-sub-auto/v2raysub/templates/admin.html)
* Add user interfaces for Auto Scan Dashboard, Auto Sources tables, and Automation Settings forms.
* Embed detailed status indicators (source, latency, failures, health state) within the config details layout.

---

### Rust Scan Engine: V2RayDAR

#### [MODIFY] [main.rs](file:///f:/Telegram%20Bots/v2ray-sub-auto/V2RayDAR-main/src/main.rs)
* Parse subcommands:
  * `worker discovery`
  * `worker health`
* Route execution directly to `worker::run(...)`.
* Configure logging and tracer to output exclusively to stderr.

#### [NEW] [worker.rs](file:///f:/Telegram%20Bots/v2ray-sub-auto/V2RayDAR-main/src/worker.rs)
* Implement Rust JSON parsing and active probing orchestration.
* Read config lists or source feeds from stdin, invoke testing pipelines, and serialize results directly to stdout.

---

## Verification Plan

### Stage 1 Verification (Startup Bug Fix)
1. Fix database startup issue in `v2raysub`.
2. Run test imports and existing integration tests.
3. Commit the fix separately.

### Stage 2 Verification (Feature Verification)
1. Verify Rust worker subcommands locally by piping test vectors to stdout.
2. Confirm the Python runner properly handles stdin/stdout pipes, version checks, and database commits.
3. Verify visual updates on the admin portal dashboard.
