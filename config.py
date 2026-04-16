import psycopg2

def get_db_connection():
    conn = psycopg2.connect(
        host="localhost",
        database="dagu",
        user="postgres",
        password="2190"  # Use the password you set
    )
    return conn
