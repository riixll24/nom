import os
import sqlite3
import uuid
import math
import base64
import json
import mimetypes
from datetime import datetime
from functools import wraps
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, jsonify, g
)

app = Flask(__name__)
app.secret_key = 'nomu-secret-key-2025'
app.config['UPLOAD_FOLDER'] = os.path.join(app.static_folder, 'uploads')
app.config['RESULTS_FOLDER'] = os.path.join(app.static_folder, 'results')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['DATABASE'] = os.path.join(os.path.dirname(__file__), 'nomu.db')

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp'}

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['RESULTS_FOLDER'], exist_ok=True)

# ─── YOLO Model ───
model = None
model_loaded = False

def load_model():
    global model, model_loaded
    if model_loaded:
        return model
    model_loaded = True
    try:
        from ultralytics import YOLO
        model_path = os.path.join(os.path.dirname(__file__), 'best.pt')
        if os.path.exists(model_path):
            model = YOLO(model_path)
            print("✅ YOLO model loaded successfully")
        else:
            print("⚠️ best.pt not found - AI prediction will not work")
    except Exception as e:
        print(f"⚠️ Could not load YOLO model: {e}")
    return model

def get_model():
    global model
    if model is None:
        return load_model()
    return model

# ─── Database ───
def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(app.config['DATABASE'])
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(app.config['DATABASE'])
    db.executescript('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            phone TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('farmer','volunteer')),
            location TEXT DEFAULT '',
            skills TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS harvest_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            crop TEXT NOT NULL,
            harvest_date TEXT NOT NULL,
            location TEXT NOT NULL,
            volunteers_needed INTEGER DEFAULT 1,
            reward TEXT DEFAULT '',
            description TEXT DEFAULT '',
            image TEXT DEFAULT '',
            status TEXT DEFAULT 'مفتوح',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farmer_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS applications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            request_id INTEGER NOT NULL,
            volunteer_id INTEGER NOT NULL,
            status TEXT DEFAULT 'قيد الانتظار',
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (request_id) REFERENCES harvest_requests(id),
            FOREIGN KEY (volunteer_id) REFERENCES users(id),
            UNIQUE(request_id, volunteer_id)
        );

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender_id INTEGER NOT NULL,
            receiver_id INTEGER NOT NULL,
            request_id INTEGER,
            content TEXT NOT NULL,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sender_id) REFERENCES users(id),
            FOREIGN KEY (receiver_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            rater_id INTEGER NOT NULL,
            rated_id INTEGER NOT NULL,
            request_id INTEGER NOT NULL,
            score INTEGER NOT NULL CHECK(score BETWEEN 1 AND 5),
            comment TEXT DEFAULT '',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (rater_id) REFERENCES users(id),
            FOREIGN KEY (rated_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS predictions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            farmer_id INTEGER NOT NULL,
            image_path TEXT NOT NULL,
            result_path TEXT,
            fruit_count INTEGER DEFAULT 0,
            estimated_yield REAL DEFAULT 0,
            volunteers_recommended INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (farmer_id) REFERENCES users(id)
        );
    ''')
    # Seed demo data
    cur = db.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        pw = generate_password_hash('123456')
        cur.execute("INSERT INTO users (name,email,password,phone,role,location) VALUES (?,?,?,?,?,?)",
                    ('المزارع خالد','farmer@nomu.com',pw,'0501234567','farmer','الأحساء'))
        cur.execute("INSERT INTO users (name,email,password,phone,role,skills) VALUES (?,?,?,?,?,?)",
                    ('اسماء احمد','volunteer@nomu.com',pw,'0559876543','volunteer','قطف التمور، إزالة الأعشاب'))
        farmer_id = 1
        db.commit()
    # Migration: add image column if missing
    try:
        db.execute("SELECT image FROM harvest_requests LIMIT 1")
    except sqlite3.OperationalError:
        db.execute("ALTER TABLE harvest_requests ADD COLUMN image TEXT DEFAULT ''")
        db.commit()
    db.close()

# ─── Auth helpers ───
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            flash('يرجى تسجيل الدخول أولاً', 'error')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def farmer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'farmer':
            flash('هذه الصفحة للمزارعين فقط', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def volunteer_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if session.get('role') != 'volunteer':
            flash('هذه الصفحة للمتطوعين فقط', 'error')
            return redirect(url_for('home'))
        return f(*args, **kwargs)
    return decorated

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_user():
    if 'user_id' in session:
        db = get_db()
        return db.execute("SELECT * FROM users WHERE id=?", (session['user_id'],)).fetchone()
    return None

@app.context_processor
def inject_user():
    return dict(current_user=get_user())

# ─── Public Routes ───
@app.route('/')
def home():
    user = get_user()
    db = get_db()
    latest = db.execute("""
        SELECT hr.*, u.name as farmer_name, u.location as farmer_location
        FROM harvest_requests hr JOIN users u ON hr.farmer_id=u.id
        WHERE hr.status='مفتوح' ORDER BY hr.created_at DESC LIMIT 6
    """).fetchall()
    if user:
        if user['role'] == 'farmer':
            return render_template('farmer_home.html', latest_opportunities=latest)
        else:
            return render_template('volunteer_home.html', latest_opportunities=latest)
    return render_template('home.html', latest_opportunities=latest)

@app.route('/how-it-works')
def how_it_works():
    return render_template('how_it_works.html')

@app.route('/about')
def about():
    return render_template('about.html')

@app.route('/opportunities')
def opportunities():
    db = get_db()
    requests = db.execute("""
        SELECT hr.*, u.name as farmer_name, u.location as farmer_location,
        (SELECT COUNT(*) FROM applications WHERE request_id=hr.id) as applicant_count
        FROM harvest_requests hr JOIN users u ON hr.farmer_id=u.id
        WHERE hr.status='مفتوح' ORDER BY hr.created_at DESC
    """).fetchall()
    return render_template('opportunities.html', requests=requests)

# ─── Auth Routes ───
@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if user and check_password_hash(user['password'], password):
            session['user_id'] = user['id']
            session['role'] = user['role']
            session['name'] = user['name']
            if user['role'] == 'farmer':
                return redirect(url_for('farmer_dashboard'))
            else:
                return redirect(url_for('volunteer_dashboard'))
        flash('البريد الإلكتروني أو كلمة المرور غير صحيحة', 'error')
    return render_template('login.html')

@app.route('/login-as/<role>')
def login_as(role):
    db = get_db()
    if role == 'farmer':
        user = db.execute("SELECT * FROM users WHERE role='farmer' LIMIT 1").fetchone()
    else:
        user = db.execute("SELECT * FROM users WHERE role='volunteer' LIMIT 1").fetchone()
    if user:
        session['user_id'] = user['id']
        session['role'] = user['role']
        session['name'] = user['name']
        if user['role'] == 'farmer':
            return redirect(url_for('farmer_dashboard'))
        else:
            return redirect(url_for('volunteer_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET','POST'])
def register():
    return render_template('register.html')

@app.route('/register/farmer', methods=['GET','POST'])
def register_farmer():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        location = request.form.get('location','').strip()
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        if not all([name, phone, email, password]):
            flash('يرجى ملء جميع الحقول المطلوبة', 'error')
            return render_template('register_farmer.html')
        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash('البريد الإلكتروني مستخدم بالفعل', 'error')
            return render_template('register_farmer.html')
        db.execute("INSERT INTO users (name,email,password,phone,role,location) VALUES (?,?,?,?,?,?)",
                   (name, email, generate_password_hash(password), phone, 'farmer', location))
        db.commit()
        flash('تم إنشاء حسابك بنجاح! يرجى تسجيل الدخول.', 'success')
        return redirect(url_for('login'))
    return render_template('register_farmer.html')

@app.route('/register/volunteer', methods=['GET','POST'])
def register_volunteer():
    if request.method == 'POST':
        name = request.form.get('name','').strip()
        phone = request.form.get('phone','').strip()
        skills = request.form.get('skills','').strip()
        email = request.form.get('email','').strip()
        password = request.form.get('password','')
        if not all([name, phone, email, password]):
            flash('يرجى ملء جميع الحقول المطلوبة', 'error')
            return render_template('register_volunteer.html')
        db = get_db()
        existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if existing:
            flash('البريد الإلكتروني مستخدم بالفعل', 'error')
            return render_template('register_volunteer.html')
        db.execute("INSERT INTO users (name,email,password,phone,role,skills) VALUES (?,?,?,?,?,?)",
                   (name, email, generate_password_hash(password), phone, 'volunteer', skills))
        db.commit()
        flash('تم إنشاء حسابك بنجاح! يرجى تسجيل الدخول.', 'success')
        return redirect(url_for('login'))
    return render_template('register_volunteer.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))

# ─── Farmer Routes ───
@app.route('/farmer/dashboard')
@login_required
@farmer_required
def farmer_dashboard():
    return render_template('farmer_dashboard.html')

@app.route('/farmer/requests')
@login_required
@farmer_required
def farmer_requests():
    db = get_db()
    requests = db.execute("""
        SELECT hr.*,
        (SELECT COUNT(*) FROM applications WHERE request_id=hr.id) as applicant_count
        FROM harvest_requests hr WHERE hr.farmer_id=? ORDER BY hr.created_at DESC
    """, (session['user_id'],)).fetchall()
    return render_template('farmer_requests.html', requests=requests)

@app.route('/farmer/new-request', methods=['GET','POST'])
@login_required
@farmer_required
def farmer_new_request():
    if request.method == 'POST':
        crop = request.form.get('crop','').strip()
        harvest_date = request.form.get('harvest_date','')
        volunteers_needed = request.form.get('volunteers_needed', 1, type=int)
        reward = request.form.get('reward','').strip()
        description = request.form.get('description','').strip()
        user = get_user()
        location = user['location'] if user else ''
        if not all([crop, harvest_date]):
            flash('يرجى ملء الحقول المطلوبة', 'error')
            return render_template('farmer_new_request.html')

        image_filename = ''
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                image_filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        db = get_db()
        db.execute("""INSERT INTO harvest_requests
            (farmer_id,crop,harvest_date,location,volunteers_needed,reward,description,image)
            VALUES (?,?,?,?,?,?,?,?)""",
            (session['user_id'], crop, harvest_date, location, volunteers_needed, reward, description, image_filename))
        db.commit()
        flash('تم نشر طلب الحصاد بنجاح!', 'success')
        return redirect(url_for('farmer_requests'))
    return render_template('farmer_new_request.html')

@app.route('/farmer/request/<int:rid>')
@login_required
@farmer_required
def farmer_request_detail(rid):
    db = get_db()
    req = db.execute("SELECT * FROM harvest_requests WHERE id=? AND farmer_id=?",
                     (rid, session['user_id'])).fetchone()
    if not req:
        flash('الطلب غير موجود', 'error')
        return redirect(url_for('farmer_requests'))
    applicants = db.execute("""
        SELECT a.*, u.name, u.phone, u.skills
        FROM applications a JOIN users u ON a.volunteer_id=u.id
        WHERE a.request_id=?
    """, (rid,)).fetchall()
    return render_template('farmer_request_detail.html', req=req, applicants=applicants)

@app.route('/farmer/application/<int:aid>/accept')
@login_required
@farmer_required
def accept_application(aid):
    db = get_db()
    app_row = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if app_row:
        db.execute("UPDATE applications SET status='مقبول' WHERE id=?", (aid,))
        db.commit()
        flash('تم قبول المتطوع', 'success')
    return redirect(url_for('farmer_request_detail', rid=app_row['request_id']))

@app.route('/farmer/application/<int:aid>/reject')
@login_required
@farmer_required
def reject_application(aid):
    db = get_db()
    app_row = db.execute("SELECT * FROM applications WHERE id=?", (aid,)).fetchone()
    if app_row:
        db.execute("UPDATE applications SET status='مرفوض' WHERE id=?", (aid,))
        db.commit()
        flash('تم رفض الطلب', 'success')
    return redirect(url_for('farmer_request_detail', rid=app_row['request_id']))

@app.route('/farmer/edit-request/<int:rid>', methods=['GET','POST'])
@login_required
@farmer_required
def farmer_edit_request(rid):
    db = get_db()
    req = db.execute("SELECT * FROM harvest_requests WHERE id=? AND farmer_id=?",
                     (rid, session['user_id'])).fetchone()
    if not req:
        flash('الطلب غير موجود', 'error')
        return redirect(url_for('farmer_requests'))

    if request.method == 'POST':
        crop = request.form.get('crop','').strip()
        harvest_date = request.form.get('harvest_date','')
        volunteers_needed = request.form.get('volunteers_needed', 1, type=int)
        reward = request.form.get('reward','').strip()
        description = request.form.get('description','').strip()
        if not all([crop, harvest_date]):
            flash('يرجى ملء الحقول المطلوبة', 'error')
            return render_template('farmer_edit_request.html', req=req)

        image_filename = req['image'] if 'image' in req.keys() else ''
        if 'image' in request.files:
            file = request.files['image']
            if file and file.filename and allowed_file(file.filename):
                image_filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], image_filename))

        db.execute("""UPDATE harvest_requests
            SET crop=?, harvest_date=?, volunteers_needed=?, reward=?, description=?, image=?
            WHERE id=? AND farmer_id=?""",
            (crop, harvest_date, volunteers_needed, reward, description, image_filename, rid, session['user_id']))
        db.commit()
        flash('تم تحديث الطلب بنجاح!', 'success')
        return redirect(url_for('farmer_requests'))

    return render_template('farmer_edit_request.html', req=req)

# ─── AI Prediction Route ───
CROP_CONFIG = {
    'olives': {
        'name_ar': 'زيتون',
        'label': 'olive',
        'class_aliases': ['olive', 'olives'],
        'avg_weight': 0.005,       # ~5g per olive
        'worker_capacity': 2000,   # olives per worker per day
        'color': (80, 120, 0),     # olive-green boxes
    },
    'figs': {
        'name_ar': 'تين',
        'label': 'fig',
        'class_aliases': ['fig', 'figs'],
        'avg_weight': 0.050,       # ~50g per fig fruit
        'worker_capacity': 400,    # figs per worker per day
        'color': (130, 60, 140),   # purple boxes
    }
}

# ─── OpenAI Vision verification ───
OPENAI_VISION_MODEL = os.environ.get('OPENAI_VISION_MODEL', 'gpt-4o-mini')

def verify_crop_with_vision(image_path, crop_type):
    """Ask an OpenAI vision model to confirm the fruit type and estimate maturity.

    Returns a dict: {matches: bool, maturity_en: str, maturity_ar: str, note_ar: str, error: str|None}.
    """
    result = {
        'matches': True,
        'maturity_en': '',
        'maturity_ar': '',
        'note_ar': '',
        'error': None,
    }

    api_key = os.environ.get('OPENAI_API_KEY')
    if not api_key:
        result['error'] = 'OPENAI_API_KEY غير مضبوط في بيئة التشغيل'
        return result

    expected = CROP_CONFIG[crop_type]['label']  # 'olive' or 'fig'
    expected_ar = CROP_CONFIG[crop_type]['name_ar']

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)

        mime, _ = mimetypes.guess_type(image_path)
        if not mime:
            mime = 'image/jpeg'
        with open(image_path, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode('ascii')
        data_url = f"data:{mime};base64,{b64}"

        system_prompt = (
            "You are an agronomy assistant. You will be given a photo and an expected fruit type. "
            "Decide if the photo's main subject is that fruit, and estimate the ripeness/maturity. "
            "Respond ONLY as minified JSON with keys: "
            "matches (boolean), maturity_en (one of: unripe, semi-ripe, ripe, overripe, unknown), "
            "maturity_ar (Arabic label: غير ناضج / نصف ناضج / ناضج / مفرط النضج / غير معروف), "
            "note_ar (short Arabic sentence, max 20 words, explaining what you see). "
            "If matches is false, still fill the other fields based on what you actually see."
        )
        user_text = f"Expected fruit: {expected} ({expected_ar}). Analyze the image."

        resp = client.chat.completions.create(
            model=OPENAI_VISION_MODEL,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": [
                    {"type": "text", "text": user_text},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ]},
            ],
        )
        content = resp.choices[0].message.content or '{}'
        data = json.loads(content)
        result['matches'] = bool(data.get('matches', False))
        result['maturity_en'] = str(data.get('maturity_en', '') or '').strip()
        result['maturity_ar'] = str(data.get('maturity_ar', '') or '').strip()
        result['note_ar'] = str(data.get('note_ar', '') or '').strip()
    except Exception as e:
        result['error'] = str(e)
        print(f"⚠️ Vision verification failed: {e}")

    return result


def filter_boxes_by_crop(results, crop_type):
    """Return only the boxes whose predicted class matches the selected crop."""
    config = CROP_CONFIG[crop_type]
    aliases = {a.lower() for a in config['class_aliases']}
    names = results[0].names  # {idx: class_name}
    matched = []
    for box in results[0].boxes:
        cls_idx = int(box.cls[0])
        cls_name = str(names.get(cls_idx, '')).lower()
        if cls_name in aliases:
            matched.append(box)
    return matched

def render_custom_result(image_path, boxes, crop_type):
    """Render detection results with the user-selected crop label."""
    import cv2

    config = CROP_CONFIG[crop_type]
    label = config['label']
    color = config['color']

    img = cv2.imread(image_path)

    for box in boxes:
        x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())
        conf = float(box.conf[0])
        # Draw bounding box
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        # Draw label with user-selected crop type
        txt = f"{label} {conf:.2f}"
        font_scale = 0.6
        thickness = 2
        (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
        cv2.rectangle(img, (x1, y1 - th - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(img, txt, (x1 + 2, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), thickness)

    return img

@app.route('/farmer/predict', methods=['GET','POST'])
@login_required
@farmer_required
def farmer_predict():
    if request.method == 'POST':
        if 'image' not in request.files:
            flash('يرجى رفع صورة', 'error')
            return render_template('farmer_predict.html')
        file = request.files['image']
        if file.filename == '' or not allowed_file(file.filename):
            flash('صيغة الملف غير مدعومة', 'error')
            return render_template('farmer_predict.html')

        crop_type = request.form.get('crop_type', 'olives')
        if crop_type not in CROP_CONFIG:
            crop_type = 'olives'
        config = CROP_CONFIG[crop_type]

        filename = str(uuid.uuid4()) + '.' + file.filename.rsplit('.', 1)[1].lower()
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)

        yolo = get_model()
        if yolo is None:
            flash('نموذج الذكاء الاصطناعي غير متاح حالياً', 'error')
            return render_template('farmer_predict.html')

        try:
            # Vision LLM check: verify crop type and estimate maturity
            vision = verify_crop_with_vision(filepath, crop_type)
            if vision['error']:
                flash(f"تعذر التحقق بالذكاء البصري: {vision['error']}", 'error')
                return render_template('farmer_predict.html')
            if not vision['matches']:
                flash(
                    f"❌ ثمرة خاطئة — هذه الصورة لا تحتوي على {config['name_ar']}. "
                    + (f"({vision['note_ar']})" if vision['note_ar'] else ''),
                    'error')
                return render_template('farmer_predict.html')

            # Low confidence to detect as many fruits as possible
            results = yolo(filepath, conf=0.10, iou=0.3)
            result_filename = 'result_' + filename
            result_path = os.path.join(app.config['RESULTS_FOLDER'], result_filename)

            # Only keep boxes whose class matches the selected crop (model has olive + fig classes)
            matched_boxes = filter_boxes_by_crop(results, crop_type)

            # Custom rendering with the correct crop label
            result_img = render_custom_result(filepath, matched_boxes, crop_type)
            import cv2
            cv2.imwrite(result_path, result_img)

            fruit_count = len(matched_boxes)
            estimated_yield = round(fruit_count * config['avg_weight'], 2)
            volunteers_recommended = max(1, math.ceil(fruit_count / config['worker_capacity']))

            db = get_db()
            db.execute("""INSERT INTO predictions
                (farmer_id, image_path, result_path, fruit_count, estimated_yield, volunteers_recommended)
                VALUES (?,?,?,?,?,?)""",
                (session['user_id'], filename, result_filename, fruit_count, estimated_yield, volunteers_recommended))
            db.commit()

            return render_template('farmer_predict_result.html',
                fruit_count=fruit_count,
                estimated_yield=estimated_yield,
                volunteers_recommended=volunteers_recommended,
                original_image=filename,
                result_image=result_filename,
                crop_name=config['name_ar'],
                maturity_ar=vision['maturity_ar'],
                maturity_en=vision['maturity_en'],
                vision_note=vision['note_ar'],
            )
        except Exception as e:
            print(f"❌ Prediction error: {e}")
            flash(f'حدث خطأ أثناء التحليل: {str(e)}', 'error')
            return render_template('farmer_predict.html')
    return render_template('farmer_predict.html')

# ─── Volunteer Routes ───
@app.route('/volunteer/dashboard')
@login_required
@volunteer_required
def volunteer_dashboard():
    return render_template('volunteer_dashboard.html')

@app.route('/volunteer/search')
@login_required
@volunteer_required
def volunteer_search():
    db = get_db()
    q = request.args.get('q', '')
    crop_filter = request.args.get('crop', '')
    date_filter = request.args.get('date', '')

    query = """
        SELECT hr.*, u.name as farmer_name, u.location as farmer_location,
        (SELECT COUNT(*) FROM applications WHERE request_id=hr.id) as applicant_count
        FROM harvest_requests hr JOIN users u ON hr.farmer_id=u.id
        WHERE hr.status='مفتوح'
    """
    params = []
    if q:
        query += " AND (hr.crop LIKE ? OR hr.location LIKE ? OR u.name LIKE ?)"
        params.extend([f'%{q}%', f'%{q}%', f'%{q}%'])
    if crop_filter:
        query += " AND hr.crop=?"
        params.append(crop_filter)
    if date_filter:
        query += " AND hr.harvest_date=?"
        params.append(date_filter)
    query += " ORDER BY hr.created_at DESC"
    requests = db.execute(query, params).fetchall()

    crops = db.execute("SELECT DISTINCT crop FROM harvest_requests WHERE status='مفتوح'").fetchall()
    return render_template('volunteer_search.html', requests=requests, crops=crops,
                           q=q, crop_filter=crop_filter, date_filter=date_filter)

@app.route('/volunteer/opportunity/<int:rid>')
@login_required
@volunteer_required
def volunteer_opportunity_detail(rid):
    db = get_db()
    req = db.execute("""
        SELECT hr.*, u.name as farmer_name, u.phone as farmer_phone,
        u.location as farmer_location
        FROM harvest_requests hr JOIN users u ON hr.farmer_id=u.id
        WHERE hr.id=?
    """, (rid,)).fetchone()
    if not req:
        flash('الفرصة غير موجودة', 'error')
        return redirect(url_for('volunteer_search'))

    already_applied = db.execute(
        "SELECT * FROM applications WHERE request_id=? AND volunteer_id=?",
        (rid, session['user_id'])).fetchone()

    ratings = db.execute("""
        SELECT AVG(score) as avg_score, COUNT(*) as count
        FROM ratings WHERE rated_id=?
    """, (req['farmer_id'],)).fetchone()

    related = db.execute("""
        SELECT hr.*, u.name as farmer_name
        FROM harvest_requests hr JOIN users u ON hr.farmer_id=u.id
        WHERE hr.id!=? AND hr.status='مفتوح' LIMIT 3
    """, (rid,)).fetchall()

    return render_template('volunteer_opportunity_detail.html',
        req=req, already_applied=already_applied, ratings=ratings, related=related)

@app.route('/volunteer/apply/<int:rid>')
@login_required
@volunteer_required
def volunteer_apply(rid):
    db = get_db()
    existing = db.execute("SELECT * FROM applications WHERE request_id=? AND volunteer_id=?",
                          (rid, session['user_id'])).fetchone()
    if existing:
        flash('لقد تقدمت بالفعل لهذه الفرصة', 'info')
    else:
        db.execute("INSERT INTO applications (request_id, volunteer_id) VALUES (?,?)",
                   (rid, session['user_id']))
        db.commit()
        flash('تم إرسال طلبك بنجاح! سيتم إعلامك برد المزارع.', 'success')
    return redirect(url_for('volunteer_opportunity_detail', rid=rid))

@app.route('/volunteer/my-requests')
@login_required
@volunteer_required
def volunteer_my_requests():
    db = get_db()
    apps = db.execute("""
        SELECT a.*, hr.crop, hr.harvest_date, hr.location, hr.farmer_id,
        u.name as farmer_name, u.phone as farmer_phone
        FROM applications a
        JOIN harvest_requests hr ON a.request_id=hr.id
        JOIN users u ON hr.farmer_id=u.id
        WHERE a.volunteer_id=? ORDER BY a.applied_at DESC
    """, (session['user_id'],)).fetchall()
    return render_template('volunteer_my_requests.html', apps=apps)

# ─── Messaging Routes ───
@app.route('/chat/<int:other_id>/<int:request_id>', methods=['GET','POST'])
@login_required
def chat(other_id, request_id):
    db = get_db()
    if request.method == 'POST':
        content = request.form.get('content','').strip()
        if content:
            db.execute("INSERT INTO messages (sender_id, receiver_id, request_id, content) VALUES (?,?,?,?)",
                       (session['user_id'], other_id, request_id, content))
            db.commit()
    messages = db.execute("""
        SELECT m.*, u.name as sender_name
        FROM messages m JOIN users u ON m.sender_id=u.id
        WHERE m.request_id=? AND
        ((m.sender_id=? AND m.receiver_id=?) OR (m.sender_id=? AND m.receiver_id=?))
        ORDER BY m.sent_at ASC
    """, (request_id, session['user_id'], other_id, other_id, session['user_id'])).fetchall()

    other_user = db.execute("SELECT * FROM users WHERE id=?", (other_id,)).fetchone()
    req = db.execute("SELECT * FROM harvest_requests WHERE id=?", (request_id,)).fetchone()
    return render_template('chat.html', messages=messages, other_user=other_user, req=req)

# ─── Rating Route ───
@app.route('/rate/<int:user_id>/<int:request_id>', methods=['POST'])
@login_required
def rate_user(user_id, request_id):
    score = request.form.get('score', 0, type=int)
    comment = request.form.get('comment', '')
    if 1 <= score <= 5:
        db = get_db()
        existing = db.execute("SELECT * FROM ratings WHERE rater_id=? AND rated_id=? AND request_id=?",
                              (session['user_id'], user_id, request_id)).fetchone()
        if not existing:
            db.execute("INSERT INTO ratings (rater_id, rated_id, request_id, score, comment) VALUES (?,?,?,?,?)",
                       (session['user_id'], user_id, request_id, score, comment))
            db.commit()
            flash('تم إرسال التقييم بنجاح', 'success')
    return redirect(request.referrer or url_for('home'))


if __name__ == '__main__':
    init_db()
    print("🌱 Nomu Platform Starting...")
    print("📍 http://127.0.0.1:5000")
    print("⏳ Loading AI model...")
    load_model()
    print("✅ Ready!")
    app.run(debug=True, port=5000, use_reloader=False)
