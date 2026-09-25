/* ════════════════════════════════════════════════
   MedRelay — main.js  (shared across all pages)
   static/js/main.js
   ════════════════════════════════════════════════ */

/* ── Scroll shadow on nav ── */
window.addEventListener('scroll', () => {
  document.querySelector('.nav')?.classList.toggle('scrolled', window.scrollY > 20);
});

/* ── Mark active nav link ── */
(function () {
  const path = location.pathname;
  document.querySelectorAll('.nav-links a').forEach(a => {
    const href = a.getAttribute('href');
    if (href && path.endsWith(href.replace(/^.*\//, '').split('?')[0])) {
      a.classList.add('active');
    }
    if (path === '/' && href === '/') a.classList.add('active');
  });
})();

/* ── Fade-up on scroll ── */
const _obs = new IntersectionObserver(entries => {
  entries.forEach(e => { if (e.isIntersecting) { e.target.classList.add('visible'); _obs.unobserve(e.target); } });
}, { threshold: 0.1, rootMargin: '0px 0px -40px 0px' });
document.querySelectorAll('.fade-up').forEach(el => _obs.observe(el));

/* ── Toast ── */
window.showToast = function (msg, type = 'default') {
  let t = document.getElementById('toast');
  if (!t) { t = Object.assign(document.createElement('div'), { id: 'toast' }); document.body.appendChild(t); }
  t.textContent = msg;
  t.style.background = type === 'success' ? '#16a34a' : type === 'error' ? '#b91c1c' : '';
  t.classList.add('show');
  clearTimeout(window._tt);
  window._tt = setTimeout(() => t.classList.remove('show'), 3500);
};

/* ── Mobile burger ── */
document.querySelector('.nav-burger')?.addEventListener('click', function () {
  const links = document.querySelector('.nav-links');
  if (!links) return;
  const open = links.style.display === 'flex';
  if (open) {
    links.removeAttribute('style');
    document.querySelector('.nav-cta')?.removeAttribute('style');
  } else {
    Object.assign(links.style, {
      display: 'flex', flexDirection: 'column',
      position: 'fixed', top: '70px', left: '0', right: '0',
      background: 'var(--white)', padding: '16px 20px',
      borderBottom: '1px solid var(--border)', boxShadow: 'var(--shadow)',
      zIndex: '200', gap: '4px',
    });
    const cta = document.querySelector('.nav-cta');
    if (cta) Object.assign(cta.style, { display: 'block', margin: '8px 0 0' });
  }
});

/* ── Smooth page fade ── */
document.querySelectorAll('a[href]').forEach(a => {
  const h = a.getAttribute('href');
  if (!h || h.startsWith('#') || h.startsWith('http') || h.startsWith('tel') || h.startsWith('mailto')) return;
  a.addEventListener('click', e => {
    e.preventDefault();
    Object.assign(document.body.style, { opacity: '0', transition: 'opacity .22s' });
    setTimeout(() => { window.location.href = h; }, 230);
  });
});
window.addEventListener('load', () => Object.assign(document.body.style, { opacity: '1', transition: 'opacity .28s' }));

/* ── File Uploader class ── */
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
  _add(fileList) {
    [...fileList].forEach(f => {
      const idx = this.files.length;
      this.files.push(f);
      if (f.type.startsWith('image/')) {
        const r = new FileReader();
        r.onload = e => this._thumb(e.target.result, idx);
        r.readAsDataURL(f);
      } else {
        this._thumb(null, idx, f.name);
      }
    });
  }
  _thumb(src, idx, name) {
    const div = Object.assign(document.createElement('div'), { className: 'preview-item', id: `pv${idx}` });
    div.innerHTML = src
      ? `<img src="${src}" alt="rx"><button class="preview-remove" onclick="window.__up.remove(${idx})">×</button>`
      : `<div style="display:flex;align-items:center;justify-content:center;flex-direction:column;height:100%;background:#162d54">
           <span style="font-size:22px">📄</span>
           <span style="font-size:9px;color:#7fa;padding:2px;word-break:break-all;text-align:center">${name}</span>
           <button class="preview-remove" onclick="window.__up.remove(${idx})">×</button>
         </div>`;
    this.grid?.appendChild(div);
  }
  remove(idx) { this.files[idx] = null; document.getElementById(`pv${idx}`)?.remove(); }
  valid()     { return this.files.filter(Boolean); }
}
window.FileUploader = FileUploader;