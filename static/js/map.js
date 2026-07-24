/* ═══════════════════════════════════════════════
   MedRelay  —  static/js/map.js
   Leaflet + OpenStreetMap  (no API key needed)
   ═══════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', async () => {

  /* ── 1. Load pharmacies from Flask API ──────── */
  let pharmacies = [];
  try {
    const res  = await fetch('/api/pharmacies');
    const data = await res.json();
    pharmacies = data.pharmacies || [];
  } catch {
    showToast('⚠️ Could not load pharmacy data', 'error');
  }

  /* ── 2. Init Leaflet map ─────────────────────── */
  const DEFAULT_LAT = 21.1458, DEFAULT_LNG = 79.0882;
  const map = L.map('mapEl', { zoomControl: false }).setView([DEFAULT_LAT, DEFAULT_LNG], 14);
  L.control.zoom({ position: 'topright' }).addTo(map);

  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    maxZoom: 19,
  }).addTo(map);

  /* ── 3. User location marker ─────────────────── */
  const userIcon = L.divIcon({
    html: `<div style="width:16px;height:16px;background:#0d9e8a;border:3px solid #fff;border-radius:50%;box-shadow:0 0 0 5px rgba(13,158,138,.22),0 2px 8px rgba(0,0,0,.25)"></div>`,
    iconSize: [16,16], iconAnchor: [8,8], className: '',
  });
  const userMarker = L.marker([DEFAULT_LAT, DEFAULT_LNG], { icon: userIcon }).addTo(map);
  userMarker.bindPopup('<div class="map-popup"><h4>📍 Your Location</h4><p>Nagpur, Maharashtra</p></div>');

  /* ── 4. Radius circle ────────────────────────── */
  let radiusKm = 5, radiusCircle;
  function drawRadius(lat = DEFAULT_LAT, lng = DEFAULT_LNG) {
    radiusCircle?.remove();
    radiusCircle = L.circle([lat, lng], {
      radius: radiusKm * 1000,
      color: '#0d9e8a', weight: 1.5,
      fillColor: '#0d9e8a', fillOpacity: 0.05,
      dashArray: '6 4',
    }).addTo(map);
  }
  drawRadius();

  /* ── 5. Pharmacy marker icon ─────────────────── */
  const pharmIcon = (open) => L.divIcon({
    html: `<div style="
      width:34px;height:34px;background:${open ? '#0d9e8a' : '#6b7f92'};
      border-radius:50% 50% 50% 0;transform:rotate(-45deg);
      border:2px solid #fff;box-shadow:0 3px 10px rgba(0,0,0,.25);
      display:flex;align-items:center;justify-content:center;">
      <span style="transform:rotate(45deg);font-size:15px">💊</span>
    </div>`,
    iconSize: [34,34], iconAnchor: [17,34], popupAnchor: [0,-36], className: '',
  });

  /* ── 6. Render pharmacies ────────────────────── */
  const markers   = [];
  const listEl    = document.getElementById('pharmList');
  const countEl   = document.getElementById('pharmCount');
  let   selectedId = null;

  function renderPharmacies(list) {
    listEl.innerHTML = '';
    markers.forEach(m => map.removeLayer(m));
    markers.length = 0;

    list.forEach((p, i) => {
      /* Map marker */
      const m = L.marker([p.lat, p.lng], { icon: pharmIcon(p.open) }).addTo(map);
      m.bindPopup(`
        <div class="map-popup">
          <h4>💊 ${p.name}</h4>
          <p>📍 ${p.address}</p>
          <p>${p.open ? '🟢 Open Now' : '🔴 Closed'} &nbsp;·&nbsp; ⭐ ${p.rating}</p>
          <a class="popup-phone" href="tel:${p.phone}">📞 ${p.phone}</a>
          <div class="popup-btns">
            <a href="tel:${p.phone}">📞 Call</a>
            <button onclick="location.href='/upload'">Send Rx</button>
          </div>
        </div>`);
      m.on('click', () => selectPharmacy(p.id, i));
      markers.push(m);

      /* Sidebar item */
      const item = document.createElement('div');
      item.className = 'pharm-item'; item.id = `li-${p.id}`;
      item.innerHTML = `
        <div class="pharm-icon">${p.open ? '🏥' : '🔒'}</div>
        <div style="flex:1;min-width:0">
          <div class="pharm-name">${p.name}</div>
          <div class="pharm-addr">${p.address}</div>
          <div class="pharm-meta">
            <span class="pharm-dist">📍 ${p.dist_km} km</span>
            <span class="pharm-phone">📞 <a href="tel:${p.phone}">${p.phone}</a></span>
            <span class="open-pill ${p.open ? 'open' : 'closed'}">${p.open ? 'Open' : 'Closed'}</span>
          </div>
          <div class="pharm-btns">
            <a class="pharm-call" href="tel:${p.phone}">📞 Call</a>
            <a class="pharm-upload" href="/upload">Send Rx</a>
          </div>
        </div>`;
      item.addEventListener('click', () => selectPharmacy(p.id, i));
      listEl.appendChild(item);
    });

    countEl.textContent = list.length;
  }

  function selectPharmacy(id, markerIdx) {
    selectedId = id;
    document.querySelectorAll('.pharm-item').forEach(el => el.classList.remove('selected'));
    document.getElementById(`li-${id}`)?.classList.add('selected');
    document.getElementById(`li-${id}`)?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    const p = pharmacies.find(x => x.id === id);
    if (p) { map.setView([p.lat, p.lng], 16, { animate: true }); markers[markerIdx]?.openPopup(); }
  }

  renderPharmacies(pharmacies);

  /* ── 7. Search filter ────────────────────────── */
  document.getElementById('mapSearch')?.addEventListener('input', function () {
    const q = this.value.toLowerCase();
    document.querySelectorAll('.pharm-item').forEach(el => {
      const name = el.querySelector('.pharm-name').textContent.toLowerCase();
      const addr = el.querySelector('.pharm-addr').textContent.toLowerCase();
      el.style.display = (name.includes(q) || addr.includes(q)) ? '' : 'none';
    });
  });

  /* ── 8. Radius slider ────────────────────────── */
  document.getElementById('mapRadius')?.addEventListener('input', async function () {
    radiusKm = +this.value;
    document.getElementById('mapRadiusVal').textContent = radiusKm + ' km';
    drawRadius();

    try {
      const res  = await fetch(`/api/pharmacies?radius=${radiusKm}`);
      const data = await res.json();
      pharmacies = data.pharmacies || [];
      renderPharmacies(pharmacies);
    } catch { /* keep existing list */ }
  });

  /* ── 9. Locate Me ────────────────────────────── */
  document.getElementById('locateBtn')?.addEventListener('click', () => {
    if (!navigator.geolocation) return showToast('⚠️ Geolocation not supported', 'error');
    navigator.geolocation.getCurrentPosition(async pos => {
      const { latitude: lat, longitude: lng } = pos.coords;
      map.setView([lat, lng], 14);
      userMarker.setLatLng([lat, lng]);
      drawRadius(lat, lng);

      try {
        const res  = await fetch(`/api/pharmacies?lat=${lat}&lng=${lng}&radius=${radiusKm}`);
        const data = await res.json();
        pharmacies = data.pharmacies || [];
        renderPharmacies(pharmacies);
        showToast(`📍 Found ${pharmacies.length} pharmacies nearby`, 'success');
      } catch { showToast('⚠️ Could not refresh pharmacies', 'error'); }

    }, () => showToast('⚠️ Could not get your location', 'error'));
  });
});