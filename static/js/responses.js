/* ═══════════════════════════════════════════════
   MedRelay  —  static/js/responses.js
   ═══════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  const order = Store.get('lastOrder');
  const grid  = document.getElementById('responseGrid');

  /* Show track banner if prescription was uploaded */
  if (order) {
    const banner = document.getElementById('trackBanner');
    if (banner) {
      banner.style.display = 'flex';
      document.getElementById('bannerTrackId').textContent = order.id;
      document.getElementById('bannerCount').textContent   = order.count;
      document.getElementById('bannerArea').textContent    = order.area;
    }
    /* Try to load real responses from Flask */
    loadResponses(order.id);
  } else {
    /* Show simulated demo data so the page isn't empty */
    loadDemoResponses();
  }

  /* ── Load from API ───────────────────────────── */
  async function loadResponses(prescId) {
    try {
      const res  = await fetch(`/api/responses/${prescId}`);
      const data = await res.json();
      if (data.responses && data.responses.length > 0) {
        renderAll(data.responses);
      } else {
        /* No real responses yet — show demo */
        loadDemoResponses();
      }
    } catch {
      loadDemoResponses();
    }
  }

  /* ── Demo data (shown when no real responses) ── */
  function loadDemoResponses() {
    const DEMO = [
      {
        pharmacy_name:'LifeCare Pharmacy', pharmacy_dist:1.2, icon:'🏥', bg:'#e6f7f5', delay:0,
        medicines:[
          { name:'Metformin 500mg × 30',    available:true,  price:142 },
          { name:'Atorvastatin 10mg × 30',  available:true,  price:210 },
          { name:'Amlodipine 5mg × 30',     available:true,  price:88  },
        ],
        total_price:440, availability:'all', created_at: new Date().toISOString(),
        pharmacy_phone:'0712-244-5678',
      },
      {
        pharmacy_name:'Wellness Pharmacy',  pharmacy_dist:1.8, icon:'🌿', bg:'#e8f5e9', delay:3500,
        medicines:[
          { name:'Metformin 500mg × 30',    available:true,  price:130 },
          { name:'Atorvastatin 10mg × 30',  available:true,  price:198 },
          { name:'Amlodipine 5mg × 30',     available:true,  price:75  },
        ],
        total_price:403, availability:'all', created_at: new Date().toISOString(),
        pharmacy_phone:'0712-277-3344',
      },
      {
        pharmacy_name:'Apollo Pharmacy',    pharmacy_dist:2.8, icon:'💊', bg:'#fef9ec', delay:7000,
        medicines:[
          { name:'Metformin 500mg × 30',    available:true,  price:138 },
          { name:'Atorvastatin 10mg × 30',  available:true,  price:228 },
          { name:'Amlodipine 5mg × 30',     available:false, price:0   },
        ],
        total_price:366, availability:'partial', created_at: new Date().toISOString(),
        pharmacy_phone:'0712-255-9900',
      },
      {
        pharmacy_name:'MedPlus Stores',     pharmacy_dist:3.5, icon:'🏪', bg:'#f0eeff', delay:11000,
        medicines:[
          { name:'Metformin 500mg × 30',    available:true,  price:155 },
          { name:'Atorvastatin 10mg × 30',  available:true,  price:205 },
          { name:'Amlodipine 5mg × 30',     available:true,  price:92  },
        ],
        total_price:452, availability:'all', created_at: new Date().toISOString(),
        pharmacy_phone:'0712-266-1122',
      },
    ];
    grid.innerHTML = '';
    DEMO.forEach((r, i) => {
      setTimeout(() => {
        appendCard(r);
        updateProgress(i + 1, DEMO.length);
        if (i < DEMO.length - 1) showToast(`🔔 New reply from ${r.pharmacy_name}!`);
        else showToast('✅ All demo replies loaded', 'success');
      }, r.delay);
    });
  }

  /* ── Render all at once (real API data) ──────── */
  function renderAll(list) {
    grid.innerHTML = '';
    list.forEach((r, i) => appendCard(r));
    updateProgress(list.length, list.length);
  }

  /* ── Build one card ──────────────────────────── */
  function appendCard(r) {
    const icons   = { 'LifeCare Pharmacy':'🏥','Wellness Pharmacy':'🌿','Apollo Pharmacy':'💊','MedPlus Stores':'🏪','Jan Aushadhi Kendra':'🏛','Sahyadri Pharma':'🌿','NetMeds Store':'🛒','Dr. Reddy\'s Pharma':'💉' };
    const bgs     = { 'all':'#e6f7f5', 'partial':'#fef9ec', 'none':'#fff1f1' };
    const icon    = r.icon || icons[r.pharmacy_name] || '💊';
    const bg      = r.bg   || bgs[r.availability]    || '#f5f5f5';
    const badgeCls= r.availability === 'all' ? 'badge-green' : r.availability === 'partial' ? 'badge-yellow' : 'badge-red';
    const badgeTxt= r.availability === 'all' ? 'All Available' : r.availability === 'partial' ? 'Partial' : 'Unavailable';
    const relTime = timeAgo(r.created_at);

    const medRows = (r.medicines || []).map(m => `
      <div class="med-row">
        <span class="med-row-name">
          <span class="med-dot ${m.available ? 'avail' : 'na'}"></span>
          ${m.name}
        </span>
        ${m.available
          ? `<span class="med-price">₹${m.price}</span>`
          : `<span class="med-price out">Out of stock</span>`}
      </div>`).join('');

    const card = document.createElement('div');
    card.className = 'response-card';
    card.style.animation = 'fadeUp .45s ease both';
    card.innerHTML = `
      <div class="rc-head">
        <div class="rc-icon" style="background:${bg}">${icon}</div>
        <div>
          <div class="rc-name">${r.pharmacy_name}</div>
          <div class="rc-dist">📍 ${r.pharmacy_dist} km away</div>
        </div>
        <span class="badge ${badgeCls}" style="margin-left:auto">${badgeTxt}</span>
      </div>
      <div class="rc-body">${medRows}</div>
      <div class="rc-foot">
        <div>
          <div class="rc-meta"><span class="rc-pulse"></span> ${relTime}</div>
          <div class="rc-total">₹${r.total_price}</div>
        </div>
        <div style="display:flex;flex-direction:column;gap:7px;align-items:flex-end">
          <a href="/map" class="btn btn-outline btn-sm">🗺️ Map</a>
          <button class="btn btn-primary btn-sm" onclick="placeOrder('${r.pharmacy_name}','₹${r.total_price}','${r.pharmacy_phone}')">Order Now</button>
        </div>
      </div>`;
    grid.appendChild(card);
  }

  /* ── Progress ────────────────────────────────── */
  function updateProgress(done, total) {
    const pct  = Math.min(100, (done / Math.max(total, 1)) * 100);
    document.getElementById('respProgressFill').style.width = pct + '%';
    document.getElementById('receivedCount').textContent    = done;
  }

  /* ── Sort ────────────────────────────────────── */
  document.getElementById('sortSelect')?.addEventListener('change', function () {
    const cards = [...grid.querySelectorAll('.response-card')];
    cards.sort((a, b) => {
      if (this.value === 'price') {
        const pa = parseInt(a.querySelector('.rc-total')?.textContent?.replace(/\D/g,'') || '9999');
        const pb = parseInt(b.querySelector('.rc-total')?.textContent?.replace(/\D/g,'') || '9999');
        return pa - pb;
      }
      if (this.value === 'dist') {
        const da = parseFloat(a.querySelector('.rc-dist')?.textContent || '99');
        const db = parseFloat(b.querySelector('.rc-dist')?.textContent || '99');
        return da - db;
      }
      return 0;
    });
    cards.forEach(c => grid.appendChild(c));
  });
});

/* ── Order confirmation ──────────────────────── */
window.placeOrder = (name, total, phone) => {
  if (confirm(`Confirm order from ${name} for ${total}?\n\nThe pharmacy will contact you on your registered number.`)) {
    Store.set('activeOrder', { pharmacy: name, total, phone, ts: Date.now() });
    showToast(`🛒 Order placed with ${name}!`, 'success');
  }
};

/* ── Relative time ───────────────────────────── */
function timeAgo(iso) {
  const diff = (Date.now() - new Date(iso)) / 1000;
  if (diff < 60)   return 'Just replied';
  if (diff < 3600) return `${Math.floor(diff/60)} min ago`;
  return `${Math.floor(diff/3600)} hr ago`;
}