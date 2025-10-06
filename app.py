from flask import Flask, render_template, redirect, url_for, flash, request, session, jsonify, make_response
from flask_pymongo import PyMongo
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from bson import ObjectId
import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask_mail import Mail, Message
import secrets
import string
import certifi
from threading import Lock
from email_client import EmailClient

# Load environment variables from this file's directory to ensure nested .env is found
_dotenv_path = os.path.join(os.path.dirname(__file__), '.env')
load_dotenv(_dotenv_path)

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY') or 'dev-key-for-testing'

# MongoDB configuration
mongo_uri = os.environ.get('MONGO_URI')
# Ensure the connection string includes the database name
if 'hostel' not in mongo_uri:
    if mongo_uri.endswith('?'):
        mongo_uri = mongo_uri + 'retryWrites=true&w=majority&appName=Cluster0'
    mongo_uri = mongo_uri.replace('?', '/hostel?', 1) if '?' in mongo_uri else mongo_uri + '/hostel'

app.config["MONGO_URI"] = mongo_uri
print(f"Connecting to MongoDB at: {mongo_uri.split('@')[-1]}")  # Log the server address (without credentials)
mongo = PyMongo(app, tlsCAFile=certifi.where())

# Create indexes for better performance
def create_indexes():
    with app.app_context():
        mongo.db.users.create_index([('email', 1)], unique=True)
        mongo.db.rooms.create_index([('room_number', 1)], unique=True)
        # Library indexes
        mongo.db.books.create_index([('book_id', 1)], unique=True)
        mongo.db.books.create_index([('title', 1)])
        mongo.db.books.create_index([('author', 1)])
        mongo.db.books_issued.create_index([('book_id', 1)])
        mongo.db.books_issued.create_index([('student_id', 1)])
        mongo.db.books_issued.create_index([('issued_at', -1)])
        # Placements indexes
        if 'placements' in mongo.db.list_collection_names():
            pass
        mongo.db.placements.create_index([('student_name', 1)])
        mongo.db.placements.create_index([('company', 1)])
        mongo.db.placements.create_index([('year', -1)])
        # Feedback (Query & Feedback) indexes
        mongo.db.feedback.create_index([('status', 1)])
        mongo.db.feedback.create_index([('created_at', -1)])
        mongo.db.feedback.create_index([('reporter_name', 1)])

# Custom template filter for formatting datetimes
@app.template_filter('datetimeformat')
def datetimeformat(value, format='%d-%m-%Y'):
    if value is None:
        return ""
    if isinstance(value, str):
        # Try to parse the string to datetime if it's not already a datetime object
        try:
            from datetime import datetime
            value = datetime.strptime(value, '%Y-%m-%dT%H:%M:%S.%f')
        except (ValueError, TypeError):
            try:
                value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
            except (ValueError, TypeError):
                return value
    return value.strftime(format)

# Initialize indexes lazily on first request (Flask 2.x/3.x compatible)
_indexes_initialized = False
_indexes_lock = Lock()

def _init_indexes_once():
    global _indexes_initialized
    if _indexes_initialized:
        return
    with _indexes_lock:
        if _indexes_initialized:
            return
        try:
            create_indexes()
            _indexes_initialized = True
        except Exception as e:
            print(f"Warning: failed to create MongoDB indexes on startup: {e}")

@app.before_request
def _ensure_indexes_before_request():
    _init_indexes_once()

# Email configuration
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.environ.get('MAIL_PASSWORD')
mail = Mail(app)
email_client = EmailClient(app, mail)
print(f"Email provider: {email_client.provider}")

# Login Manager
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# User class for Flask-Login
class User(UserMixin):
    def __init__(self, user_data):
        self.user_data = user_data
        self.id = str(user_data['_id'])
        self.role = user_data.get('role', 'student')
    
    def get_id(self):
        return str(self.user_data['_id'])

@login_manager.user_loader
def load_user(user_id):
    user_data = mongo.db.users.find_one({'_id': ObjectId(user_id)})
    if not user_data:
        return None
    return User(user_data)

def generate_random_password(length=8):
    """Generate a random password"""
    characters = string.ascii_letters + string.digits + string.punctuation
    return ''.join(secrets.choice(characters) for _ in range(length))

def send_credentials_email(email, username, password):
    """Send login credentials to the user's email"""
    subject = 'Your Hostel Management System Credentials'
    body = f'''
Welcome to Hostel Management System!

Your login credentials:
Username: {username}
Password: {password}

Please change your password after first login.

Regards,
Hostel Management Team
'''
    # Use bulk-capable client (Brevo if configured, else Flask-Mail fallback)
    email_client.send_single(email, subject, body)

def _generate_otp(length=6):
    """Generate a numeric OTP code of given length."""
    digits = string.digits
    return ''.join(secrets.choice(digits) for _ in range(length))

def send_reset_otp_email(email, otp):
    """Send password reset OTP to the user's email.
    Includes a short unique token in subject to avoid threading collisions.
    """
    uniq = secrets.token_hex(4)
    subject = f"Your Hostel MS Password Reset Code [{uniq}]"
    body = f"""
You requested to reset your password for Hostel Management System.

Your OTP code is: {otp}
This code expires in 10 minutes.

If you did not request this, please ignore this email.
"""
    email_client.send_single(email, subject, body)

# Authentication Routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
        
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        remember = True if request.form.get('remember') else False
        
        user_data = mongo.db.users.find_one({'email': email})
        
        if not user_data or not check_password_hash(user_data['password'], password):
            flash('Invalid email or password', 'error')
            return redirect(url_for('login'))
            
        user = User(user_data)
        login_user(user, remember=remember)
        
        if user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif user.role == 'warden':
            return redirect(url_for('warden_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
            
    return render_template('auth/login.html')

# -----------------------------
# Forgot / Reset Password (OTP) 
# -----------------------------

@app.route('/forgot-password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        if not email:
            flash('Please enter your email address', 'error')
            return redirect(url_for('forgot_password'))
        user = mongo.db.users.find_one({'email': email})
        if not user:
            # Still avoid revealing whether email exists; no flash shown
            return redirect(url_for('forgot_password'))
        # Generate and store OTP
        otp = _generate_otp(6)
        expires_at = datetime.utcnow() + timedelta(minutes=10)
        mongo.db.password_resets.delete_many({'user_id': user['_id']})
        mongo.db.password_resets.insert_one({
            'user_id': user['_id'],
            'email': email,
            'otp': otp,
            'attempts': 0,
            'expires_at': expires_at,
            'created_at': datetime.utcnow()
        })
        try:
            send_reset_otp_email(email, otp)
        except Exception as e:
            print(f"Error sending reset OTP email: {e}")
        return redirect(url_for('reset_password', email=email))
    return render_template('auth/forgot_password.html')

@app.route('/reset-password', methods=['GET', 'POST'])
def reset_password():
    email = (request.values.get('email') or '').strip().lower()
    if request.method == 'POST':
        otp = (request.form.get('otp') or '').strip()
        new_password = request.form.get('new_password') or ''
        confirm_password = request.form.get('confirm_password') or ''
        email = (request.form.get('email') or '').strip().lower() or email

        if not email or not otp:
            flash('Email and OTP are required', 'error')
            return redirect(url_for('reset_password', email=email))
        if len(new_password) < 6 or new_password != confirm_password:
            flash('Passwords must match and be at least 6 characters', 'error')
            return redirect(url_for('reset_password', email=email))

        user = mongo.db.users.find_one({'email': email})
        if not user:
            flash('Invalid OTP or expired', 'error')
            return redirect(url_for('reset_password', email=email))

        pr = mongo.db.password_resets.find_one({'user_id': user['_id']})
        if not pr:
            flash('Invalid OTP or expired', 'error')
            return redirect(url_for('reset_password', email=email))
        # Validate expiry and attempts
        if pr.get('expires_at') and pr['expires_at'] < datetime.utcnow():
            mongo.db.password_resets.delete_one({'_id': pr['_id']})
            flash('OTP expired. Please request a new one.', 'error')
            return redirect(url_for('forgot_password'))
        if pr.get('attempts', 0) >= 5:
            mongo.db.password_resets.delete_one({'_id': pr['_id']})
            flash('Too many attempts. Please request a new OTP.', 'error')
            return redirect(url_for('forgot_password'))
        if pr['otp'] != otp:
            mongo.db.password_resets.update_one({'_id': pr['_id']}, {'$inc': {'attempts': 1}})
            flash('Invalid OTP', 'error')
            return redirect(url_for('reset_password', email=email))

        # Update password
        hashed = generate_password_hash(new_password, method='sha256')
        mongo.db.users.update_one({'_id': user['_id']}, {'$set': {'password': hashed}})
        mongo.db.password_resets.delete_one({'_id': pr['_id']})
        flash('Password has been reset. You can now log in.', 'success')
        return redirect(url_for('login'))

    return render_template('auth/reset_password.html', email=email)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

# Dashboard Routes
@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_dashboard'))
        elif current_user.role == 'warden':
            return redirect(url_for('warden_dashboard'))
        else:
            return redirect(url_for('student_dashboard'))
    return render_template('index.html')

# -----------------------------
# SEO: robots.txt and sitemap.xml
# -----------------------------

@app.route('/robots.txt')
def robots_txt():
    base = request.url_root.rstrip('/') if request else ''
    lines = [
        'User-agent: *',
        # Block private areas and APIs
        'Disallow: /admin/',
        'Disallow: /warden/',
        'Disallow: /student/',
        'Disallow: /api/',
        # Allow these explicitly (optional)
        'Allow: /',
        f'Sitemap: {base}/sitemap.xml'
    ]
    resp = make_response('\n'.join(lines) + '\n')
    resp.headers['Content-Type'] = 'text/plain; charset=utf-8'
    return resp

@app.route('/sitemap.xml')
def sitemap_xml():
    # Public routes to include in sitemap
    pages = [
        ('index', {}),
        ('login', {}),
        ('forgot_password', {}),
    ]
    urlset = []
    for endpoint, params in pages:
        try:
            loc = url_for(endpoint, _external=True, **params)
        except Exception:
            # Skip if route missing
            continue
        urlset.append(f"""
    <url>
      <loc>{loc}</loc>
      <changefreq>weekly</changefreq>
      <priority>0.8</priority>
    </url>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{''.join(urlset)}
</urlset>
"""
    resp = make_response(xml)
    resp.headers['Content-Type'] = 'application/xml; charset=utf-8'
    return resp

@app.route('/favicon.ico')
def favicon():
    return redirect(url_for('static', filename='images/favicon.png'))

@app.route('/admin/dashboard')
@login_required
def admin_dashboard():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    
    try:
        # Initialize stats with default values
        stats = {
            'students_count': 0,
            'rooms_count': 0,
            'books_count': 0,
            'pending_feedback': 0
        }
        
        # Safely get counts, handling cases where collections might not exist
        if 'users' in mongo.db.list_collection_names():
            stats['students_count'] = mongo.db.users.count_documents({'role': 'student'})
            
        if 'rooms' in mongo.db.list_collection_names():
            stats['rooms_count'] = mongo.db.rooms.count_documents({})
            
        if 'books' in mongo.db.list_collection_names():
            stats['books_count'] = mongo.db.books.count_documents({})
            
        if 'feedback' in mongo.db.list_collection_names():
            stats['pending_feedback'] = mongo.db.feedback.count_documents({'status': 'pending'})
        
        # Get recent activities (you can customize this query based on your activity log)
        recent_activities = []
        
        return render_template('admin/dashboard.html', 
                            stats=stats, 
                            recent_activities=recent_activities)
    except Exception as e:
        print(f"Error in admin_dashboard: {str(e)}")
        # Return minimal data to prevent template errors
        return render_template('admin/dashboard.html',
                            stats=stats,
                            recent_activities=[])

@app.route('/warden/dashboard')
@login_required
def warden_dashboard():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))
    
    # Get statistics for warden dashboard
    stats = {
        'students_count': mongo.db.users.count_documents({'role': 'student'}),
        'total_rooms': mongo.db.rooms.count_documents({}),
        # Consider a room occupied when current_occupancy >= capacity (independent of stored status)
        'occupied_rooms': mongo.db.rooms.count_documents({
            '$expr': {
                '$gte': [
                    { '$ifNull': [ '$current_occupancy', 0 ] },
                    { '$ifNull': [ '$capacity', 0 ] }
                ]
            }
        }),
        'books_count': mongo.db.books.count_documents({}),
        'new_feedback': mongo.db.feedback.count_documents({'status': {'$ne': 'resolved'}})
    }
    
    # Get recent leave applications
    leave_applications = list(mongo.db.leave_applications
        .find({'status': 'pending'})
        .sort('applied_date', -1)
        .limit(5))
    
    # Get recent notices
    notices = list(mongo.db.notices
        .find()
        .sort('date', -1)
        .limit(3))
    
    # Sample attendance stats (replace with actual data from your database)
    attendance_stats = {
        'present_percentage': 75,
        'leave_percentage': 15,
        'absent_percentage': 10
    }
    
    return render_template('warden/dashboard.html', stats=stats)

@app.route('/student/dashboard')
@login_required
def student_dashboard():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    
    # Get room mates if room is assigned
    room_mates = []
    if current_user.user_data.get('room_number'):
        room_mates = list(mongo.db.users.find({
            'room_number': current_user.user_data['room_number'],
            '_id': {'$ne': ObjectId(current_user.id)},
            'role': 'student'
        }))
    
    # Get borrowed books
    borrowed_books = list(mongo.db.books_issued.find({
        'student_id': ObjectId(current_user.id),
        'status': {'$in': ['issued', 'overdue']}
    }))
    
    # Get recent notices
    notices = list(mongo.db.notices
        .find()
        .sort('date', -1)
        .limit(5))
    
    return render_template('student/dashboard.html',
                         room_mates=room_mates,
                         borrowed_books=borrowed_books,
                         notices=notices)

@app.route('/student/room-members')
@login_required
def student_room_members():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    # If no room assigned, inform and redirect back to dashboard
    rn = current_user.user_data.get('room_number')
    if not rn:
        flash('You have not been assigned a room yet.', 'warning')
        return redirect(url_for('student_dashboard'))
    # Fetch roommates (excluding current user)
    mates = list(mongo.db.users.find({
        'role': 'student',
        'room_number': rn,
        '_id': {'$ne': ObjectId(current_user.id)}
    }).sort('name', 1))
    # Fetch room details for capacity if available
    room = mongo.db.rooms.find_one({'room_number': rn}) or {}
    return render_template('student/room_members.html', room_mates=mates, room=room)

@app.route('/student/books')
@login_required
def student_books():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    books = list(mongo.db.books.find().sort('title', 1))
    # Active borrows for this student
    current_txs = list(mongo.db.books_issued.find({
        'student_id': ObjectId(current_user.id),
        'status': {'$in': ['issued', 'overdue']}
    }).sort('issued_at', -1))
    # Past transactions (returned)
    past_txs = list(mongo.db.books_issued.find({
        'student_id': ObjectId(current_user.id),
        'status': 'returned'
    }).sort('returned_at', -1))
    return render_template('student/books.html', books=books, current_transactions=current_txs, past_transactions=past_txs)

# -----------------------------
# Query & Feedback (Student)
# -----------------------------

@app.route('/student/feedback', methods=['GET'])
@login_required
def student_feedback():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    # Pagination params
    try:
        page = int(request.args.get('page', 1) or 1)
    except Exception:
        page = 1
    page = page if page > 0 else 1
    per_page = 10
    skip = (page - 1) * per_page

    # Fetch recent feedback items from all users, newest first
    filt = {}
    total_count = mongo.db.feedback.count_documents(filt)
    total_pages = (total_count + per_page - 1) // per_page if total_count else 1
    cursor = mongo.db.feedback.find(filt).sort('created_at', -1).skip(skip).limit(per_page)
    items = list(cursor)
    for it in items:
        it['_id'] = str(it['_id'])
        if isinstance(it.get('reporter_id'), ObjectId):
            it['reporter_id'] = str(it['reporter_id'])
    categories = ['Maintenance', 'Room Allocation', 'Mess', 'Library', 'Disciplinary', 'Other']
    return render_template(
        'student/feedback.html',
        items=items,
        categories=categories,
        page=page,
        per_page=per_page,
        total_pages=total_pages,
        total_count=total_count
    )

@app.route('/student/feedback/add', methods=['POST'])
@login_required
def student_add_feedback():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    try:
        title = (request.form.get('title') or '').strip()
        category = (request.form.get('category') or '').strip()
        description = (request.form.get('description') or '').strip()
        if not title or not description:
            flash('Title and description are required', 'error')
            return redirect(url_for('student_feedback'))
        doc = {
            'title': title,
            'category': category or 'Other',
            'description': description,
            'reporter_name': current_user.user_data.get('name'),
            'reporter_id': ObjectId(current_user.id),
            'status': 'open',
            'resolution_notes': '',
            'created_at': datetime.utcnow(),
            'resolved_at': None
        }
        mongo.db.feedback.insert_one(doc)
        flash('Your query/feedback has been submitted', 'success')
    except Exception as e:
        print(f"Error student_add_feedback: {e}")
        flash('Failed to submit feedback', 'error')
    return redirect(url_for('student_feedback'))

# -----------------------------
# Placements (Student)
# -----------------------------

@app.route('/student/placements')
@login_required
def student_placements():
    if current_user.role != 'student':
        flash('Access denied: Student privileges required', 'error')
        return redirect(url_for('index'))
    # Search and pagination
    q = (request.args.get('q') or '').strip()
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    per_page = 10

    # Build MongoDB filter
    query = {}
    if q:
        regex = {'$regex': q, '$options': 'i'}
        or_clauses = [
            {'student_name': regex},
            {'company': regex},
            {'role': regex},
            {'location': regex},
        ]
        # If q looks like a year, also match exact year
        try:
            q_year = int(q)
            or_clauses.append({'year': q_year})
        except Exception:
            pass
        query = {'$or': or_clauses}

    total_count = mongo.db.placements.count_documents(query)
    skip = (page - 1) * per_page
    cursor = (mongo.db.placements
              .find(query)
              .sort([('year', -1), ('package_lpa', -1), ('student_name', 1)])
              .skip(skip)
              .limit(per_page))
    placements = list(cursor)
    for p in placements:
        p['_id'] = str(p['_id'])

    total_pages = (total_count + per_page - 1) // per_page
    return render_template('student/placements.html',
                           placements=placements,
                           q=q,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages)

# -----------------------------
# Placements (Warden - view)
# -----------------------------
@app.route('/warden/placements')
@login_required
def warden_placements():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))
    # Search and pagination (same as student view)
    q = (request.args.get('q') or '').strip()
    try:
        page = int(request.args.get('page', 1))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    per_page = 10

    # Build MongoDB filter
    query = {}
    if q:
        regex = {'$regex': q, '$options': 'i'}
        or_clauses = [
            {'student_name': regex},
            {'company': regex},
            {'role': regex},
            {'location': regex}
        ]
        # If q is a 4-digit year, include it
        try:
            yr = int(q)
            if 1900 <= yr <= 2100:
                or_clauses.append({'year': yr})
        except Exception:
            pass
        query = {'$or': or_clauses}

    total_count = mongo.db.placements.count_documents(query)
    total_pages = (total_count + per_page - 1) // per_page
    skip = (page - 1) * per_page

    cursor = (mongo.db.placements.find(query)
              .sort([('year', -1), ('package_lpa', -1), ('student_name', 1)])
              .skip(skip)
              .limit(per_page))
    placements = list(cursor)
    for p in placements:
        p['_id'] = str(p['_id'])

    return render_template('warden/placements.html',
                           placements=placements,
                           q=q,
                           page=page,
                           per_page=per_page,
                           total_count=total_count,
                           total_pages=total_pages)

# API Routes
@app.route('/api/rooms', methods=['GET'])
@login_required
def get_rooms():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    rooms = list(mongo.db.rooms.find())
    # Convert ObjectId to string for JSON serialization
    for room in rooms:
        room['_id'] = str(room['_id'])
    return jsonify(rooms)

@app.route('/api/rooms/<room_id>', methods=['GET'])
@login_required
def get_room(room_id):
    if current_user.role not in ['admin', 'warden']:
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        room = mongo.db.rooms.find_one({'_id': ObjectId(room_id)})
        if not room:
            return jsonify({'error': 'Room not found'}), 404
            
        room['_id'] = str(room['_id'])
        return jsonify(room)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/warden/rooms')
@login_required
def warden_rooms():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))
    rooms = list(mongo.db.rooms.find().sort('room_number', 1))
    for room in rooms:
        room['_id'] = str(room['_id'])
    return render_template('warden/rooms.html', rooms=rooms)

@app.route('/api/rooms', methods=['POST'])
@login_required
def add_room():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        data = None
        if request.is_json:
            data = request.get_json(silent=True)
        if not data:
            # Fallback to form data (HTML form submission)
            data = {
                'room_number': request.form.get('room_number'),
                'floor': request.form.get('floor'),
                'room_type': request.form.get('room_type'),
                'capacity': request.form.get('capacity'),
                'rent': request.form.get('rent'),
                'description': request.form.get('description')
            }
        
        # Validate required fields (minimal)
        required_fields = ['room_number', 'room_type']
        for field in required_fields:
            if not data.get(field):
                # If this was a form submission, flash + redirect
                if not request.is_json:
                    flash(f'Missing required field: {field}', 'error')
                    return redirect(url_for('admin_rooms'))
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Check if room number already exists
        if mongo.db.rooms.find_one({'room_number': data['room_number']}):
            if not request.is_json:
                flash('Room number already exists', 'error')
                return redirect(url_for('admin_rooms'))
            return jsonify({'error': 'Room number already exists'}), 400
        
        # Determine optional numeric fields with defaults
        capacity_val = None
        rent_val = None
        if data.get('capacity') is not None and data.get('capacity') != '':
            try:
                capacity_val = int(data['capacity'])
            except Exception:
                if not request.is_json:
                    flash('Capacity must be an integer', 'error')
                    return redirect(url_for('admin_rooms'))
                return jsonify({'error': 'Invalid capacity'}), 400
        if data.get('rent') is not None and data.get('rent') != '':
            try:
                rent_val = float(data['rent'])
            except Exception:
                if not request.is_json:
                    flash('Rent must be a number', 'error')
                    return redirect(url_for('admin_rooms'))
                return jsonify({'error': 'Invalid rent'}), 400

        # Defaults by room type
        room_type_val = data['room_type']
        if capacity_val is None:
            capacity_val = 6 if room_type_val == 'regular' else 0
        if rent_val is None:
            rent_val = 5000.0 if room_type_val == 'regular' else 0.0

        # Normalize floor to 'ground' or integer, default 'ground'
        floor_val = data.get('floor') or 'ground'
        if isinstance(floor_val, str):
            f = floor_val.strip().lower()
            if f in ('ground', 'g', '0'):
                floor_val = 'ground'
            else:
                try:
                    floor_val = int(f)
                except Exception:
                    # keep original string if not convertible
                    pass

        room = {
            'room_number': data['room_number'],
            'floor': floor_val,
            'room_type': data['room_type'],
            'capacity': capacity_val,
            'current_occupancy': 0,
            'rent': rent_val,
            'status': 'available',
            'created_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        # Add optional fields if provided
        if data.get('description'):
            room['description'] = data.get('description')
        
        # Insert into database
        result = mongo.db.rooms.insert_one(room)
        
        if not request.is_json:
            flash('Room added successfully', 'success')
            return redirect(url_for('admin_rooms'))
        else:
            return jsonify({
                'message': 'Room added successfully',
                'room_id': str(result.inserted_id)
            }), 201
        
    except Exception as e:
        if not request.is_json:
            flash('Failed to add room', 'error')
            return redirect(url_for('admin_rooms'))
        return jsonify({'error': str(e)}), 500

@app.route('/api/rooms/<room_id>', methods=['PUT'])
@login_required
def update_room(room_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        data = request.get_json()
        updates = {}
        
        # Only update fields that are provided in the request
        updatable_fields = ['room_number', 'floor', 'room_type', 'capacity', 'rent', 'description', 'status']
        for field in updatable_fields:
            if field in data:
                updates[field] = data[field]
        
        # Add updated_at timestamp
        updates['updated_at'] = datetime.utcnow()
        
        # Update the room
        result = mongo.db.rooms.update_one(
            {'_id': ObjectId(room_id)},
            {'$set': updates}
        )
        
        if result.matched_count == 0:
            return jsonify({'error': 'Room not found'}), 404
            
        return jsonify({'message': 'Room updated successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Get students assigned to a room
@app.route('/api/rooms/<room_id>/students', methods=['GET'])
@login_required
def get_room_students(room_id):
    # Allow admin and warden to view
    if current_user.role not in ['admin', 'warden']:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        room = mongo.db.rooms.find_one({'_id': ObjectId(room_id)})
        if not room:
            return jsonify({'error': 'Room not found'}), 404

        cursor = mongo.db.users.find(
            {'role': 'student', 'room_number': room.get('room_number')},
            {'name': 1, 'email': 1, 'phone': 1, 'year': 1, 'branch': 1, 'stream': 1}
        )
        students = []
        for s in cursor:
            s['_id'] = str(s['_id'])
            students.append(s)
        return jsonify({'room_number': room.get('room_number'), 'students': students})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/rooms/<room_id>', methods=['DELETE'])
@login_required
def delete_room(room_id):
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
        
    try:
        # Check if room has occupants
        room = mongo.db.rooms.find_one({'_id': ObjectId(room_id)})
        if not room:
            return jsonify({'error': 'Room not found'}), 404
            
        if room.get('current_occupancy', 0) > 0:
            return jsonify({'error': 'Cannot delete a room with occupants'}), 400
        
        # Delete the room
        result = mongo.db.rooms.delete_one({'_id': ObjectId(room_id)})
        
        if result.deleted_count == 0:
            return jsonify({'error': 'Room not found'}), 404
            
        return jsonify({'message': 'Room deleted successfully'})
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Admin Panel Routes
@app.route('/admin/students')
@login_required
def admin_students():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    
    # Get all students
    students = list(mongo.db.users.find({'role': 'student'}).sort('name', 1))
    
    # Convert ObjectId to string for template rendering
    for student in students:
        student['_id'] = str(student['_id'])
    
    return render_template('admin/students.html', students=students)

@app.route('/api/students/<student_id>', methods=['GET'])
@login_required
def get_student(student_id):
    if current_user.role not in ['admin', 'warden']:
        return jsonify({'error': 'Unauthorized'}), 403
    try:
        s = mongo.db.users.find_one({'_id': ObjectId(student_id), 'role': 'student'})
        if not s:
            return jsonify({'error': 'Student not found'}), 404
        s['_id'] = str(s['_id'])
        return jsonify(s)
    except Exception as e:
        return jsonify({'error': str(e)}), 400

@app.route('/warden/students')
@login_required
def warden_students():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))

    # Get all students for view-only listing
    students = list(mongo.db.users.find({'role': 'student'}).sort('name', 1))
    for s in students:
        s['_id'] = str(s['_id'])
    return render_template('warden/students.html', students=students)

@app.route('/admin/students/<student_id>/edit', methods=['POST'])
@login_required
def edit_student(student_id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_students'))
    try:
        s = mongo.db.users.find_one({'_id': ObjectId(student_id), 'role': 'student'})
        if not s:
            flash('Student not found', 'error')
            return redirect(url_for('admin_students'))

        # Collect fields
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        year = request.form.get('year')
        stream = request.form.get('stream')
        branch = request.form.get('branch')
        college = request.form.get('college')
        swd_id = (request.form.get('swd_id') or '').strip()
        if not swd_id:
            flash('SWD ID is required', 'error')
            return redirect(url_for('admin_students'))

        updates = {}
        if name: updates['name'] = name
        if email:
            # Check duplicate email excluding current student
            other = mongo.db.users.find_one({'email': email, '_id': {'$ne': ObjectId(student_id)}})
            if other:
                flash('A user with this email already exists', 'error')
                return redirect(url_for('admin_students'))
            updates['email'] = email
        if phone: updates['phone'] = phone
        if year:
            try:
                year_int = int(year)
                if year_int < 1 or year_int > 5:
                    raise ValueError()
                updates['year'] = year_int
            except Exception:
                flash('Year must be a number between 1 and 5', 'error')
                return redirect(url_for('admin_students'))
        if stream:
            if stream not in {'engineering', 'medical'}:
                flash('Invalid stream selected', 'error')
                return redirect(url_for('admin_students'))
            updates['stream'] = stream
        if branch: updates['branch'] = branch
        if college: updates['college'] = college
        # SWD ID required and always updated
        updates['swd_id'] = swd_id

        if updates:
            updates['updated_at'] = datetime.utcnow()
            mongo.db.users.update_one({'_id': ObjectId(student_id)}, {'$set': updates})
            flash('Student updated successfully', 'success')
        else:
            flash('No changes submitted', 'info')
        return redirect(url_for('admin_students'))
    except Exception as e:
        print(f"Error editing student: {e}")
        flash('Error updating student', 'error')
        return redirect(url_for('admin_students'))

@app.route('/admin/students/<student_id>/delete', methods=['POST'])
@login_required
def delete_student(student_id):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_students'))
    try:
        s = mongo.db.users.find_one({'_id': ObjectId(student_id), 'role': 'student'})
        if not s:
            flash('Student not found', 'error')
            return redirect(url_for('admin_students'))

        # If student assigned to a room, decrement occupancy safely
        rn = s.get('room_number')
        if rn:
            room = mongo.db.rooms.find_one({'room_number': rn})
            if room:
                curr = int(room.get('current_occupancy', 0) or 0)
                new_val = curr - 1 if curr > 0 else 0
                mongo.db.rooms.update_one({'_id': room['_id']}, {'$set': {'current_occupancy': new_val, 'updated_at': datetime.utcnow()}})

        mongo.db.users.delete_one({'_id': ObjectId(student_id)})
        flash('Student deleted', 'success')
        return redirect(url_for('admin_students'))
    except Exception as e:
        print(f"Error deleting student: {e}")
        flash('Error deleting student', 'error')
        return redirect(url_for('admin_students'))
@app.route('/admin/students/add', methods=['POST'])
@login_required
def add_student():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    
    try:
        name = request.form.get('name')
        email = request.form.get('email')
        phone = request.form.get('phone')
        year = request.form.get('year')
        stream = request.form.get('stream')
        branch = request.form.get('branch')
        college = request.form.get('college')
        swd_id = (request.form.get('swd_id') or '').strip()

        # Basic validation (SWD ID is required)
        if not all([name, email, phone, year, stream, branch, college, swd_id]):
            flash('All fields are required', 'error')
            return redirect(url_for('admin_students'))

        try:
            year_int = int(year)
            if year_int < 1 or year_int > 5:
                raise ValueError()
        except Exception:
            flash('Year must be a number between 1 and 5', 'error')
            return redirect(url_for('admin_students'))

        allowed_streams = {'engineering', 'medical'}
        if stream not in allowed_streams:
            flash('Invalid stream selected', 'error')
            return redirect(url_for('admin_students'))

        # Check if email already exists
        if mongo.db.users.find_one({'email': email}):
            flash('A user with this email already exists', 'error')
            return redirect(url_for('admin_students'))
        
        # Generate a random password
        password = generate_random_password()
        hashed_password = generate_password_hash(password)
        
        # Create new student
        student = {
            'name': name,
            'email': email,
            'password': hashed_password,
            'role': 'student',
            'created_at': datetime.utcnow(),
            'status': 'active',
            'phone': phone,
            'year': year_int,
            'stream': stream,
            'branch': branch,
            'college': college,
            'swd_id': swd_id
        }
        
        # Insert into database
        mongo.db.users.insert_one(student)
        
        # Send email with credentials
        try:
            # Use email as username
            send_credentials_email(email, email, password)
            flash('Student added and credentials emailed successfully', 'success')
        except Exception as e:
            print(f"Error sending email: {e}")
            flash('Student added, but failed to send email credentials', 'warning')
        
        return redirect(url_for('admin_students'))
        
    except Exception as e:
        print(f"Error adding student: {e}")
        flash('Error adding student', 'error')
        return redirect(url_for('admin_students'))

@app.route('/admin/rooms')
@login_required
def admin_rooms():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    
    # Get all rooms
    rooms = list(mongo.db.rooms.find().sort('room_number', 1))
    
    # Convert ObjectId to string for template rendering
    for room in rooms:
        room['_id'] = str(room['_id'])
    
    return render_template('admin/rooms.html', rooms=rooms)

@app.route('/admin/rooms/add', methods=['GET'])
@login_required
def admin_rooms_add_page():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    # Render a full-page Add Room form (posts to /api/rooms)
    return render_template('admin/room_add.html')

# Assign Students to Rooms (Admin)
@app.route('/admin/rooms/assign', methods=['GET', 'POST'])
@login_required
def admin_assign_students():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))

    if request.method == 'POST':
        try:
            room_id = request.form.get('room_id')
            selected_students = request.form.getlist('student_ids')

            if not room_id or not selected_students:
                flash('Please select a room and at least one student', 'error')
                return redirect(url_for('admin_assign_students'))

            room = mongo.db.rooms.find_one({'_id': ObjectId(room_id)})
            if not room:
                flash('Selected room not found', 'error')
                return redirect(url_for('admin_assign_students'))

            capacity = int(room.get('capacity', 0))
            current = int(room.get('current_occupancy', 0))
            available = max(0, capacity - current)

            if len(selected_students) > available:
                flash(f'Only {available} bed(s) available in Room {room.get("room_number")}', 'error')
                return redirect(url_for('admin_assign_students'))

            # Assign students: set users.room_number to the room's room_number
            # Also increment room current_occupancy accordingly
            room_number = room.get('room_number')

            # Update users who are still unassigned to avoid double-assignment
            user_update_result = mongo.db.users.update_many(
                {
                    '_id': {'$in': [ObjectId(sid) for sid in selected_students]},
                    'role': 'student',
                    '$or': [
                        {'room_number': {'$exists': False}},
                        {'room_number': None},
                        {'room_number': ''}
                    ]
                },
                {'$set': {'room_number': room_number}}
            )

            actually_assigned = user_update_result.modified_count
            if actually_assigned == 0:
                flash('No students assigned. They may already be assigned to a room.', 'error')
                return redirect(url_for('admin_assign_students'))

            mongo.db.rooms.update_one(
                {'_id': ObjectId(room_id)},
                {'$inc': {'current_occupancy': actually_assigned}}
            )

            flash(f'Successfully assigned {actually_assigned} student(s) to Room {room_number}', 'success')
            return redirect(url_for('admin_rooms'))
        except Exception as e:
            print(f"Error assigning students: {e}")
            flash('An error occurred while assigning students', 'error')
            return redirect(url_for('admin_assign_students'))

    # GET: render form with rooms and unassigned students
    rooms = list(mongo.db.rooms.find().sort('room_number', 1))
    for r in rooms:
        r['_id'] = str(r['_id'])

    unassigned_students = list(mongo.db.users.find({
        'role': 'student',
        '$or': [
            {'room_number': {'$exists': False}},
            {'room_number': None},
            {'room_number': ''}
        ]
    }).sort('name', 1))
    for s in unassigned_students:
        s['_id'] = str(s['_id'])

    return render_template('admin/assign_students.html', rooms=rooms, students=unassigned_students)

# -----------------------------
# Library Management (Admin)
# -----------------------------

@app.route('/admin/books')
@login_required
def admin_books():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    books = list(mongo.db.books.find().sort('title', 1))
    for b in books:
        b['_id'] = str(b['_id'])
    return render_template('admin/books.html', books=books)

@app.route('/warden/books')
@login_required
def warden_books():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))
    books = list(mongo.db.books.find().sort('title', 1))
    for b in books:
        b['_id'] = str(b['_id'])
    return render_template('warden/books.html', books=books)

@app.route('/admin/books/add', methods=['POST'])
@login_required
def add_book():
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_books'))
    try:
        book_id = (request.form.get('book_id') or '').strip()
        title = (request.form.get('title') or '').strip()
        author = (request.form.get('author') or '').strip()
        price = (request.form.get('price') or '').strip()
        if not all([book_id, title, author, price]):
            flash('All fields are required', 'error')
            return redirect(url_for('admin_books'))
        try:
            price_val = float(price)
        except Exception:
            flash('Price must be a valid number', 'error')
            return redirect(url_for('admin_books'))
        if mongo.db.books.find_one({'book_id': book_id}):
            flash('A book with this Book ID already exists', 'error')
            return redirect(url_for('admin_books'))
        book = {
            'book_id': book_id,
            'title': title,
            'author': author,
            'price': price_val,
            'status': 'available',
            'created_at': datetime.utcnow()
        }
        mongo.db.books.insert_one(book)
        flash('Book added successfully', 'success')
    except Exception as e:
        print(f"Error adding book: {e}")
        flash('Failed to add book', 'error')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/<book_oid>/edit', methods=['POST'])
@login_required
def edit_book(book_oid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_books'))
    try:
        b = mongo.db.books.find_one({'_id': ObjectId(book_oid)})
        if not b:
            flash('Book not found', 'error')
            return redirect(url_for('admin_books'))
        book_id = (request.form.get('book_id') or '').strip()
        title = (request.form.get('title') or '').strip()
        author = (request.form.get('author') or '').strip()
        price = (request.form.get('price') or '').strip()
        if not all([book_id, title, author, price]):
            flash('All fields are required', 'error')
            return redirect(url_for('admin_books'))
        try:
            price_val = float(price)
        except Exception:
            flash('Price must be a valid number', 'error')
            return redirect(url_for('admin_books'))
        other = mongo.db.books.find_one({'book_id': book_id, '_id': {'$ne': ObjectId(book_oid)}})
        if other:
            flash('Another book with this Book ID already exists', 'error')
            return redirect(url_for('admin_books'))
        updates = {
            'book_id': book_id,
            'title': title,
            'author': author,
            'price': price_val,
            'updated_at': datetime.utcnow()
        }
        mongo.db.books.update_one({'_id': ObjectId(book_oid)}, {'$set': updates})
        flash('Book updated successfully', 'success')
    except Exception as e:
        print(f"Error editing book: {e}")
        flash('Failed to update book', 'error')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/<book_oid>/delete', methods=['POST'])
@login_required
def delete_book(book_oid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_books'))
    try:
        b = mongo.db.books.find_one({'_id': ObjectId(book_oid)})
        if not b:
            flash('Book not found', 'error')
            return redirect(url_for('admin_books'))
        if b.get('status') == 'issued':
            flash('Cannot delete a book that is currently issued', 'error')
            return redirect(url_for('admin_books'))
        mongo.db.books.delete_one({'_id': ObjectId(book_oid)})
        flash('Book deleted', 'success')
    except Exception as e:
        print(f"Error deleting book: {e}")
        flash('Failed to delete book', 'error')
    return redirect(url_for('admin_books'))

@app.route('/api/books', methods=['GET'])
@login_required
def api_books():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    q = (request.args.get('q') or '').strip().lower()
    filt = {}
    if q:
        filt = {'$or': [
            {'book_id': {'$regex': q, '$options': 'i'}},
            {'title': {'$regex': q, '$options': 'i'}},
            {'author': {'$regex': q, '$options': 'i'}}
        ]}
    books = list(mongo.db.books.find(filt).sort('title', 1))
    for b in books:
        b['_id'] = str(b['_id'])
    return jsonify(books)

@app.route('/admin/books/<book_oid>/issue', methods=['POST'])
@login_required
def issue_book(book_oid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_books'))
    try:
        book = mongo.db.books.find_one({'_id': ObjectId(book_oid)})
        if not book:
            flash('Book not found', 'error')
            return redirect(url_for('admin_books'))
        if book.get('status') == 'issued':
            flash('Book is already issued', 'error')
            return redirect(url_for('admin_books'))
        # Student identification by SWD ID or name
        student_swd = (request.form.get('student_swd_id') or '').strip()
        student_name = (request.form.get('student_name') or '').strip()
        if not (student_swd or student_name):
            flash('Provide student SWD ID or Name', 'error')
            return redirect(url_for('admin_books'))
        sfilt = {'role': 'student'}
        if student_swd:
            sfilt['swd_id'] = student_swd
        elif student_name:
            sfilt['name'] = {'$regex': f"^{student_name}$", '$options': 'i'}
        student = mongo.db.users.find_one(sfilt)
        if not student:
            flash('Student not found', 'error')
            return redirect(url_for('admin_books'))
        # Create transaction
        issued_at = datetime.utcnow()
        tx = {
            'book_id': book.get('book_id'),
            'book_title': book.get('title'),
            'student_id': student['_id'],
            'student_name': student.get('name'),
            'student_swd_id': student.get('swd_id'),
            'issued_at': issued_at,
            'due_at': issued_at + timedelta(days=15),
            'returned_at': None,
            'status': 'issued'
        }
        mongo.db.books_issued.insert_one(tx)
        mongo.db.books.update_one({'_id': book['_id']}, {'$set': {'status': 'issued', 'updated_at': datetime.utcnow()}})
        flash('Book issued successfully', 'success')
    except Exception as e:
        print(f"Error issuing book: {e}")
        flash('Failed to issue book', 'error')
    return redirect(url_for('admin_books'))

@app.route('/admin/books/<book_oid>/return', methods=['POST'])
@login_required
def return_book(book_oid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_transactions'))
    try:
        book = mongo.db.books.find_one({'_id': ObjectId(book_oid)})
        if not book:
            flash('Book not found', 'error')
            return redirect(url_for('admin_transactions'))
        if book.get('status') not in ['issued', 'overdue']:
            flash('Book is not marked as issued/overdue', 'error')
            return redirect(url_for('admin_transactions'))
        # Find latest open transaction for this book_id (issued or overdue)
        tx = mongo.db.books_issued.find_one({'book_id': book['book_id'], 'status': {'$in': ['issued', 'overdue']}}, sort=[('issued_at', -1)])
        if not tx:
            flash('No active transaction found', 'error')
            return redirect(url_for('admin_transactions'))
        mongo.db.books_issued.update_one({'_id': tx['_id']}, {'$set': {'status': 'returned', 'returned_at': datetime.utcnow()}})
        mongo.db.books.update_one({'_id': book['_id']}, {'$set': {'status': 'available', 'updated_at': datetime.utcnow()}})
        flash('Book returned successfully', 'success')
    except Exception as e:
        print(f"Error returning book: {e}")
        flash('Failed to return book', 'error')
    return redirect(url_for('admin_transactions'))

# -----------------------------
# Placements (Admin)
# -----------------------------

@app.route('/admin/placements', methods=['GET'])
@login_required
def admin_placements():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    # Fetch all placements sorted by year desc then student name
    placements = list(mongo.db.placements.find().sort([('year', -1), ('student_name', 1)]))
    for p in placements:
        p['_id'] = str(p['_id'])
    return render_template('admin/placements.html', placements=placements)

@app.route('/admin/placements/add', methods=['POST'])
@login_required
def add_placement():
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_placements'))
    try:
        student_name = (request.form.get('student_name') or '').strip()
        package_lpa = (request.form.get('package_lpa') or '').strip()
        company = (request.form.get('company') or '').strip()
        role = (request.form.get('role') or '').strip()
        location = (request.form.get('location') or '').strip()
        year = (request.form.get('year') or '').strip()
        linkedin_url = (request.form.get('linkedin_url') or '').strip()

        if not all([student_name, package_lpa, company, role, location, year]):
            flash('All fields are required', 'error')
            return redirect(url_for('admin_placements'))

        try:
            package_val = float(package_lpa)
        except Exception:
            flash('Package (LPA) must be a number', 'error')
            return redirect(url_for('admin_placements'))
        try:
            year_val = int(year)
        except Exception:
            flash('Year must be an integer', 'error')
            return redirect(url_for('admin_placements'))

        doc = {
            'student_name': student_name,
            'package_lpa': package_val,
            'company': company,
            'role': role,
            'location': location,
            'year': year_val,
            'created_at': datetime.utcnow()
        }
        # Optional fields
        if linkedin_url:
            doc['linkedin_url'] = linkedin_url
        mongo.db.placements.insert_one(doc)
        flash('Placement added successfully', 'success')
    except Exception as e:
        print(f"Error adding placement: {e}")
        flash('Failed to add placement', 'error')
    return redirect(url_for('admin_placements'))

@app.route('/admin/transactions')
@login_required
def admin_transactions():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    # Backfill due_at for older records and auto-mark overdue where past due date
    now = datetime.utcnow()
    try:
        # Backfill due_at for any issued/overdue txs missing it
        missing_cursor = mongo.db.books_issued.find({'status': {'$in': ['issued', 'overdue']}, 'due_at': {'$exists': False}})
        for m in missing_cursor:
            issued_at = m.get('issued_at')
            try:
                if isinstance(issued_at, str):
                    # Try parse common formats used by our filter
                    try:
                        issued_at = datetime.strptime(issued_at, '%Y-%m-%dT%H:%M:%S.%f')
                    except Exception:
                        try:
                            issued_at = datetime.strptime(issued_at, '%Y-%m-%d %H:%M:%S')
                        except Exception:
                            issued_at = now
                due_at = issued_at + timedelta(days=15)
                mongo.db.books_issued.update_one({'_id': m['_id']}, {'$set': {'due_at': due_at}})
            except Exception:
                pass
    except Exception:
        pass
    try:
        mongo.db.books_issued.update_many(
            {'status': 'issued', 'due_at': {'$lt': now}},
            {'$set': {'status': 'overdue'}}
        )
    except Exception:
        pass
    current_txs = list(mongo.db.books_issued.find({'status': {'$in': ['issued', 'overdue']}}).sort('issued_at', -1))
    past_txs = list(mongo.db.books_issued.find({'status': 'returned'}).sort('issued_at', -1))
    # Enrich and stringify ids
    def enrich(tlist):
        for t in tlist:
            t['_id'] = str(t['_id'])
            if isinstance(t.get('student_id'), ObjectId):
                t['student_id'] = str(t['student_id'])
            # Find book oid for return action
            try:
                book = mongo.db.books.find_one({'book_id': t.get('book_id')})
                if book:
                    t['book_oid'] = str(book['_id'])
            except Exception:
                pass
        return tlist
    current_txs = enrich(current_txs)
    past_txs = enrich(past_txs)
    return render_template('admin/transactions.html', current_transactions=current_txs, past_transactions=past_txs)

# -----------------------------
# Query & Feedback (Admin)
# -----------------------------

@app.route('/admin/feedback', methods=['GET'])
@login_required
def admin_feedback():
    if current_user.role != 'admin':
        flash('Access denied: Admin privileges required', 'error')
        return redirect(url_for('index'))
    # Show open first, then resolved, newest first within groups
    open_items = list(mongo.db.feedback.find({'status': {'$ne': 'resolved'}}).sort('created_at', -1))
    resolved_items = list(mongo.db.feedback.find({'st atus': 'resolved'}).sort('resolved_at', -1))
    return render_template('admin/feedback.html', open_items=open_items, resolved_items=resolved_items)

@app.route('/admin/feedback/add', methods=['POST'])
@login_required
def add_feedback():
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_feedback'))
    try:
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        reporter_name = (request.form.get('reporter_name') or '').strip()
        if not title or not description:
            flash('Title and description are required', 'error')
            return redirect(url_for('admin_feedback'))
        doc = {
            'title': title,
            'description': description,
            'reporter_name': reporter_name or current_user.user_data.get('name'),
            'status': 'open',
            'resolution_notes': '',
            'created_at': datetime.utcnow(),
            'resolved_at': None
        }
        mongo.db.feedback.insert_one(doc)
        flash('Query/Feedback added', 'success')
    except Exception as e:
        print(f"Error adding feedback: {e}")
        flash('Failed to add', 'error')
    return redirect(url_for('admin_feedback'))

# -----------------------------
# Profile (All authenticated users)
# -----------------------------

@app.route('/profile', methods=['GET'])
@login_required
def profile():
    # Prepare a safe dict of user fields to show
    u = getattr(current_user, 'user_data', {}) or {}
    details = {
        'name': u.get('name'),
        'email': u.get('email'),
        'phone': u.get('phone'),
        'swd_id': u.get('swd_id'),
        'stream': u.get('stream'),
        'branch': u.get('branch'),
        'college': u.get('college'),
        'year': u.get('year'),
        'role': getattr(current_user, 'role', None),
    }
    return render_template('profile.html', details=details)

@app.route('/change-password', methods=['POST'])
@login_required
def change_password():
    """Allow any authenticated user to change their password"""
    current_pwd = (request.form.get('current_password') or '').strip()
    new_pwd = (request.form.get('new_password') or '').strip()
    confirm_pwd = (request.form.get('confirm_password') or '').strip()

    # Basic validations
    if not current_pwd or not new_pwd or not confirm_pwd:
        flash('All password fields are required.', 'error')
        return redirect(url_for('profile'))
    if new_pwd != confirm_pwd:
        flash('New password and confirmation do not match.', 'error')
        return redirect(url_for('profile'))
    if len(new_pwd) < 8:
        flash('New password must be at least 8 characters long.', 'error')
        return redirect(url_for('profile'))
    if new_pwd == current_pwd:
        flash('New password must be different from current password.', 'error')
        return redirect(url_for('profile'))

    # Verify current password against DB and update
    try:
        user = mongo.db.users.find_one({'_id': ObjectId(current_user.id)})
        if not user or not check_password_hash(user.get('password', ''), current_pwd):
            flash('Current password is incorrect.', 'error')
            return redirect(url_for('profile'))
        hashed = generate_password_hash(new_pwd)
        mongo.db.users.update_one({'_id': user['_id']}, {
            '$set': {
                'password': hashed,
                'updated_at': datetime.utcnow()
            }
        })
        flash('Password updated successfully.', 'success')
    except Exception as e:
        print(f"Error changing password: {e}")
        flash('Failed to change password. Please try again.', 'error')
    return redirect(url_for('profile'))

@app.route('/admin/feedback/<fid>/resolve', methods=['POST'])
@login_required
def resolve_feedback(fid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_feedback'))
    notes = (request.form.get('resolution_notes') or '').strip()
    try:
        mongo.db.feedback.update_one({'_id': ObjectId(fid)}, {
            '$set': {
                'status': 'resolved',
                'resolution_notes': notes,
                'resolved_at': datetime.utcnow()
            }
        })
        flash('Marked as resolved', 'success')
    except Exception as e:
        print(f"Error resolving feedback: {e}")
        flash('Failed to resolve', 'error')
    return redirect(url_for('admin_feedback'))

@app.route('/admin/feedback/<fid>/unresolve', methods=['POST'])
@login_required
def unresolve_feedback(fid):
    if current_user.role != 'admin':
        flash('Unauthorized', 'error')
        return redirect(url_for('admin_feedback'))
    try:
        mongo.db.feedback.update_one({'_id': ObjectId(fid)}, {
            '$set': {
                'status': 'open',
                'resolved_at': None
            },
            '$unset': {
                'resolution_notes': ''
            }
        })
        flash('Moved back to open', 'success')
    except Exception as e:
        print(f"Error unresolving feedback: {e}")
        flash('Failed to unresolve', 'error')
    return redirect(url_for('admin_feedback'))

# -----------------------------
# Query & Feedback (Warden)
# -----------------------------

@app.route('/warden/feedback', methods=['GET'])
@login_required
def warden_feedback():
    if current_user.role != 'warden':
        flash('Access denied: Warden privileges required', 'error')
        return redirect(url_for('index'))
    # Show open first, then resolved
    open_items = list(mongo.db.feedback.find({'status': {'$ne': 'resolved'}}).sort('created_at', -1))
    resolved_items = list(mongo.db.feedback.find({'status': 'resolved'}).sort('resolved_at', -1))
    return render_template('warden/feedback.html', open_items=open_items, resolved_items=resolved_items)


@app.route('/warden/feedback/add', methods=['POST'])
@login_required
def warden_add_feedback():
    if current_user.role != 'warden':
        flash('Unauthorized', 'error')
        return redirect(url_for('warden_feedback'))
    try:
        title = (request.form.get('title') or '').strip()
        description = (request.form.get('description') or '').strip()
        reporter_name = (request.form.get('reporter_name') or '').strip()
        if not title or not description:
            flash('Title and description are required', 'error')
            return redirect(url_for('warden_feedback'))
        doc = {
            'title': title,
            'description': description,
            'reporter_name': reporter_name or current_user.user_data.get('name'),
            'status': 'open',
            'resolution_notes': '',
            'created_at': datetime.utcnow(),
            'resolved_at': None
        }
        mongo.db.feedback.insert_one(doc)
        flash('Query/Feedback added', 'success')
    except Exception as e:
        print(f"Error warden_add_feedback: {e}")
        flash('Failed to add', 'error')
    return redirect(url_for('warden_feedback'))


@app.route('/warden/feedback/<fid>/resolve', methods=['POST'])
@login_required
def warden_resolve_feedback(fid):
    if current_user.role != 'warden':
        flash('Unauthorized', 'error')
        return redirect(url_for('warden_feedback'))
    notes = (request.form.get('resolution_notes') or '').strip()
    try:
        mongo.db.feedback.update_one({'_id': ObjectId(fid)}, {
            '$set': {
                'status': 'resolved',
                'resolution_notes': notes,
                'resolved_at': datetime.utcnow()
            }
        })
        flash('Marked as resolved', 'success')
    except Exception as e:
        print(f"Error warden_resolve_feedback: {e}")
        flash('Failed to resolve', 'error')
    return redirect(url_for('warden_feedback'))


@app.route('/warden/feedback/<fid>/unresolve', methods=['POST'])
@login_required
def warden_unresolve_feedback(fid):
    if current_user.role != 'warden':
        flash('Unauthorized', 'error')
        return redirect(url_for('warden_feedback'))
    try:
        mongo.db.feedback.update_one({'_id': ObjectId(fid)}, {
            '$set': {
                'status': 'open',
                'resolved_at': None
            },
            '$unset': {
                'resolution_notes': ''
            }
        })
        flash('Moved back to open', 'success')
    except Exception as e:
        print(f"Error warden_unresolve_feedback: {e}")
        flash('Failed to unresolve', 'error')
    return redirect(url_for('warden_feedback'))

@app.route('/api/transactions', methods=['GET'])
@login_required
def api_transactions():
    if current_user.role != 'admin':
        return jsonify({'error': 'Unauthorized'}), 403
    q = (request.args.get('q') or '').strip()
    filt = {}
    if q:
        regex = {'$regex': q, '$options': 'i'}
        filt = {'$or': [
            {'book_id': regex},
            {'book_title': regex},
            {'student_name': regex},
            {'student_swd_id': regex}
        ]}
    txs = list(mongo.db.books_issued.find(filt).sort('issued_at', -1))
    for t in txs:
        t['_id'] = str(t['_id'])
        if isinstance(t.get('student_id'), ObjectId):
            t['student_id'] = str(t['student_id'])
    return jsonify(txs)

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
