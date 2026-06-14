# Retired Surfaces

This document is a current anti-regression boundary. It exists to keep removed legacy surfaces from being reintroduced.

## Retired

- `/api/translate`
- legacy `GraphAgent` app path
- external `network-translator` dependency path
- old service port `8020`
- standalone legacy frontend backups

## Current Replacement

- Main agent runtime: `POST /api/agent/message`
- REMOVED (v2.1.1): `POST /api/agent/run`
- Config translation module: `POST /api/modules/config-translation/translate`
- Unified frontend: React/Vite app under `frontend/src/`
- Runtime architecture: `agent/runtime/` with `ToolRouter`, capability registry, context builder, and workspace stores

## Anti-Regression Rules

- Do not restore `/api/translate` as a current API.
- Do not describe retired surfaces as current product behavior.
- Do not add a live `GraphAgent` route or app.
- Do not depend on an external `network-translator` repository.
- Do not use port `8020` as a current runtime port.
- Do not restore legacy static frontend backups as active UI.
