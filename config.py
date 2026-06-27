import os
import psycopg2

def get_db_connection():
    """
    Return a PostgreSQL connection using the Render DATABASE_URL environment variable.
    """
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL environment variable not set!")
    
    # Connect using the full DSN (including sslmode=require for Render)
    conn = psycopg2.connect(dsn=database_url, sslmode='require')
    return conn
