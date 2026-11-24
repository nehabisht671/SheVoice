from flask import Flask, render_template, request, redirect, session, url_for, flash
from datetime import datetime, timedelta
import mysql.connector
import os
import random
import smtplib
app = Flask(__name__)
app.secret_key = "shevoice_secret_key"


# ============================================================
# DATABASE
# ============================================================

db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="root123",
    database="shevoice"
)


UPLOAD_FOLDER = "static/uploads"
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


# ============================================================
# HOME
# ============================================================

@app.route('/')
def home():
    return render_template('index.html')
@app.route('/committee')
def committee_selection():
    cursor = db.cursor(dictionary=True)

    cursor.execute("""
        SELECT id, name, description
        FROM committees
        ORDER BY id
    """)

    committees = cursor.fetchall()
    cursor.close()

    return render_template('committee_selection.html', committees=committees)


# ============================================================
# REGISTER
# ============================================================

@app.route('/register', methods=['GET', 'POST'])
def register():

    if request.method == 'POST':

        name = request.form.get('name', '').strip()
        student_id = request.form.get('student_id', '').strip()
        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        # ---------------- REQUIRED FIELDS ----------------

        if not name or not student_id or not email or not password:

            flash("Please fill in all fields.")

            return render_template("register.html")


        cursor = db.cursor(dictionary=True)

        try:

            # ---------------- DUPLICATE CHECK ----------------

            cursor.execute("""
                SELECT id
                FROM users
                WHERE email = %s
                   OR student_id = %s
            """, (email, student_id))

            existing_user = cursor.fetchone()


            if existing_user:

                flash(
                    "Email or Student ID already registered. "
                    "Please log in."
                )

                return render_template("register.html")


            # ---------------- REGISTER STUDENT ----------------

            cursor.execute("""
                INSERT INTO users
                (
                    name,
                    student_id,
                    email,
                    password,
                    role
                )
                VALUES (%s, %s, %s, %s, %s)
            """, (
                name,
                student_id,
                email,
                password,
                'student'
            ))


            db.commit()


            flash(
                "Registration successful! Please log in."
            )


            return redirect(
                url_for('login', role='student')
            )


        except Exception as e:

            db.rollback()

            print("Registration error:", e)

            flash(
                "Registration failed. Please try again."
            )


        finally:

            cursor.close()


        return render_template("register.html")


    return render_template("register.html")


# ============================================================
# LOGIN
# ============================================================

@app.route('/login', methods=['GET', 'POST'])
def login():

    role = request.args.get('role', 'student')
    committee_id = request.args.get('committee_id')

    if request.method == 'POST':

        email = request.form.get('email', '').strip().lower()
        password = request.form.get('password', '')

        role = request.form.get('role', 'student')
        committee_id = request.form.get('committee_id')

        print("ROLE:", role)

        cursor = db.cursor(dictionary=True)

        cursor.execute("""
            SELECT *
            FROM users
            WHERE email = %s
              AND password = %s
              AND role = %s
        """, (email, password, role))

        user = cursor.fetchone()

        print("USER:", user)

        # Verify committee selection
        if user and role == 'committee' and committee_id:

            if str(user.get('committee_id')) != str(committee_id):
                user = None

        # Invalid login
        if not user:

            cursor.close()

            flash(
                "Invalid email, password or role.",
                "danger"
            )

            return render_template(
                'login.html',
                role=role,
                committee_id=committee_id
            )

        # Create session
        session['user_id'] = user['id']
        session['name'] = user['name']
        session['role'] = user['role']
        session['student_id'] = user.get('student_id')
        session['email'] = user['email']

        cursor.close()

        # Redirect according to role
        if role == 'admin':

            return redirect('/admin_dashboard')

        elif role == 'committee':

            return redirect('/committee_dashboard')

        else:

            return redirect('/student_dashboard')

    return render_template(
        'login.html',
        role=role,
        committee_id=committee_id
    )



# ============================================================
# STUDENT DASHBOARD
# ============================================================

@app.route('/student_dashboard')
def student_dashboard():

    if session.get('role') != 'student':

        return redirect('/login?role=student')


    user_id = session.get('user_id')

    cursor = db.cursor(dictionary=True)


    # ---------------- TOTAL ----------------

    cursor.execute("""
        SELECT COUNT(*) AS total
        FROM complaints
        WHERE student_id = %s
    """, (user_id,))

    total = cursor.fetchone()['total']


    # ---------------- PENDING ----------------

    cursor.execute("""
        SELECT COUNT(*) AS pending
        FROM complaints
        WHERE student_id = %s
          AND status = 'Pending'
    """, (user_id,))

    pending = cursor.fetchone()['pending']


    # ---------------- IN PROGRESS ----------------

    cursor.execute("""
        SELECT COUNT(*) AS progress
        FROM complaints
        WHERE student_id = %s
          AND status = 'In Progress'
    """, (user_id,))

    progress = cursor.fetchone()['progress']


    # ---------------- RESOLVED ----------------

    cursor.execute("""
        SELECT COUNT(*) AS resolved
        FROM complaints
        WHERE student_id = %s
          AND status = 'Resolved'
    """, (user_id,))

    resolved = cursor.fetchone()['resolved']


    # ---------------- ALL COMPLAINTS ----------------

    cursor.execute("""
        SELECT
            id,
            category,
            status
        FROM complaints
        WHERE student_id = %s
        ORDER BY id DESC
    """, (user_id,))

    complaints = cursor.fetchall()


    cursor.close()


    return render_template(
        "student_dashboard.html",

        total_complaints=total,

        pending_complaints=pending,

        progress_complaints=progress,

        resolved_complaints=resolved,

        complaints=complaints
    )


# ============================================================
# FILE COMPLAINT
# ============================================================

@app.route('/file_complaint', methods=['GET', 'POST'])
def file_complaint():

    if session.get('role') != 'student':

        return redirect('/login?role=student')


    cursor = db.cursor()


    if request.method == 'POST':

        category = request.form.get('category')

        description = request.form.get('description')

        anonymous = (
            1
            if request.form.get('anonymous') == 'Yes'
            else 0
        )


        # Logged-in student's users.id
        user_id = session.get('user_id')


        # ---------------- FILE UPLOAD ----------------

        proof = request.files.get('proof')

        filename = None


        if proof and proof.filename != "":

            filename = proof.filename

            proof.save(
                os.path.join(
                    UPLOAD_FOLDER,
                    filename
                )
            )


        # ====================================================
        # NEW COMPLAINT ALWAYS STARTS AS PENDING
        # ====================================================

        cursor.execute("""
            INSERT INTO complaints
            (
                student_id,
                category,
                description,
                anonymous,
                proof,
                status,
                created_at
            )
            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s,
                %s,
                NOW()
            )
        """, (
            user_id,
            category,
            description,
            anonymous,
            filename,
            'Pending'
        ))


        db.commit()


        cursor.close()


        flash(
            "Complaint Submitted Successfully ✅"
        )


        return redirect('/student_dashboard')


    cursor.close()


    return render_template(
        'file_complaint.html'
    )


# ============================================================
# MY COMPLAINTS
# ============================================================

@app.route('/my_complaints')
def my_complaints():

    if session.get('role') != 'student':

        return redirect('/login?role=student')


    user_id = session.get('user_id')


    cursor = db.cursor()


    cursor.execute("""
        SELECT
            id,
            category,
            created_at,
            status
        FROM complaints
        WHERE student_id = %s
        ORDER BY id DESC
    """, (user_id,))


    complaints = cursor.fetchall()


    cursor.close()


    return render_template(
        "my_complaints.html",
        complaints=complaints
    )


@app.route('/admin_dashboard')
def admin_dashboard():

    if session.get('role') != 'admin':
        return redirect('/login?role=admin')

    cursor = db.cursor(dictionary=True)

    try:

        # ==========================================
        # 1. OVERALL STATISTICS
        # ==========================================

        cursor.execute("""
            SELECT
                COUNT(*) AS total,

                SUM(CASE
                    WHEN status = 'Pending'
                    THEN 1 ELSE 0
                END) AS pending,

                SUM(CASE
                    WHEN status = 'In Progress'
                    THEN 1 ELSE 0
                END) AS progress,

                SUM(CASE
                    WHEN status = 'Resolved'
                    THEN 1 ELSE 0
                END) AS resolved,

                SUM(CASE
                    WHEN priority = 'High'
                    THEN 1 ELSE 0
                END) AS high

            FROM complaints
        """)

        stats = cursor.fetchone()

        total = stats['total'] or 0
        pending = stats['pending'] or 0
        progress = stats['progress'] or 0
        resolved = stats['resolved'] or 0
        high_priority = stats['high'] or 0


        # ==========================================
        # 2. CATEGORY STATISTICS
        # ==========================================

        cursor.execute("""
            SELECT category, COUNT(*) AS count
            FROM complaints
            GROUP BY category
            ORDER BY count DESC
        """)

        category_stats = cursor.fetchall()


        # ==========================================
        # 3. PRIORITY STATISTICS
        # ==========================================

        cursor.execute("""
            SELECT
                COALESCE(priority, 'Medium') AS priority,
                COUNT(*) AS count

            FROM complaints

            GROUP BY COALESCE(priority, 'Medium')
        """)

        priority_stats = cursor.fetchall()


        # ==========================================
        # 4. ASSIGNMENT STATISTICS
        # ==========================================

        cursor.execute("""
            SELECT
                CASE
                    WHEN assigned_cell IS NULL
                    THEN 'Unassigned'
                    ELSE 'Assigned'
                END AS assignment_status,

                COUNT(*) AS count

            FROM complaints

            GROUP BY assignment_status
        """)

        assignment_stats = cursor.fetchall()


        # ==========================================
        # 5. ALL COMPLAINTS
        # ==========================================

        cursor.execute("""
            SELECT
                c.id,
                c.category,
                c.status,
                c.anonymous,
                c.priority,
                c.created_at,
                c.assigned_cell,

                u.student_id,

                com.name AS committee_name

            FROM complaints c

            JOIN users u
                ON c.student_id = u.id

            LEFT JOIN committees com
                ON c.assigned_cell = com.id

            ORDER BY c.id DESC
        """)

        complaints = cursor.fetchall()


        # ==========================================
        # 6. CHART DATA
        # ==========================================

        chart_status_labels = [
            'Pending',
            'In Progress',
            'Resolved'
        ]

        chart_status_values = [
            pending,
            progress,
            resolved
        ]


        chart_category_labels = [
            row['category']
            for row in category_stats
        ]

        chart_category_values = [
            row['count']
            for row in category_stats
        ]


        chart_priority_labels = [
            row['priority']
            for row in priority_stats
        ]

        chart_priority_values = [
            row['count']
            for row in priority_stats
        ]


        chart_assignment_labels = [
            row['assignment_status']
            for row in assignment_stats
        ]

        chart_assignment_values = [
            row['count']
            for row in assignment_stats
        ]


    finally:

        cursor.close()


    # ==========================================
    # 7. SEND DATA TO HTML
    # ==========================================

    return render_template(

        'admin_dashboard.html',

        total_complaints=total,

        pending_complaints=pending,

        progress_complaints=progress,

        in_progress_complaints=progress,

        resolved_complaints=resolved,

        high_priority=high_priority,

        complaints=complaints,

        category_stats=category_stats,

        priority_stats=priority_stats,

        chart_status_labels=chart_status_labels,

        chart_status_values=chart_status_values,

        chart_category_labels=chart_category_labels,

        chart_category_values=chart_category_values,

        chart_priority_labels=chart_priority_labels,

        chart_priority_values=chart_priority_values,

        chart_assignment_labels=chart_assignment_labels,

        chart_assignment_values=chart_assignment_values

    )

# ============================================================
# COMMITTEE DASHBOARD
# ============================================================

@app.route('/committee_dashboard')
def committee_dashboard():

    if session.get('role') != 'committee':

        return redirect(
            '/login?role=committee'
        )


    user_id = session.get('user_id')


    cursor = db.cursor(dictionary=True)


    # ========================================================
    # GET LOGGED-IN COMMITTEE
    # ========================================================

    cursor.execute("""
        SELECT
            u.id,
            u.name,
            u.email,
            u.committee_id,
            c.name AS committee_name

        FROM users u

        LEFT JOIN committees c
            ON u.committee_id = c.id

        WHERE u.id = %s
          AND u.role = 'committee'
    """, (user_id,))


    committee_user = cursor.fetchone()


    if not committee_user:

        cursor.close()

        return (
            "Committee account not properly configured.",
            403
        )


    committee_id = committee_user['committee_id']


    if not committee_id:

        cursor.close()

        return (
            "No committee assigned to this account.",
            403
        )


    # ========================================================
    # GET ASSIGNED COMPLAINTS
    # ========================================================

    cursor.execute("""
        SELECT
            c.id,
            c.category,
            c.priority,
            c.status,
            c.created_at,
            ca.assigned_at

        FROM complaints c

        INNER JOIN complaint_assignments ca
            ON c.id = ca.complaint_id

        WHERE ca.committee_id = %s

        ORDER BY c.created_at DESC
    """, (committee_id,))


    complaints = cursor.fetchall()


    # ========================================================
    # COUNTS
    # ========================================================

    total = len(complaints)


    pending = sum(
        1
        for c in complaints
        if c['status'] == 'Pending'
    )


    in_progress = sum(
        1
        for c in complaints
        if c['status'] == 'In Progress'
    )


    resolved = sum(
        1
        for c in complaints
        if c['status'] == 'Resolved'
    )


    cursor.close()


    return render_template(
        'committee_dashboard.html',

        committee_name=committee_user['committee_name'],

        complaints=complaints,

        total=total,

        pending=pending,

        in_progress=in_progress,

        resolved=resolved
    )


# ============================================================
# COMMITTEE COMPLAINT DETAIL
# ============================================================

@app.route(
    '/committee/complaint/<int:id>',
    methods=['GET', 'POST']
)
def committee_complaint_detail(id):

    if session.get('role') != 'committee':

        return redirect(
            '/login?role=committee'
        )


    user_email = session.get('email')


    cursor = db.cursor(dictionary=True)


    # ========================================================
    # FIND COMMITTEE
    # ========================================================

    cursor.execute("""
        SELECT
            id,
            name

        FROM committees

        WHERE email = %s
    """, (user_email,))


    committee = cursor.fetchone()


    if not committee:

        cursor.close()

        return (
            "Committee account not connected.",
            403
        )


    committee_id = committee['id']


    # ========================================================
    # MAKE SURE COMPLAINT IS ASSIGNED TO THIS COMMITTEE
    # ========================================================

    cursor.execute("""
        SELECT
            c.id,
            c.category,
            c.description,
            c.anonymous,
            c.proof,
            c.priority,
            c.status,
            c.created_at,

            ca.assigned_at

        FROM complaint_assignments ca

        JOIN complaints c
            ON ca.complaint_id = c.id

        WHERE ca.complaint_id = %s
          AND ca.committee_id = %s

        ORDER BY ca.id DESC

        LIMIT 1
    """, (
        id,
        committee_id
    ))


    complaint = cursor.fetchone()


    if not complaint:

        cursor.close()

        return (
            "Complaint not assigned to your committee.",
            403
        )


    # ========================================================
    # COMMITTEE UPDATES STATUS
    # ========================================================

    if request.method == 'POST':

        new_status = request.form.get('status')

        remarks = request.form.get('remarks')


        old_status = complaint['status']


        # ---------------- VALID STATUS ----------------

        if new_status not in [
            'Pending',
            'In Progress',
            'Resolved'
        ]:

            cursor.close()

            flash("Invalid status.")

            return redirect(
                url_for(
                    'committee_complaint_detail',
                    id=id
                )
            )


        # ====================================================
        # UPDATE ONLY complaints.status
        #
        # DO NOT update complaint_assignments.status.
        #
        # Assignment status remains "Assigned".
        # ====================================================

        cursor.execute("""
            UPDATE complaints

            SET status = %s

            WHERE id = %s
        """, (
            new_status,
            id
        ))


        # ====================================================
        # UPDATE HISTORY
        # ====================================================

        cursor.execute("""
            INSERT INTO complaint_updates
            (
                complaint_id,
                updated_by,
                old_status,
                new_status,
                remarks
            )

            VALUES
            (
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """, (
            id,
            session.get('user_id'),
            old_status,
            new_status,
            remarks
        ))


        # ====================================================
        # AUDIT LOG
        # ====================================================

        cursor.execute("""
            INSERT INTO audit_logs
            (
                user_id,
                complaint_id,
                action
            )

            VALUES
            (
                %s,
                %s,
                %s
            )
        """, (
            session.get('user_id'),
            id,
            (
                f"Committee updated complaint status "
                f"from {old_status} to {new_status}"
            )
        ))


        # ====================================================
        # GET STUDENT WHO FILED COMPLAINT
        # ====================================================

        cursor.execute("""
            SELECT student_id

            FROM complaints

            WHERE id = %s
        """, (id,))


        complaint_owner = cursor.fetchone()


        # ====================================================
        # NOTIFY STUDENT
        # ====================================================

        if complaint_owner:

            cursor.execute("""
                INSERT INTO notifications
                (
                    user_id,
                    complaint_id,
                    message
                )

                VALUES
                (
                    %s,
                    %s,
                    %s
                )
            """, (
                complaint_owner['student_id'],
                id,
                (
                    f"Your complaint SV{id:03d} "
                    f"has been updated to {new_status}."
                )
            ))


        db.commit()


        flash(
            "Complaint updated successfully."
        )


        cursor.close()


        return redirect(
            url_for(
                'committee_complaint_detail',
                id=id
            )
        )


    # ========================================================
    # UPDATE HISTORY
    # ========================================================

    cursor.execute("""
        SELECT
            cu.old_status,
            cu.new_status,
            cu.remarks,
            cu.created_at,
            u.name AS updated_by_name

        FROM complaint_updates cu

        JOIN users u
            ON cu.updated_by = u.id

        WHERE cu.complaint_id = %s

        ORDER BY cu.id DESC
    """, (id,))


    updates = cursor.fetchall()


    cursor.close()


    return render_template(
        'committee_complaint_detail.html',

        complaint=complaint,

        committee=committee,

        updates=updates
    )


# ============================================================
# ADMIN COMPLAINT DETAIL
#
# IMPORTANT:
# Admin can VIEW the complaint.
# Admin can ASSIGN/REASSIGN the committee.
# Admin CANNOT change the complaint status.
# ============================================================

@app.route('/complaint/<int:id>')
def complaint_detail(id):

    if session.get('role') != 'admin':

        return redirect(
            '/login?role=admin'
        )


    cursor = db.cursor(dictionary=True)


    # ========================================================
    # GET COMPLAINT
    # ========================================================

    cursor.execute("""
        SELECT
            c.*,

            u.name,
            u.email,
            u.student_id,

            com.name AS committee_name

        FROM complaints c

        JOIN users u
            ON c.student_id = u.id

        LEFT JOIN committees com
            ON c.assigned_cell = com.id

        WHERE c.id = %s
    """, (id,))


    complaint = cursor.fetchone()


    if not complaint:

        cursor.close()

        return "Complaint not found", 404


    # ========================================================
    # GET COMMITTEES
    # ========================================================

    cursor.execute("""
        SELECT
            id,
            name,
            description

        FROM committees

        ORDER BY name
    """)


    committees = cursor.fetchall()


    # ========================================================
    # GET CURRENT ASSIGNMENT
    # ========================================================

    cursor.execute("""
        SELECT
            ca.id,
            ca.assigned_at,
            ca.status,
            ca.committee_id,

            com.name AS committee_name

        FROM complaint_assignments ca

        JOIN committees com
            ON ca.committee_id = com.id

        WHERE ca.complaint_id = %s

        ORDER BY ca.id DESC

        LIMIT 1
    """, (id,))


    assignment = cursor.fetchone()


    cursor.close()


    return render_template(
        "complaint_detail.html",

        complaint=complaint,

        committees=committees,

        assignment=assignment
    )


# ============================================================
# ASSIGN / REASSIGN COMPLAINT
#
# ONLY ADMIN CAN DO THIS.
#
# URL:
# /assign_complaint/<complaint_id>
#
# Status remains Pending/In Progress/Resolved.
# Assignment status remains "Assigned".
# ============================================================

@app.route(
    '/assign_complaint/<int:complaint_id>',
    methods=['POST']
)
def assign_complaint(complaint_id):

    if session.get('role') != 'admin':

        return redirect(
            '/login?role=admin'
        )


    committee_id = request.form.get(
        'committee_id'
    )


    # ========================================================
    # COMMITTEE REQUIRED
    # ========================================================

    if not committee_id:

        flash(
            "Please select a committee."
        )

        return redirect(
            url_for(
                'complaint_detail',
                id=complaint_id
            )
        )


    cursor = db.cursor(dictionary=True)


    # ========================================================
    # CHECK COMPLAINT
    # ========================================================

    cursor.execute("""
        SELECT
            id,
            status

        FROM complaints

        WHERE id = %s
    """, (complaint_id,))


    complaint = cursor.fetchone()


    if not complaint:

        cursor.close()

        flash(
            "Complaint not found."
        )

        return redirect(
            '/admin_dashboard'
        )


    # ========================================================
    # CHECK COMMITTEE
    # ========================================================

    cursor.execute("""
        SELECT
            id,
            name

        FROM committees

        WHERE id = %s
    """, (committee_id,))


    committee = cursor.fetchone()


    if not committee:

        cursor.close()

        flash(
            "Invalid committee selected."
        )

        return redirect(
            url_for(
                'complaint_detail',
                id=complaint_id
            )
        )


    # ========================================================
    # CHECK EXISTING ASSIGNMENT
    # ========================================================

    cursor.execute("""
        SELECT
            id

        FROM complaint_assignments

        WHERE complaint_id = %s

        ORDER BY id DESC

        LIMIT 1
    """, (complaint_id,))


    existing = cursor.fetchone()


    # ========================================================
    # REASSIGN
    # ========================================================

    if existing:

        cursor.execute("""
            UPDATE complaint_assignments

            SET
                committee_id = %s,
                assigned_by = %s,
                assigned_at = NOW(),
                status = 'Assigned'

            WHERE id = %s
        """, (
            committee_id,
            session.get('user_id'),
            existing['id']
        ))


    # ========================================================
    # FIRST ASSIGNMENT
    # ========================================================

    else:

        cursor.execute("""
            INSERT INTO complaint_assignments
            (
                complaint_id,
                committee_id,
                assigned_by,
                assigned_at,
                status
            )

            VALUES
            (
                %s,
                %s,
                %s,
                NOW(),
                'Assigned'
            )
        """, (
            complaint_id,
            committee_id,
            session.get('user_id')
        ))


    # ========================================================
    # STORE ASSIGNED COMMITTEE
    #
    # IMPORTANT:
    # We DO NOT change complaints.status here.
    #
    # If it was Pending, it remains Pending.
    # ========================================================

    cursor.execute("""
        UPDATE complaints

        SET assigned_cell = %s

        WHERE id = %s
    """, (
        committee_id,
        complaint_id
    ))


    db.commit()


    cursor.close()


    flash(
        f"Complaint SV{complaint_id:03d} assigned to "
        f"{committee['name']} successfully."
    )


    return redirect(
        url_for(
            'complaint_detail',
            id=complaint_id
        )
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route('/logout')
def logout():

    session.clear()

    return redirect('/')


# ============================================================
# RUN
# ============================================================

if __name__ == '__main__':

    app.run(
        debug=True
    )