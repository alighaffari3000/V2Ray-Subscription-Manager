# V2RayDAR Worker Execution Contract (Version 1)

This document freezes the standard request/response contract and CLI options of the stateless V2RayDAR worker subcommands (`discovery` and `health`).

---

## 1. Request Contract (Standard Input - stdin)

All inputs passed to the worker must be serialized as UTF-8 JSON.

### A. Auto Discovery Request Schema
```json
{
  "schema_version": 1,
  "mode": "discovery",
  "job_id": "unique-uuid-hex",
  "sources": [
    {
      "name": "source-name",
      "url": "https://example.com/sub",
      "priority": 100
    }
  ],
  "scan_all": false,
  "target_count": 10
}
```

`scan_all` and `target_count` are optional early-stop controls. When `scan_all`
is `false` (or omitted) and `target_count` is set, probing halts as soon as that
many reachable configs are found instead of testing every candidate — a large
saving for big subscriptions. Set `scan_all` to `true` to force a full scan.
Omitting both probes every candidate.

### B. Health Check Request Schema
```json
{
  "schema_version": 1,
  "mode": "health_check",
  "job_id": "unique-uuid-hex",
  "configs": [
    {
      "uri": "vmess://...",
      "protocol": "vmess"
    }
  ]
}
```

---

## 2. Response Contract (Standard Output - stdout)

All output is logged to stdout as a single-line or pretty-printed JSON payload. All trace/debug logs must be printed exclusively to stderr.

### A. Success Output Schema
```json
{
  "schema_version": 1,
  "success": true,
  "worker_version": "0.5.4",
  "job_id": "unique-uuid-hex",
  "duration_ms": 1250,
  "results": [
    {
      "uri": "vmess://...",
      "protocol": "vmess",
      "reachable": true,
      "latency_ms": 120,
      "country_code": "DE",
      "validation": "active_http",
      "error": null,
      "source": "source-name"
    }
  ],
  "error": null
}
```

`reachable` is the pass/fail flag — it is `true` only when the probe actually
succeeded. `validation` names the *method* that produced that verdict
(`"active_http"` for a full sing-box tunnel check, `"tcp_connect"` for a
TCP-only check), not a literal `"Success"`. Consumers must gate on `reachable`,
never on a specific `validation` string.

### B. Error Output Schema
```json
{
  "schema_version": 1,
  "success": false,
  "worker_version": "0.5.4",
  "job_id": "unique-uuid-hex",
  "duration_ms": 250,
  "results": [],
  "error": "Descriptive error message detailing why the operation failed"
}
```

---

## 3. CLI Tuning Options

Runtime performance tuning is managed exclusively via Command Line Interface (CLI) arguments:

* `--fetch-concurrency <usize>`: Limits the count of concurrent subscription feeds downloads (default: `4`).
* `--probe-concurrency <usize>`: Limits the count of concurrent active ping probes (default: `10`).
* `--probe-process-concurrency <usize>`: Limits the count of parallel active probe processes (default: `2`).

---

## 4. Exit & Error Codes

* `0`: Success. The worker executed completely and outputted a valid JSON payload on stdout (even if individual configurations failed validation).
* `1`: General command error or unhandled panic (printed to stderr).
* `5` / Other: Worker execution failed prior to schema parsing.

---

## 5. Timeout & Cancellation Behavior

* **Timeout**: Subprocess timeout is enforced by the caller (Python Runner) using a default timeout threshold (e.g. 600s).
* **Cancellation**: Upon receiving `SIGINT` (Ctrl+C) or `SIGTERM`, the worker receives the cancellation event, aborts queueing further batches, flushes already validated configs to stdout, and exits gracefully with code `0`.

---

## 6. Backward Compatibility Rules

* **Stable Rule**: Any change to the request or response schema requires incrementing the `schema_version` integer.
* **Compatibility**: Future worker releases can add optional fields to either input or output schemas without modifying `schema_version`. The Python parser must ignore unrecognized fields.
