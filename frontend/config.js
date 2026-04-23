// Rate BIPH — runtime config. Edit these for deployment.
window.API_BASE = ''; // same-origin — FastAPI serves frontend + /api on ratebiph.com
// Swap in the real sitekey from https://dash.cloudflare.com/?to=/:account/turnstile for prod.
// The value below is Cloudflare's public "always-passes" test key — fine for local dev, useless in prod.
window.TURNSTILE_SITEKEY = '0x4AAAAAADB2js6CoDaemG_P';
