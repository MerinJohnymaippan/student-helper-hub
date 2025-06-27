from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
import openai
import sqlite3
from datetime import datetime, date
import os
import random
from werkzeug.utils import secure_filename
from dotenv import load_dotenv
import base64
from PIL import Image
# 👇 you already imported these, so you’re fine:
from itsdangerous import URLSafeTimedSerializer, SignatureExpired, BadSignature
from flask_mail import Mail, Message
import google.generativeai as genai
from flask_mail import Mail

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
print("EMAIL:", os.environ.get("MAIL_USERNAME"))


model = genai.GenerativeModel(model_name="models/gemini-1.5-flash-002")

# ─────────────────────────────────────────────────────────
# 1)  Create the Flask app FIRST … (this is already here)
# ─────────────────────────────────────────────────────────
app = Flask(__name__)
app.secret_key = 'your_secret_key_here'   # keep this line

# ─────────────────────────────────────────────────────────
# 2)  NOW add the “Step 1” mail + token setup **RIGHT HERE**
#     (immediately after app creation, before any routes)
# ─────────────────────────────────────────────────────────
# --- Mail configuration (tweak if you use a different SMTP) ---
app.config.update(
    MAIL_SERVER=os.environ.get("MAIL_SERVER"),
    MAIL_PORT=int(os.environ.get("MAIL_PORT")),
    MAIL_USE_TLS=os.environ.get("MAIL_USE_TLS") == "true",
    MAIL_USERNAME=os.environ.get("MAIL_USERNAME"),
    MAIL_PASSWORD=os.environ.get("MAIL_PASSWORD"),
)
app.config["MAIL_DEFAULT_SENDER"] = os.environ.get("MAIL_DEFAULT_SENDER")

mail = Mail(app)

# --- Single global serializer for reset tokens ---
s = URLSafeTimedSerializer(app.secret_key)

# ─────────────────────────────────────────────────────────
# 3)  Nothing else changes; keep the rest of your code,
#     routes, helpers, etc. exactly as‑is under this point.
# ─────────────────────────────────────────────────────────



UPLOAD_FOLDER = 'static/uploads'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'docx', 'xlsx', 'pptx', 'txt'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def init_db():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT NOT NULL UNIQUE,
            password TEXT NOT NULL
        )
    ''')
    # existing task/note/resource table creation here...
    c.execute('''
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            description TEXT,
            due_date TEXT,
            priority TEXT,
            done INTEGER DEFAULT 0,
            user_id INTEGER NOT NULL
);

    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            color TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER,
            filename TEXT,
            FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS resources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            filename TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS timetable (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT NOT NULL,
            day TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            color TEXT DEFAULT '#5bc0de',
            description TEXT,
            filename TEXT
        );

    ''')

    conn.commit()
    conn.close()
def get_db_connection():
    conn = sqlite3.connect('database.db')  # or whatever your DB file is named
    conn.row_factory = sqlite3.Row
    return conn
def get_user(user_id):
    conn = get_db_connection()
    user = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    conn.close()
    return user


@app.route('/')
def index():
    return redirect(url_for('login'))
@app.route('/timetable', methods=['GET', 'POST'])
def timetable():
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    if request.method == 'POST':
        subject = request.form.get('subject')
        day = request.form.get('day')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        description = request.form.get('description')
        color = request.form.get('color') or '#5bc0de'

        filename = None
        file = request.files.get('file')
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

        cursor.execute("""
            INSERT INTO timetable (user_id, subject, day, start_time, end_time, description, color, filename)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, subject, day, start_time, end_time, description, color, filename))
        conn.commit()
        flash('Class added to timetable!', 'success')

    cursor.execute("SELECT id, subject, day, start_time, end_time, description, color, filename FROM timetable WHERE user_id = ?", (user_id,))
    entries = cursor.fetchall()
    conn.close()

    # Prepare timetable dict by day for easy rendering
    timetable_by_day = {d: [] for d in ['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday']}
    for e in entries:
        timetable_by_day[e[2]].append({
            'id': e[0],
            'subject': e[1],
            'start_time': e[3],
            'end_time': e[4],
            'description': e[5],
            'color': e[6],
            'filename': e[7]
        })

    return render_template('timetable.html', timetable=timetable_by_day)


@app.route('/timetable/edit/<int:id>', methods=['GET', 'POST'])
def edit_timetable(id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute("SELECT id, subject, day, start_time, end_time, description, color, filename FROM timetable WHERE id = ? AND user_id = ?", (id, user_id))
    entry = cursor.fetchone()

    if not entry:
        conn.close()
        flash('Class not found.', 'error')
        return redirect(url_for('timetable'))

    if request.method == 'POST':
        subject = request.form.get('subject')
        day = request.form.get('day')
        start_time = request.form.get('start_time')
        end_time = request.form.get('end_time')
        description = request.form.get('description')
        color = request.form.get('color') or '#5bc0de'

        filename = entry[7]
        file = request.files.get('file')
        if file and file.filename != '' and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(filepath)

        cursor.execute("""
            UPDATE timetable
            SET subject=?, day=?, start_time=?, end_time=?, description=?, color=?, filename=?
            WHERE id=? AND user_id=?
        """, (subject, day, start_time, end_time, description, color, filename, id, user_id))
        conn.commit()
        conn.close()
        flash('Class updated successfully!', 'success')
        return redirect(url_for('timetable'))

    conn.close()
    # Pass entry as dict
    entry_dict = {
        'id': entry[0],
        'subject': entry[1],
        'day': entry[2],
        'start_time': entry[3],
        'end_time': entry[4],
        'description': entry[5],
        'color': entry[6],
        'filename': entry[7]
    }
    return render_template('edit_timetable.html', entry=entry_dict)


@app.route('/timetable/delete/<int:id>', methods=['POST'])
def delete_timetable(id):
    if 'user_id' not in session:
        flash('Please login first.', 'error')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    cursor.execute("SELECT filename FROM timetable WHERE id = ? AND user_id = ?", (id, user_id))
    file_row = cursor.fetchone()
    if file_row and file_row[0]:
        try:
            os.remove(os.path.join(app.config['UPLOAD_FOLDER'], file_row[0]))
        except:
            pass  # ignore errors

    cursor.execute("DELETE FROM timetable WHERE id = ? AND user_id = ?", (id, user_id))
    conn.commit()
    conn.close()
    flash('Class deleted successfully!', 'success')
    return redirect(url_for('timetable'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        email = request.form['email']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE username = ? OR email = ?", (username, email))
        existing_user = c.fetchone()

        if existing_user:
            conn.close()
            return "Username or email already exists. <a href='/register'>Try again</a>"

        c.execute("INSERT INTO users (username, email, password) VALUES (?, ?, ?)",
                  (username, email, password))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username=? AND password=?", (username, password))
        user = c.fetchone()
        conn.close()

        if user:
            session['user_id'] = user[0]
            return redirect(url_for('home'))
        else:
            return "Invalid username or password. <a href='/login'>Try again</a>"
    return render_template('login.html')

# Forgot Password
@app.route('/forgot_password', methods=['GET', 'POST'])
def forgot_password():
    if request.method == 'POST':
        email = request.form['email'].strip().lower()
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT * FROM users WHERE email = ?", (email,))
        user = c.fetchone()
        conn.close()

        if user:
            token = s.dumps(email, salt='password-reset')
            reset_link = url_for('reset_password_token', token=token, _external=True)

            msg = Message(
                subject="Reset Your Password - Student Helper Hub",
                recipients=[email],
                body=f"Click the link to reset your password: {reset_link}\n\nThis link is valid for 1 hour."
            )
            mail.send(msg)

            flash("A password reset link has been sent to your email.", "info")
        else:
            flash("If the email is registered, you will receive a reset link.", "info")

        return redirect(url_for('login'))
    return render_template('forgot_password.html')


@app.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password_token(token):
    try:
        email = s.loads(token, salt='password-reset', max_age=3600)
    except SignatureExpired:
        flash("The password reset link has expired.", "error")
        return redirect(url_for('forgot_password'))
    except BadSignature:
        flash("Invalid or tampered password reset link.", "error")
        return redirect(url_for('forgot_password'))

    if request.method == 'POST':
        new_password = request.form['new_password']
        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("UPDATE users SET password = ? WHERE email = ?", (new_password, email))
        conn.commit()
        conn.close()
        flash("Your password has been reset successfully!", "success")
        return redirect(url_for('login'))

    return render_template('reset_password.html', change_mode=False)



# Other existing routes (dashboard, notes, todo, profile, resources, logout, etc.)
# — You already included those fully in your code so they stay exactly the same —
@app.route('/dashboard')
def dashboard():
    # -------------------------------- safety guard
    if 'user_id' not in session:
        return redirect(url_for('login'))
    user_id = session['user_id']
    # -------------------------------- DB work
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # ── card counts ─────────────────────────────────────────────────────────────
    # tasks
    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ?", (user_id,))
    total_tasks = c.fetchone()[0]

    c.execute("SELECT COUNT(*) FROM tasks WHERE user_id = ? AND done = 0", (user_id,))
    pending_tasks = c.fetchone()[0]

    # notes  (no user_id column ⇒ count every note)
    c.execute("SELECT COUNT(*) FROM notes")
    total_notes = c.fetchone()[0]

    # classes today
    today_day = datetime.now().strftime("%A")          # e.g. 'Monday'
    c.execute("SELECT COUNT(*) FROM timetable WHERE user_id = ? AND day = ?", (user_id, today_day))
    today_classes_count = c.fetchone()[0]

    # ── info‑panel lists ────────────────────────────────────────────────────────
    # next 3 upcoming tasks that have a due_date
    c.execute(
        "SELECT text, due_date FROM tasks "
        "WHERE user_id = ? AND due_date IS NOT NULL "
        "ORDER BY due_date ASC LIMIT 3",
        (user_id,)
    )
    upcoming_tasks = c.fetchall()

    # today’s schedule (subject, start, end) in timetable
    c.execute(
        "SELECT subject, start_time, end_time FROM timetable "
        "WHERE user_id = ? AND day = ? "
        "ORDER BY start_time",
        (user_id, today_day)
    )
    today_schedule = c.fetchall()

    # 3 most‑recent notes (by id)
    c.execute("SELECT title FROM notes ORDER BY id DESC LIMIT 3")
    recent_notes = c.fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        today=datetime.now().strftime("%A, %B %d, %Y"),
        total_tasks=total_tasks,
        pending_tasks=pending_tasks,
        total_notes=total_notes,
        today_classes_count=today_classes_count,
        upcoming_tasks=upcoming_tasks,
        today_schedule=today_schedule,
        recent_notes=recent_notes,
    )








@app.route('/home')
def home():
    return render_template('home.html')

@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/contact', methods=['GET', 'POST'])
def contact():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        subject = request.form.get('subject')
        message = request.form.get('message')

        try:
            msg = Message(
                subject=f"[SHH Contact] {subject}",
                sender=app.config['MAIL_USERNAME'],  # your configured sender
                recipients=[app.config['MAIL_USERNAME']],  # sending to yourself
                body=f"""
You received a message via the SHH Contact Form.

From: {name}
Email: {email}
Subject: {subject}

Message:
{message}
                """
            )
            mail.send(msg)
            flash("✅ Message sent successfully!", "success")
        except Exception as e:
            flash("❌ Failed to send message. Please try again later.", "danger")
            print("Contact form error:", e)

        return redirect(url_for('contact'))

    return render_template('contact.html')




@app.route('/profile', methods=['GET'])
def profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    user = get_user(user_id)
    edit_mode = request.args.get('edit') == 'true'
    return render_template('profile.html', user=user, edit_mode=edit_mode)

@app.route('/edit_profile', methods=['POST'])
def edit_profile():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('login'))

    full_name = request.form['full_name']
    email = request.form['email']
    birthday = request.form.get('birthday')
    school = request.form.get('school')
    major = request.form.get('major')
    bio = request.form.get('bio')

    photo = request.files.get('photo')
    delete_photo = request.form.get('delete_photo')

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if delete_photo:
        c.execute("SELECT photo FROM users WHERE id = ?", (user_id,))
        result = c.fetchone()
        if result and result[0]:
            photo_path = os.path.join(app.config['UPLOAD_FOLDER'], result[0])
            if os.path.exists(photo_path):
                os.remove(photo_path)
            c.execute("UPDATE users SET photo = NULL WHERE id = ?", (user_id,))

    elif photo and photo.filename != '' and allowed_file(photo.filename):
        filename = secure_filename(photo.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        photo.save(filepath)
        c.execute("UPDATE users SET photo = ? WHERE id = ?", (filename, user_id))

    c.execute('''
        UPDATE users SET full_name=?, email=?, birthday=?, school=?, major=?, bio=? WHERE id=?
    ''', (full_name, email, birthday, school, major, bio, user_id))

    conn.commit()
    conn.close()

    return redirect(url_for('profile'))

@app.route('/change_password', methods=['GET', 'POST'])
def change_password():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']

        conn = sqlite3.connect('database.db')
        c = conn.cursor()
        c.execute("SELECT password FROM users WHERE id = ?", (session['user_id'],))
        db_password = c.fetchone()[0]

        if current_password != db_password:
            flash('Current password is incorrect.', 'error')
            conn.close()
            return redirect(url_for('change_password'))

        c.execute("UPDATE users SET password = ? WHERE id = ?", (new_password, session['user_id']))
        conn.commit()
        conn.close()
        flash('Password changed successfully.', 'success')
        return redirect(url_for('profile'))

    return render_template('reset_password.html', change_mode=True)



@app.route('/delete_account', methods=['POST'])
def delete_account():
    if 'user_id' not in session:
        flash('You must be logged in to delete your account.')
        return redirect(url_for('login'))

    user_id = session['user_id']

    conn = get_db_connection()
    conn.execute('DELETE FROM tasks WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM timetable WHERE user_id = ?', (user_id,))
    conn.execute('DELETE FROM users WHERE id = ?', (user_id,))
    conn.commit()
    conn.close()

    session.clear()
    flash('Your account has been deleted.')
    return redirect(url_for('register'))
@app.route('/notifications', methods=['GET', 'POST'])
def notifications():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # handle save
    if request.method == 'POST':
        email_updates   = 1 if request.form.get('email_updates')   else 0
        task_reminders  = 1 if request.form.get('task_reminders')  else 0
        c.execute("""
            UPDATE users
               SET email_updates=?, task_reminders=?
             WHERE id=?
        """, (email_updates, task_reminders, user_id))
        conn.commit()
        flash("Notification preferences saved.", "success")
        conn.close()
        return redirect(url_for('profile'))

    # GET – show form
    user = c.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return render_template('notifications.html', user=user)


# NOTES ROUTES WITH MULTIPLE ATTACHMENTS

@app.route('/notes', methods=['GET', 'POST'])
def notes():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        title = request.form.get('note_title')
        content = request.form.get('note_content')
        color_choices = ['#ffd1dc', '#c1f0f6', '#f9f9a9', '#d3f8d3']
        color = random.choice(color_choices)

        c.execute("INSERT INTO notes (title, content, color) VALUES (?, ?, ?)", (title, content, color))
        note_id = c.lastrowid

        files = request.files.getlist('attachments')
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"note{note_id}_{int(datetime.now().timestamp())}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(filepath)
                c.execute("INSERT INTO attachments (note_id, filename) VALUES (?, ?)", (note_id, unique_filename))

        conn.commit()

    c.execute("SELECT id, title, content, color FROM notes ORDER BY id DESC")
    notes_rows = c.fetchall()
    notes_data = []

    for row in notes_rows:
        note_id = row[0]
        c.execute("SELECT id, filename FROM attachments WHERE note_id = ?", (note_id,))
        attachments = [{'id': r[0], 'filename': r[1]} for r in c.fetchall()]
        notes_data.append({
            'id': row[0],
            'title': row[1],
            'content': row[2],
            'color': row[3],
            'attachments': attachments
        })

    conn.close()
    return render_template('notes.html', notes=notes_data)

@app.route('/notes/edit/<int:note_id>', methods=['GET', 'POST'])
def edit_note(note_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        delete_attachment_id = request.form.get('delete_attachment_id')
        if delete_attachment_id:
            c.execute("SELECT filename FROM attachments WHERE id = ?", (delete_attachment_id,))
            row = c.fetchone()
            if row:
                filename = row[0]
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                if os.path.exists(filepath):
                    os.remove(filepath)
            c.execute("DELETE FROM attachments WHERE id = ?", (delete_attachment_id,))
            conn.commit()
            conn.close()
            return redirect(url_for('edit_note', note_id=note_id))

        title = request.form.get('note_title')
        content = request.form.get('note_content')
        c.execute("UPDATE notes SET title = ?, content = ? WHERE id = ?", (title, content, note_id))

        files = request.files.getlist('attachments')
        for file in files:
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                unique_filename = f"note{note_id}_{int(datetime.now().timestamp())}_{filename}"
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
                file.save(filepath)
                c.execute("INSERT INTO attachments (note_id, filename) VALUES (?, ?)", (note_id, unique_filename))

        conn.commit()
        conn.close()
        return redirect(url_for('notes'))

    c.execute("SELECT id, title, content FROM notes WHERE id = ?", (note_id,))
    note = c.fetchone()
    if not note:
        conn.close()
        flash("Note not found.", "error")
        return redirect(url_for('notes'))

    c.execute("SELECT id, filename FROM attachments WHERE note_id = ?", (note_id,))
    attachments = [{'id': row[0], 'filename': row[1]} for row in c.fetchall()]
    conn.close()

    note_data = {
        'id': note[0],
        'title': note[1],
        'content': note[2],
        'attachments': attachments
    }

    return render_template('edit_note.html', note=note_data)

@app.route('/notes/delete/<int:note_id>', methods=['POST'])
def delete_note(note_id):
    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT filename FROM attachments WHERE note_id = ?", (note_id,))
    attachments = c.fetchall()
    for (filename,) in attachments:
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if os.path.exists(file_path):
            os.remove(file_path)

    c.execute("DELETE FROM attachments WHERE note_id = ?", (note_id,))
    c.execute("DELETE FROM notes WHERE id = ?", (note_id,))
    conn.commit()
    conn.close()
    flash("Note deleted successfully!", "success")
    return redirect(url_for('notes'))



# TODO ROUTES
@app.route('/todo', methods=['GET', 'POST'])
def todo():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    if request.method == 'POST':
        task_text = request.form.get('task')
        description = request.form.get('description')
        due_date = request.form.get('due_date')
        priority = request.form.get('priority')
        c.execute(
            "INSERT INTO tasks (text, description, due_date, priority, user_id) VALUES (?, ?, ?, ?, ?)",
            (task_text, description, due_date, priority, session['user_id'])
        )
        conn.commit()

    c.execute(
        "SELECT * FROM tasks WHERE user_id = ? ORDER BY id DESC",
        (session['user_id'],)
    )
    tasks = c.fetchall()
    conn.close()

    today = date.today().isoformat()
    due_tasks = [t for t in tasks if t[3] and t[3] <= today and not t[5]]  # due_date at index 3, done at 5
    completed_tasks = [t for t in tasks if t[5]]
    pending_tasks = [t for t in tasks if not t[5]]

    return render_template('todo.html',
                           tasks=tasks,
                           due_tasks=due_tasks,
                           completed_tasks=completed_tasks,
                           pending_tasks=pending_tasks,
                           total=len(tasks),
                           due=len(due_tasks),
                           completed=len(completed_tasks),
                           pending=len(pending_tasks))


@app.route('/mark_done/<int:task_id>', methods=['POST'])
def mark_done(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("SELECT done FROM tasks WHERE id = ? AND user_id = ?", (task_id, session['user_id']))
    row = c.fetchone()
    if row:
        current = row[0]
        c.execute("UPDATE tasks SET done = ? WHERE id = ? AND user_id = ?", (0 if current else 1, task_id, session['user_id']))
        conn.commit()

    conn.close()
    return redirect(url_for('todo'))


@app.route('/delete_task/<int:task_id>', methods=['POST'])
def delete_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(url_for('todo'))


@app.route('/edit_task/<int:task_id>', methods=['POST'])
def edit_task(task_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))

    task_name = request.form['task']
    description = request.form.get('description', '')
    due_date = request.form.get('due_date', '')
    priority = request.form.get('priority', '')

    conn = sqlite3.connect('database.db')
    c = conn.cursor()

    c.execute("""
        UPDATE tasks
        SET text = ?, description = ?, due_date = ?, priority = ?
        WHERE id = ? AND user_id = ?
    """, (task_name, description, due_date, priority, task_id, session['user_id']))

    conn.commit()
    conn.close()

    flash('Task updated successfully.')
    return redirect(url_for('todo'))


@app.route("/resources")
def resources():
    return render_template("resources.html")

@app.route('/ask', methods=['POST'])
def ask():
    question = request.form.get('question', '').strip()
    image_file = request.files.get('image')

    try:
        if image_file:
            # Save and open image
            filename = secure_filename(image_file.filename)
            path = os.path.join(UPLOAD_FOLDER, filename)
            image_file.save(path)
            img = Image.open(path)

            model = genai.GenerativeModel('models/gemini-1.5-flash')
            response = model.generate_content([question, img])
        else:
            model = genai.GenerativeModel('models/gemini-1.5-flash')
            response = model.generate_content(question)

        return jsonify({'answer': response.text})

    except Exception as e:
        return jsonify({'answer': f"⚠️ Error: {str(e)}"})











@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))



@app.route('/reset_tasks')
def reset_tasks():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS tasks")
    conn.commit()
    conn.close()
    return "Tasks table dropped."

@app.route('/reset_notes')
def reset_notes():
    conn = sqlite3.connect('database.db')
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS attachments")
    c.execute("DROP TABLE IF EXISTS notes")
    c.execute('''
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            color TEXT
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            note_id INTEGER,
            filename TEXT,
            FOREIGN KEY(note_id) REFERENCES notes(id) ON DELETE CASCADE
        )
    ''')
    conn.commit()
    conn.close()
    return "✅ Notes and attachments tables reset successfully."
@app.route('/test-email')
def test_email():
    try:
        msg = Message("Test Email from SHH", 
                      sender=app.config['MAIL_USERNAME'],
                      recipients=[app.config['MAIL_USERNAME']],
                      body="This is a test message from your Flask app.")
        mail.send(msg)
        return "✅ Test email sent!"
    except Exception as e:
        return f"❌ Failed: {e}"


if __name__ == '__main__':
    import os
    port = int(os.environ.get('PORT', 5000))  # Use Render's port or default 5000
    init_db()
    app.run(host='0.0.0.0', port=port, debug=True)

