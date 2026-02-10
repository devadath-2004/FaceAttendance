from flask import Flask, jsonify, request, Response
from flask_cors import CORS
from datetime import datetime
from database import init_db, get_connection
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io

app = Flask(__name__)
CORS(app)
init_db()

# ---------------- HOME ----------------
@app.route("/")
def home():
    return jsonify({"message": "Flask + SQLite running"})

# ---------------- LOGIN ----------------
@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    conn = get_connection()
    cur = conn.cursor()

    cur.execute(
        "SELECT * FROM admins WHERE username=? AND password=?",
        (data.get("username"), data.get("password"))
    )
    admin = cur.fetchone()
    conn.close()

    return jsonify({"success": bool(admin)})

# ---------------- REGISTER STUDENT ----------------
@app.route("/api/register-student", methods=["POST"])
def register_student():
    data = request.json
    try:
        conn = get_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO students (name, roll, department) VALUES (?, ?, ?)",
            (data["name"], data["roll"], data["department"])
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except:
        return jsonify({"success": False, "error": "Student already exists"}), 400

# ---------------- MARK ATTENDANCE ----------------
@app.route("/api/mark-attendance", methods=["POST"])
def mark_attendance():
    data = request.json
    roll = data.get("roll")
    status = data.get("status")

    today = datetime.now().strftime("%Y-%m-%d")
    time_now = datetime.now().strftime("%I:%M %p")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT id FROM students WHERE roll=?", (roll,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    student_id = student[0]

    cur.execute(
        "SELECT * FROM attendance WHERE student_id=? AND date=?",
        (student_id, today)
    )
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "error": "Already marked"}), 400

    cur.execute(
        "INSERT INTO attendance (student_id, date, time, status) VALUES (?, ?, ?, ?)",
        (student_id, today, time_now, status)
    )

    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ---------------- DASHBOARD + ANALYTICS ----------------
@app.route("/api/attendance", methods=["GET"])
def dashboard_data():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cur = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM students")
    total_students = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present'", (date,))
    present = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Late'", (date,))
    late = cur.fetchone()[0]

    cur.execute("SELECT COUNT(*) FROM attendance WHERE date=? AND status='Absent'", (date,))
    absent = cur.fetchone()[0]

    attendance_percent = (
        round(((present + late) / total_students) * 100, 2)
        if total_students > 0 else 0
    )

    cur.execute("""
        SELECT s.name, s.roll,
               COALESCE(a.time, '-') AS time,
               COALESCE(a.status, 'Absent') AS status
        FROM students s
        LEFT JOIN attendance a
        ON s.id = a.student_id AND a.date=?
        ORDER BY s.roll
    """, (date,))

    rows = cur.fetchall()
    conn.close()

    records = [{
        "name": r[0],
        "roll": r[1],
        "time": r[2],
        "status": r[3]
    } for r in rows]

    return jsonify({
        "date": date,
        "total_students": total_students,
        "present": present,
        "late": late,
        "absent": total_students - (present + late),
        "attendance_percent": attendance_percent,
        "records": records
    })

# ---------------- PDF EXPORT ----------------
@app.route("/api/export-pdf", methods=["GET"])
def export_pdf():
    date = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.name, s.roll,
               COALESCE(a.time, '-') AS time,
               COALESCE(a.status, 'Absent') AS status
        FROM students s
        LEFT JOIN attendance a
        ON s.id = a.student_id AND a.date=?
        ORDER BY s.roll
    """, (date,))
    rows = cur.fetchall()
    conn.close()

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, height - 50, "Face Attendance Report")

    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, height - 80, f"Date: {date}")

    y = height - 120
    pdf.setFont("Helvetica", 10)

    for i, r in enumerate(rows, start=1):
        pdf.drawString(50, y, f"{i}. {r[0]} | {r[1]} | {r[2]} | {r[3]}")
        y -= 18
        if y < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = height - 50

    pdf.save()
    buffer.seek(0)

    return Response(
        buffer,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment;filename=attendance_{date}.pdf"}
    )

if __name__ == "__main__":
    app.run(debug=True, port=5000)
