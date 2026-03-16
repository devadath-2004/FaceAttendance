import sqlite3

DB_NAME = "attendance.db"

# All 7 periods with their start/end times
PERIODS = [
    {"id": 1, "label": "Period 1", "start": "09:00", "end": "09:50"},
    {"id": 2, "label": "Period 2", "start": "10:00", "end": "10:50"},
    {"id": 3, "label": "Period 3", "start": "11:00", "end": "11:50"},
    {"id": 4, "label": "Period 4", "start": "12:00", "end": "12:50"},
    {"id": 5, "label": "Period 5", "start": "13:40", "end": "14:30"},
    {"id": 6, "label": "Period 6", "start": "14:40", "end": "15:30"},
    {"id": 7, "label": "Period 7", "start": "15:40", "end": "16:30"},
]

def get_connection():
    return sqlite3.connect(DB_NAME)

def init_db():
    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS admins (
        id       INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password TEXT
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id            INTEGER PRIMARY KEY AUTOINCREMENT,
        name          TEXT,
        roll          TEXT UNIQUE,
        class         TEXT,
        department    TEXT,
        face_encoding TEXT
    )""")

    # attendance now has a period column (1–7)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        date       TEXT,
        time       TEXT,
        period     INTEGER DEFAULT 1,
        status     TEXT,
        FOREIGN KEY(student_id) REFERENCES students(id)
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS class_timing (
        id          INTEGER PRIMARY KEY,
        class_start TEXT NOT NULL DEFAULT '09:00',
        grace_mins  INTEGER NOT NULL DEFAULT 10,
        late_mins   INTEGER NOT NULL DEFAULT 30
    )""")

    cur.execute("""
    CREATE TABLE IF NOT EXISTS faculty (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        name       TEXT,
        faculty_id TEXT UNIQUE,
        department TEXT,
        subject    TEXT,
        username   TEXT UNIQUE,
        password   TEXT
    )""")

    # faculty_periods: which periods each faculty teaches on which day
    cur.execute("""
    CREATE TABLE IF NOT EXISTS faculty_periods (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        faculty_id INTEGER,
        day        TEXT,
        period_id  INTEGER,
        FOREIGN KEY(faculty_id) REFERENCES faculty(id),
        UNIQUE(faculty_id, day, period_id)
    )""")

    cur.execute("INSERT OR IGNORE INTO admins (username, password) VALUES ('admin', 'admin123')")
    cur.execute("INSERT OR IGNORE INTO class_timing (id, class_start, grace_mins, late_mins) VALUES (1, '09:00', 10, 30)")

    conn.commit()

    # Safe migrations
    for sql in [
        "ALTER TABLE students ADD COLUMN face_encoding TEXT",
        "ALTER TABLE students ADD COLUMN class TEXT",
        "ALTER TABLE attendance ADD COLUMN period INTEGER DEFAULT 1",
        "ALTER TABLE faculty_periods ADD COLUMN day TEXT DEFAULT 'Monday'",
    ]:
        try:
            cur.execute(sql)
            conn.commit()
        except sqlite3.OperationalError:
            pass

    conn.close()