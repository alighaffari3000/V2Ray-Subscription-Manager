use std::collections::HashSet;
use std::io::{self, Read};
use std::time::Instant;
use anyhow::{anyhow, Context, Result};
use serde::{Deserialize, Serialize};

use crate::config::{AppConfig, SubscriptionSource};
use crate::model::{Candidate, ProbeStopPolicy, RankedConfig};
use crate::probe::probe_candidates;
use crate::subscription::load_candidates_with_cache;

pub const SCHEMA_VERSION: u32 = 1;
pub const WORKER_VERSION: &str = env!("CARGO_PKG_VERSION");

#[derive(Debug, Deserialize)]
pub struct WorkerInput {
    pub schema_version: u32,
    pub mode: String,
    pub job_id: String,
    pub sources: Option<Vec<InputSource>>,
    pub configs: Option<Vec<InputConfig>>,
    // Discovery early-stop controls (both optional; absent = scan everything).
    // When `scan_all` is false and `target_count` is set, probing halts as soon
    // as that many reachable configs are found instead of testing all of them.
    pub scan_all: Option<bool>,
    pub target_count: Option<usize>,
    pub timeout_seconds: Option<u64>,
}

#[derive(Debug, Deserialize)]
pub struct InputSource {
    pub name: String,
    pub url: String,
    pub priority: Option<u32>,
}

#[derive(Debug, Deserialize)]
pub struct InputConfig {
    pub uri: String,
    pub protocol: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct WorkerOutput {
    pub schema_version: u32,
    pub success: bool,
    pub worker_version: &'static str,
    pub job_id: String,
    pub duration_ms: u128,
    pub results: Vec<WorkerResult>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct WorkerResult {
    pub uri: String,
    pub protocol: String,
    pub reachable: bool,
    pub latency_ms: Option<u128>,
    pub country_code: Option<String>,
    pub validation: String,
    pub error: Option<String>,
    pub source: String,
}

pub enum WorkerMode {
    Discovery,
    Health,
}

pub async fn run(mode: WorkerMode, config: AppConfig) -> Result<()> {
    let start_time = Instant::now();

    // 1. Read entire stdin to buffer
    let mut stdin_buffer = String::new();
    io::stdin().read_to_string(&mut stdin_buffer)
        .context("Failed to read JSON input from stdin")?;

    // 2. Parse JSON input
    let input: WorkerInput = match serde_json::from_str(&stdin_buffer) {
        Ok(parsed) => parsed,
        Err(err) => {
            let output = WorkerOutput {
                schema_version: SCHEMA_VERSION,
                success: false,
                worker_version: WORKER_VERSION,
                job_id: "unknown".to_string(),
                duration_ms: start_time.elapsed().as_millis(),
                results: Vec::new(),
                error: Some(format!("Invalid JSON payload: {err}")),
            };
            println!("{}", serde_json::to_string(&output)?);
            return Err(anyhow!("Invalid input JSON: {err}"));
        }
    };

    let job_id = input.job_id.clone();

    // 3. Schema Version Validation
    if input.schema_version != SCHEMA_VERSION {
        let output = WorkerOutput {
            schema_version: SCHEMA_VERSION,
            success: false,
            worker_version: WORKER_VERSION,
            job_id: job_id.clone(),
            duration_ms: start_time.elapsed().as_millis(),
            results: Vec::new(),
            error: Some(format!(
                "Unsupported schema version: expected {}, got {}",
                SCHEMA_VERSION, input.schema_version
            )),
        };
        println!("{}", serde_json::to_string(&output)?);
        return Err(anyhow!("Unsupported schema version"));
    }

    // Set up cancellation signal listener task
    let cancel_flag = std::sync::Arc::new(std::sync::atomic::AtomicBool::new(false));
    let cancel_flag_cloned = cancel_flag.clone();
    tokio::spawn(async move {
        if let Ok(()) = tokio::signal::ctrl_c().await {
            eprintln!("Worker received Ctrl+C cancellation signal. Stopping after current batch...");
            cancel_flag_cloned.store(true, std::sync::atomic::Ordering::SeqCst);
        }
    });

    if let Some(timeout_secs) = input.timeout_seconds {
        let cancel_flag_timeout = cancel_flag.clone();
        tokio::spawn(async move {
            let margin = 15;
            if timeout_secs > margin {
                tokio::time::sleep(tokio::time::Duration::from_secs(timeout_secs - margin)).await;
                eprintln!("Worker reached internal timeout limit ({timeout_secs}s). Stopping after current batch to return partial results...");
                cancel_flag_timeout.store(true, std::sync::atomic::Ordering::SeqCst);
            }
        });
    }

    // 4. Dispatch based on mode
    let results = match mode {
        WorkerMode::Discovery => {
            run_discovery(input, config, cancel_flag).await
        }
        WorkerMode::Health => {
            run_health(input, config, cancel_flag).await
        }
    };

    // 5. Build and print the output
    match results {
        Ok(probed_results) => {
            let output = WorkerOutput {
                schema_version: SCHEMA_VERSION,
                success: true,
                worker_version: WORKER_VERSION,
                job_id: job_id.clone(),
                duration_ms: start_time.elapsed().as_millis(),
                results: probed_results,
                error: None,
            };
            println!("{}", serde_json::to_string(&output)?);
            Ok(())
        }
        Err(err) => {
            let output = WorkerOutput {
                schema_version: SCHEMA_VERSION,
                success: false,
                worker_version: WORKER_VERSION,
                job_id: job_id.clone(),
                duration_ms: start_time.elapsed().as_millis(),
                results: Vec::new(),
                error: Some(err.to_string()),
            };
            println!("{}", serde_json::to_string(&output)?);
            Err(err)
        }
    }
}

async fn run_discovery(input: WorkerInput, config: AppConfig, cancel_flag: std::sync::Arc<std::sync::atomic::AtomicBool>) -> Result<Vec<WorkerResult>> {
    let input_sources = input.sources.ok_or_else(|| anyhow!("Missing 'sources' field for discovery mode"))?;
    
    // Map input sources to AppConfig's SubscriptionSource
    let sources = input_sources.into_iter().map(|s| {
        SubscriptionSource {
            name: s.name,
            url: s.url,
            enabled: true,
            priority: s.priority.unwrap_or(100),
        }
    }).collect::<Vec<_>>();

    let mut worker_config = config;
    worker_config.subscriptions = sources;

    // Load candidates from the sources
    let fetched = load_candidates_with_cache(&worker_config, |_| async {}, None).await?;
    let candidates = fetched.candidates;

    if candidates.is_empty() {
        return Ok(Vec::new());
    }

    // Probe the candidates. When the caller asks for early stop (scan_all=false)
    // and gives a target, halt once that many reachable configs are found rather
    // than probing every candidate — a large saving for big subscriptions.
    let scan_all = input.scan_all.unwrap_or(false);
    let top_n = if scan_all {
        candidates.len()
    } else {
        input
            .target_count
            .map(|n| n.clamp(1, candidates.len()))
            .unwrap_or(candidates.len())
    };
    let stop_policy = ProbeStopPolicy {
        scan_all_configs: scan_all,
        top_n,
        prioritize_stability: false,
        return_configs_asap: false,
        previous_working_keys: HashSet::new(),
        cancel_flag: Some(cancel_flag),
    };

    let ranked = probe_candidates(candidates, &worker_config.probe, None, &stop_policy).await;

    Ok(map_ranked_results(ranked))
}

async fn run_health(input: WorkerInput, config: AppConfig, cancel_flag: std::sync::Arc<std::sync::atomic::AtomicBool>) -> Result<Vec<WorkerResult>> {
    let input_configs = input.configs.ok_or_else(|| anyhow!("Missing 'configs' field for health_check mode"))?;

    // Map input configs to V2RayDAR Candidates
    let mut candidates = Vec::new();
    for (index, cfg) in input_configs.into_iter().enumerate() {
        // Parse share link using our standard parser
        match crate::parser::parse_share_link("health-check", 100, &cfg.uri) {
            Ok(mut candidate) => {
                // Ensure candidate has a unique stable ID based on index
                candidate.id = format!("hc-{index}");
                candidates.push(candidate);
            }
            Err(_err) => {
                // Return failed configs directly if parsing fails
                candidates.push(Candidate {
                    id: format!("hc-{index}"),
                    dedup_key: format!("failed-parse-{}", index),
                    source: "health-check".to_string(),
                    priority: 100,
                    protocol: cfg.protocol.clone().unwrap_or_else(|| "unknown".to_string()),
                    name: format!("Invalid URI #{index}"),
                    endpoint: crate::model::Endpoint {
                        host: "invalid".to_string(),
                        port: 0,
                    },
                    uri: cfg.uri.clone(),
                });
            }
        }
    }

    if candidates.is_empty() {
        return Ok(Vec::new());
    }

    // Probe the candidates
    let stop_policy = ProbeStopPolicy {
        scan_all_configs: true,
        top_n: candidates.len(),
        prioritize_stability: false,
        return_configs_asap: false,
        previous_working_keys: HashSet::new(),
        cancel_flag: Some(cancel_flag),
    };

    let ranked = probe_candidates(candidates, &config.probe, None, &stop_policy).await;

    Ok(map_ranked_results(ranked))
}

fn map_ranked_results(ranked: Vec<RankedConfig>) -> Vec<WorkerResult> {
    ranked.into_iter().map(|rc| {
        WorkerResult {
            uri: rc.uri,
            protocol: rc.protocol,
            reachable: rc.reachable,
            latency_ms: rc.latency_ms,
            country_code: rc.country_code,
            validation: rc.validation,
            error: rc.error,
            source: rc.source,
        }
    }).collect()
}
