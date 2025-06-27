import sqlite3

conn = sqlite3.connect('database.db')  # Open your existing database file
c = conn.cursor()

try:
    c.execute("ALTER TABLE tasks ADD COLUMN user_id INTEGER")  # Add the column
    print("user_id column added successfully!")
except sqlite3.OperationalError:
    print("user_id column already exists.")

conn.commit()
conn.close()

import sqlite3
conn = sqlite3.connect('database.db')
c = conn.cursor()
c.execute("ALTER TABLE users ADD COLUMN email_updates INTEGER DEFAULT 1;")
c.execute("ALTER TABLE users ADD COLUMN task_reminders INTEGER DEFAULT 1;")
conn.commit()
conn.close()
