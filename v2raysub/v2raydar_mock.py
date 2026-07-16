# -*- coding: utf-8 -*-
"""Mock V2RayDAR worker subprocess CLI for integration and failure testing."""

import sys
import json
import time
import os

def main():
    # Basic CLI parsing
    args = sys.argv[1:]
    
    # Needs to match "worker discovery" or "worker health"
    if len(args) < 2 or args[0] != "worker":
        print("Usage: v2raydar_mock.py worker [discovery|health]", file=sys.stderr)
        sys.exit(1)
        
    mode = args[1]
    
    # Read stdin
    try:
        input_data = sys.stdin.read()
    except Exception as e:
        print(f"Error reading stdin: {e}", file=sys.stderr)
        sys.exit(1)
        
    # Check if we should trigger timeout or invalid input before parsing JSON
    if "trigger-timeout" in input_data or "hc-timeout" in input_data:
        time.sleep(10) # Simulate timeout (the test will use a shorter timeout)
        
    if "trigger-invalid-json" in input_data or "hc-invalid-json" in input_data:
        print("not a json string")
        sys.exit(0)
        
    if "trigger-nonzero-exit" in input_data or "hc-nonzero-exit" in input_data:
        sys.exit(5)
        
    if "trigger-crash" in input_data or "hc-crash" in input_data:
        os._exit(12)
        
    # Try parsing
    try:
        payload = json.loads(input_data)
    except Exception as e:
        # If it's invalid JSON, return a standard error
        output = {
            "schema_version": 1,
            "success": False,
            "worker_version": "mock-0.1.0",
            "job_id": "unknown",
            "duration_ms": 10,
            "results": [],
            "error": f"Failed to parse stdin: {e}"
        }
        print(json.dumps(output))
        sys.exit(0)
        
    # Check unsupported schema
    if payload.get("schema_version") != 1 or "trigger-unsupported-schema" in input_data or "hc-unsupported-schema" in input_data:
        output = {
            "schema_version": 2, # unsupported version
            "success": False,
            "worker_version": "mock-0.1.0",
            "job_id": payload.get("job_id", "unknown") if isinstance(payload, dict) else "unknown",
            "duration_ms": 10,
            "results": [],
            "error": "Unsupported schema version"
        }
        print(json.dumps(output))
        sys.exit(0)
        
    # Normal response simulation
    results = []
    
    if mode == "discovery":
        sources = payload.get("sources", [])
        for src in sources:
            name = src.get("name", "mock-src")
            url = src.get("url", "")
            
            if "trigger-benchmark" in url:
                for i in range(2000):
                    results.append({
                        "uri": f"vmess://benchmark-config-{i}-{name}",
                        "protocol": "vmess",
                        "reachable": True,
                        "latency_ms": 50,
                        "country_code": "US",
                        "validation": "Success",
                        "error": None,
                        "source": name
                    })
            else:
                # Generate a working config and a failing config
                results.append({
                    "uri": f"vmess://mock-healthy-from-{name}",
                    "protocol": "vmess",
                    "reachable": True,
                    "latency_ms": 80,
                    "country_code": "DE",
                    "validation": "Success",
                    "error": None,
                    "source": name
                })
                results.append({
                    "uri": f"vless://mock-unhealthy-from-{name}",
                    "protocol": "vless",
                    "reachable": False,
                    "latency_ms": None,
                    "country_code": None,
                    "validation": "ActiveTestTimeout",
                    "error": "Connection timed out",
                    "source": name
                })
            
    elif mode == "health":
        configs = payload.get("configs", [])
        for index, cfg in enumerate(configs):
            uri = cfg.get("uri", "")
            protocol = cfg.get("protocol", "vmess")
            
            # Simulate some configs failing, others succeeding
            # Trigger unhealthy if the URI contains 'mock-unhealthy'
            if "mock-unhealthy" in uri or index % 2 == 1:
                results.append({
                    "uri": uri,
                    "protocol": protocol,
                    "reachable": False,
                    "latency_ms": None,
                    "country_code": None,
                    "validation": "ActiveTestTimeout",
                    "error": "Connection timed out",
                    "source": "health-check"
                })
            else:
                results.append({
                    "uri": uri,
                    "protocol": protocol,
                    "reachable": True,
                    "latency_ms": 110,
                    "country_code": "US",
                    "validation": "Success",
                    "error": None,
                    "source": "health-check"
                })
                
    output = {
        "schema_version": 1,
        "success": True,
        "worker_version": "mock-0.1.0",
        "job_id": payload.get("job_id", "unknown"),
        "duration_ms": 120,
        "results": results,
        "error": None
    }
    print(json.dumps(output))

if __name__ == "__main__":
    main()
