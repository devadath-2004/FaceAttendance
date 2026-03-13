from flask import Flask, jsonify, request, Response, send_from_directory
from flask_cors import CORS
from datetime import datetime
from database import init_db, get_connection, PERIODS
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import io, base64, os
import numpy as np
import cv2
from PIL import Image
import torch
from facenet_pytorch import MTCNN, InceptionResnetV1

FRONTEND_FOLDER = os.path.join(os.path.dirname(__file__), "..", "frondend")
app = Flask(__name__, static_folder=FRONTEND_FOLDER, static_url_path="")
CORS(app)
init_db()

# ── FaceNet model ──────────────────────────────────────────────
device = "cuda" if torch.cuda.is_available() else "cpu"
mtcnn  = MTCNN(image_size=160, margin=20, keep_all=False, device=device)
resnet = InceptionResnetV1(pretrained="vggface2").eval().to(device)
print(f"[FaceNet] Running on {device.upper()}")

# ── Period helpers ─────────────────────────────────────────────
def get_current_period():
    """Return the period dict that is currently active, or None if between periods."""
    now     = datetime.now()
    now_min = now.hour * 60 + now.minute
    for p in PERIODS:
        sh, sm = map(int, p["start"].split(":"))
        eh, em = map(int, p["end"].split(":"))
        if sh * 60 + sm <= now_min <= eh * 60 + em:
            return p
    return None

def get_period_status(period):
    """
    Given a period dict, return Present / Late / Absent based on
    how many minutes after period start the student arrived.
    Grace = 10 min  →  Present
    10–20 min late  →  Late
    After that      →  Absent
    """
    now     = datetime.now()
    now_min = now.hour * 60 + now.minute
    sh, sm  = map(int, period["start"].split(":"))
    diff    = now_min - (sh * 60 + sm)

    if diff <= 10:
        return "Present"
    elif diff <= 20:
        return "Late"
    else:
        return "Absent"

# ── Face helpers ───────────────────────────────────────────────
def get_embedding_from_b64(b64):
    if "," in b64:
        b64 = b64.split(",")[1]
    arr    = np.frombuffer(base64.b64decode(b64), dtype=np.uint8)
    bgr    = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    rgb    = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    tensor = mtcnn(Image.fromarray(rgb))
    if tensor is None:
        return None
    with torch.no_grad():
        emb = resnet(tensor.unsqueeze(0).to(device))
    return emb.squeeze().cpu().numpy()

def emb_to_str(e):  return ",".join(map(str, e.tolist()))
def str_to_emb(s):  return np.array(list(map(float, s.split(","))))
def cosine(a, b):   return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))

# ── Serve frontend ─────────────────────────────────────────────
@app.route("/", defaults={"path": "index.html"})
@app.route("/<path:path>")
def serve_frontend(path):
    if path.startswith("api/"):
        return jsonify({"error": "Not found"}), 404
    return send_from_directory(FRONTEND_FOLDER, path)

# ── Login (admin OR faculty) ───────────────────────────────────
@app.route("/api/login", methods=["POST"])
def login():
    d    = request.json
    conn = get_connection()
    cur  = conn.cursor()

    # Check admin first
    cur.execute("SELECT * FROM admins WHERE username=? AND password=?",
                (d.get("username"), d.get("password")))
    if cur.fetchone():
        conn.close()
        return jsonify({"success": True, "role": "admin", "name": "Admin", "periods": []})

    # Check faculty
    cur.execute("SELECT id, name FROM faculty WHERE username=? AND password=?",
                (d.get("username"), d.get("password")))
    faculty = cur.fetchone()
    if not faculty:
        conn.close()
        return jsonify({"success": False})

    faculty_db_id = faculty[0]
    faculty_name  = faculty[1]

    # Get assigned periods
    cur.execute("SELECT period_id FROM faculty_periods WHERE faculty_id=?", (faculty_db_id,))
    assigned = [row[0] for row in cur.fetchall()]
    conn.close()

    return jsonify({
        "success": True,
        "role":    "faculty",
        "name":    faculty_name,
        "id":      faculty_db_id,
        "periods": assigned      # e.g. [1, 3]
    })

# ── Get all faculty (for admin panel) ─────────────────────────
@app.route("/api/faculty", methods=["GET"])
def get_faculty():
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, faculty_id, department, subject FROM faculty")
    rows = cur.fetchall()

    result = []
    for r in rows:
        cur.execute("SELECT period_id FROM faculty_periods WHERE faculty_id=?", (r[0],))
        periods = [p[0] for p in cur.fetchall()]
        result.append({
            "id": r[0], "name": r[1], "faculty_id": r[2],
            "department": r[3], "subject": r[4], "periods": periods
        })
    conn.close()
    return jsonify({"faculty": result})

# ── Assign periods to faculty (admin only) ─────────────────────
@app.route("/api/assign-periods", methods=["POST"])
def assign_periods():
    d          = request.json
    faculty_id = d.get("faculty_id")   # DB id of faculty
    periods    = d.get("periods", [])  # list of period ids e.g. [1,3]

    conn = get_connection()
    cur  = conn.cursor()

    # Clear existing assignments and re-insert
    cur.execute("DELETE FROM faculty_periods WHERE faculty_id=?", (faculty_id,))
    for pid in periods:
        cur.execute(
            "INSERT OR IGNORE INTO faculty_periods (faculty_id, period_id) VALUES (?,?)",
            (faculty_id, int(pid))
        )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ── Register faculty ───────────────────────────────────────────
@app.route("/api/register-faculty", methods=["POST"])
def register_faculty():
    d = request.json
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO faculty (name, faculty_id, department, subject, username, password)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (d["name"], d["faculty_id"], d["department"], d["subject"],
              d["username"], d["password"]))
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except:
        return jsonify({"success": False, "error": "Faculty ID or username already exists"}), 400

# ── Periods list ───────────────────────────────────────────────
@app.route("/api/periods", methods=["GET"])
def get_periods():
    current = get_current_period()
    return jsonify({
        "periods":        PERIODS,
        "current_period": current
    })

# ── Register student ───────────────────────────────────────────
@app.route("/api/register-student", methods=["POST"])
def register_student():
    d = request.json
    try:
        conn = get_connection()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO students (name, roll, class, department) VALUES (?, ?, ?, ?)",
            (d["name"], d["roll"], d["class"], d["department"])
        )
        conn.commit()
        conn.close()
        return jsonify({"success": True})
    except:
        return jsonify({"success": False, "error": "Student already exists"}), 400

# ── Register face ──────────────────────────────────────────────
@app.route("/api/register-face", methods=["POST"])
def register_face():
    d    = request.json
    roll = d.get("roll")
    img  = d.get("image")
    if not roll or not img:
        return jsonify({"success": False, "error": "Missing data"}), 400
    emb = get_embedding_from_b64(img)
    if emb is None:
        return jsonify({"success": False, "error": "No face detected. Try again."}), 400
    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("UPDATE students SET face_encoding=? WHERE roll=?", (emb_to_str(emb), roll))
    if cur.rowcount == 0:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404
    conn.commit()
    conn.close()
    return jsonify({"success": True, "message": "Face registered"})

# ── Recognize face + period-wise attendance ────────────────────
@app.route("/api/recognize-face", methods=["POST"])
def recognize_face():
    d   = request.json
    img = d.get("image")
    period_id = int(d.get("period_id", 0))   # sent from frontend

    if not img:
        return jsonify({"success": False, "error": "No image"}), 400

    incoming = get_embedding_from_b64(img)
    if incoming is None:
        return jsonify({"success": False, "error": "No face detected"}), 200

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id, name, roll, face_encoding FROM students WHERE face_encoding IS NOT NULL")
    students = cur.fetchall()
    conn.close()

    if not students:
        return jsonify({"success": False, "error": "No registered faces"}), 400

    # Match
    best_score, best_idx = -1, -1
    for i, s in enumerate(students):
        score = cosine(incoming, str_to_emb(s[3]))
        if score > best_score:
            best_score, best_idx = score, i

    if best_score < 0.7:
        return jsonify({"success": False, "error": "Face not recognised"}), 200

    student_id   = students[best_idx][0]
    student_name = students[best_idx][1]
    student_roll = students[best_idx][2]
    confidence   = round(best_score * 100, 1)

    # Find period
    period = next((p for p in PERIODS if p["id"] == period_id), None)
    if period is None:
        period = get_current_period()
    if period is None:
        return jsonify({"success": False, "error": "No active period right now"}), 400

    auto_status = get_period_status(period)
    today       = datetime.now().strftime("%Y-%m-%d")
    time_now    = datetime.now().strftime("%I:%M %p")

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute(
        "SELECT status FROM attendance WHERE student_id=? AND date=? AND period=?",
        (student_id, today, period["id"])
    )
    existing = cur.fetchone()

    if existing:
        conn.close()
        return jsonify({
            "success": True, "already_marked": True,
            "name": student_name, "roll": student_roll,
            "confidence": confidence, "status": existing[0],
            "period": period["label"], "time": time_now
        })

    cur.execute(
        "INSERT INTO attendance (student_id, date, time, period, status) VALUES (?, ?, ?, ?, ?)",
        (student_id, today, time_now, period["id"], auto_status)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "success": True, "already_marked": False,
        "name": student_name, "roll": student_roll,
        "confidence": confidence, "status": auto_status,
        "period": period["label"], "time": time_now
    })

# ── Update attendance (admin edit, frozen after 5 days) ───────
@app.route("/api/update-attendance", methods=["POST"])
def update_attendance():
    d         = request.json
    roll      = d.get("roll")
    date      = d.get("date")
    period_id = int(d.get("period_id", 1))
    new_status = d.get("status")

    # Check freeze: date must be within 5 days of today
    try:
        record_date = datetime.strptime(date, "%Y-%m-%d").date()
        today       = datetime.now().date()
        delta       = (today - record_date).days
        if delta > 5:
            return jsonify({"success": False, "error": "Record is frozen. Edits are only allowed within 5 days."}), 403
    except:
        return jsonify({"success": False, "error": "Invalid date"}), 400

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM students WHERE roll=?", (roll,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    student_id = student[0]
    time_now   = datetime.now().strftime("%I:%M %p")

    # Update if exists, insert if not
    cur.execute(
        "SELECT id FROM attendance WHERE student_id=? AND date=? AND period=?",
        (student_id, date, period_id)
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            "UPDATE attendance SET status=? WHERE student_id=? AND date=? AND period=?",
            (new_status, student_id, date, period_id)
        )
    else:
        cur.execute(
            "INSERT INTO attendance (student_id, date, time, period, status) VALUES (?,?,?,?,?)",
            (student_id, date, time_now, period_id, new_status)
        )

    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ── Mark attendance manually ───────────────────────────────────
@app.route("/api/mark-attendance", methods=["POST"])
def mark_attendance():
    d         = request.json
    roll      = d.get("roll")
    status    = d.get("status")
    period_id = int(d.get("period_id", 1))

    today    = datetime.now().strftime("%Y-%m-%d")
    time_now = datetime.now().strftime("%I:%M %p")

    conn = get_connection()
    cur  = conn.cursor()
    cur.execute("SELECT id FROM students WHERE roll=?", (roll,))
    student = cur.fetchone()
    if not student:
        conn.close()
        return jsonify({"success": False, "error": "Student not found"}), 404

    student_id = student[0]
    cur.execute(
        "SELECT * FROM attendance WHERE student_id=? AND date=? AND period=?",
        (student_id, today, period_id)
    )
    if cur.fetchone():
        conn.close()
        return jsonify({"success": False, "error": "Already marked for this period"}), 400

    cur.execute(
        "INSERT INTO attendance (student_id, date, time, period, status) VALUES (?, ?, ?, ?, ?)",
        (student_id, today, time_now, period_id, status)
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

# ── Attendance summary per student (for 75% alert) ────────────
@app.route("/api/attendance-summary", methods=["GET"])
def attendance_summary():
    """
    Returns each student's overall attendance percentage
    across all periods and all dates.
    Flags students below the threshold (default 75%).
    """
    threshold = float(request.args.get("threshold", 75))

    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT id, name, roll, class, department FROM students")
    students = cur.fetchall()

    # Total possible attendance slots =
    # number of distinct (date, period) combinations that have been recorded
    cur.execute("""
        SELECT COUNT(DISTINCT date || '-' || period) FROM attendance
    """)
    total_slots = cur.fetchone()[0] or 0

    summary = []
    for s in students:
        student_id = s[0]

        # Count Present + Late as attended
        cur.execute("""
            SELECT COUNT(*) FROM attendance
            WHERE student_id=? AND status IN ('Present','Late')
        """, (student_id,))
        attended = cur.fetchone()[0]

        cur.execute("""
            SELECT COUNT(*) FROM attendance WHERE student_id=?
        """, (student_id,))
        total_marked = cur.fetchone()[0]

        # Use total_slots as denominator if available, else total_marked
        denominator = total_slots if total_slots > 0 else total_marked
        percentage  = round((attended / denominator) * 100, 1) if denominator > 0 else 0

        summary.append({
            "name":        s[1],
            "roll":        s[2],
            "class":       s[3] or "—",
            "department":  s[4] or "—",
            "attended":    attended,
            "total":       denominator,
            "percentage":  percentage,
            "below":       percentage < threshold,
            "critical":    percentage < 60   # critically low
        })

    conn.close()

    # Sort: critical first, then below threshold, then rest
    summary.sort(key=lambda x: x["percentage"])

    below_count = sum(1 for s in summary if s["below"])

    return jsonify({
        "threshold":   threshold,
        "total_slots": total_slots,
        "students":    summary,
        "below_count": below_count
    })

# ── Attendance summary per student (for 75% alert) ────────────
@app.route("/api/attendance", methods=["GET"])
def dashboard_data():
    date      = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    period_id = request.args.get("period")   # optional filter

    conn = get_connection()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM students")
    total_students = cur.fetchone()[0]

    period_filter = f"AND period={int(period_id)}" if period_id else ""

    cur.execute(f"SELECT COUNT(*) FROM attendance WHERE date=? AND status='Present' {period_filter}", (date,))
    present = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM attendance WHERE date=? AND status='Late' {period_filter}", (date,))
    late = cur.fetchone()[0]

    attendance_percent = round(((present + late) / total_students) * 100, 2) if total_students > 0 else 0

    if period_id:
        cur.execute("""
            SELECT s.name, s.roll, s.class,
                   COALESCE(a.time, '-'),
                   COALESCE(a.status, 'Absent'),
                   COALESCE(a.period, 0)
            FROM students s
            LEFT JOIN attendance a
              ON s.id = a.student_id AND a.date=? AND a.period=?
            ORDER BY s.roll
        """, (date, int(period_id)))
    else:
        cur.execute("""
            SELECT s.name, s.roll, s.class,
                   COALESCE(a.time, '-'),
                   COALESCE(a.status, 'Absent'),
                   COALESCE(a.period, 0)
            FROM students s
            LEFT JOIN attendance a ON s.id = a.student_id AND a.date=?
            ORDER BY s.roll, a.period
        """, (date,))

    rows = cur.fetchall()
    conn.close()

    return jsonify({
        "date": date,
        "total_students": total_students,
        "present": present,
        "late": late,
        "absent": total_students - (present + late),
        "attendance_percent": attendance_percent,
        "periods": PERIODS,
        "records": [{
            "name": r[0], "roll": r[1], "class": r[2],
            "time": r[3], "status": r[4],
            "period": next((p["label"] for p in PERIODS if p["id"] == r[5]), "—")
        } for r in rows]
    })

# ── CSV export ─────────────────────────────────────────────────
@app.route("/api/export-csv", methods=["GET"])
def export_csv():
    date      = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    period_id = request.args.get("period")

    conn = get_connection()
    cur  = conn.cursor()
    if period_id:
        cur.execute("""
            SELECT s.name, s.roll, s.class, s.department,
                   COALESCE(a.time,'-'), COALESCE(a.status,'Absent'), a.period
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id AND a.date=? AND a.period=?
            ORDER BY s.roll
        """, (date, int(period_id)))
    else:
        cur.execute("""
            SELECT s.name, s.roll, s.class, s.department,
                   COALESCE(a.time,'-'), COALESCE(a.status,'Absent'), a.period
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id AND a.date=?
            ORDER BY s.roll, a.period
        """, (date,))
    rows = cur.fetchall()
    conn.close()

    lines = ["Name,Roll,Class,Department,Time,Status,Period"]
    for r in rows:
        period_label = next((p["label"] for p in PERIODS if p["id"] == r[6]), "—")
        lines.append(f"{r[0]},{r[1]},{r[2]},{r[3]},{r[4]},{r[5]},{period_label}")

    return Response("\n".join(lines), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=attendance_{date}.csv"})

# ── PDF export ─────────────────────────────────────────────────
@app.route("/api/export-pdf", methods=["GET"])
def export_pdf():
    date      = request.args.get("date") or datetime.now().strftime("%Y-%m-%d")
    period_id = request.args.get("period")

    conn = get_connection()
    cur  = conn.cursor()
    if period_id:
        cur.execute("""
            SELECT s.name, s.roll,
                   COALESCE(a.time,'-'), COALESCE(a.status,'Absent'), a.period
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id AND a.date=? AND a.period=?
            ORDER BY s.roll
        """, (date, int(period_id)))
    else:
        cur.execute("""
            SELECT s.name, s.roll,
                   COALESCE(a.time,'-'), COALESCE(a.status,'Absent'), a.period
            FROM students s
            LEFT JOIN attendance a ON s.id=a.student_id AND a.date=?
            ORDER BY s.roll, a.period
        """, (date,))
    rows = cur.fetchall()
    conn.close()

    buffer = io.BytesIO()
    pdf    = canvas.Canvas(buffer, pagesize=A4)
    w, h   = A4

    period_label = next((p["label"] for p in PERIODS if p["id"] == int(period_id)), "All Periods") if period_id else "All Periods"

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(50, h - 50, "Face Attendance Report")
    pdf.setFont("Helvetica", 12)
    pdf.drawString(50, h - 75, f"Date: {date}   |   {period_label}")

    y = height = h - 115
    pdf.setFont("Helvetica-Bold", 10)
    pdf.drawString(50, y, "#   Name                Roll        Time        Status      Period")
    y -= 20
    pdf.setFont("Helvetica", 10)

    for i, r in enumerate(rows, 1):
        pl = next((p["label"] for p in PERIODS if p["id"] == r[4]), "—")
        pdf.drawString(50, y, f"{i:<4}{r[0]:<20}{r[1]:<12}{r[2]:<12}{r[3]:<12}{pl}")
        y -= 18
        if y < 50:
            pdf.showPage()
            pdf.setFont("Helvetica", 10)
            y = h - 50

    pdf.save()
    buffer.seek(0)
    return Response(buffer, mimetype="application/pdf",
                    headers={"Content-Disposition": f"attachment;filename=attendance_{date}.pdf"})

if __name__ == "__main__":
    app.run(debug=True, port=5000)