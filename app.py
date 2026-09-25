import os, uuid, math, json, time, hashlib
from datetime import datetime
from functools import wraps

import requests as http_req
from flask import (Flask, request, jsonify, render_template,
                   send_from_directory, session, redirect, url_for)
from flask_cors import CORS
from werkzeug.utils import secure_filename

from dotenv import load_dotenv
load_dotenv()

try:
    import bcrypt
    USE_BCRYPT = True
except ImportError:
    USE_BCRYPT = False

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'medrelay-dev-secret-change-in-prod')
CORS(app, supports_credentials=True)

import os

# ── Upload ─────
UPLOAD_FOLDER = 'uploads'
ALLOWED_EXT   = {'jpg','jpeg','png','pdf','webp'}
app.config['UPLOAD_FOLDER']      = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 10 * 1024 * 1024
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ── MySQL ──
from mysql.connector import pooling
DB_CFG = dict(
    host=os.getenv('DB_HOST','localhost'), port=int(os.getenv('DB_PORT',3306)),
    user=os.getenv('DB_USER','root'),     password=os.getenv('DB_PASSWORD'),
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
    if not _pool: 
        raise RuntimeError('DB not available')
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

# ── Passwords ──
def hash_pw(plain):
    if USE_BCRYPT:
        return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()
    return hashlib.sha256(plain.encode()).hexdigest()

def check_pw(plain, hashed):
    if USE_BCRYPT:
        try: return bcrypt.checkpw(plain.encode(), hashed.encode())
        except: pass
    return hashlib.sha256(plain.encode()).hexdigest() == hashed

# ── Auth decorators ─
def pharmacy_required(f):
    @wraps(f)
    def wrap(*a, **kw):
        if 'pharmacy_id' not in session:
            return redirect(url_for('pharmacist_login_page'))
        return f(*a, **kw)
    return wrap

def customer_required(f):
    """Gate a route behind customer login.
    API routes (/api/...) get a 401 JSON error.
    Page routes redirect to the customer login page, remembering where to
    return to afterwards via ?next=...
    """
    @wraps(f)
    def wrap(*a, **kw):
        if 'customer_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': 'Please login first'}), 401
            return redirect(url_for('customer_login_page', next=request.path))
        return f(*a, **kw)
    return wrap

# ── Overpass ──
OVERPASS = ['https://overpass-api.de/api/interpreter',
            'https://overpass.kumi.systems/api/interpreter']
_ov_cache = {}; CACHE_TTL = 300

# ── Utils ─
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
                    'logo':'', 'delivery':False, 'source':'osm'})
    return sorted(out, key=lambda x: x['dist_km'])


#  PAGE ROUTES
@app.route('/')
def index():
    # customer_id / customer_name are already available inside index.html
    # via Flask's automatic `session` template global, but we also pass
    # them explicitly for clarity / in case you template-inherit elsewhere.
    return render_template(
        'index.html',
        customer_logged_in='customer_id' in session,
        customer_name=session.get('customer_name'),
    )

@app.route('/upload')
def upload_page(): return render_template('upload.html')

@app.route('/map')
def map_page(): return render_template('map.html')

@app.route('/responses')
@customer_required
def responses_page():
    # Only a logged-in customer can view the responses page at all.
    return render_template('responses.html')

@app.route("/nearby-pharmacies", methods=["POST"])
def nearby_pharmacies():
    pass

@app.route('/pharmacy/login', methods=['GET', 'POST'])
def pharmacist_login_page():
    if request.method == 'POST':
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')

        pharmacy = qry("""
            SELECT pharmacy_id, name, email, password_hash
            FROM pharmacies
            WHERE email = %s
              AND is_active = 1
              AND is_verified = 1
        """, (email,), fetch='one')

        if not pharmacy:
            return jsonify({
                'success': False,
                'error': 'Invalid email or password'
            }), 401

        if not check_pw(password, pharmacy['password_hash']):
            return jsonify({
                'success': False,
                'error': 'Invalid email or password'
            }), 401

        session['pharmacy_id'] = pharmacy['pharmacy_id']
        session['pharmacy_name'] = pharmacy['name']

        return jsonify({
            'success': True,
            'redirect': '/pharmacy/dashboard'
        })

    return render_template('login.html')
 

@app.route('/pharmacy/logout', methods=['GET','POST'])
def pharmacy_logout():
    session.clear()
    return redirect(url_for('pharmacist_login_page'))

@app.route('/uploads/<path:filename>')
def serve_upload(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


#  API: Health
@app.route('/api/health')
def health():
    try: qry('SELECT 1', fetch='one'); db_ok=True
    except: db_ok=False
    return jsonify({'status':'ok','db':db_ok,'time':datetime.utcnow().isoformat()})


@app.route('/pharmacy/register')
def pharmacy_register_page(): return render_template('pharmacy_register.html')

@app.route('/customer/register')
def customer_register_page(): return render_template('customer_register.html')


# ══════════════════════════════════════════════════════════════════════════
#  Customer login page + logout page  (NEW)
# ══════════════════════════════════════════════════════════════════════════
@app.route('/customer/login', methods=['GET'])
def customer_login_page():
    if 'customer_id' in session:
        return redirect(url_for('index'))
    next_url = request.args.get('next', '')
    return render_template('login.html', next_url=next_url)


@app.route('/customer/logout', methods=['GET', 'POST'])
def customer_logout_page():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('customer_email', None)
    return redirect(url_for('index'))


#  API: Pharmacy Registration
@app.route('/api/pharmacy/register', methods=['POST'])
def api_pharmacy_register():
    d = request.form

    # Required fields
    for f in [
        'name', 'phone', 'email', 'password',
        'address', 'area', 'city', 'pincode',
        'drug_license', 'lat', 'lng'
    ]:
        if not d.get(f, '').strip():
            return jsonify({
                'success': False,
                'error': f'"{f}" is required'
            }), 400

    try:
        # Check whether pharmacy is already registered
        existing = qry(
            '''
            SELECT pharmacy_id
            FROM pharmacies
            WHERE phone = %s
               OR email = %s
               OR drug_license_no = %s
            ''',
            (
                d['phone'],
                d['email'],
                d['drug_license']
            ),
            fetch='one'
        )

        if existing:
            return jsonify({
                'success': False,
                'error': 'Phone, email or drug license already registered'
            }), 409


        # --------------------------------------------------
        # FIND CITY ID
        # --------------------------------------------------
        city = qry(''' SELECT city_id FROM cities
            WHERE name = %s LIMIT 1 ''',
            (d['city'].strip(),),
            fetch='one'
        )

        if not city:
            return jsonify({
                'success': False,
                'error': f'City "{d["city"].strip()}" not found'
            }), 400

        city_id = city['city_id'] if isinstance(city, dict) else city[0]


        # --------------------------------------------------
        # CREATE PHARMACY
        # --------------------------------------------------
        pid = new_uuid()
        pw = hash_pw(d['password'])
        qry(
            '''INSERT INTO pharmacies(
                pharmacy_id,
                name,
                address_line,
                area,
                city_id,
                pincode,
                phone,
                email,
                drug_license_no,
                gst_number,
                proprietor_name,
                latitude,
                longitude,
                password_hash,
                delivery_radius_km,
                accepts_delivery,
                opening_time,
                closing_time,
                is_active,
                is_verified
            )
            VALUES
            (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s
            )
            ''',
            (
                pid,
                d['name'].strip(),
                d['address'].strip(),
                d['area'].strip(),
                city_id,
                d['pincode'].strip(),
                d['phone'].strip(),
                d['email'].strip(),
                d['drug_license'].strip(),
                d.get('gst', '').strip(),
                d.get('proprietor', '').strip(),
                float(d['lat']),
                float(d['lng']),
                pw,
                float(d.get('del_radius', 5)),
                1 if d.get('delivery') in ('true', '1', 'on') else 0,
                d.get('open_time', '09:00'),
                d.get('close_time', '21:00'),
                1,
                1
            ),
            fetch='insert'
        )

        return jsonify({
            'success': True,
            'pharmacy_id': pid,
            'message': 'Registration submitted. Our team will verify within 24 hours.'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    
# ══════════════════════════════════════════════════════════════════════════
#  API: Customer Registration
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/customer/register', methods=['POST'])
def api_customer_register():
    d = request.get_json(force=True)

    for f in ['full_name', 'phone', 'email', 'password']:
        if not d.get(f, '').strip():
            return jsonify({
                'success': False,
                'error': f'"{f}" is required'
            }), 400

    try:
        existing = qry(
            '''
            SELECT customer_id
            FROM customers
            WHERE phone = %s
               OR email = %s
            ''',
            (d['phone'].strip(), d['email'].strip()),
            fetch='one'
        )

        if existing:
            return jsonify({
                'success': False,
                'error': 'Phone or email already registered'
            }), 409

        cid = new_uuid()
        pw  = hash_pw(d['password'])

        qry(
            '''
            INSERT INTO customers(
                customer_id, full_name, phone, email, password_hash, is_active
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ''',
            (
                cid,
                d['full_name'].strip(),
                d['phone'].strip(),
                d['email'].strip(),
                pw,
                1
            ),
            fetch='insert'
        )

        return jsonify({
            'success': True,
            'customer_id': cid,
            'message': 'Registration successful. You can now log in.'
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


#  API: Customer Login
@app.route('/api/customer/login', methods=['POST'])
def api_customer_login():
    data  = request.get_json(force=True)
    email = data.get('email', '').strip()
    pw    = data.get('password', '')

    if not email or not pw:
        return jsonify({'success': False, 'error': 'Email and password required'}), 400

    try:
        cust = qry('SELECT * FROM customers WHERE email=%s AND is_active=1', (email,), fetch='one')
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

    if not cust or not check_pw(pw, cust.get('password_hash', '')):
        return jsonify({'success': False, 'error': 'Invalid email or password'}), 401

    session['customer_id']    = cust['customer_id']
    session['customer_name']  = cust['full_name']
    session['customer_email'] = cust['email']

    return jsonify({
        'success': True,
        'customer_id': cust['customer_id'],
        'name': cust['full_name']
    })


#  API: Customer Logout
@app.route('/api/customer/logout', methods=['POST'])
def api_customer_logout():
    session.pop('customer_id', None)
    session.pop('customer_name', None)
    session.pop('customer_email', None)
    return jsonify({'success': True})


#  API: Currently logged-in customer (handy for JS on any page)
@app.route('/api/customer/me')
def api_customer_me():
    if 'customer_id' not in session:
        return jsonify({'success': True, 'logged_in': False})
    return jsonify({
        'success': True,
        'logged_in': True,
        'customer_id': session['customer_id'],
        'name': session.get('customer_name'),
        'email': session.get('customer_email'),
    })

    
#  API: Pharmacy Login
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


#  API: Dashboard — pharmacy profile
@app.route('/pharmacy/dashboard')
def pharmacy_dashboard():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return redirect('/pharmacy/login')

    pharmacy = qry("""
        SELECT pharmacy_id, name, phone, email,
               address_line, area, pincode,
               accepts_delivery
        FROM pharmacies
        WHERE pharmacy_id = %s
    """, (pharmacy_id,), fetch='one')

    if not pharmacy:
        session.clear()
        return redirect('/pharmacy/login')

    return render_template(
        'pharmacy_dashboard.html',
        pharmacy=pharmacy
    )


#  API: Dashboard — stats summary
@app.route('/api/pharmacy/stats')
def pharmacy_stats():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return jsonify({
            'success': False,
            'error': 'Please login first'
        }), 401

    try:
        # REQUESTED PRESCRIPTIONS
        requested = qry("""
            SELECT COUNT(*) AS total
            FROM prescription_broadcasts
            WHERE pharmacy_id = %s
        """, (pharmacy_id,), fetch='one')

        # RESPONDED ORDERS
        responded = qry("""
            SELECT COUNT(*) AS total
            FROM orders
            WHERE pharmacy_id = %s
        """, (pharmacy_id,), fetch='one')

        # COMPLETED ORDERS
        completed = qry("""
            SELECT COUNT(*) AS total
            FROM orders
            WHERE pharmacy_id = %s
              AND status IN ('delivered', 'completed')
        """, (pharmacy_id,), fetch='one')

        return jsonify({
            'success': True,
            'requested_orders':
                requested['total'] if requested else 0,

            'responded_orders':
                responded['total'] if responded else 0,

            'completed_orders':
                completed['total'] if completed else 0
        })

    except Exception as e:
        print("PHARMACY STATS ERROR:", e)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


#  API: Dashboard — orders list
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


@app.route('/test-db')
def test_db():
    try:
        rows = qry("""SELECT pharmacy_id, name, latitude, longitude,
                   is_active, is_verified
            FROM pharmacies""")

        print("Number of pharmacies:", len(rows))

        for r in rows:
            print(r)

        return jsonify({
            'success': True,
            'count': len(rows),
            'pharmacies': rows
        })

    except Exception as e:
        print(e)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


#  API: Dashboard — order detail + status update
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


#  API: Dashboard — submit availability response to a prescription
@app.route('/api/pharmacy/respond/<prescription_id>', methods=['POST'])
def api_pharmacy_respond(prescription_id):
    pharmacy_id = session.get('pharmacy_id')
    if not pharmacy_id:
        return jsonify({
            'success': False,
            'error': 'Please login first'
        }), 401
    data = request.form

    try:
        # Make sure this pharmacy actually received this prescription
        broadcast = qry("""
            SELECT broadcast_id
            FROM prescription_broadcasts
            WHERE prescription_id = %s
              AND pharmacy_id = %s
        """, (prescription_id, pharmacy_id), fetch='one')

        if not broadcast:
            return jsonify({
                'success': False,
                'error': 'This prescription was not sent to your pharmacy'
            }), 403


        # Prevent duplicate responses
        existing = qry("""
            SELECT response_id
            FROM pharmacy_responses
            WHERE prescription_id = %s
              AND pharmacy_id = %s
        """, (prescription_id, pharmacy_id), fetch='one')

        if existing:

            return jsonify({
                'success': False,
                'error': 'You have already responded to this prescription'
            }), 409


        availability = data.get('availability')
        if availability not in ('all', 'partial', 'none'):
            return jsonify({
                'success': False,
                'error': 'Invalid availability'
            }), 400


        total_price = data.get('total_price') or None
        delivery_available = ( 1 if data.get('delivery_available') == '1' else 0 )
        estimated_time = ( data.get('estimated_time_min') or None )
        notes = data.get('notes', '').strip()

        # Generate response ID
        response_id = new_uuid()

        # Insert overall response
        qry("""
            INSERT INTO pharmacy_responses
            (
                response_id,
                prescription_id,
                pharmacy_id,
                availability,
                total_price,
                delivery_available,
                estimated_time_min,
                notes
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            response_id,
            prescription_id,
            pharmacy_id,
            availability,
            total_price,
            delivery_available,
            estimated_time,
            notes
        ), fetch='insert')

        # Medicine arrays
        names = data.getlist('medicine_name[]')
        quantities = data.getlist('quantity[]')
        available = data.getlist('is_available[]')
        prices = data.getlist('unit_price[]')
        substitutes = data.getlist('substitute_name[]')
        substitute_prices = data.getlist('substitute_price[]')

        # Insert medicine items
        for i in range(len(names)):
            medicine_name = names[i].strip()
            if not medicine_name:
                continue

            quantity = (
                quantities[i].strip()
                if i < len(quantities)
                else None
            )
            is_available = (
                1
                if i < len(available)
                and available[i] == '1'
                else 0
            )
            unit_price = (
                prices[i]
                if i < len(prices)
                and prices[i].strip()
                else None
            )
            substitute_name = (
                substitutes[i].strip()
                if i < len(substitutes)
                and substitutes[i].strip()
                else None
            )
            substitute_price = (
                substitute_prices[i]
                if i < len(substitute_prices)
                and substitute_prices[i].strip()
                else None
            )
            subtotal = None

            # Calculate subtotal when possible
            if unit_price and quantity:
                try:
                    import re
                    match = re.search(
                        r'\d+',
                        quantity
                    )
                    if match:
                        qty = int(match.group())
                        subtotal = (
                            float(unit_price) * qty
                        )
                except Exception:
                    subtotal = None

            qry("""
                INSERT INTO response_medicine_items
                (
                    response_id,
                    medicine_name,
                    quantity,
                    is_available,
                    unit_price,
                    subtotal,
                    substitute_name,
                    substitute_price
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
            """, (
                response_id,
                medicine_name,
                quantity,
                is_available,
                unit_price,
                subtotal,
                substitute_name,
                substitute_price
            ), fetch='insert')

        # Mark broadcast as responded
        qry("""
            UPDATE prescription_broadcasts
            SET
                status = 'responded',
                responded_at = CURRENT_TIMESTAMP
            WHERE prescription_id = %s
              AND pharmacy_id = %s
        """, (
            prescription_id,
            pharmacy_id
        ))

        return jsonify({
            'success': True,
            'response_id': response_id,
            'message': 'Response submitted successfully'
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)}), 500


@app.route('/api/pharmacy/requests', methods=['GET'])
def pharmacy_requests():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return jsonify({
            'success': False,
            'error': 'Please login first'
        }), 401

    try:
        requests = qry("""
            SELECT
                p.prescription_id,
                p.patient_name,
                p.phone,
                p.area,
                p.notes,
                p.status AS prescription_status,

                pb.distance_km,
                pb.status AS broadcast_status,
                pb.sent_at,
                pb.read_at,
                pb.responded_at

            FROM prescription_broadcasts pb

            JOIN prescriptions p
                ON p.prescription_id = pb.prescription_id

            WHERE pb.pharmacy_id = %s

            ORDER BY pb.sent_at DESC
        """, (pharmacy_id,), fetch='all')

        return jsonify({
            'success': True,
            'requests': requests or []
        })

    except Exception as e:
        print("PHARMACY REQUESTS ERROR:", e)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    

@app.route('/pharmacy/request/<prescription_id>')
def pharmacy_view_request(prescription_id):
    pharmacy_id = session.get('pharmacy_id')
    
    if not pharmacy_id:
        return redirect('/pharmacy/login')

    try:
        # TEST 1: Prescription + broadcast
        prescription = qry("""
            SELECT
                p.prescription_id,
                p.patient_id,
                p.patient_name,
                p.phone,
                p.area,
                p.city_id,
                p.notes,
                p.patient_lat,
                p.patient_lng,
                p.search_radius_km,
                p.status,
                p.expires_at,
                p.created_at,
                pb.distance_km,
                pb.status AS broadcast_status,
                pb.sent_at,
                pb.read_at,
                pb.responded_at
            FROM prescriptions p
            JOIN prescription_broadcasts pb
                ON p.prescription_id = pb.prescription_id
            WHERE p.prescription_id = %s
              AND pb.pharmacy_id = %s
        """, (prescription_id, pharmacy_id), fetch='one')

        if not prescription:
            return "Prescription not found", 404

        # TEST 2: Images
        images = qry("""
            SELECT
                image_id,
                file_path,
                file_name,
                file_type,
                file_size_kb,
                sort_order,
                uploaded_at
            FROM prescription_images
            WHERE prescription_id = %s
            ORDER BY sort_order ASC
        """, (prescription_id,), fetch='all')

        # TEST 3: Mark read
        qry("""
            UPDATE prescription_broadcasts
            SET status = CASE
                WHEN status = 'sent' THEN 'read' ELSE status
                END,
                read_at = CASE
                    WHEN read_at IS NULL THEN CURRENT_TIMESTAMP
                    ELSE read_at
                END
            WHERE prescription_id = %s
              AND pharmacy_id = %s
        """, (prescription_id, pharmacy_id))

        # TEST 4: Template
        return render_template('pharmacy_view_request.html',
                        prescription = prescription,
                        images=images
                    )

    except Exception as e:
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/pharmacy/orders/responded')
def pharmacy_orders_responded():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return redirect('/pharmacy/login')

    try:
        orders = qry("""
            SELECT o.order_id, o.prescription_id, o.patient_name,
                o.patient_phone, o.delivery_address, o.total_amount,
                o.payment_mode, o.payment_status, o.status,
                o.placed_at, o.updated_at
            FROM orders o
            WHERE o.pharmacy_id = %s
            ORDER BY o.placed_at DESC
        """, (pharmacy_id,), fetch='all')

        return render_template(
            'pharmacy_orders_responded.html',
            orders=orders
        )
    except Exception as e:
        print("RESPONDED ORDERS ERROR:", e)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/pharmacy/orders/completed')
def pharmacy_orders_completed():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return redirect('/pharmacy/login')

    try:
        orders = qry("""
            SELECT o.order_id, o.prescription_id, o.patient_name, o.patient_phone, 
                o.delivery_address, o.total_amount, o.payment_mode, o.payment_status, 
                o.status, o.placed_at, o.updated_at
            FROM orders o
            WHERE o.pharmacy_id = %s
              AND o.status IN ('delivered', 'completed')
            ORDER BY o.updated_at DESC
        """, (pharmacy_id,), fetch='all')

        return render_template(
            'pharmacy_orders_completed.html',
            orders=orders
        )
    except Exception as e:
        print("COMPLETED ORDERS ERROR:", e)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

    
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
    lat = float(request.args.get("lat", 21.1458))
    lng = float(request.args.get("lng", 79.0882))
    radius = float(request.args.get("radius", 3))

    q = request.args.get('q','').lower().strip()

    if not lat or not lng:
        return jsonify({'success':False,'error':'lat and lng required'}), 400

    # Registered pharmacies from DB
    registered = []
    try:
        rows = qry("SELECT * FROM pharmacies WHERE is_active=1 AND is_verified=1")
        for r in rows:
            print(r["name"])
            print(r["latitude"], r["longitude"])
            d = haversine(lat, lng, float(r['latitude']), float(r['longitude']))
            print("Distance:", d)

            if d <= radius:
                registered.append({
                    'osm_id':None, 'db_id':r['pharmacy_id'],
                    'name':r['name'], 'phone':r['phone'],
                    'address':f"{r['address_line']}, {r['area']}",
                    'lat':float(r['latitude']), 'lng':float(r['longitude']),
                    'dist_km':d,
                    'open':bool(r.get('is_open_now')),
                    'hours':f"{r.get('opening_time','')} – {r.get('closing_time','')}",
                    'logo':r.get('logo_path',''),
                    'delivery':bool(r.get('accepts_delivery')),
                    'source':'medrelay',
                })
    except Exception as e:
        app.logger.warning(f'DB pharmacies Error: {e}')

    
    # OSM pharmacies
    ck = f'{round(lat,4)},{round(lng,4)},{radius}'
    cached = _ov_cache.get(ck)
    osm = []
    if cached and (time.time()-cached[0]) < CACHE_TTL:
        print("USING CACHED OSM DATA")
        osm = cached[1]
    else:
        oq = f"""
            [out:json][timeout:25];
            (
            node["amenity"="pharmacy"](around:{int(radius*1000)},{lat},{lng});
            way["amenity"="pharmacy"](around:{int(radius*1000)},{lat},{lng});
            relation["amenity"="pharmacy"](around:{int(radius*1000)},{lat},{lng});
            );
            out center tags;
            """
        for mirror in OVERPASS:
            print("Trying Overpass:", mirror)
            try:
                r = http_req.post(mirror, data={'data':oq},
                    headers={'Content-Type':'application/x-www-form-urlencoded'}, timeout=30)
                
                if r.status_code == 200:
                    result = r.json()
                    elements = result.get('elements', [])
                    osm = norm_overpass(elements, lat, lng)
                    _ov_cache[ck] = (time.time(), osm)
                    break
                else:
                    print("OVERPASS ERROR:")
                    print(r.text[:1000])

            except Exception as ex:
                print("OVERPASS EXCEPTION:", repr(ex))

        
    # Merge — registered names win
    reg_names = {p['name'].lower() for p in registered}
    merged = sorted(registered + [p for p in osm if p['name'].lower() not in reg_names],
                    key=lambda x: x['dist_km'])
    
    merged = [p for p in merged
                  if q in p['name'].lower()
                  or q in p['address'].lower()
                  or q in p['phone']]
        
    return jsonify({'success':True,'count':len(merged),'pharmacies':merged})


# ══════════════════════════════════════════════════════════════════════════
#  API: Prescriptions
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/prescriptions', methods=['POST'])
@customer_required
def api_upload():
    customer_id = session['customer_id']

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
        # patient_id ties this prescription/order to the logged-in customer,
        # so later we can filter "my orders" / "my responses" by it.
        qry("""INSERT INTO prescriptions
            (prescription_id,patient_id,patient_name,phone,area,notes,
             patient_lat,patient_lng,search_radius_km,status,
             notified_count,expires_at)
            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,'broadcasted',0,
                   DATE_ADD(NOW(),INTERVAL 48 HOUR))""",
            (tid,customer_id,name,phone,area,notes,lat or None,lng or None,radius), fetch='insert')

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
            qry("UPDATE prescriptions SET notified_count=%s WHERE prescription_id=%s",(notified,tid), fetch='exec')
    except Exception as e:
        app.logger.error(e)

    return jsonify({'success':True,'prescription_id':tid,'notified_count':notified,'images':images})


# ══════════════════════════════════════════════════════════════════════════
#  API: Customer's own prescriptions / orders  (NEW)
# ══════════════════════════════════════════════════════════════════════════
@app.route('/api/customer/prescriptions')
@customer_required
def api_customer_prescriptions():
    cid = session['customer_id']
    try:
        rows = qry("""
            SELECT prescription_id, patient_name, area, status,
                   notified_count, created_at, expires_at
            FROM prescriptions
            WHERE patient_id = %s
            ORDER BY created_at DESC
        """, (cid,), fetch='all')
        return jsonify({'success': True, 'prescriptions': rows or []})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/prescriptions/<pid>')
@customer_required
def api_get_prescription(pid):
    cid = session['customer_id']
    try:
        rx = qry('SELECT * FROM prescriptions WHERE prescription_id=%s',(pid,),fetch='one')
        if not rx: return jsonify({'success':False,'error':'Not found'}),404
        # Ownership check — a customer can only view their own prescription.
        if rx.get('patient_id') != cid:
            return jsonify({'success':False,'error':'Not authorized to view this prescription'}), 403
        imgs  = qry('SELECT * FROM prescription_images WHERE prescription_id=%s ORDER BY sort_order',(pid,))
        resps = qry('SELECT * FROM pharmacy_responses WHERE prescription_id=%s ORDER BY responded_at',(pid,))
        for r in resps:
            r['medicines'] = qry('SELECT * FROM response_medicine_items WHERE response_id=%s',(r['response_id'],))
        return jsonify({'success':True,'prescription':rx,'images':imgs,'responses':resps})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}),500

@app.route('/api/responses/<pid>')
@customer_required
def api_get_responses(pid):
    cid = session['customer_id']
    try:
        rx = qry('SELECT patient_id FROM prescriptions WHERE prescription_id=%s', (pid,), fetch='one')
        if not rx:
            return jsonify({'success': False, 'error': 'Not found'}), 404
        # Ownership check — only the customer who submitted this prescription
        # can see the pharmacy responses to it.
        if rx.get('patient_id') != cid:
            return jsonify({'success': False, 'error': 'Not authorized to view these responses'}), 403

        resps = qry('SELECT * FROM pharmacy_responses WHERE prescription_id=%s ORDER BY total_price',(pid,))
        for r in resps:
            r['medicines'] = qry('SELECT * FROM response_medicine_items WHERE response_id=%s',(r['response_id'],))
        return jsonify({'success':True,'count':len(resps),'responses':resps})
    except Exception as e:
        return jsonify({'success':False,'error':str(e)}),500

    
@app.route('/pharmacy/request/<prescription_id>/respond')
def pharmacy_respond_page(prescription_id):
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return redirect('/pharmacy/login')
    try:
        request_data = qry("""
            SELECT p.prescription_id, pb.distance_km, pb.status, p.patient_name, p.phone,
                p.area, p.notes, p.patient_lat, p.patient_lng
            FROM prescription_broadcasts pb
            JOIN prescriptions p
                ON p.prescription_id = pb.prescription_id
            WHERE p.prescription_id = %s
            AND pb.pharmacy_id = %s
        """, (prescription_id, pharmacy_id), fetch='one')

        if not request_data:
            return "Prescription not found or not sent to the Pharmacy", 404

        images = qry("""
                SELECT
                    image_id,
                    file_path,
                    file_name,
                    file_type
                FROM prescription_images
                WHERE prescription_id = %s
                ORDER BY sort_order, uploaded_at
            """, (prescription_id,), fetch='all')

        return render_template(
                'pharmacy_respond.html',
                request_data = request_data,
                images=images
            )

    except Exception as e:
        print("RESPOND PAGE ERROR:", e)
        return "Internal Server Error", 500


@app.route('/pharmacy/profile')
def pharmacy_profile():
    pharmacy_id = session.get('pharmacy_id')

    if not pharmacy_id:
        return redirect('/pharmacy/login')

    try:
        pharmacy = qry("""
            SELECT
                pharmacy_id,
                name,
                phone,
                email,
                address_line,
                area,
                pincode,
                drug_license_no,
                gst_number,
                proprietor_name,
                latitude,
                longitude,
                accepts_delivery,
                delivery_radius_km,
                opening_time,
                closing_time,
                is_active,
                is_verified
            FROM pharmacies
            WHERE pharmacy_id = %s
        """, (pharmacy_id,), fetch='one')

        if not pharmacy:
            session.clear()
            return redirect('/pharmacy/login')

        return render_template(
            'pharmacy_profile.html',
            pharmacy=pharmacy
        )

    except Exception as e:

        print("PHARMACY PROFILE ERROR:", e)

        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# print(f"Password: {hash_pw('Wellness@123')}")
if __name__ == '__main__':
    app.run(debug=True, port=5000)