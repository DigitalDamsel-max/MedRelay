/* ═══════════════════════════════════════════════
   MedRelay  —  static/js/main.js
   Shared utilities loaded on every page
   ═══════════════════════════════════════════════ */

/* ── Nav scroll shadow ────────────────────────── */
window.addEventListener('scroll', () => {
  document.querySelector('.nav')?.classList.toggle('scrolled', window.scrollY > 20);
});

/* ── Active nav link ──────────────────────────── */
(function () {
  const path = location.pathname.replace(/\/$/, '') || '/';
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href');
    if (href === path || href === path + '/') a.classList.add('active');
  });
})();

/* ── Fade-up intersection observer ───────────── */
const _io = new IntersectionObserver(entries => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); _io.unobserve(e.target); } });
}, { threshold: 0.08, rootMargin: '0px 0px -36px 0px' });
document.querySelectorAll('.fade-up').forEach(el => _io.observe(el));

/* ── Toast ────────────────────────────────────── */
window.showToast = function (msg, type = 'default') {
  let t = document.getElementById('toast');
  if (!t) { t = document.createElement('div'); t.id = 'toast'; document.body.appendChild(t); }
  t.textContent = msg;
  t.className = 'show';
  t.style.background = type === 'success' ? '#15803d' : type === 'error' ? '#b91c1c' : '';
  clearTimeout(window._tt);
  window._tt = setTimeout(() => t.classList.remove('show'), 3500);
};

/* ── Mobile hamburger ─────────────────────────── */
document.querySelector('.nav-hamburger')?.addEventListener('click', () => {
  const links = document.querySelector('.nav-links');
  const cta   = document.querySelector('.nav-cta');
  if (!links) return;
  const open = links.style.display === 'flex';
  if (!open) {
    links.style.cssText = `
      display:flex; flex-direction:column;
      position:fixed; top:70px; left:0; right:0;
      background:var(--white); padding:16px 20px;
      border-bottom:1px solid var(--border);
      box-shadow:var(--sh); z-index:299; gap:2px;`;
    if (cta) { cta.style.display = 'block'; cta.style.marginTop = '8px'; }
  } else {
    links.style.cssText = '';
    if (cta) cta.style.cssText = '';
  }
});

/* ── Smooth page fade ─────────────────────────── */
window.addEventListener('load', () => {
  document.body.style.opacity = '1';
  document.body.style.transition = 'opacity .3s';
});
document.querySelectorAll('a[href]').forEach(a => {
  const h = a.getAttribute('href');
  if (!h.startsWith('#') && !h.startsWith('http') && !h.startsWith('tel') && !h.startsWith('mailto')) {
    a.addEventListener('click', e => {
      e.preventDefault();
      document.body.style.opacity = '0';
      setTimeout(() => location.href = h, 240);
    });
  }
});

/* ── FileUploader class ───────────────────────── */
class FileUploader {
  constructor(dropId, inputId, gridId) {
    this.dz    = document.getElementById(dropId);
    this.input = document.getElementById(inputId);
    this.grid  = document.getElementById(gridId);
    this.files = [];
    if (!this.dz) return;
    this.dz.addEventListener('dragover',  e => { e.preventDefault(); this.dz.classList.add('drag-over'); });
    this.dz.addEventListener('dragleave', () => this.dz.classList.remove('drag-over'));
    this.dz.addEventListener('drop',      e => { e.preventDefault(); this.dz.classList.remove('drag-over'); this._add(e.dataTransfer.files); });
    this.input?.addEventListener('change', e => this._add(e.target.files));
  }
  _add(list) {
    [...list].forEach(f => {
      const idx = this.files.length;
      this.files.push(f);
      if (f.type.startsWith('image/')) {
        const r = new FileReader();
        r.onload = e => this._thumb(e.target.result, idx);
        r.readAsDataURL(f);
      } else {
        this._thumbDoc(f.name, idx);
      }
    });
  }
  _thumb(src, idx) {
    const d = document.createElement('div');
    d.className = 'preview-item'; d.id = `pv-${idx}`;
    d.innerHTML = `<img src="${src}" alt=""><button class="preview-remove" data-idx="${idx}">×</button>`;
    d.querySelector('button').addEventListener('click', () => this._rm(idx));
    this.grid?.appendChild(d);
  }
  _thumbDoc(name, idx) {
    const d = document.createElement('div');
    d.className = 'preview-item'; d.id = `pv-${idx}`;
    d.style.cssText = 'display:flex;align-items:center;justify-content:center;flex-direction:column;background:#162d54;';
    d.innerHTML = `<div style="font-size:22px">📄</div><div style="font-size:9px;color:#8be;padding:2px;word-break:break-all;text-align:center">${name}</div><button class="preview-remove" data-idx="${idx}">×</button>`;
    d.querySelector('button').addEventListener('click', () => this._rm(idx));
    this.grid?.appendChild(d);
  }
  _rm(idx) { this.files[idx] = null; document.getElementById(`pv-${idx}`)?.remove(); }
  valid()   { return this.files.filter(Boolean); }
}
window.FileUploader = FileUploader;

/* ── localStorage helpers ─────────────────────── */
window.Store = {
  set: (k, v) => localStorage.setItem(k, JSON.stringify(v)),
  get: (k)    => { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  del: (k)    => localStorage.removeItem(k),
};