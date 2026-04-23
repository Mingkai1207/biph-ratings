// Rate BIPH — runtime config. Edit these for deployment.
window.API_BASE = ''; // same-origin — FastAPI serves frontend + /api on ratebiph.com
// Production Cloudflare Turnstile sitekey for ratebiph.com.
// For local dev, swap in the always-passing test key '1x00000000000000000000AA'.
window.TURNSTILE_SITEKEY = '0x4AAAAAADB2js6CoDaemG_P';
