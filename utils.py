# utils.py
import hashlib
import oracledb

# ---------------- Oracle DB Credentials ----------------
DB_USER = "system"
DB_PASSWORD = "system"
DB_DSN = "localhost/XEPDB1"

# Connect to Oracle DB
def get_connection():
    return oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)

# Hash password
def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

# Verify login
def verify_login(username, password):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT password_hash, role FROM Users WHERE username=:1", (username,))
    result = cursor.fetchone()
    conn.close()
    if result:
        stored_hash, role = result
        if stored_hash == hash_password(password):
            return True, role
    return False, None
