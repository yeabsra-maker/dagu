from flask import request, jsonify, session
import bcrypt
from config import get_db_connection
import datetime
import logging
import re
from functools import wraps

# Set up logging for security events
logging.basicConfig(filename='logs/security.log', level=logging.INFO)

def admin_required(f):
    """Decorator to check if user is admin"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "Not authenticated"}), 401
        
        user_id = session['user_id']
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            result = cursor.fetchone()
            if not result or result[0] != 'admin':
                return jsonify({"error": "Admin access required"}), 403
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        finally:
            cursor.close()
            conn.close()
        
        return f(*args, **kwargs)
    return decorated_function

def validate_password(password):
    """
    Validate password strength:
    - At least 8 characters
    - At least 1 uppercase letter
    - At least 1 number
    - At least 1 special character
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[0-9]', password):
        return False, "Password must contain at least one number"
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character (!@#$%^&* etc.)"
    
    return True, "Password is strong"

def register_user():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    ip_address = request.remote_addr

    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    
    # Validate username
    if len(username) < 3:
        return jsonify({"error": "Username must be at least 3 characters"}), 400
    
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return jsonify({"error": "Username can only contain letters, numbers, and underscores"}), 400
    
    # Validate password strength
    is_valid, message = validate_password(password)
    if not is_valid:
        return jsonify({"error": message}), 400

    hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute(
            "INSERT INTO users (username, password_hash) VALUES (%s, %s)",
            (username, hashed_pw.decode('utf-8'))
        )
        conn.commit()
        
        # Log successful registration
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (NULL, %s, %s)",
            ('user_registered', ip_address)
        )
        conn.commit()
        
        logging.info(f"New user registered: {username} from IP {ip_address}")

        return jsonify({"message": "User registered successfully"})

    except Exception as e:
        conn.rollback()
        return jsonify({"error": "User may already exist"}), 400

    finally:
        cursor.close()
        conn.close()

def login_user():
    data = request.json
    username = data.get("username")
    password = data.get("password")
    ip_address = request.remote_addr
    
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check login attempts (prevent brute force)
        cursor.execute(
            "SELECT COUNT(*) FROM security_logs WHERE event = 'failed_login' AND ip_address = %s AND timestamp > NOW() - INTERVAL '15 minutes'",
            (ip_address,)
        )
        attempt_count = cursor.fetchone()[0]
        
        if attempt_count >= 5:
            logging.warning(f"Brute force attempt detected from IP: {ip_address}")
            return jsonify({"error": "Too many login attempts. Try again later."}), 429
        
        # Get user from database
        cursor.execute(
            "SELECT id, username, password_hash FROM users WHERE username = %s",
            (username,)
        )
        user = cursor.fetchone()
        
        if not user:
            # Log failed attempt
            cursor.execute(
                "INSERT INTO security_logs (user_id, event, ip_address) VALUES (NULL, %s, %s)",
                ('failed_login', ip_address)
            )
            conn.commit()
            logging.info(f"Failed login: username '{username}' not found from IP {ip_address}")
            return jsonify({"error": "Invalid credentials"}), 401
        
        user_id, db_username, password_hash = user
        
        # Verify password
        if bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8')):
            # Get user role
            cursor.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            user_role = cursor.fetchone()[0]
            
            # Create session
            session['user_id'] = user_id
            session['username'] = db_username
            session['role'] = user_role
            session['created_at'] = str(datetime.datetime.now())
            
            # Log successful login
            cursor.execute(
                "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
                (user_id, 'successful_login', ip_address)
            )
            conn.commit()
            
            logging.info(f"Successful login: user {db_username} from IP {ip_address}")
            
            return jsonify({
                "message": "Login successful",
                "user": {
                    "id": user_id,
                    "username": db_username,
                    "role": user_role
                }
            })
        else:
            # Log failed password attempt
            cursor.execute(
                "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
                (user_id, 'failed_login', ip_address)
            )
            conn.commit()
            
            logging.info(f"Failed login: wrong password for '{db_username}' from IP {ip_address}")
            return jsonify({"error": "Invalid credentials"}), 401
            
    except Exception as e:
        conn.rollback()
        logging.error(f"Login error: {str(e)}")
        return jsonify({"error": "Login failed"}), 500
    finally:
        cursor.close()
        conn.close()

def logout_user():
    if 'user_id' in session:
        user_id = session['user_id']
        username = session.get('username', 'unknown')
        ip_address = request.remote_addr
        
        # Log logout
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Update user to offline immediately
        cursor.execute(
            "UPDATE users SET is_online = FALSE WHERE id = %s",
            (user_id,)
        )
        conn.commit()
        
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
            (user_id, 'logout', ip_address)
        )
        conn.commit()
        cursor.close()
        conn.close()
        
        logging.info(f"Logout: user {username} from IP {ip_address}")
        
        # Clear session
        session.clear()
        return jsonify({"message": "Logged out successfully"})
    
    return jsonify({"error": "Not logged in"}), 401

def check_session():
    if 'user_id' in session:
        return jsonify({
            "authenticated": True,
            "user": {
                "id": session['user_id'],
                "username": session.get('username'),
                "role": session.get('role')
            }
        })
    return jsonify({"authenticated": False}), 401
