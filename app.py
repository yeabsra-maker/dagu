from flask import Flask, session, render_template, jsonify, request
from flask_wtf.csrf import CSRFProtect, generate_csrf
from auth import register_user, login_user, logout_user, check_session, admin_required, validate_password
from messages import get_users, send_message, get_messages, get_conversations, search_users
from config import get_db_connection
import os
import time
import bcrypt
import logging
import traceback
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = True   # For HTTPS
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = 1800

csrf = CSRFProtect(app)

typing_users = {}

# ==================== SECURITY HEADERS ====================
@app.after_request
def add_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['X-XSS-Protection'] = '1; mode=block'
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains; preload'
    response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; font-src 'self' https://cdnjs.cloudflare.com;"
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    return response

# ==================== CSRF TOKEN ====================
@app.route("/csrf-token", methods=["GET"])
def get_csrf_token():
    return jsonify({"csrf_token": generate_csrf()})

# ==================== AUTH ROUTES ====================
@app.route("/register", methods=["POST"])
@csrf.exempt
def register():
    return register_user()

@app.route("/login", methods=["POST"])
@csrf.exempt
def login():
    return login_user()

@app.route("/logout", methods=["POST"])
@csrf.exempt
def logout():
    return logout_user()

@app.route("/check-session", methods=["GET"])
def session_check():
    return check_session()

# ==================== MESSAGING ROUTES ====================
@app.route("/users", methods=["GET"])
def users():
    return get_users()

@app.route("/search-users", methods=["GET"])
def search_users_route():
    return search_users()

@app.route("/send-message", methods=["POST"])
@csrf.exempt
def send():
    return send_message()

@app.route("/messages", methods=["GET"])
def messages():
    return get_messages()

@app.route("/conversations", methods=["GET"])
def conversations():
    return get_conversations()

@app.route("/update-status", methods=["POST"])
@csrf.exempt
def update_status():
    from messages import update_user_status
    update_user_status()
    return jsonify({"status": "ok"})

# ==================== TYPING ====================
@app.route("/typing", methods=["POST"])
@csrf.exempt
def set_typing():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.json
    receiver_id = data.get('receiver_id')
    is_typing = data.get('typing', False)
    if receiver_id:
        key = f"{session['user_id']}_{receiver_id}"
        if is_typing:
            typing_users[key] = time.time()
        else:
            typing_users.pop(key, None)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Missing receiver_id"}), 400

@app.route("/typing-status", methods=["GET"])
def get_typing():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    current_user_id = session['user_id']
    typing_to_me = []
    now = time.time()
    to_remove = [k for k, ts in typing_users.items() if now - ts > 3]
    for k in to_remove:
        typing_users.pop(k, None)
    for key, ts in typing_users.items():
        sender_id, receiver_id = key.split('_')
        if int(receiver_id) == current_user_id and now - ts <= 3:
            typing_to_me.append(int(sender_id))
    return jsonify({"typing_users": typing_to_me})

# ==================== REACTIONS ====================
@app.route("/add-reaction", methods=["POST"])
@csrf.exempt
def add_reaction():
    from messages import add_reaction
    return add_reaction()

@app.route("/remove-reaction", methods=["POST"])
@csrf.exempt
def remove_reaction():
    from messages import remove_reaction
    return remove_reaction()

@app.route("/message-reactions/<int:message_id>", methods=["GET"])
def get_reactions(message_id):
    from messages import get_message_reactions
    return get_message_reactions(message_id)

@app.route("/mark-seen", methods=["POST"])
@csrf.exempt
def mark_seen():
    from messages import mark_conversation_seen
    data = request.json
    other_user_id = data.get('user_id')
    if other_user_id:
        mark_conversation_seen(other_user_id)
        return jsonify({"status": "ok"})
    return jsonify({"error": "Missing user_id"}), 400

# ==================== ADMIN ROUTES ====================
@app.route("/admin")
@admin_required
def admin_dashboard():
    return render_template("admin.html")

@app.route("/admin/stats", methods=["GET"])
@admin_required
def admin_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT COUNT(*) FROM users")
        total_users = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM messages")
        total_messages = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM security_logs WHERE event = 'failed_login'")
        failed_logins = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM users WHERE last_seen > NOW() - INTERVAL '30 seconds'")
        online_users = cursor.fetchone()[0]
        return jsonify({
            "total_users": total_users,
            "total_messages": total_messages,
            "failed_logins": failed_logins,
            "online_users": online_users
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin/users", methods=["GET"])
@admin_required
def admin_users():
    from datetime import datetime
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT u.id, u.username, u.last_seen, u.role, COUNT(m.id) as message_count
            FROM users u
            LEFT JOIN messages m ON u.id = m.sender_id OR u.id = m.receiver_id
            GROUP BY u.id
            ORDER BY u.id
        """)
        users = cursor.fetchall()
        user_list = []
        now = datetime.now()
        for user in users:
            user_id, username, last_seen, role, msg_count = user
            is_online = False
            last_seen_str = None
            if last_seen:
                diff = now - last_seen
                if diff.total_seconds() < 30:
                    is_online = True
                if diff.total_seconds() < 60:
                    last_seen_str = "Just now"
                elif diff.total_seconds() < 3600:
                    minutes = int(diff.total_seconds() / 60)
                    last_seen_str = f"{minutes} min ago"
                elif diff.total_seconds() < 86400:
                    hours = int(diff.total_seconds() / 3600)
                    last_seen_str = f"{hours} hours ago"
                else:
                    days = int(diff.total_seconds() / 86400)
                    last_seen_str = f"{days} days ago"
            else:
                last_seen_str = "Never"
            user_list.append({
                "id": user_id,
                "username": username,
                "is_online": is_online,
                "last_seen": last_seen_str,
                "role": role,
                "message_count": msg_count
            })
        return jsonify({"users": user_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin/logs", methods=["GET"])
@admin_required
def admin_logs():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT l.id, l.user_id, l.event, l.ip_address, l.timestamp, u.username
            FROM security_logs l
            LEFT JOIN users u ON l.user_id = u.id
            ORDER BY l.timestamp DESC
            LIMIT 100
        """)
        logs = cursor.fetchall()
        log_list = []
        for log in logs:
            log_list.append({
                "id": log[0],
                "user_id": log[1],
                "username": log[5] if log[5] else "System",
                "event": log[2],
                "ip_address": log[3],
                "timestamp": log[4].isoformat() if log[4] else None
            })
        return jsonify({"logs": log_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin/messages", methods=["GET"])
@admin_required
def admin_messages():
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            SELECT m.id, m.sender_id, m.receiver_id, m.encrypted_message, m.timestamp,
                   s.username as sender_name, r.username as receiver_name
            FROM messages m
            LEFT JOIN users s ON m.sender_id = s.id
            LEFT JOIN users r ON m.receiver_id = r.id
            ORDER BY m.timestamp DESC
            LIMIT 100
        """)
        messages = cursor.fetchall()
        msg_list = []
        for msg in messages:
            msg_list.append({
                "id": msg[0],
                "sender_id": msg[1],
                "sender_name": msg[5] if msg[5] else str(msg[1]),
                "receiver_id": msg[2],
                "receiver_name": msg[6] if msg[6] else str(msg[2]),
                "encrypted_message": msg[3],
                "timestamp": msg[4].isoformat() if msg[4] else None
            })
        return jsonify({"messages": msg_list})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/admin/set-role", methods=["POST"])
@admin_required
def admin_set_role():
    data = request.json
    user_id = data.get('user_id')
    role = data.get('role')
    if not user_id or role not in ['admin', 'user']:
        return jsonify({"error": "Invalid request"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("UPDATE users SET role = %s WHERE id = %s", (role, user_id))
        conn.commit()
        return jsonify({"message": "Role updated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== AVATAR UPLOAD ====================
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOAD_FOLDER = 'static/uploads/avatars'
MAX_FILE_SIZE = 5 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/upload-avatar", methods=["POST"])
@csrf.exempt
def upload_avatar():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    if 'avatar' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file(file.filename):
        return jsonify({"error": "File type not allowed. Use PNG, JPG, JPEG, GIF, or WEBP"}), 400
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"error": "File too large. Max 5MB"}), 400
    user_id = session['user_id']
    filename = secure_filename(f"{user_id}_{int(time.time())}_{file.filename}")
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT avatar FROM users WHERE id = %s", (user_id,))
        old = cursor.fetchone()
        if old and old[0]:
            old_path = os.path.join(UPLOAD_FOLDER, old[0])
            if os.path.exists(old_path):
                os.remove(old_path)
        cursor.execute("UPDATE users SET avatar = %s WHERE id = %s", (filename, user_id))
        conn.commit()
        avatar_url = f"/static/uploads/avatars/{filename}"
        return jsonify({"success": True, "avatar_url": avatar_url})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

@app.route("/current-avatar", methods=["GET"])
def current_avatar():
    from messages import get_current_user_avatar
    return jsonify({"avatar_url": get_current_user_avatar()})

# ==================== USER DETAILS ====================
@app.route("/get-user-details/<int:user_id>")
def api_get_user_details(user_id):
    from messages import get_user_status
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT username, avatar FROM users WHERE id = %s", (user_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    if row:
        status = get_user_status(user_id)
        return jsonify({
            "username": row[0],
            "avatar_url": f"/static/uploads/avatars/{row[1]}" if row[1] else "/static/images/default-avatar.png",
            "online": status["online"],
            "last_seen": status["last_seen"]
        })
    return jsonify({"error": "not found"}), 404

# ==================== CLEAR CONVERSATION ====================
@app.route("/clear-conversation", methods=["POST"])
@csrf.exempt
def api_clear_conversation():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    data = request.json
    other_user_id = data.get('user_id')
    if not other_user_id:
        return jsonify({"error": "Missing user_id"}), 400
    current_user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            DELETE FROM messages 
            WHERE (sender_id = %s AND receiver_id = %s) 
               OR (sender_id = %s AND receiver_id = %s)
        """, (current_user_id, other_user_id, other_user_id, current_user_id))
        conn.commit()
        return jsonify({"message": "Conversation cleared"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== DUMMY GROUP ENDPOINT ====================
@app.route("/my-groups", methods=["GET"])
def my_groups():
    return jsonify({"groups": []})

# ==================== CHANGE PASSWORD ====================
@app.route("/change-password", methods=["POST"])
@csrf.exempt
def change_password():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    old_password = data.get('old_password')
    new_password = data.get('new_password')
    
    if not old_password or not new_password:
        return jsonify({"error": "Missing old or new password"}), 400
    
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT password_hash FROM users WHERE id = %s", (user_id,))
        row = cursor.fetchone()
        if not row:
            return jsonify({"error": "User not found"}), 404
        
        stored_hash = row[0]
        
        if not bcrypt.checkpw(old_password.encode('utf-8'), stored_hash.encode('utf-8')):
            return jsonify({"error": "Current password is incorrect"}), 401
        
        is_valid, message = validate_password(new_password)
        if not is_valid:
            return jsonify({"error": message}), 400
        
        new_hashed = bcrypt.hashpw(new_password.encode('utf-8'), bcrypt.gensalt())
        
        cursor.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hashed.decode('utf-8'), user_id))
        conn.commit()
        
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
            (user_id, 'password_changed', request.remote_addr)
        )
        conn.commit()
        
        return jsonify({"message": "Password changed successfully"})
    
    except Exception as e:
        conn.rollback()
        logging.error(f"Password change error: {str(e)}")
        return jsonify({"error": "Failed to change password"}), 500
    finally:
        cursor.close()
        conn.close()

# ==================== FILE UPLOAD ====================
ALLOWED_FILE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'txt', 'doc', 'docx', 'zip', 'mp3', 'mp4'}
MAX_FILE_SIZE = 10 * 1024 * 1024
UPLOAD_FILE_FOLDER = 'static/uploads/files'

os.makedirs(UPLOAD_FILE_FOLDER, exist_ok=True)

def allowed_file_upload(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_FILE_EXTENSIONS

@app.route("/upload-file", methods=["POST"])
@csrf.exempt
def upload_file():
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    if 'file' not in request.files:
        return jsonify({"error": "No file uploaded"}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "No file selected"}), 400
    if not allowed_file_upload(file.filename):
        return jsonify({"error": "File type not allowed"}), 400
    
    file.seek(0, os.SEEK_END)
    size = file.tell()
    file.seek(0)
    if size > MAX_FILE_SIZE:
        return jsonify({"error": "File too large (max 10MB)"}), 400
    
    user_id = session['user_id']
    original_filename = secure_filename(file.filename)
    timestamp = int(time.time())
    safe_filename = f"{user_id}_{timestamp}_{original_filename}"
    filepath = os.path.join(UPLOAD_FILE_FOLDER, safe_filename)
    file.save(filepath)
    
    file_url = f"/static/uploads/files/{safe_filename}"
    return jsonify({
        "success": True,
        "file_url": file_url,
        "filename": original_filename,
        "size": size
    })

# ==================== TEST DATABASE CONNECTION ====================
@app.route('/test-db')
def test_db():
    conn = None
    cursor = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1")
        result = cursor.fetchone()
        return f"✅ Database connection successful! Result: {result}"
    except Exception as e:
        return f"❌ Database error:<br><pre>{traceback.format_exc()}</pre>"
    finally:
        if cursor:
            cursor.close()
        if conn:
            conn.close()

# ==================== FRONTEND ROUTES ====================
@app.route("/")
def home():
    return render_template("index.html")

@app.route("/login")
def login_page():
    return render_template("login.html", csrf_token=generate_csrf())

@app.route("/register")
def register_page():
    return render_template("register.html", csrf_token=generate_csrf())

@app.route("/chat")
def chat_page():
    return render_template("chat.html", csrf_token=generate_csrf())

# ==================== RUN ====================
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=5000, ssl_context=('ssl/cert.pem', 'ssl/key.pem'))
