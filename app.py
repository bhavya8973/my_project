from flask import Flask, render_template, request, jsonify, session
from flask_cors import CORS
import sqlite3, hashlib, re, random
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'blackspot_india_2024_secret_key_xK9mP2qR'
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False
app.config['SESSION_PERMANENT'] = True
CORS(app, supports_credentials=True, origins=['http://127.0.0.1:5000', 'http://localhost:5000'])

# Make session cookie work properly
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

DB = 'blackspot.db'

# ─── DB HELPERS ──────────────────────────────────────────────────────────────

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def sanitize(t):
    if not t: return t
    return re.sub(r'[<>"\';]', '', str(t).strip())[:500]

def migrate_db():
    conn = get_db()
    c = conn.cursor()
    migrations = [
        "ALTER TABLE blackspots ADD COLUMN suggested_by INTEGER DEFAULT NULL",
        "ALTER TABLE reports ADD COLUMN user_id INTEGER DEFAULT NULL",
        "ALTER TABLE reports ADD COLUMN location_name TEXT DEFAULT ''",
    ]
    for sql in migrations:
        try:
            c.execute(sql)
            conn.commit()
            print(f"[Migration] OK: {sql[:50]}")
        except Exception:
            pass  # column already exists, skip
    conn.close()
    print("[Migration] Done.")

def init_db():
    conn = get_db(); c = conn.cursor()

    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS admins (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS blackspots (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        lat REAL NOT NULL,
        lng REAL NOT NULL,
        description TEXT,
        severity TEXT DEFAULT 'high',
        state TEXT,
        approved INTEGER DEFAULT 1,
        suggested_by INTEGER DEFAULT NULL,
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    c.execute('''CREATE TABLE IF NOT EXISTS reports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT NOT NULL,
        lat REAL,
        lng REAL,
        description TEXT NOT NULL,
        location_name TEXT,
        status TEXT DEFAULT 'pending',
        created_at TEXT DEFAULT CURRENT_TIMESTAMP
    )''')

    # Default admin
    pwd = hashlib.sha256('admin123'.encode()).hexdigest()
    c.execute("INSERT OR IGNORE INTO admins (username,password) VALUES (?,?)", ('admin', pwd))

    # Sample blackspots
    spots = [
        ("Dhaulpur-Morena Highway NH3",26.6867,77.8916,"High accident zone, sharp turns","high","Madhya Pradesh"),
        ("Agra-Lucknow Expressway Km 90",27.1767,78.0081,"Frequent high-speed crashes, fog-prone","high","Uttar Pradesh"),
        ("Yamuna Expressway Km 135",27.8974,77.6419,"Multiple fatal accidents due to speeding","high","Uttar Pradesh"),
        ("NH44 Gwalior Near Dobra",26.2183,78.1828,"Narrow stretch, heavy truck movement","medium","Madhya Pradesh"),
        ("Pune-Mumbai Expressway Km 75",18.7679,73.3876,"Landslide-prone, slippery during monsoon","high","Maharashtra"),
        ("Nashik-Pune NH60 Near Ghoti",19.7515,73.7898,"Sharp curves, high-speed zone","high","Maharashtra"),
        ("Delhi-Meerut Expressway Near Dasna",28.6833,77.5167,"Dense fog in winter, multiple accidents","high","Uttar Pradesh"),
        ("Chennai-Bangalore NH48 Near Krishnagiri",12.5266,78.2131,"Hilly terrain, truck accidents frequent","medium","Tamil Nadu"),
        ("Hyderabad ORR Shamshabad Section",17.2403,78.4294,"High speed crashes at night, poor lighting","high","Telangana"),
        ("Mumbai-Pune Expressway Khopoli Ghat",18.7748,73.3397,"Steep gradient, brake failure accidents","high","Maharashtra"),
        ("Kolkata-Durgapur Expressway Km 65",23.1765,87.2619,"Overtaking accidents, poor road condition","medium","West Bengal"),
        ("NH58 Rishikesh-Badrinath Near Devprayag",30.1451,78.5958,"Narrow mountain road, frequent landslides","high","Uttarakhand"),
        ("Rajkot-Ahmedabad NH947",22.6708,70.8022,"High speed corridor, cattle on road","medium","Gujarat"),
        ("Belgaum-Pune NH48 Londa Ghat",15.4667,74.5167,"Steep descent, wet road accidents","high","Karnataka"),
        ("Jaipur-Delhi NH48 Shahpura",27.3890,75.9653,"Two-lane bottleneck, overtaking accidents","high","Rajasthan"),
        ("Bhopal-Indore NH12 Near Hoshangabad",22.7433,77.7293,"Wildlife crossing zone, night accidents","medium","Madhya Pradesh"),
        ("Chandigarh-Shimla NH5 Parwanoo",30.8367,76.9641,"Mountain road, fog and rain accidents","high","Himachal Pradesh"),
        ("Lucknow-Varanasi NH19 Near Sultanpur",26.2584,82.0784,"Poor road surface, night accidents","medium","Uttar Pradesh"),
        ("Patna-Gaya NH83",25.1022,84.9000,"Single lane widening zone, construction","medium","Bihar"),
        ("Coimbatore-Salem NH544 Near Avinashi",11.1908,77.2673,"High speed accidents at traffic junction","high","Tamil Nadu"),
    ]
    c.executemany("INSERT OR IGNORE INTO blackspots (name,lat,lng,description,severity,state) VALUES (?,?,?,?,?,?)", spots)
    conn.commit(); conn.close()

# ─── PUBLIC ───────────────────────────────────────────────────────────────────

@app.route('/')
def index(): return render_template('index.html')

@app.route('/admin')
def admin_page(): return render_template('admin.html')

# ─── USER AUTH ────────────────────────────────────────────────────────────────

@app.route('/api/user/signup', methods=['POST'])
def user_signup():
    d = request.get_json()
    name = sanitize(d.get('name',''))
    phone = sanitize(d.get('phone',''))
    password = d.get('password','')
    if not name or not phone or not password:
        return jsonify({'error':'All fields required'}), 400
    if not re.match(r'^\d{10}$', phone):
        return jsonify({'error':'Enter valid 10-digit phone number'}), 400
    if len(password) < 4:
        return jsonify({'error':'Password must be at least 4 characters'}), 400
    hpwd = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db()
    try:
        conn.execute("INSERT INTO users (name,phone,password) VALUES (?,?,?)", (name, phone, hpwd))
        conn.commit()
        user = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        conn.close()
        return jsonify({'success':True, 'name': user['name']})
    except:
        conn.close()
        return jsonify({'error':'Phone number already registered'}), 409

@app.route('/api/user/login', methods=['POST'])
def user_login():
    d = request.get_json()
    phone = sanitize(d.get('phone',''))
    password = d.get('password','')
    hpwd = hashlib.sha256(password.encode()).hexdigest()
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE phone=? AND password=?", (phone, hpwd)).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        session['user_name'] = user['name']
        return jsonify({'success':True, 'name': user['name']})
    return jsonify({'error':'Invalid phone or password'}), 401

@app.route('/api/user/logout', methods=['POST'])
def user_logout():
    session.pop('user_id', None)
    session.pop('user_name', None)
    return jsonify({'success':True})

@app.route('/api/user/me', methods=['GET'])
def user_me():
    if session.get('user_id'):
        return jsonify({'logged_in':True, 'name': session.get('user_name')})
    return jsonify({'logged_in':False})

# ─── BLACKSPOTS (PUBLIC) ──────────────────────────────────────────────────────

@app.route('/api/blackspots')
def get_blackspots():
    conn = get_db()
    spots = conn.execute("SELECT * FROM blackspots WHERE approved=1").fetchall()
    conn.close()
    return jsonify([dict(s) for s in spots])

# ─── USER SUGGEST BLACKSPOT ───────────────────────────────────────────────────

@app.route('/api/user/suggest', methods=['POST'])
def suggest_blackspot():
    d = request.get_json(force=True, silent=True)
    if not d:
        return jsonify({'error': 'No data received'}), 400
    name = sanitize(d.get('name', ''))
    description = sanitize(d.get('description', ''))
    state = sanitize(d.get('state', ''))
    severity = sanitize(d.get('severity', 'medium'))
    user_id = session.get('user_id')
    try:
        lat = float(d.get('lat') or 0)
        lng = float(d.get('lng') or 0)
    except (TypeError, ValueError):
        return jsonify({'error': 'Invalid coordinates'}), 400
    if not name or not description:
        return jsonify({'error': 'Name and description are required'}), 400
    if lat is None or lng is None:
        return jsonify({'error': 'GPS coordinates are required'}), 400
    conn = get_db()
    conn.execute(
        """INSERT INTO blackspots (name,lat,lng,description,severity,state,approved,suggested_by)
            VALUES (?,?,?,?,?,?,0,?)""",
        (name, lat, lng, description, severity, state, user_id)
    )
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Suggestion submitted! Admin will review it.'})

# ─── USER REPORT ──────────────────────────────────────────────────────────────

@app.route('/api/report', methods=['POST'])
def submit_report():
    d = request.get_json(force=True, silent=True)
    if not d:
        return jsonify({'error': 'No data received'}), 400
    rtype = sanitize(d.get('type', ''))
    description = sanitize(d.get('description', ''))
    location_name = sanitize(d.get('location_name', ''))
    user_id = session.get('user_id')
    try:
        lat = float(d.get('lat') or 0)
        lng = float(d.get('lng') or 0)
    except (TypeError, ValueError):
        lat, lng = 0.0, 0.0

    if not description:
        return jsonify({'error': 'Description is required'}), 400
    # Accept any type or default to complaint
    if rtype not in ['blackspot', 'complaint', 'suggestion']:
        rtype = 'complaint'

    conn = get_db()
    conn.execute("INSERT INTO reports (user_id,type,lat,lng,description,location_name) VALUES (?,?,?,?,?,?)",
                 (user_id, rtype, lat, lng, description, location_name))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── ADMIN AUTH ───────────────────────────────────────────────────────────────

def admin_required(f):
    from functools import wraps
    @wraps(f)
    def dec(*a, **kw):
        if not session.get('admin_logged_in'):
            return jsonify({'error':'Unauthorized'}), 401
        return f(*a, **kw)
    return dec

@app.route('/api/admin/login', methods=['POST'])
def admin_login():
    d = request.get_json()
    username = sanitize(d.get('username',''))
    password = hashlib.sha256(d.get('password','').encode()).hexdigest()
    conn = get_db()
    admin = conn.execute("SELECT * FROM admins WHERE username=? AND password=?", (username,password)).fetchone()
    conn.close()
    if admin:
        session['admin_logged_in'] = True
        session['admin_username'] = username
        return jsonify({'success':True})
    return jsonify({'error':'Invalid credentials'}), 401

@app.route('/api/admin/logout', methods=['POST'])
def admin_logout():
    session.clear()
    return jsonify({'success':True})

# ─── ADMIN BLACKSPOTS ─────────────────────────────────────────────────────────

@app.route('/api/admin/blackspots', methods=['GET'])
@admin_required
def admin_get_blackspots():
    conn = get_db()
    spots = conn.execute("SELECT * FROM blackspots ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(s) for s in spots])

@app.route('/api/admin/blackspots', methods=['POST'])
@admin_required
def admin_add_blackspot():
    d = request.get_json()
    name = sanitize(d.get('name',''))
    lat = float(d.get('lat',0))
    lng = float(d.get('lng',0))
    if not name or not lat or not lng:
        return jsonify({'error':'Name, lat, lng required'}), 400
    conn = get_db()
    conn.execute("INSERT INTO blackspots (name,lat,lng,description,severity,state,approved) VALUES (?,?,?,?,?,?,1)",
                 (name, lat, lng, sanitize(d.get('description','')), sanitize(d.get('severity','high')), sanitize(d.get('state',''))))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/blackspots/<int:sid>', methods=['PUT'])
@admin_required
def admin_update_blackspot(sid):
    d = request.get_json()
    conn = get_db()
    conn.execute("UPDATE blackspots SET name=?,description=?,severity=?,state=?,approved=? WHERE id=?",
                 (sanitize(d.get('name','')), sanitize(d.get('description','')),
                  sanitize(d.get('severity','high')), sanitize(d.get('state','')),
                  int(d.get('approved',1)), sid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/blackspots/<int:sid>', methods=['DELETE'])
@admin_required
def admin_delete_blackspot(sid):
    conn = get_db()
    conn.execute("DELETE FROM blackspots WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── ADMIN SUGGESTIONS ────────────────────────────────────────────────────────

@app.route('/api/admin/suggestions', methods=['GET'])
@admin_required
def admin_get_suggestions():
    conn = get_db()
    rows = conn.execute("""
        SELECT b.*, u.name as user_name, u.phone as user_phone
        FROM blackspots b
        LEFT JOIN users u ON b.suggested_by = u.id
        WHERE b.suggested_by IS NOT NULL
        ORDER BY b.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/suggestions/<int:sid>/approve', methods=['POST'])
@admin_required
def approve_suggestion(sid):
    conn = get_db()
    conn.execute("UPDATE blackspots SET approved=1 WHERE id=?", (sid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

@app.route('/api/admin/suggestions/<int:sid>/reject', methods=['POST'])
@admin_required
def reject_suggestion(sid):
    conn = get_db()
    conn.execute("DELETE FROM blackspots WHERE id=? AND suggested_by IS NOT NULL", (sid,))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── ADMIN REPORTS ────────────────────────────────────────────────────────────

@app.route('/api/admin/reports', methods=['GET'])
@admin_required
def admin_get_reports():
    conn = get_db()
    rows = conn.execute("""
        SELECT r.*, u.name as user_name, u.phone as user_phone
        FROM reports r
        LEFT JOIN users u ON r.user_id = u.id
        ORDER BY r.created_at DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route('/api/admin/reports/<int:rid>', methods=['PUT'])
@admin_required
def admin_update_report(rid):
    status = sanitize(request.get_json().get('status','pending'))
    conn = get_db()
    conn.execute("UPDATE reports SET status=? WHERE id=?", (status, rid))
    conn.commit(); conn.close()
    return jsonify({'success':True})

# ─── ADMIN CHANGE PASSWORD ───────────────────────────────────────────────────

@app.route('/api/admin/change-password', methods=['POST'])
@admin_required
def change_password():
    d = request.get_json(force=True, silent=True)
    if not d:
        return jsonify({'error': 'No data received'}), 400
    current = d.get('current_password', '').strip()
    new_pwd = d.get('new_password', '').strip()
    if not current or not new_pwd:
        return jsonify({'error': 'Both fields are required'}), 400
    if len(new_pwd) < 4:
        return jsonify({'error': 'Password must be at least 4 characters'}), 400

    current_hash = hashlib.sha256(current.encode()).hexdigest()
    new_hash     = hashlib.sha256(new_pwd.encode()).hexdigest()

    # Get username from request body, session, or default to 'admin'
    username = d.get('username', '').strip() or session.get('admin_username', 'admin')

    conn = get_db()
    # Try matching by username + password first, then just by password
    admin = conn.execute(
        "SELECT * FROM admins WHERE username=? AND password=?", (username, current_hash)
    ).fetchone()
    if not admin:
        # Fallback: match any admin with that password
        admin = conn.execute(
            "SELECT * FROM admins WHERE password=?", (current_hash,)
        ).fetchone()
    if not admin:
        conn.close()
        return jsonify({'error': 'Current password is incorrect'}), 401
    # Update that admin's password
    conn.execute("UPDATE admins SET password=? WHERE id=?", (new_hash, admin['id']))
    conn.commit()
    conn.close()
    return jsonify({'success': True, 'message': 'Password updated successfully'})

# ─── ADMIN STATS ──────────────────────────────────────────────────────────────

@app.route('/api/admin/stats', methods=['GET'])
@admin_required
def admin_stats():
    conn = get_db()
    return jsonify({
        'total_blackspots': conn.execute("SELECT COUNT(*) FROM blackspots WHERE approved=1").fetchone()[0],
        'pending_suggestions': conn.execute("SELECT COUNT(*) FROM blackspots WHERE approved=0 AND suggested_by IS NOT NULL").fetchone()[0],
        'pending_reports': conn.execute("SELECT COUNT(*) FROM reports WHERE status='pending'").fetchone()[0],
        'total_users': conn.execute("SELECT COUNT(*) FROM users").fetchone()[0],
        'total_reports': conn.execute("SELECT COUNT(*) FROM reports").fetchone()[0],
    })

if __name__ == '__main__':
    init_db()
    migrate_db()
    app.run(debug=True, port=5000)