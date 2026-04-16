from flask import request, jsonify, session
from config import get_db_connection
from cryptography.fernet import Fernet
import logging
import os
import sys
import time
from datetime import datetime

# Set up logging
logging.basicConfig(filename='logs/security.log', level=logging.INFO)

# Encryption setup - Use environment variable for key
def get_encryption_key():
    """Load encryption key from environment variable"""
    key = os.environ.get('DAGU_ENCRYPTION_KEY')
    if not key:
        print("❌ CRITICAL ERROR: DAGU_ENCRYPTION_KEY environment variable not set!")
        print("❌ Please set it with: export DAGU_ENCRYPTION_KEY='your_key_here'")
        sys.exit(1)
    return key.encode('utf-8')

# Initialize encryption
cipher = Fernet(get_encryption_key())

def encrypt_message(message):
    """Encrypt a message before storing"""
    return cipher.encrypt(message.encode('utf-8')).decode('utf-8')

def decrypt_message(encrypted_message):
    """Decrypt a message after retrieving"""
    return cipher.decrypt(encrypted_message.encode('utf-8')).decode('utf-8')

def mark_message_delivered(message_id):
    """Mark a message as delivered"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "UPDATE messages SET delivered = TRUE WHERE id = %s",
            (message_id,)
        )
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Error marking message delivered: {str(e)}")
        return False
    finally:
        cursor.close()
        conn.close()

def mark_conversation_seen(other_user_id):
    """Mark all messages from other_user as seen"""
    if 'user_id' not in session:
        return False
    
    current_user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE messages SET seen = TRUE, seen_at = CURRENT_TIMESTAMP 
            WHERE sender_id = %s AND receiver_id = %s AND seen = FALSE
        """, (other_user_id, current_user_id))
        conn.commit()
        return True
    except Exception as e:
        logging.error(f"Error marking conversation seen: {str(e)}")
        return False
    finally:
        cursor.close()
        conn.close()

def update_user_status():
    """Update user's last seen and online status"""
    if 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            user_id = session['user_id']
            cursor.execute(
                "UPDATE users SET last_seen = CURRENT_TIMESTAMP, is_online = TRUE WHERE id = %s",
                (user_id,)
            )
            conn.commit()
            print(f"[DEBUG] Updated status for user {user_id}")
        except Exception as e:
            logging.error(f"Error updating status: {str(e)}")
        finally:
            cursor.close()
            conn.close()

def get_user_status(user_id):
    """Get user's online status and last seen based on actual last_seen time"""
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "SELECT last_seen FROM users WHERE id = %s",
            (user_id,)
        )
        result = cursor.fetchone()
        if result and result[0]:
            last_seen = result[0]
            now = datetime.now()
            diff = now - last_seen
            
            # User is online only if last_seen was within last 30 seconds
            is_online = diff.total_seconds() < 30
            
            # Format last seen string
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
                if days == 1:
                    last_seen_str = "Yesterday"
                else:
                    last_seen_str = f"{days} days ago"
            
            return {"online": is_online, "last_seen": last_seen_str}
        return {"online": False, "last_seen": "Unknown"}
    except Exception as e:
        logging.error(f"Error getting user status: {str(e)}")
        return {"online": False, "last_seen": "Unknown"}
    finally:
        cursor.close()
        conn.close()

def get_users():
    """Get list of all users (except current user)"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    current_user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id, username, avatar, last_seen FROM users WHERE id != %s ORDER BY username",
            (current_user_id,)
        )
        users = cursor.fetchall()
        
        user_list = []
        for user in users:
            user_id = user[0]
            username = user[1]
            avatar = user[2]
            last_seen = user[3]
            
            # Calculate online status based on last_seen
            is_online = False
            if last_seen:
                now = datetime.now()
                diff = now - last_seen
                if diff.total_seconds() < 30:
                    is_online = True
            
            avatar_url = f"/static/uploads/avatars/{avatar}" if avatar else "/static/images/default-avatar.png"
            
            user_list.append({
                "id": user_id,
                "username": username,
                "online": is_online,
                "avatar_url": avatar_url
            })
        
        return jsonify({"users": user_list})
    
    except Exception as e:
        logging.error(f"Error fetching users: {str(e)}")
        return jsonify({"error": "Failed to fetch users"}), 500
    finally:
        cursor.close()
        conn.close()

def send_message():
    """Send an encrypted message to another user"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    receiver_id = data.get("receiver_id")
    message_text = data.get("message")
    
    if not receiver_id or not message_text:
        return jsonify({"error": "Missing receiver_id or message"}), 400
    
    message_text = message_text.strip()
    if len(message_text) > 1000:
        return jsonify({"error": "Message too long"}), 400
    
    sender_id = session['user_id']
    
    try:
        encrypted_message = encrypt_message(message_text)
    except Exception as e:
        logging.error(f"Encryption failed: {str(e)}")
        return jsonify({"error": "Message encryption failed"}), 500
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("SELECT id FROM users WHERE id = %s", (receiver_id,))
        if not cursor.fetchone():
            return jsonify({"error": "Receiver not found"}), 404
        
        cursor.execute(
            "INSERT INTO messages (sender_id, receiver_id, encrypted_message, delivered, seen) VALUES (%s, %s, %s, %s, %s)",
            (sender_id, receiver_id, encrypted_message, False, False)
        )
        conn.commit()
        
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
            (sender_id, 'message_sent', request.remote_addr)
        )
        conn.commit()
        
        logging.info(f"Message sent from user {sender_id} to user {receiver_id}")
        
        return jsonify({"message": "Message sent successfully"})
    
    except Exception as e:
        conn.rollback()
        logging.error(f"Error sending message: {str(e)}")
        return jsonify({"error": "Failed to send message"}), 500
    finally:
        cursor.close()
        conn.close()

def get_messages():
    """Get conversation with another user"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    other_user_id = request.args.get('user_id')
    if not other_user_id:
        return jsonify({"error": "Missing user_id parameter"}), 400
    
    current_user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT m.id, m.sender_id, m.encrypted_message, m.timestamp,
                   u_sender.username as sender_name,
                   u_receiver.username as receiver_name,
                   m.delivered, m.seen
            FROM messages m
            JOIN users u_sender ON m.sender_id = u_sender.id
            JOIN users u_receiver ON m.receiver_id = u_receiver.id
            WHERE (m.sender_id = %s AND m.receiver_id = %s)
               OR (m.sender_id = %s AND m.receiver_id = %s)
            ORDER BY m.timestamp ASC
        """, (current_user_id, int(other_user_id), int(other_user_id), current_user_id))
        
        messages = cursor.fetchall()
        
        # Get reactions for messages
        message_ids = [msg[0] for msg in messages]
        reactions_dict = {}
        
        if message_ids:
            cursor.execute("""
                SELECT message_id, reaction, user_id
                FROM message_reactions
                WHERE message_id = ANY(%s)
            """, (message_ids,))
            
            for row in cursor.fetchall():
                msg_id = row[0]
                if msg_id not in reactions_dict:
                    reactions_dict[msg_id] = []
                reactions_dict[msg_id].append({
                    "reaction": row[1],
                    "user_id": row[2]
                })
        
        conversation = []
        for msg in messages:
            try:
                decrypted_text = decrypt_message(msg[2])
                
                msg_reactions = reactions_dict.get(msg[0], [])
                reaction_summary = {}
                user_reacted_list = []
                for r in msg_reactions:
                    reaction_summary[r['reaction']] = reaction_summary.get(r['reaction'], 0) + 1
                    if r['user_id'] == current_user_id:
                        user_reacted_list.append(r['reaction'])
                
                conversation.append({
                    "id": msg[0],
                    "sender_id": msg[1],
                    "sender_name": msg[4],
                    "message": decrypted_text,
                    "timestamp": msg[3].isoformat() if msg[3] else None,
                    "is_me": msg[1] == current_user_id,
                    "delivered": msg[6] if len(msg) > 6 else False,
                    "seen": msg[7] if len(msg) > 7 else False,
                    "reactions": reaction_summary,
                    "user_reacted": user_reacted_list
                })
            except Exception as e:
                logging.error(f"Failed to decrypt message {msg[0]}: {str(e)}")
                continue
        
        mark_conversation_seen(int(other_user_id))
        
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
            (current_user_id, 'viewed_conversation', request.remote_addr)
        )
        conn.commit()
        
        return jsonify({
            "conversation": conversation,
            "with_user": int(other_user_id)
        })
    
    except Exception as e:
        logging.error(f"Error retrieving messages: {str(e)}")
        return jsonify({"error": f"Failed to retrieve messages: {str(e)}"}), 500
    finally:
        cursor.close()
        conn.close()

def get_conversations():
    """Get list of users the current user has conversed with"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    current_user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT DISTINCT 
                u.id,
                u.username,
                u.last_seen,
                u.avatar,
                (SELECT encrypted_message FROM messages 
                 WHERE (sender_id = %s AND receiver_id = u.id) 
                    OR (sender_id = u.id AND receiver_id = %s)
                 ORDER BY timestamp DESC LIMIT 1) as last_encrypted,
                (SELECT timestamp FROM messages 
                 WHERE (sender_id = %s AND receiver_id = u.id) 
                    OR (sender_id = u.id AND receiver_id = %s)
                 ORDER BY timestamp DESC LIMIT 1) as last_time
            FROM users u
            WHERE u.id != %s
            AND EXISTS (
                SELECT 1 FROM messages 
                WHERE (sender_id = %s AND receiver_id = u.id) 
                   OR (sender_id = u.id AND receiver_id = %s)
            )
            ORDER BY last_time DESC
        """, (current_user_id, current_user_id, current_user_id, current_user_id, 
              current_user_id, current_user_id, current_user_id))
        
        conversations = []
        for row in cursor.fetchall():
            last_message = ""
            if row[4]:
                try:
                    last_message = decrypt_message(row[4])
                    last_message = last_message[:50] + "..." if len(last_message) > 50 else last_message
                except:
                    last_message = "[Encrypted message]"
            
            last_seen_time = row[2]
            
            # Calculate online status based on last_seen (30 seconds threshold)
            is_online = False
            if last_seen_time:
                now = datetime.now()
                diff = now - last_seen_time
                if diff.total_seconds() < 30:
                    is_online = True
            
            # Format last seen display string
            last_seen_str = None
            if last_seen_time:
                now = datetime.now()
                diff = now - last_seen_time
                if diff.total_seconds() < 60:
                    last_seen_str = "online"
                elif diff.total_seconds() < 3600:
                    minutes = int(diff.total_seconds() / 60)
                    last_seen_str = f"active {minutes} min ago"
                elif diff.total_seconds() < 86400:
                    hours = int(diff.total_seconds() / 3600)
                    last_seen_str = f"active {hours} hour{'s' if hours > 1 else ''} ago"
                else:
                    days = int(diff.total_seconds() / 86400)
                    if days == 1:
                        last_seen_str = "active yesterday"
                    else:
                        last_seen_str = f"active {days} days ago"
            else:
                last_seen_str = "offline"
            
            # Build avatar URL
            avatar_url = f"/static/uploads/avatars/{row[3]}" if row[3] else "/static/images/default-avatar.png"
            
            conversations.append({
                "user_id": row[0],
                "username": row[1],
                "online": is_online,
                "last_seen": last_seen_str,
                "avatar_url": avatar_url,
                "last_message": last_message,
                "last_time": row[5].isoformat() if row[5] else None
            })
        
        return jsonify({"conversations": conversations})
    
    except Exception as e:
        logging.error(f"Error fetching conversations: {str(e)}")
        return jsonify({"error": "Failed to fetch conversations"}), 500
    finally:
        cursor.close()
        conn.close()

def search_users():
    """Search for users by username"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    query = request.args.get('q', '')
    current_user_id = session['user_id']
    
    if len(query) < 2:
        return jsonify({"users": []})
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            "SELECT id, username, last_seen, avatar FROM users WHERE id != %s AND username ILIKE %s LIMIT 10",
            (current_user_id, f'%{query}%')
        )
        users = cursor.fetchall()
        
        user_list = []
        for user in users:
            user_id = user[0]
            username = user[1]
            last_seen = user[2]
            avatar = user[3]
            
            # Calculate online status based on last_seen
            is_online = False
            last_seen_str = None
            
            if last_seen:
                now = datetime.now()
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
                    if days == 1:
                        last_seen_str = "Yesterday"
                    else:
                        last_seen_str = f"{days} days ago"
            
            avatar_url = f"/static/uploads/avatars/{avatar}" if avatar else "/static/images/default-avatar.png"
            
            user_list.append({
                "id": user_id,
                "username": username,
                "online": is_online,
                "last_seen": last_seen_str,
                "avatar_url": avatar_url
            })
        
        return jsonify({"users": user_list})
    except Exception as e:
        logging.error(f"Error searching users: {str(e)}")
        return jsonify({"error": "Search failed"}), 500
    finally:
        cursor.close()
        conn.close()

def add_reaction():
    """Add or update a reaction to a message"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    message_id = data.get('message_id')
    reaction = data.get('reaction')
    
    if not message_id or not reaction:
        return jsonify({"error": "Missing message_id or reaction"}), 400
    
    user_id = session['user_id']
    
    # Validate reaction emoji
    valid_reactions = ['👍', '❤️', '😂', '😮', '😢', '😡', '👎', '🎉', '🔥', '💯']
    if reaction not in valid_reactions:
        return jsonify({"error": "Invalid reaction"}), 400
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check if message exists and user is part of conversation
        cursor.execute("""
            SELECT sender_id, receiver_id FROM messages WHERE id = %s
        """, (message_id,))
        msg = cursor.fetchone()
        
        if not msg:
            return jsonify({"error": "Message not found"}), 404
        
        # Check if user is part of the conversation
        if user_id not in (msg[0], msg[1]):
            return jsonify({"error": "Unauthorized"}), 403
        
        # Upsert reaction (insert or update)
        cursor.execute("""
            INSERT INTO message_reactions (message_id, user_id, reaction)
            VALUES (%s, %s, %s)
            ON CONFLICT (message_id, user_id)
            DO UPDATE SET reaction = EXCLUDED.reaction
            RETURNING id
        """, (message_id, user_id, reaction))
        
        conn.commit()
        
        # Log the event
        cursor.execute(
            "INSERT INTO security_logs (user_id, event, ip_address) VALUES (%s, %s, %s)",
            (user_id, f'reacted_to_message_{reaction}', request.remote_addr)
        )
        conn.commit()
        
        return jsonify({"message": "Reaction added", "reaction": reaction})
    
    except Exception as e:
        conn.rollback()
        logging.error(f"Error adding reaction: {str(e)}")
        return jsonify({"error": "Failed to add reaction"}), 500
    finally:
        cursor.close()
        conn.close()

def remove_reaction():
    """Remove a reaction from a message"""
    if 'user_id' not in session:
        return jsonify({"error": "Not authenticated"}), 401
    
    data = request.json
    message_id = data.get('message_id')
    
    if not message_id:
        return jsonify({"error": "Missing message_id"}), 400
    
    user_id = session['user_id']
    
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            DELETE FROM message_reactions
            WHERE message_id = %s AND user_id = %s
        """, (message_id, user_id))
        conn.commit()
        
        return jsonify({"message": "Reaction removed"})
    
    except Exception as e:
        conn.rollback()
        logging.error(f"Error removing reaction: {str(e)}")
        return jsonify({"error": "Failed to remove reaction"}), 500
    finally:
        cursor.close()
        conn.close()

def get_current_user_avatar():
    """Get current user's avatar URL"""
    if 'user_id' in session:
        conn = get_db_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT avatar FROM users WHERE id = %s", (session['user_id'],))
            result = cursor.fetchone()
            if result and result[0]:
                return f"/static/uploads/avatars/{result[0]}"
        except Exception as e:
            logging.error(f"Error getting avatar: {str(e)}")
        finally:
            cursor.close()
            conn.close()
    return "/static/images/default-avatar.png"

def get_message_reactions(message_id):
    """Get all reactions for a message"""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute("""
            SELECT reaction, COUNT(*) as count, array_agg(user_id) as users
            FROM message_reactions
            WHERE message_id = %s
            GROUP BY reaction
        """, (message_id,))
        
        reactions = []
        for row in cursor.fetchall():
            reactions.append({
                "reaction": row[0],
                "count": row[1],
                "users": row[2]
            })
        
        return jsonify({"reactions": reactions})
    
    except Exception as e:
        logging.error(f"Error getting reactions: {str(e)}")
        return jsonify({"error": "Failed to get reactions"}), 500
    finally:
        cursor.close()
        conn.close()
