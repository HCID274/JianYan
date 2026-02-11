@echo off

REM Example env file for publish.cmd
REM 1) Copy this file to publish_env.local.cmd
REM 2) Fill in real values (DO NOT COMMIT publish_env.local.cmd)

REM Required
set "UPLOAD_API_BASES=https://yourhost:4443,https://yourhost:4444"
set "UPLOAD_TOKEN=YOUR_BEARER_TOKEN_HERE"

REM Optional: used by /api/release/publish to build download URLs
set "DOWNLOAD_BASE_URL=https://yourdomain.example/downloads"

REM Optional: keep last N versions on server (server decides what to delete)
set "KEEP_VERSIONS=3"

REM Optional: upload tuning
set "CONCURRENCY=8"
set "CHUNK_MB=8"
set "UPLOAD_TIMEOUT=60"
set "UPLOAD_RETRIES=8"

REM Optional: dangerous (skip TLS verify)
REM set "UPLOAD_INSECURE=1"

REM Optional: allow overwriting same filename on server
REM set "OVERWRITE=1"
