# Deployment Readiness

## Local services

From the project root, install Python and frontend dependencies as documented in
the root README, then run:

```powershell
python .\run_sprintd.py
```

- UI: `http://127.0.0.1:5173/`
- API documentation: `http://127.0.0.1:8000/docs`
- Stop both services: press `Ctrl+C` in the launcher terminal.

## Versioned inputs

The catalogue, productivity rules, project parameters, golden references and
audited user-facing inventory manifest are versioned. Original tenders, local
uploads, generated PDFs, evaluation responses and provider credentials remain
local and ignored.

## Verification commands

```powershell
.\.venv\Scripts\python.exe -m pytest
Push-Location .\frontend
npm test
npm run build
Pop-Location
```

The optional AI provider is disabled by default. Copy `.env.example` to `.env`
only for explicitly authorized experiments; never expose that file to Vite.
