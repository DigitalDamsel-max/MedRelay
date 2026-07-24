/* ═══════════════════════════════════════════════
   MedRelay  —  static/js/upload.js
   ═══════════════════════════════════════════════ */

document.addEventListener('DOMContentLoaded', () => {

  /* File uploader */
  const uploader = new FileUploader('dropZone', 'fileInput', 'previewGrid');

  /* Radius slider */
  document.getElementById('radius')?.addEventListener('input', e => {
    document.getElementById('radiusVal').textContent = e.target.value + ' km';
  });

  /* Form submit */
  document.getElementById('uploadForm')?.addEventListener('submit', async e => {
    e.preventDefault();

    const patientName = document.getElementById('patientName').value.trim();
    const phone       = document.getElementById('phone').value.trim();
    const area        = document.getElementById('area').value.trim();
    const files       = uploader.valid();

    if (!patientName) return showToast('⚠️ Enter patient name', 'error');
    if (!phone)       return showToast('⚠️ Enter mobile number', 'error');
    if (!area)        return showToast('⚠️ Enter your area', 'error');
    if (!files.length) return showToast('⚠️ Upload at least one prescription photo', 'error');

    /* UI: loading state */
    const btn  = document.getElementById('submitBtn');
    const sp   = document.getElementById('btnSpinner');
    const btxt = document.getElementById('btnText');
    btn.disabled = true;
    sp.style.display = 'block';
    btxt.textContent = 'Sending to pharmacies…';

    try {
      /* Build FormData for Flask */
      const fd = new FormData();
      fd.append('patient_name', patientName);
      fd.append('phone',        phone);
      fd.append('area',         area);
      fd.append('city',         document.getElementById('city').value.trim());
      fd.append('notes',        document.getElementById('notes').value.trim());
      fd.append('radius',       document.getElementById('radius').value);
      files.forEach(f => fd.append('images', f));

      const res  = await fetch('/api/prescriptions', { method: 'POST', body: fd });
      const data = await res.json();

      if (!data.success) throw new Error(data.errors?.join(', ') || 'Upload failed');

      /* Save for responses page */
      Store.set('lastOrder', {
        id:       data.prescription_id,
        name:     patientName,
        area:     area,
        count:    data.notified_count,
        radius:   document.getElementById('radius').value,
        ts:       Date.now(),
      });

      /* Show success panel */
      document.getElementById('formPanel').style.display   = 'none';
      document.getElementById('successPanel').style.display = 'block';
      document.getElementById('trackIdVal').textContent    = data.prescription_id;
      document.getElementById('countVal').textContent      = data.notified_count;
      document.getElementById('radiusSent').textContent    = document.getElementById('radius').value;

      /* Animate progress */
      let pct = 0;
      const fill = document.getElementById('progressFill');
      const iv   = setInterval(() => {
        pct += Math.random() * 12;
        if (pct > 72) { clearInterval(iv); pct = 72; }
        fill.style.width = pct + '%';
      }, 700);

      showToast(`✅ Sent to ${data.notified_count} pharmacies!`, 'success');

    } catch (err) {
      showToast('❌ ' + err.message, 'error');
      btn.disabled = false;
      sp.style.display = 'none';
      btxt.textContent = '📤 Send to Nearby Pharmacies';
    }
  });

  /* Reset */
  document.getElementById('resetBtn')?.addEventListener('click', () => {
    document.getElementById('uploadForm').reset();
    document.getElementById('previewGrid').innerHTML = '';
    uploader.files = [];
    document.getElementById('formPanel').style.display   = 'block';
    document.getElementById('successPanel').style.display = 'none';
    document.getElementById('submitBtn').disabled = false;
    document.getElementById('btnSpinner').style.display  = 'none';
    document.getElementById('btnText').textContent = '📤 Send to Nearby Pharmacies';
    document.getElementById('progressFill').style.width  = '0';
    document.getElementById('radiusVal').textContent = '5 km';
  });
});