// Rate BIPH — shared frontend helpers. Vanilla JS, no framework.
(function () {
  const API = window.API_BASE || '';

  // ——— Fetch wrapper
  async function api(path, opts = {}) {
    const res = await fetch(API + path, {
      ...opts,
      headers: { 'Content-Type': 'application/json', ...(opts.headers || {}) },
    });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) {
      const err = new Error((data && (data.message || data.detail)) || res.statusText);
      err.status = res.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  // ——— Avatar helpers (hash name -> color from warm palette)
  const AVATAR_COLORS = [
    'oklch(0.85 0.08 70)',
    'oklch(0.86 0.07 110)',
    'oklch(0.84 0.09 40)',
    'oklch(0.86 0.06 170)',
    'oklch(0.84 0.08 20)',
    'oklch(0.87 0.06 150)',
    'oklch(0.85 0.09 85)',
    'oklch(0.83 0.08 55)',
  ];
  function hashString(s) {
    let h = 0;
    for (let i = 0; i < s.length; i++) h = ((h << 5) - h + s.charCodeAt(i)) | 0;
    return Math.abs(h);
  }
  function avatarColor(name) {
    return AVATAR_COLORS[hashString(name) % AVATAR_COLORS.length];
  }
  function initials(name) {
    const parts = (name || '').trim().split(/\s+/).filter(Boolean);
    if (!parts.length) return '?';
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }
  function avatarEl(name, size = 44) {
    const el = document.createElement('div');
    el.className = 'avatar';
    el.style.width = size + 'px';
    el.style.height = size + 'px';
    el.style.borderRadius = size * 0.3 + 'px';
    el.style.fontSize = size * 0.42 + 'px';
    el.style.background = avatarColor(name);
    el.textContent = initials(name);
    return el;
  }

  // ——— Stars
  const STAR_PATH = 'M12 2.5l2.95 5.98 6.6.96-4.78 4.66 1.13 6.57L12 17.58l-5.9 3.1 1.13-6.58L2.45 9.44l6.6-.96L12 2.5z';
  function starSvg(kind, id, size) {
    const star = 'var(--star)';
    const empty = 'var(--line-strong)';
    let fill, stroke;
    if (kind === 'full') { fill = star; stroke = star; }
    else if (kind === 'half') { fill = `url(#h-${id})`; stroke = star; }
    else { fill = empty; stroke = empty; }
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" data-kind="${kind}">
      <defs><linearGradient id="h-${id}"><stop offset="50%" stop-color="${star}"/><stop offset="50%" stop-color="${empty}"/></linearGradient></defs>
      <path d="${STAR_PATH}" fill="${fill}" stroke="${stroke}" stroke-width="0.8" stroke-linejoin="round"/>
    </svg>`;
  }
  function renderStars(container, value, { size = 18, interactive = false, onChange } = {}) {
    container.innerHTML = '';
    container.classList.add('stars');
    if (interactive) container.classList.add('stars--interactive');
    const id = 's' + Math.random().toString(36).slice(2, 7);
    let hover = 0;
    const draw = (v) => {
      container.innerHTML = '';
      for (let i = 1; i <= 5; i++) {
        let kind = 'empty';
        if (i <= Math.floor(v)) kind = 'full';
        else if (i - 0.5 <= v) kind = 'half';
        const wrap = document.createElement('span');
        wrap.style.display = 'inline-flex';
        wrap.style.cursor = interactive ? 'pointer' : 'default';
        wrap.innerHTML = starSvg(kind, id + '-' + i, size);
        if (interactive) {
          wrap.addEventListener('mouseenter', () => { hover = i; draw(hover); });
          wrap.addEventListener('click', () => { onChange && onChange(i); });
        }
        container.appendChild(wrap);
      }
    };
    draw(value || 0);
    if (interactive) {
      container.addEventListener('mouseleave', () => { hover = 0; draw(value || 0); });
      container.setValue = (v) => { value = v; draw(v); };
    }
  }

  // ——— Toast
  function toast(msg) {
    let el = document.querySelector('.toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = msg;
    el.classList.add('toast--show');
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.remove('toast--show'), 3200);
  }

  // ——— Relative date
  function relDate(iso) {
    if (!iso) return '';
    const d = new Date(iso);
    if (isNaN(d)) return '';
    const days = Math.floor((Date.now() - d.getTime()) / 86400000);
    if (days < 1) return 'today';
    if (days < 7) return `${days}d ago`;
    if (days < 30) return `${Math.floor(days / 7)}w ago`;
    if (days < 365) return `${Math.floor(days / 30)}mo ago`;
    return `${Math.floor(days / 365)}y ago`;
  }

  // ——— Turnstile loader
  let turnstileLoaded = false;
  function loadTurnstile() {
    if (turnstileLoaded) return;
    turnstileLoaded = true;
    const s = document.createElement('script');
    s.src = 'https://challenges.cloudflare.com/turnstile/v0/api.js';
    s.async = true; s.defer = true;
    document.head.appendChild(s);
  }
  function mountTurnstile(slot, onToken) {
    loadTurnstile();
    const render = () => {
      if (!window.turnstile) return setTimeout(render, 150);
      window.turnstile.render(slot, {
        sitekey: window.TURNSTILE_SITEKEY,
        callback: (t) => onToken(t),
      });
    };
    render();
  }

  // ——— Topnav helper (logo + links)
  function renderTopnav(active) {
    const host = document.querySelector('[data-topnav]');
    if (!host) return;
    host.innerHTML = `
      <div class="topnav">
        <div class="topnav__inner">
          <a href="index.html" class="logo">
            <span class="logo__mark">
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
                <rect x="6" y="13.5" width="10" height="1.4" rx="0.7" fill="oklch(0.98 0.01 75)"/>
                <rect x="6" y="16.5" width="7" height="1.4" rx="0.7" fill="oklch(0.98 0.01 75)"/>
                <path d="M13.5 9.8l3.6-3.6a1 1 0 0 1 1.4 0l1 1a1 1 0 0 1 0 1.4l-3.6 3.6-2.6.6.2-3z" fill="oklch(0.98 0.01 75)"/>
              </svg>
            </span>
            <span class="logo__word">Rate <em>BIPH</em></span>
          </a>
          <div class="topnav__links">
            <a href="index.html" class="topnav__link ${active==='home'?'is-active':''}">Browse</a>
            <a href="submit.html" class="topnav__link ${active==='submit'?'is-active':''}">Submit a teacher</a>
          </div>
        </div>
      </div>`;
  }

  function renderFooter() {
    const host = document.querySelector('[data-footer]');
    if (!host) return;
    host.innerHTML = `<footer class="footer">
      <div>Rate BIPH is student-run and independent of Beijing International Private High. Reviews are anonymous and moderated.<br/>
      Be kind. Be honest. Be specific.</div>
    </footer>`;
  }

  window.RB = { api, renderStars, avatarEl, initials, avatarColor, toast, relDate, mountTurnstile, renderTopnav, renderFooter };
  document.addEventListener('DOMContentLoaded', () => {
    renderTopnav(document.body.dataset.page);
    renderFooter();
  });
})();
