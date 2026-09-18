# Header the SPA sends on every request (frontend/src/api.js); the CSRF
# middleware requires it (or an allow-listed Origin) on state-changing calls.
SPA_HEADERS = {"X-Requested-With": "XMLHttpRequest"}
