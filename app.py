# ═══════════════════════════════════════════════════════════════════════════
#  MedRelay — Flask Backend   app.py
#
#  pip install flask flask-cors pillow werkzeug requests mysql-connector-python bcrypt
#  python app.py  →  http://localhost:5000
# ═══════════════════════════════════════════════════════════════════════════

import os, uuid, math, json, time, hashlib
from datetime import datetime
from functools import wraps

import requests as http_req
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, session, redirect, url_for)
from flask_cors import CORS
from werkzeug.utils import secure_filename

try:
    import bcrypt
    USE_BCRYPT = True
except ImportError:
    USE_BCRYPT = False

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'medrelay-dev-secret-change-in-prod')
CORS(app, supports_credentials=True)

# ── Upload ────────────────────────────────────────────────────────────────
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXT   = {'jpg','jpeg','png','pdf','webp'}
app.config['UPLOAD_FOLDER']      = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── MySQL ─────────────────────────────────────────────────────────────────
import mysql.connector
from mysql.connector import pooling

DB_CFG = dict(
    host=os.getenv('DB_HOST','localhost'), port=int(os.getenv('DB_PORT',3306)),
    user=os.getenv('DB_USER','root'),     password='Pihu@4124',
    database=os.getenv('DB_NAME','medrelay'),
    charset='utf8mb4', autocommit=True,
)
try:
    _pool = pooling.MySQLConnectionPool(pool_name='mr', pool_size=8, **DB_CFG)
    print('[DB] MySQL pool ready')
except Exception as e:
    _pool = None
    print(f'[DB] WARNING: {e}')

def db_conn():
    if not _pool: raise RuntimeError('DB not available')
    return _pool.get_connection()

def qry(sql, params=None, fetch='all'):
    conn = db_conn()
    try:
        cur = conn.cursor(dictionary=True)
        cur.execute(sql, params or ())
        if fetch == 'all':    return cur.fetchall()
        if fetch == 'one':    return cur.fetchone()
        if fetch == 'insert': conn.commit(); return cur.lastrowid
        conn.commit(); return cur.rowcount
    finally:
        conn.close()

# ── Passwords ─────────────────────────────────────────────────────────────
def hash_pw(plain):
    if USE_BCRYPT:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    return hashlib.sha256(plain.encode()).hexdigest()

def check_pw(plain, hashed):
    if USE_BCRYPT:
        try: return bcrypt.checkpw(plain.encode(), hashed.encode())
        except: pass
    return hashlib.sha256(plain.encode()).hexdigest() == hashed

# ── Auth decorator ────────────────────────────────────────────────────────
def pharmacy_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if 'pharmacy_id' not in session:
            return redirect(url_for('pharmacist_login_page'))
        return f(*a, **kw)
    return wrap

# ── Overpass ──────────────────────────────────────────────────────────────
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter']
_ov_cache = {}; CACHE_TTL = 300

# ── Utils ─────────────────────────────────────────────────────────────────
def new_uuid(): return str(uuid.uuid4())

def track_id():
    return f"MR-{datetime.now().strftime('%Y%m%d')}-{str(uuid.uuid4().int)[:4]}"

def haversine(la1,lo1,la2,lo2):
    R,d = 6371, math.pi/180
    a = math.sin((la2-la1)*d/2)**2 + math.cos(la1*d)*math.cos(la2*d)*math.sin((lo2-lo1)*d/2)**2
    return round(R*2*math.atan2(math.sqrt(a), math.sqrt(1-a)), 3)

def allowed(fn):
    return '.' in fn and fn.rsplit('.',1)[1].lower() in ALLOWED_EXT

def build_addr(t):
    return ', '.join(filter(None,[
        t.get('addr:housenumber'), t.get('addr:street'),
        t.get('addr:suburb') or t.get('addr:neighbourhood'),
        t.get('addr:city') or t.get('addr:town'),
    ]))

def parse_oh(oh):
    if not oh: return None
    if '24/7' in oh: return True
    if oh.strip().lower() == 'off': return False
    import re
    nm = datetime.now().hour*60 + datetime.now().minute
    m  = re.search(r'(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})', oh)
    if m: return int(m[1])*60+int(m[2]) <= nm <= int(m[3])*60+int(m[4])
    return None

def norm_overpass(elements, ulat, ulng):
    out = []
    for el in elements:
        lat = el.get('lat') or (el.get('center') or {}).get('lat')
        lng = el.get('lon') or (el.get('center') or {}).get('lon')
        if not lat or not lng: continue
        t = el.get('tags', {})
        ph= (t.get('phone') or t.get('contact:phone') or '').split(';')[0].strip()
        out.append({'osm_id':str(el['id']), 'db_id':None,
                    'name': t.get('name') or t.get('brand') or 'Pharmacy',
                    'phone':ph, 'address':build_addr(t),
                    'lat':lat, 'lng':lng,
                    'dist_km':haversine(ulat,ulng,lat,lng),
                    'open':parse_oh(t.get('opening_hours')),
                    'hours':t.get('opening_hours',''),
                    'rating':0, 'logo':'', 'delivery':False, 'source':'osm'})
    return sorted(out, key=lambda x: x['dist_km'])


# ══════════════════════════════════════════════════════════════════════════
#  PAGE ROUTES
# ══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index(): return render_template('index.html')

@app.route('/upload')
def upload_page(): return render_template('upload.html')

@app.route('/map')
def map_page(): return render_template('map.html')

@app.route('/responses')
def responses_page(): return render_template('responses.html')

@app.route('/pharmacy/register')
def pharmacy_register_page(): return render_template('pharmacy_register.html')

@app.route('/pharmacy/login')
def pharmacist_login_page():
    if 'pharmacy_id' in session:
        return redirect(url_for('pharmacist_dashboard'))
    return render_template('pharmacy_login.html')

@app.route('/pharmacy/dashboard')
@pharmacy_required
def pharmacist_dashboard(): return render_template('pharmacy_dashboard.html')

@app.route('/pharmacy/logout')
def pharmacy_logout():
    session.clear()
    return redirect(url_for('pharmacist_login_page'))

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


# ══════════════════════════════════════════════════════════════════════════
#  API: Health
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/health')
def health():
    try: qry('SELECT 1', fetch='one'); db_ok=True
    except: db_ok=False
    return jsonify({'status':'ok','db':db_ok,'time':datetime.utcnow().isoformat()})


# ══════════════════════════════════════════════════════════════════════════
#  API: Pharmacy Registration
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/register', methods=['POST'])
def api_pharmacy_register():
    d = request.form
    for f in ['name','phone','email','password','address','area','city','pincode','drug_license','lat','lng']:
        if not d.get(f,'').strip():
            return jsonify({'success':False,'error':f'"{f}" is required'}), 400
    try:
        ex = qry('SELECT pharmacy_id FROM pharmacies WHERE phone=%s OR email=%s OR drug_license_no=%s',
                 (d['phone'], d['email'], d['drug_license']), fetch='one')
        if ex: return jsonify({'success':False,'error':'Phone, email or drug license already registered'}), 409
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

    pid = new_uuid()
    pw  = hash_pw(d['password'])
    logo_path = ''
    logo = request.files.get('logo')
    if logo and logo.filename and allowed(logo.filename):
        fn = secure_filename(f'{pid}_{logo.filename}')
        logo.save(os.path.join(UPLOAD_FOLDER, fn))
        logo_path = f'/uploads/{fn}'

    try:
        qry("""INSERT INTO pharmacies
            (pharmacy_id,name,address_line,area,city,pincode,
             phone,email,drug_license_no,gst_number,proprietor_name,
             latitude,longitude,password_hash,logo_path,
             delivery_radius_km,accepts_delivery,opening_time,closing_time,
             is_active,is_verified,rating,total_ratings)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1,0,0.0,0)""",
            (pid, d['name'].strip(), d['address'].strip(), d['area'].strip(),
             d['city'].strip(), d['pincode'].strip(),
             d['phone'].strip(), d['email'].strip(),
             d['drug_license'].strip(), d.get('gst','').strip(),
             d.get('proprietor','').strip(),
             float(d['lat']), float(d['lng']),
             pw, logo_path,
             float(d.get('delivery_radius',5)),
             1 if d.get('accepts_delivery') in ('true','1','on') else 0,
             d.get('opening_time','09:00'), d.get('closing_time','21:00')),
            fetch='insert')
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

    return jsonify({'success':True,'pharmacy_id':pid,
                    'message':'Registration submitted. Our team will verify within 24 hours.'})


# ══════════════════════════════════════════════════════════════════════════
#  API: Pharmacy Login
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/login', methods=['POST'])
def api_pharmacy_login():
    data  = request.get_json(force=True)
    email = data.get('email','').strip()
    pw    = data.get('password','')
    if not email or not pw:
        return jsonify({'success':False,'error':'Email and password required'}), 400
    try:
        ph = qry('SELECT * FROM pharmacies WHERE email=%s AND is_active=1', (email,), fetch='one')
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

    if not ph or not check_pw(pw, ph.get('password_hash','')):
        return jsonify({'success':False,'error':'Invalid email or password'}), 401

    session['pharmacy_id']    = ph['pharmacy_id']
    session['pharmacy_name']  = ph['name']
    session['pharmacy_email'] = ph['email']
    return jsonify({'success':True,'pharmacy_id':ph['pharmacy_id'],
                    'name':ph['name'],'verified':bool(ph.get('is_verified'))})


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — current pharmacy profile
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/me')
@pharmacy_required
def api_pharmacy_me():
    try:
        ph = qry('SELECT * FROM pharmacies WHERE pharmacy_id=%s',
                 (session['pharmacy_id'],), fetch='one')
        if not ph: return jsonify({'success':False,'error':'Not found'}), 404
        ph.pop('password_hash', None)
        return jsonify({'success':True,'pharmacy':ph})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — stats summary
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/stats')
@pharmacy_required
def api_pharmacy_stats():
    pid   = session['pharmacy_id']
    today = datetime.now().strftime('%Y-%m-%d')
    stats = {}
    try:
        def s(sql, p): return (qry(sql, p, fetch='one') or {})

        stats['pending_requests'] = s(
            "SELECT COUNT(*) c FROM prescription_broadcasts WHERE pharmacy_id=%s AND status='sent'", (pid,)).get('c',0)
        stats['today_orders'] = s(
            "SELECT COUNT(*) c FROM orders WHERE pharmacy_id=%s AND DATE(placed_at)=%s", (pid,today)).get('c',0)
        stats['total_orders'] = s(
            "SELECT COUNT(*) c FROM orders WHERE pharmacy_id=%s", (pid,)).get('c',0)
        stats['today_revenue'] = float(s(
            "SELECT COALESCE(SUM(total_amount),0) s FROM orders WHERE pharmacy_id=%s AND DATE(placed_at)=%s AND payment_status='paid'",
            (pid,today)).get('s',0))
        stats['total_revenue'] = float(s(
            "SELECT COALESCE(SUM(total_amount),0) s FROM orders WHERE pharmacy_id=%s AND payment_status='paid'",
            (pid,)).get('s',0))
        stats['avg_rating'] = round(float(s(
            "SELECT COALESCE(AVG(score),0) a FROM ratings WHERE pharmacy_id=%s", (pid,)).get('a',0)), 1)
        stats['total_ratings'] = s(
            "SELECT COUNT(*) c FROM ratings WHERE pharmacy_id=%s", (pid,)).get('c',0)
        stats['active_deliveries'] = s(
            "SELECT COUNT(*) c FROM orders WHERE pharmacy_id=%s AND status='out_for_delivery'", (pid,)).get('c',0)
        stats['unread_requests'] = stats['pending_requests']
        return jsonify({'success':True,'stats':stats})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — incoming prescription requests
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/requests')
@pharmacy_required
def api_pharmacy_requests():
    pid = session['pharmacy_id']
    try:
        rows = qry("""
            SELECT pb.broadcast_id, pb.prescription_id,
                   pb.distance_km, pb.status AS broadcast_status, pb.sent_at,
                   p.patient_name, p.phone, p.area, p.notes,
                   p.status AS rx_status, p.created_at, p.expires_at,
                   (SELECT COUNT(*) FROM prescription_images pi2
                    WHERE pi2.prescription_id=p.prescription_id) AS image_count,
                   (SELECT response_id FROM pharmacy_responses pr2
                    WHERE pr2.prescription_id=p.prescription_id
                      AND pr2.pharmacy_id=%s LIMIT 1) AS already_responded
            FROM prescription_broadcasts pb
            JOIN prescriptions p ON p.prescription_id=pb.prescription_id
            WHERE pb.pharmacy_id=%s
              AND p.expires_at > NOW()
            ORDER BY pb.sent_at DESC LIMIT 60""", (pid, pid))
        return jsonify({'success':True,'requests':rows})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — orders list
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/orders')
@pharmacy_required
def api_pharmacy_orders():
    pid    = session['pharmacy_id']
    status = request.args.get('status','')
    try:
        sql = """
            SELECT o.order_id, o.prescription_id, o.patient_name, o.patient_phone,
                   o.is_delivery, o.delivery_address, o.subtotal, o.discount,
                   o.delivery_charge, o.total_amount, o.payment_mode,
                   o.payment_status, o.status, o.placed_at, o.updated_at,
                   GROUP_CONCAT(oi.medicine_name SEPARATOR ', ') AS medicines_list,
                   SUM(oi.quantity) AS total_items
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id=o.order_id
            WHERE o.pharmacy_id=%s"""
        params = [pid]
        if status: sql += ' AND o.status=%s'; params.append(status)
        sql += ' GROUP BY o.order_id ORDER BY o.placed_at DESC LIMIT 100'
        return jsonify({'success':True,'orders':qry(sql, params)})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — order detail + status update
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/orders/<order_id>', methods=['GET','PATCH'])
@pharmacy_required
def api_pharmacy_order(order_id):
    pid = session['pharmacy_id']
    if request.method == 'GET':
        try:
            o = qry('SELECT * FROM orders WHERE order_id=%s AND pharmacy_id=%s',
                    (order_id,pid), fetch='one')
            if not o: return jsonify({'success':False,'error':'Not found'}), 404
            o['items'] = qry('SELECT * FROM order_items WHERE order_id=%s', (order_id,))
            return jsonify({'success':True,'order':o})
        except Exception as e:
            return jsonify({'success':False,'error':str(e)}), 500
    else:
        data = request.get_json(force=True)
        new_status = data.get('status')
        VALID = ['confirmed','preparing','ready_for_pickup',
                 'out_for_delivery','delivered','cancelled']
        if new_status not in VALID:
            return jsonify({'success':False,'error':'Invalid status'}), 400
        try:
            qry('UPDATE orders SET status=%s,updated_at=NOW() WHERE order_id=%s AND pharmacy_id=%s',
                (new_status, order_id, pid), fetch='exec')
            qry("""INSERT INTO audit_log(table_name,record_id,action,changed_by,new_data)
                   VALUES('orders',%s,'UPDATE',%s,%s)""",
                (order_id, pid, json.dumps({'status':new_status})), fetch='exec')
            return jsonify({'success':True,'status':new_status})
        except Exception as e:
            return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — submit availability response to a prescription
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/respond', methods=['POST'])
@pharmacy_required
def api_pharmacy_respond():
    pid  = session['pharmacy_id']
    data = request.get_json(force=True)
    rx_id    = data.get('prescription_id')
    meds     = data.get('medicines', [])
    total    = data.get('total_price', 0)
    notes    = data.get('notes', '')
    delivery = bool(data.get('delivery_available', False))
    eta      = data.get('estimated_time_min')

    if not rx_id or not meds:
        return jsonify({'success':False,'error':'Missing prescription_id or medicines'}), 400

    all_a = all(m.get('available') for m in meds)
    any_a = any(m.get('available') for m in meds)
    avail = 'all' if all_a else ('partial' if any_a else 'none')
    rid   = new_uuid()

    try:
        ph = qry('SELECT name,phone FROM pharmacies WHERE pharmacy_id=%s', (pid,), fetch='one')
        qry("""INSERT INTO pharmacy_responses
            (response_id,prescription_id,pharmacy_id,pharmacy_osm_name,pharmacy_phone,
             availability,total_price,delivery_available,estimated_time_min,notes)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (rid,rx_id,pid,ph['name'],ph['phone'],avail,total,delivery,eta,notes),
            fetch='insert')
        for m in meds:
            qry("""INSERT INTO response_medicine_items
                (response_id,medicine_name,quantity,is_available,
                 unit_price,subtotal,substitute_name,substitute_price)
                VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                (rid, m.get('name',''), m.get('quantity',''),
                 1 if m.get('available') else 0,
                 m.get('price',0), m.get('subtotal',0),
                 m.get('substitute_name',''), m.get('substitute_price') or None),
                fetch='insert')
        qry("""UPDATE prescription_broadcasts
               SET status='responded', responded_at=NOW()
               WHERE prescription_id=%s AND pharmacy_id=%s""",
            (rx_id, pid), fetch='exec')
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500

    return jsonify({'success':True,'response_id':rid,'availability':avail})


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — ratings
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/ratings')
@pharmacy_required
def api_pharmacy_ratings():
    pid = session['pharmacy_id']
    try:
        rows = qry("""SELECT r.*,o.patient_name FROM ratings r
                      JOIN orders o ON o.order_id=r.order_id
                      WHERE r.pharmacy_id=%s ORDER BY r.rated_at DESC LIMIT 50""", (pid,))
        return jsonify({'success':True,'ratings':rows})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Dashboard — update profile
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacy/profile', methods=['PATCH'])
@pharmacy_required
def api_pharmacy_profile():
    pid = session['pharmacy_id']
    d   = request.get_json(force=True)
    ALLOWED = ['accepts_delivery','delivery_radius_km','is_open_now',
               'opening_time','closing_time','gst_number','alt_phone']
    sets, vals = [], []
    for f in ALLOWED:
        if f in d: sets.append(f'{f}=%s'); vals.append(d[f])
    if not sets:
        return jsonify({'success':False,'error':'Nothing to update'}), 400
    vals.append(pid)
    try:
        qry(f"UPDATE pharmacies SET {','.join(sets)},updated_at=NOW() WHERE pharmacy_id=%s",
            vals, fetch='exec')
        return jsonify({'success':True})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}), 500


# ══════════════════════════════════════════════════════════════════════════
#  API: Public pharmacy list (registered DB + OSM)
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/pharmacies')
def api_pharmacies():
    lat    = request.args.get('lat',  type=float)
    lng    = request.args.get('lng',  type=float)
    radius = request.args.get('radius', 5.0, type=float)
    q      = request.args.get('q','').lower().strip()
    if not lat or not lng:
        return jsonify({'success':False,'error':'lat and lng required'}), 400

    # Registered pharmacies from DB
    registered = []
    try:
        rows = qry("SELECT * FROM pharmacies WHERE is_active=1 AND is_verified=1")
        for r in rows:
            d = haversine(lat, lng, float(r['latitude']), float(r['longitude']))
            if d <= radius:
                registered.append({
                    'osm_id':None, 'db_id':r['pharmacy_id'],
                    'name':r['name'], 'phone':r['phone'],
                    'address':f"{r['address_line']}, {r['area']}",
                    'lat':float(r['latitude']), 'lng':float(r['longitude']),
                    'dist_km':d,
                    'open':bool(r.get('is_open_now')),
                    'hours':f"{r.get('opening_time','')} – {r.get('closing_time','')}",
                    'rating':float(r.get('rating') or 0),
                    'logo':r.get('logo_path',''),
                    'delivery':bool(r.get('accepts_delivery')),
                    'source':'medrelay',
                })
    except Exception as e:
        app.logger.warning(f'DB pharmacies: {e}')

    # OSM pharmacies
    ck = f'{round(lat,4)},{round(lng,4)},{radius}'
    cached = _ov_cache.get(ck)
    osm = []
    if cached and (time.time()-cached[0]) < CACHE_TTL:
        osm = cached[1]
    else:
        oq = (f'[out:json][timeout:25];'
              f'(node[amenity=pharmacy](around:{int(radius*1000)},{lat},{lng});'
              f'way[amenity=pharmacy](around:{int(radius*1000)},{lat},{lng}););'
              f'out center tags;')
        for mirror in OVERPASS:
            try:
                r = http_req.post(mirror, data={'data':oq},
                    headers={'Content-Type':'application/x-www-form-urlencoded'}, timeout=18)
                if r.status_code == 200:
                    osm = norm_overpass(r.json().get('elements',[]), lat, lng)
                    _ov_cache[ck] = (time.time(), osm)
                    break
            except Exception as ex:
                app.logger.warning(f'Overpass: {ex}')

    # Merge — registered names win
    reg_names = {p['name'].lower() for p in registered}
    merged = sorted(registered + [p for p in osm if p['name'].lower() not in reg_names],
                    key=lambda x: x['dist_km'])
    if q:
        merged = [p for p in merged
                  if q in p['name'].lower()
                  or q in p['address'].lower()
                  or q in p['phone']]
    return jsonify({'success':True,'count':len(merged),'pharmacies':merged})


# ══════════════════════════════════════════════════════════════════════════
#  API: Prescriptions
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/prescriptions', methods=['POST'])
def api_upload():
    name   = request.form.get('patientName','').strip()
    phone  = request.form.get('phone','').strip()
    area   = request.form.get('area','').strip()
    notes  = request.form.get('notes','').strip()
    radius = float(request.form.get('radius',5))
    lat    = float(request.form.get('lat',0) or 0)
    lng    = float(request.form.get('lng',0) or 0)

    if not name:  return jsonify({'success':False,'error':'Patient name required'}), 400
    if not phone: return jsonify({'success':False,'error':'Phone required'}), 400
    if not area:  return jsonify({'success':False,'error':'Area required'}), 400

    files, images = request.files.getlist('images'), []
    for f in files:
        if f and f.filename and allowed(f.filename):
            fn = secure_filename(f'{uuid.uuid4().hex}_{f.filename}')
            f.save(os.path.join(UPLOAD_FOLDER, fn))
            images.append(f'/uploads/{fn}')
    if not images:
        return jsonify({'success':False,'error':'At least one prescription image required'}), 400

    tid = track_id()
    notified = 0
    try:
        qry("""INSERT INTO prescriptions
            (prescription_id,patient_name,phone,area,notes,
             patient_lat,patient_lng,search_radius_km,status,
             notified_count,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,'broadcasted',0,
                   DATE_ADD(NOW(),INTERVAL 48 HOUR))""",
            (tid,name,phone,area,notes,lat or None,lng or None,radius), fetch='insert')

        for i,fp in enumerate(images,1):
            fn=fp.split('/')[-1]; ext=fn.rsplit('.',1)[-1].lower()
            qry("INSERT INTO prescription_images(image_id,prescription_id,file_path,file_name,file_type,sort_order)VALUES(%s,%s,%s,%s,%s,%s)",
                (new_uuid(),tid,fp,fn,ext,i), fetch='insert')

        if lat and lng:
            phs = qry("SELECT pharmacy_id,latitude,longitude FROM pharmacies WHERE is_active=1 AND is_verified=1")
            for ph in phs:
                d = haversine(lat,lng,float(ph['latitude']),float(ph['longitude']))
                if d <= radius:
                    try:
                        qry("INSERT IGNORE INTO prescription_broadcasts(prescription_id,pharmacy_id,distance_km,status)VALUES(%s,%s,%s,'sent')",
                            (tid,ph['pharmacy_id'],d), fetch='insert')
                        notified += 1
                    except: pass
            qry("UPDATE prescriptions SET notified_count=%s WHERE prescription_id=%s",
                (notified,tid), fetch='exec')
    except Exception as e:
        app.logger.error(e)

    return jsonify({'success':True,'prescription_id':tid,'notified_count':notified,'images':images})

@app.route('/api/prescriptions/<pid>')
def api_get_prescription(pid):
    try:
        rx = qry('SELECT * FROM prescriptions WHERE prescription_id=%s',(pid,),fetch='one')
        if not rx: return jsonify({'success':False,'error':'Not found'}),404
        imgs  = qry('SELECT * FROM prescription_images WHERE prescription_id=%s ORDER BY sort_order',(pid,))
        resps = qry('SELECT * FROM pharmacy_responses WHERE prescription_id=%s ORDER BY responded_at',(pid,))
        for r in resps:
            r['medicines'] = qry('SELECT * FROM response_medicine_items WHERE response_id=%s',(r['response_id'],))
        return jsonify({'success':True,'prescription':rx,'images':imgs,'responses':resps})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}),500

@app.route('/api/responses/<pid>')
def api_get_responses(pid):
    try:
        resps = qry('SELECT * FROM pharmacy_responses WHERE prescription_id=%s ORDER BY total_price',(pid,))
        for r in resps:
            r['medicines'] = qry('SELECT * FROM response_medicine_items WHERE response_id=%s',(r['response_id'],))
        return jsonify({'success':True,'count':len(resps),'responses':resps})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}),500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
    
    
    

    
# import os, uuid, json
# from datetime import datetime
# from flask import Flask, request, jsonify, send_from_directory, render_template
# from flask_cors import CORS
# from werkzeug.utils import secure_filename

# app = Flask(__name__, static_folder="static", template_folder="templates")
# CORS(app)

# # ── Config ──────────────────────────────────────────
# UPLOAD_FOLDER   = os.path.join(os.path.dirname(__file__), "uploads")
# ALLOWED_EXT     = {"png", "jpg", "jpeg", "webp", "pdf"}
# MAX_CONTENT_LEN = 10 * 1024 * 1024   # 10 MB

# os.makedirs(UPLOAD_FOLDER, exist_ok=True)
# app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
# app.config["MAX_CONTENT_LENGTH"] = MAX_CONTENT_LEN

# # ── In-memory "database" (swap for SQLite/Postgres) ─
# prescriptions: dict = {}   # id → prescription dict
# responses:     dict = {}   # prescription_id → [response, ...]

# # ── Static pharmacy data (Nagpur) ───────────────────
# PHARMACIES = [
#     {"id":"ph1","name":"LifeCare Pharmacy",    "address":"17 Civil Lines, Nagpur",     "phone":"0712-244-5678","lat":21.1458,"lng":79.0882,"open":True, "rating":4.8,"dist_km":1.2},
#     {"id":"ph2","name":"Apollo Pharmacy",      "address":"Dharampeth, Nagpur",          "phone":"0712-255-9900","lat":21.1536,"lng":79.0775,"open":True, "rating":4.6,"dist_km":2.8},
#     {"id":"ph3","name":"MedPlus Stores",       "address":"Sitabuldi, Nagpur",           "phone":"0712-266-1122","lat":21.1418,"lng":79.0760,"open":False,"rating":4.3,"dist_km":3.5},
#     {"id":"ph4","name":"Wellness Pharmacy",    "address":"Ramdaspeth, Nagpur",          "phone":"0712-277-3344","lat":21.1490,"lng":79.0840,"open":True, "rating":4.7,"dist_km":1.8},
#     {"id":"ph5","name":"Jan Aushadhi Kendra",  "address":"Itwari, Nagpur",              "phone":"0712-288-5566","lat":21.1582,"lng":79.0912,"open":True, "rating":4.1,"dist_km":4.2},
#     {"id":"ph6","name":"Sahyadri Pharma",      "address":"Sadar, Nagpur",               "phone":"0712-299-7788","lat":21.1430,"lng":79.0980,"open":False,"rating":4.5,"dist_km":3.0},
#     {"id":"ph7","name":"NetMeds Store",        "address":"Mahal, Nagpur",               "phone":"0712-300-9900","lat":21.1500,"lng":79.0700,"open":True, "rating":4.2,"dist_km":5.1},
#     {"id":"ph8","name":"Dr. Reddy's Pharma",   "address":"Wardhaman Nagar, Nagpur",     "phone":"0712-311-2233","lat":21.1610,"lng":79.0850,"open":True, "rating":4.4,"dist_km":4.8},
# ]

# # ── Helpers ─────────────────────────────────────────
# def allowed_file(filename: str) -> bool:
#     return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

# def make_track_id() -> str:
#     date_str = datetime.now().strftime("%Y%m%d")
#     short    = str(uuid.uuid4())[:4].upper()
#     return f"MR-{date_str}-{short}"

# def haversine(lat1, lng1, lat2, lng2) -> float:
#     """Return distance in km between two lat/lng points."""
#     from math import radians, sin, cos, sqrt, atan2
#     R = 6371
#     dlat = radians(lat2 - lat1)
#     dlng = radians(lng2 - lng1)
#     a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
#     return R * 2 * atan2(sqrt(a), sqrt(1 - a))

# # ════════════════════════════════════════════════════
# #  PAGE ROUTES  (serve HTML templates)
# # ════════════════════════════════════════════════════
# @app.route("/")
# def index():
#     return render_template("index.html")

# @app.route("/upload")
# def upload_page():
#     return render_template("upload.html")

# @app.route("/map")
# def map_page():
#     return render_template("map.html")

# @app.route("/responses")
# def responses_page():
#     return render_template("responses.html")

# # ── Serve uploaded prescription images ──────────────
# @app.route("/uploads/<filename>")
# def uploaded_file(filename):
#     return send_from_directory(app.config["UPLOAD_FOLDER"], filename)

# # ════════════════════════════════════════════════════
# #  API — PHARMACIES
# # ════════════════════════════════════════════════════
# @app.route("/api/pharmacies", methods=["GET"])
# def get_pharmacies():
#     """
#     GET /api/pharmacies
#     Optional query params: lat, lng, radius (km, default 10)
#     Returns list of pharmacies sorted by distance.
#     """
#     lat    = request.args.get("lat",    type=float)
#     lng    = request.args.get("lng",    type=float)
#     radius = request.args.get("radius", type=float, default=10.0)

#     result = []
#     for p in PHARMACIES:
#         entry = dict(p)
#         if lat is not None and lng is not None:
#             entry["dist_km"] = round(haversine(lat, lng, p["lat"], p["lng"]), 2)
#         if entry["dist_km"] <= radius:
#             result.append(entry)

#     result.sort(key=lambda x: x["dist_km"])
#     return jsonify({"success": True, "count": len(result), "pharmacies": result})

# # ════════════════════════════════════════════════════
# #  API — PRESCRIPTIONS
# # ════════════════════════════════════════════════════
# @app.route("/api/prescriptions", methods=["POST"])
# def upload_prescription():
#     """
#     POST /api/prescriptions
#     Form fields: patient_name, phone, area, city, notes, radius
#     Files:       images[]
#     Returns:     { success, prescription_id, notified_count, prescription }
#     """
#     patient_name = request.form.get("patient_name", "").strip()
#     phone        = request.form.get("phone",        "").strip()
#     area         = request.form.get("area",         "").strip()
#     city         = request.form.get("city",         "").strip()
#     notes        = request.form.get("notes",        "").strip()
#     radius       = float(request.form.get("radius", 5))
#     lat          = request.form.get("lat",   type=float)
#     lng          = request.form.get("lng",   type=float)

#     # Validate
#     errors = []
#     if not patient_name: errors.append("patient_name is required")
#     if not phone:        errors.append("phone is required")
#     if not area:         errors.append("area is required")
#     if errors:
#         return jsonify({"success": False, "errors": errors}), 400

#     # Save uploaded files
#     files = request.files.getlist("images")
#     saved_paths = []
#     for f in files:
#         if f and f.filename and allowed_file(f.filename):
#             filename = f"{uuid.uuid4().hex}_{secure_filename(f.filename)}"
#             f.save(os.path.join(app.config["UPLOAD_FOLDER"], filename))
#             saved_paths.append(f"/uploads/{filename}")

#     if not saved_paths:
#         return jsonify({"success": False, "errors": ["At least one prescription image is required"]}), 400

#     # Build record
#     presc_id = make_track_id()
#     nearby   = [p for p in PHARMACIES if p["dist_km"] <= radius]

#     prescription = {
#         "id":           presc_id,
#         "patient_name": patient_name,
#         "phone":        phone,
#         "area":         area,
#         "city":         city,
#         "notes":        notes,
#         "images":       saved_paths,
#         "radius_km":    radius,
#         "lat":          lat,
#         "lng":          lng,
#         "status":       "pending",
#         "created_at":   datetime.now().isoformat(),
#         "notified_pharmacies": [p["id"] for p in nearby],
#     }

#     prescriptions[presc_id] = prescription
#     responses[presc_id]     = []

#     # In production: send WhatsApp / SMS / email to each pharmacy here
#     # notify_pharmacies(nearby, prescription)

#     return jsonify({
#         "success":         True,
#         "prescription_id": presc_id,
#         "notified_count":  len(nearby),
#         "prescription":    prescription,
#     }), 201


# @app.route("/api/prescriptions/<presc_id>", methods=["GET"])
# def get_prescription(presc_id):
#     """GET /api/prescriptions/<id>  — fetch prescription + its responses."""
#     p = prescriptions.get(presc_id)
#     if not p:
#         return jsonify({"success": False, "error": "Prescription not found"}), 404
#     return jsonify({
#         "success":      True,
#         "prescription": p,
#         "responses":    responses.get(presc_id, []),
#     })

# # ════════════════════════════════════════════════════
# #  API — PHARMACY RESPONSES  (pharmacist-side)
# # ════════════════════════════════════════════════════
# @app.route("/api/responses", methods=["POST"])
# def submit_response():
#     """
#     POST /api/responses
#     JSON body:
#     {
#       "prescription_id": "MR-...",
#       "pharmacy_id":     "ph1",
#       "medicines": [
#         { "name": "Metformin 500mg x30", "available": true,  "price": 142 },
#         { "name": "Atorvastatin 10mg x30","available": false, "price": 0  }
#       ],
#       "total_price": 142,
#       "notes": "Delivery available",
#       "delivery_available": true
#     }
#     """
#     data = request.get_json(silent=True) or {}

#     presc_id    = data.get("prescription_id")
#     pharmacy_id = data.get("pharmacy_id")
#     medicines   = data.get("medicines", [])

#     if not presc_id or not pharmacy_id or not medicines:
#         return jsonify({"success": False, "error": "Missing required fields"}), 400

#     if presc_id not in prescriptions:
#         return jsonify({"success": False, "error": "Prescription not found"}), 404

#     pharmacy = next((p for p in PHARMACIES if p["id"] == pharmacy_id), None)
#     if not pharmacy:
#         return jsonify({"success": False, "error": "Pharmacy not found"}), 404

#     all_avail  = all(m.get("available") for m in medicines)
#     any_avail  = any(m.get("available") for m in medicines)
#     avail_str  = "all" if all_avail else ("partial" if any_avail else "none")

#     response_obj = {
#         "id":                str(uuid.uuid4()),
#         "prescription_id":   presc_id,
#         "pharmacy_id":       pharmacy_id,
#         "pharmacy_name":     pharmacy["name"],
#         "pharmacy_phone":    pharmacy["phone"],
#         "pharmacy_dist":     pharmacy["dist_km"],
#         "medicines":         medicines,
#         "total_price":       data.get("total_price", 0),
#         "notes":             data.get("notes", ""),
#         "delivery_available":data.get("delivery_available", False),
#         "availability":      avail_str,
#         "created_at":        datetime.now().isoformat(),
#     }

#     responses[presc_id].append(response_obj)
#     return jsonify({"success": True, "response": response_obj}), 201


# @app.route("/api/responses/<presc_id>", methods=["GET"])
# def get_responses(presc_id):
#     """GET /api/responses/<prescription_id>  — all pharmacy replies."""
#     if presc_id not in prescriptions:
#         return jsonify({"success": False, "error": "Prescription not found"}), 404
#     return jsonify({
#         "success":   True,
#         "count":     len(responses.get(presc_id, [])),
#         "responses": responses.get(presc_id, []),
#     })

# # ════════════════════════════════════════════════════
# #  HEALTH CHECK
# # ════════════════════════════════════════════════════
# @app.route("/api/health")
# def health():
#     return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})

# # ════════════════════════════════════════════════════
# if __name__ == "__main__":
#     print("\n  ╔═══════════════════════════════╗")
#     print("  ║  MedRelay Flask Server         ║")
#     print("  ║  http://localhost:5000          ║")
#     print("  ╚═══════════════════════════════╝\n")
#     app.run(debug=True, port=5000)