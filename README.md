# Atlas API

Operational backend for Atlas - API layer and trade execution.

## Purpose

- Serve data to atlas-frontend
- Execute trades on GMX V2 via dHEDGE vaults (Arbitrum)
- Store strategy metadata and investor reports

## Local Development

```bash
pip install -e ".[dev]"
uvicorn api.main:app --reload
```

Open http://localhost:8000/docs for Swagger UI.
