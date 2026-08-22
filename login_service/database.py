import sqlite3  #python pre intalled , this function connects to our database file
import os

# Create data directory if it doesn't exist
os.makedirs('/app/data', exist_ok=True)

def get_db_connection(): #command helps us to open/connect to users.db
    conn = sqlite3.connect('/app/data/users.db')  #connects to the database file named users.db
    conn.row_factory = sqlite3.Row  #this allows us to access the columns of the database by name instead of index like in tuples 
    return conn  
#------to create user table ---
def create_users_table():
    conn=get_db_connection() #connect to the database function we made above
    #SQL query will now create table if it doesnt exist with username , password and role 
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,   -- unique username
            password TEXT NOT NULL,      -- hashed password
            role TEXT NOT NULL           -- student or teacher
        )
    """)
    conn.commit() # save changes
    conn.close() #this is imp to avoid database locks
    