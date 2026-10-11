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

## Cloud reverse proxy

Production frontend builds default to the same-origin API base `/api`; local
Vite development continues to call `http://127.0.0.1:8000`. An explicit
`VITE_API_BASE_URL` may override either value at frontend build time.

The reverse proxy must route `/api/*` to Uvicorn before applying the frontend
single-page fallback. FastAPI accepts both preserved paths (`/api/jobs`) and
stripped paths (`/jobs`), so either proxy convention is supported. For example:

```nginx
location /api/ {
    client_max_body_size 100m;
    proxy_read_timeout 300s;
    proxy_pass http://127.0.0.1:8000;
}

location / {
    try_files $uri /index.html;
}
```

After deployment, verify `GET /api/health`, then `POST /api/jobs`,
`GET /api/jobs/{job_id}` and `GET /api/jobs/{job_id}/results`. A frontend HTML
404 at an `/api` URL means the proxy rule is missing or ordered after the SPA
fallback; a FastAPI JSON 404 means the backend version has not been updated.
