const DEFAULT_LAT = 21.1458;
const DEFAULT_LNG = 79.0882;

let currentLat = DEFAULT_LAT;
let currentLng = DEFAULT_LNG;

let pharmacies = [];
document.addEventListener('DOMContentLoaded', async () => {

    /* ── 1. Init Leaflet map ─────────────────────── */
    const map = L.map('mapEl', {
        zoomControl: false
    }).setView([DEFAULT_LAT, DEFAULT_LNG], 14);

    L.control.zoom({position: 'topright'}).addTo(map);

    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors',
        maxZoom: 19}).addTo(map);


    /* ── 2. User location marker ─────────────────── */
    const userIcon = L.divIcon({
        html: `
            <div style="
                width:16px;
                height:16px;
                background:#0d9e8a;
                border:3px solid #fff;
                border-radius:50%;
                box-shadow:
                    0 0 0 5px rgba(13,158,138,.22),
                    0 2px 8px rgba(0,0,0,.25)
            "></div>`,
        iconSize: [16, 16],
        iconAnchor: [8, 8], className: ''
    });

    const userMarker = L.marker([DEFAULT_LAT, DEFAULT_LNG],
        { icon: userIcon }).addTo(map);

    userMarker.bindPopup('📍 Your Location<br>Nagpur, Maharashtra');

    /* ── 3. Radius circle ────────────────────────── */
    let radiusKm = 5;
    let radiusCircle;

    function drawRadius(lat = DEFAULT_LAT, lng = DEFAULT_LNG
    ) { radiusCircle?.remove();
        radiusCircle = L.circle([lat, lng], {
            radius: radiusKm * 1000,
            color: '#0d9e8a',
            weight: 1.5,
            fillColor: '#0d9e8a',
            fillOpacity: 0.05,
            dashArray: '6 4'}).addTo(map);
    }
    drawRadius();

    /* ── 4. Pharmacy marker icon ─────────────────── */
    const pharmIcon = (open) => L.divIcon({
        html: `
            <div style="
                width:34px;
                height:34px;
                background:${open ? '#0d9e8a' : '#6b7f92'};
                border-radius:50% 50% 50% 0;
                transform:rotate(-45deg);
                border:2px solid #fff;
                box-shadow:0 3px 10px rgba(0,0,0,.25);
                display:flex;
                align-items:center;
                justify-content:center;">
                <span style="
                    transform:rotate(45deg);
                    font-size:15px">💊</span>
            </div>
        `,
        iconSize: [34, 34],
        iconAnchor: [17, 34],
        popupAnchor: [0, -36],
        className: ''
    });

    /* ── 5. DOM elements ─────────────────────────── */
    const markers = [];
    const listEl = document.getElementById('pharmList');
    const countEl = document.getElementById('pharmCount');

    let selectedId = null;

    function calculateDistance(lat1, lon1, lat2, lon2) {
      const R = 6371; // Earth radius in km
      const dLat = (lat2 - lat1) * Math.PI / 180;
      const dLon = (lon2 - lon1) * Math.PI / 180;
      const a = Math.sin(dLat / 2) ** 2 +
                Math.cos(lat1 * Math.PI / 180) *
                Math.cos(lat2 * Math.PI / 180) *
                Math.sin(dLon / 2) ** 2;

      const c = 2 * Math.atan2( Math.sqrt(a), Math.sqrt(1 - a));
      return R * c;
    }

    /* ── 6. Convert API data to frontend format ──── */
    function normalizePharmacy(p) {
        return {
            db_id: p.pharmacy_id ?? p.db_id,
            name: p.name ?? 'Pharmacy',
            address: p.address_line ?? p.address ?? '',
            area: p.area ?? '',
            phone: p.phone ?? '',
            lat: Number(p.latitude ?? p.lat),
            lng: Number(p.longitude ?? p.lng),
            open: Boolean(p.is_open_now ?? p.open),
            dist_km: calculateDistance(
                  currentLat,currentLng,
                  Number(p.latitude ?? p.lat),
                  Number(p.longitude ?? p.lng)
              ).toFixed(2),
            is_verified: Boolean(p.is_verified),
            accepts_delivery: Boolean(p.accepts_delivery)
        };
    }

    /* ── 7. Render pharmacies ────────────────────── */
    function renderPharmacies(list) {
        console.log(
            'Rendering',
            list.length,
            'pharmacies'
        );
        console.log( 'Pharmacy data:',list);
        listEl.innerHTML = '';
        markers.forEach(m => {
            map.removeLayer(m);});
        markers.length = 0;

        list.forEach((p, i) => {
            console.log('Marker:',p.name,p.lat,p.lng);

            /* Make sure coordinates are valid */
            if (
                !Number.isFinite(p.lat) ||
                !Number.isFinite(p.lng)
            ) {
                console.error('Invalid coordinates:',p);
                return;}

            /* ── Map marker ───────────────────── */
            const m = L.marker( [p.lat, p.lng],
                {icon: pharmIcon(p.open)}).addTo(map);

            m.bindPopup(`
                <div class="map-popup">
                    <h4>💊 ${p.name}</h4>
                    <p> 📍 ${p.address} </p>
                    <p>  ${p.open  ? '🟢 Open Now' : '🔴 Closed' } </p>

                    <a class="popup-phone" href="tel:${p.phone}">📞 ${p.phone}</a>
                    <div class="popup-btns">
                        <a href="tel:${p.phone}">📞 Call</a>
                        <button onclick="location.href='/upload'"> Send Rx </button>
                    </div>
                </div>
            `);
            m.on('click', () => {selectPharmacy(p.db_id, i);})
            markers.push(m);

            /* ── Sidebar item ────────────────── */
            const item = document.createElement('div');
            item.className = 'pharm-item';
            item.id = `li-${p.db_id}`;
            item.innerHTML = `
                <div class="pharm-icon"> ${p.open ? '🏥' : '🔒'} </div>
                <div class="pharm-content">
                    <div class="pharm-name"> ${p.name} </div>
                    <div class="pharm-addr"> ${p.address} </div>
                    <div class="pharm-meta">
                        <span class="pharm-dist">📍 ${p.dist_km} km</span>
                        <span class="pharm-phone">📞<a href="tel:${p.phone}">${p.phone}</a></span>
                        <span class="open-pill ${p.open? 'open' : 'closed' }">${p.open ? 'Open' : 'Closed'}</span>
                    </div>
                    <div class="pharm-btns">
                        <a class="pharm-call" href="tel:${p.phone}">📞 Call</a>
                        <a class="pharm-upload" href="/upload"> Send Rx </a>
                    </div>
                </div>
            `;
            item.addEventListener('click',() => selectPharmacy(p.db_id, i));
            listEl.appendChild(item);
        });
        countEl.textContent = list.length;
        console.log('Markers created:',markers.length
        );
    }
    /* ── 8. Select pharmacy ──────────────────────── */
    function selectPharmacy(id, markerIdx) {
        selectedId = id;
        document.querySelectorAll('.pharm-item')
            .forEach(el => {el.classList.remove('selected');
            });
        const selected = document.getElementById(`li-${id}`);
        selected?.classList.add('selected');
        selected?.scrollIntoView({behavior: 'smooth',block: 'nearest'
        });
        const p = pharmacies.find(x => x.db_id === id);

        if (p) {map.setView( [p.lat, p.lng],16,{ animate: true });
            markers[markerIdx]?.openPopup();
          }
    }

    /* ── 9. Load pharmacies initially ───────────── */
    async function loadPharmacies() {
        console.log('Loading pharmacies from API...');

        try {
            const res = await fetch(
                `/api/pharmacies?lat=${currentLat}&lng=${currentLng}&radius=${radiusKm}`
            );
            if (!res.ok) {throw new Error(`HTTP ${res.status}`);}
            const data = await res.json();
            console.log('API response:',data);
            pharmacies.sort( (a, b) => Number(a.dist_km) - Number(b.dist_km));

            const rawPharmacies = data.pharmacies || [];
            console.log('Raw pharmacies:',rawPharmacies);
            pharmacies =rawPharmacies.map(normalizePharmacy);

            console.log('Normalized pharmacies:',pharmacies);
            renderPharmacies(pharmacies);

            /* Fit map to pharmacies */
            const bounds = pharmacies.filter(p => Number.isFinite(p.lat) && Number.isFinite(p.lng))
                .map(p => [p.lat,p.lng]);

            if (bounds.length > 0) {
                map.fitBounds(bounds, {padding: [50, 50]});
            }

            /* Update status */
            const loadingText = document.querySelector('#pharmList');
            console.log(`Successfully loaded ${pharmacies.length} pharmacies`);

        } catch (error) {
            console.error('Failed to load pharmacies:',error);
            showToast('⚠️ Could not load pharmacy data','error');
        }
    }

    /* IMPORTANT: Load pharmacies when map starts */
    await loadPharmacies();

    /* ── 10. Search filter ───────────────────────── */
    document.getElementById('mapSearch') ?.addEventListener('input',
            function () {
                const q = this.value.toLowerCase();

                document.querySelectorAll('.pharm-item').forEach(el => {
                        const name = el.querySelector('.pharm-name')
                            ?.textContent.toLowerCase() || '';

                        const addr = el.querySelector('.pharm-addr')
                            ?.textContent.toLowerCase() || '';
                        el.style.display = (name.includes(q) || addr.includes(q)) ? '' : 'none';
                    });
            }
        );

    /* ── 11. Radius slider ───────────────────────── */
    document.getElementById('mapRadius')?.addEventListener('input',
      async function () {radiusKm = +this.value;

      document.getElementById('mapRadiusVal').textContent = radiusKm + ' km';
      drawRadius();

      try {
        const res = await fetch(`/api/pharmacies?lat=${currentLat}&lng=${currentLng}&radius=${radiusKm}`);
        const data = await res.json();

        console.log('Radius API response:',data);
        pharmacies =(data.pharmacies || []).map(normalizePharmacy);

                    renderPharmacies(pharmacies);
                } catch (error) {
                    console.error('Radius refresh failed:',error);
                }
            }
        );

    /* ── 12. Locate Me ───────────────────────────── */
    document.getElementById('locateBtn') ?.addEventListener( 'click',() => {
      if (!navigator.geolocation) {
        showToast( '⚠️ Geolocation not supported','error');
        return;}

        navigator.geolocation.getCurrentPosition((position) => {
            const latitude = position.coords.latitude;
            const longitude = position.coords.longitude;

            document.getElementById('latitude').value = latitude;
            document.getElementById('longitude').value = longitude;

        });
              
        navigator.geolocation.getCurrentPosition(
          async pos => {
            const {latitude: lat,longitude: lng} = pos.coords;
            currentLat = lat;
            currentLng = lng;

            map.setView([lat, lng],14);
            userMarker.setLatLng([lat, lng]);
            drawRadius(lat,lng);

            try {
                            const res = await fetch( `/api/pharmacies?lat=${lat}&lng=${lng}&radius=${radiusKm}` );
                            const data = await res.json();
                            console.log('Location API response:',data);

                            pharmacies = (data.pharmacies || []).map(normalizePharmacy);
                            console.log('Number of pharmacies:',pharmacies.length);
                            renderPharmacies(pharmacies);

                            showToast(`📍 Found ${pharmacies.length} pharmacies nearby`,'success');
            } catch (error) {
                            console.error('Location refresh failed:', error);
                            showToast('⚠️ Could not refresh pharmacies', 'error');
            }
          },
          () => {showToast('⚠️ Could not get your location','error');
      });
      
    });
});

