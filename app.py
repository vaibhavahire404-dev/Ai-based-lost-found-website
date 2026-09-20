from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3
import os
import uuid
import cv2

from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash, check_password_hash
from authlib.integrations.flask_client import OAuth


# ============================================================
# APP CONFIGURATION
# ============================================================

app = Flask(__name__)

app.secret_key = os.environ.get(
    "SECRET_KEY",
    "change-this-secret-key"
)

oauth = OAuth(app)


# ============================================================
# GOOGLE OAUTH
# ============================================================

google = oauth.register(
    name="google",
    client_id=os.environ.get("GOOGLE_CLIENT_ID"),
    client_secret=os.environ.get("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={
        "scope": "openid email profile"
    }
)


# ============================================================
# PATHS
# ============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB = os.path.join(
    BASE_DIR,
    "lostfound.db"
)

UPLOAD_DIR = os.path.join(
    BASE_DIR,
    "static",
    "uploads"
)

os.makedirs(
    UPLOAD_DIR,
    exist_ok=True
)


ALLOWED_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png"
}


# ============================================================
# DATABASE
# ============================================================

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def init_db():

    con = db()

    con.executescript("""
    
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        item_type TEXT NOT NULL,
        item_name TEXT NOT NULL,
        category TEXT,
        color TEXT,
        model_number TEXT,
        location TEXT,
        date TEXT,
        description TEXT,
        image TEXT,
        status TEXT DEFAULT 'Active',
        FOREIGN KEY(user_id) REFERENCES users(id)
    );

    CREATE TABLE IF NOT EXISTS matches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lost_id INTEGER,
        found_id INTEGER,
        score REAL,
        FOREIGN KEY(lost_id) REFERENCES items(id),
        FOREIGN KEY(found_id) REFERENCES items(id)
    );

    """)

    columns = [
        row["name"]
        for row in con.execute(
            "PRAGMA table_info(items)"
        ).fetchall()
    ]

    if "color" not in columns:
        con.execute(
            "ALTER TABLE items ADD COLUMN color TEXT"
        )

    if "model_number" not in columns:
        con.execute(
            "ALTER TABLE items ADD COLUMN model_number TEXT"
        )

    con.commit()
    con.close()


# ============================================================
# HELPERS
# ============================================================

def allowed_file(filename):

    return (
        "." in filename
        and filename.rsplit(
            ".",
            1
        )[1].lower() in ALLOWED_EXTENSIONS
    )


def normalize(value):

    return (
        str(value or "")
        .strip()
        .lower()
    )


# ============================================================
# IMAGE MATCHING
# ============================================================

def image_similarity(path1, path2):

    try:

        if not path1 or not path2:
            return 0.0

        if not os.path.exists(path1):
            return 0.0

        if not os.path.exists(path2):
            return 0.0

        img1 = cv2.imread(
            path1,
            cv2.IMREAD_GRAYSCALE
        )

        img2 = cv2.imread(
            path2,
            cv2.IMREAD_GRAYSCALE
        )

        if img1 is None or img2 is None:
            return 0.0

        orb = cv2.ORB_create(
            nfeatures=1000
        )

        kp1, des1 = orb.detectAndCompute(
            img1,
            None
        )

        kp2, des2 = orb.detectAndCompute(
            img2,
            None
        )

        if des1 is None or des2 is None:
            return 0.0

        matcher = cv2.BFMatcher(
            cv2.NORM_HAMMING,
            crossCheck=True
        )

        matches = matcher.match(
            des1,
            des2
        )

        if not matches:
            return 0.0

        good = [
            m
            for m in matches
            if m.distance < 65
        ]

        base = max(
            12,
            min(
                len(kp1),
                len(kp2)
            )
        )

        score = (
            len(good) / base
        ) * 100

        return round(
            min(
                100.0,
                score
            ),
            2
        )

    except Exception as e:

        print(
            "Image matching error:",
            e
        )

        return 0.0


# ============================================================
# HOME
# ============================================================

@app.route("/")
def home():

    con = db()

    lost = con.execute("""
        SELECT *
        FROM items
        WHERE item_type='Lost'
        ORDER BY id DESC
    """).fetchall()

    found = con.execute("""
        SELECT *
        FROM items
        WHERE item_type='Found'
        ORDER BY id DESC
    """).fetchall()

    con.close()

    return render_template(
        "index.html",
        lost=lost,
        found=found
    )


# ============================================================
# REGISTER
# ============================================================

@app.route(
    "/register",
    methods=["GET", "POST"]
)
def register():

    if request.method == "POST":

        name = request.form.get(
            "name",
            ""
        ).strip()

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        if not name or not email or not password:

            flash(
                "Please fill all required fields."
            )

            return redirect(
                url_for("register")
            )

        if len(password) < 6:

            flash(
                "Password must contain at least 6 characters."
            )

            return redirect(
                url_for("register")
            )

        try:

            con = db()

            hashed_password = generate_password_hash(
                password
            )

            con.execute("""
                INSERT INTO users(
                    name,
                    email,
                    password
                )
                VALUES(?,?,?)
            """, (
                name,
                email,
                hashed_password
            ))

            con.commit()
            con.close()

            flash(
                "Registration successful. Please login."
            )

            return redirect(
                url_for("login")
            )

        except sqlite3.IntegrityError:

            flash(
                "Email already registered."
            )

            return redirect(
                url_for("register")
            )

    return render_template(
        "register.html"
    )


# ============================================================
# LOGIN
# ============================================================

@app.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    if request.method == "POST":

        email = request.form.get(
            "email",
            ""
        ).strip().lower()

        password = request.form.get(
            "password",
            ""
        )

        con = db()

        user = con.execute("""
            SELECT *
            FROM users
            WHERE email=?
        """, (
            email,
        )).fetchone()

        con.close()

        if user:

            password_ok = False

            try:
                password_ok = check_password_hash(
                    user["password"],
                    password
                )
            except Exception:
                password_ok = False

            # Compatibility with old plain-text accounts
            if not password_ok and user["password"] == password:

                password_ok = True

                con = db()

                con.execute("""
                    UPDATE users
                    SET password=?
                    WHERE id=?
                """, (
                    generate_password_hash(password),
                    user["id"]
                ))

                con.commit()
                con.close()

            if password_ok:

                session["uid"] = user["id"]
                session["name"] = user["name"]

                return redirect(
                    url_for("dashboard")
                )

        flash(
            "Invalid email or password."
        )

    return render_template(
        "login.html"
    )


# ============================================================
# LOGOUT
# ============================================================

@app.route("/logout")
def logout():

    session.clear()

    flash(
        "You have been logged out."
    )

    return redirect(
        url_for("home")
    )


# ============================================================
# GOOGLE LOGIN
# ============================================================

@app.route("/login/google")
def login_google():

    if not os.environ.get(
        "GOOGLE_CLIENT_ID"
    ) or not os.environ.get(
        "GOOGLE_CLIENT_SECRET"
    ):

        flash(
            "Google Login is not configured."
        )

        return redirect(
            url_for("login")
        )

    redirect_uri = url_for(
        "google_callback",
        _external=True
    )

    return google.authorize_redirect(
        redirect_uri
    )


@app.route("/auth/google/callback")
def google_callback():

    try:

        token = google.authorize_access_token()

        userinfo = token.get(
            "userinfo"
        )

        if not userinfo:

            userinfo = google.userinfo()

        email = normalize(
            userinfo.get(
                "email",
                ""
            )
        )

        name = (
            userinfo.get(
                "name",
                ""
            ).strip()
        )

        if not name:
            name = email.split("@")[0]

        if not email:

            flash(
                "Google account email was not received."
            )

            return redirect(
                url_for("login")
            )

        con = db()

        user = con.execute("""
            SELECT *
            FROM users
            WHERE email=?
        """, (
            email,
        )).fetchone()

        if not user:

            random_password = uuid.uuid4().hex

            con.execute("""
                INSERT INTO users(
                    name,
                    email,
                    password
                )
                VALUES(?,?,?)
            """, (
                name,
                email,
                generate_password_hash(
                    random_password
                )
            ))

            con.commit()

            user = con.execute("""
                SELECT *
                FROM users
                WHERE email=?
            """, (
                email,
            )).fetchone()

        con.close()

        session["uid"] = user["id"]
        session["name"] = user["name"]

        flash(
            "Google login successful."
        )

        return redirect(
            url_for("dashboard")
        )

    except Exception as e:

        print(
            "Google Login Error:",
            e
        )

        flash(
            "Google login failed. Please try again."
        )

        return redirect(
            url_for("login")
        )


# ============================================================
# REPORT LOST / FOUND
# ============================================================

@app.route(
    "/report/<kind>",
    methods=["GET", "POST"]
)
def report(kind):

    if "uid" not in session:

        flash(
            "Please login first."
        )

        return redirect(
            url_for("login")
        )

    if kind not in (
        "lost",
        "found"
    ):

        return redirect(
            url_for("home")
        )

    if request.method == "POST":

        item_name = request.form.get(
            "item_name",
            ""
        ).strip()

        category = request.form.get(
            "category",
            ""
        ).strip()

        color = request.form.get(
            "color",
            ""
        ).strip()

        model_number = request.form.get(
            "model_number",
            ""
        ).strip()

        location = request.form.get(
            "location",
            ""
        ).strip()

        date = request.form.get(
            "date",
            ""
        ).strip()

        description = request.form.get(
            "description",
            ""
        ).strip()

        if not item_name:
            flash("Please enter item name.")
            return redirect(request.url)

        if not category:
            flash("Please enter category.")
            return redirect(request.url)

        if not color:
            flash("Please enter colour.")
            return redirect(request.url)

        if not location:
            flash("Please enter location.")
            return redirect(request.url)

        if not date:
            flash("Please select date.")
            return redirect(request.url)

        if not description:
            flash("Please enter description.")
            return redirect(request.url)

        image = request.files.get(
            "image"
        )

        filename = ""

        if image and image.filename:

            safe_name = secure_filename(
                image.filename
            )

            if not allowed_file(
                safe_name
            ):

                flash(
                    "Only JPG, JPEG and PNG images are allowed."
                )

                return redirect(
                    request.url
                )

            extension = safe_name.rsplit(
                ".",
                1
            )[1].lower()

            filename = (
                uuid.uuid4().hex
                + "."
                + extension
            )

            image.save(
                os.path.join(
                    UPLOAD_DIR,
                    filename
                )
            )

        try:

            con = db()

            con.execute("""
                INSERT INTO items(
                    user_id,
                    item_type,
                    item_name,
                    category,
                    color,
                    model_number,
                    location,
                    date,
                    description,
                    image,
                    status
                )
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
            """, (
                session["uid"],
                kind.title(),
                item_name,
                category,
                color,
                model_number,
                location,
                date,
                description,
                filename,
                "Active"
            ))

            con.commit()
            con.close()

            flash(
                f"{kind.title()} item reported successfully."
            )

            return redirect(
                url_for("dashboard")
            )

        except Exception as e:

            print(
                "Report Save Error:",
                e
            )

            flash(
                "Unable to save report."
            )

            return redirect(
                request.url
            )

    return render_template(
        "report.html",
        kind=kind.title()
    )


# ============================================================
# DASHBOARD
# ============================================================

@app.route("/dashboard")
def dashboard():

    if "uid" not in session:

        return redirect(
            url_for("login")
        )

    con = db()

    items = con.execute("""
        SELECT *
        FROM items
        WHERE user_id=?
        ORDER BY id DESC
    """, (
        session["uid"],
    )).fetchall()

    total = len(items)

    lost_count = sum(
        1
        for item in items
        if item["item_type"] == "Lost"
    )

    found_count = sum(
        1
        for item in items
        if item["item_type"] == "Found"
    )

    con.close()

    return render_template(
        "dashboard.html",
        items=items,
        total=total,
        lost_count=lost_count,
        found_count=found_count
    )


# ============================================================
# AI MATCHING
# ============================================================

@app.route(
    "/matches/<int:item_id>"
)
def matches(item_id):

    con = db()

    item = con.execute("""
        SELECT *
        FROM items
        WHERE id=?
    """, (
        item_id,
    )).fetchone()

    if not item:

        con.close()

        flash(
            "Item not found."
        )

        return redirect(
            url_for("home")
        )

    opposite_type = (
        "Found"
        if item["item_type"] == "Lost"
        else "Lost"
    )

    candidates = con.execute("""
        SELECT *
        FROM items
        WHERE item_type=?
        AND status='Active'
        AND id != ?
        ORDER BY id DESC
    """, (
        opposite_type,
        item_id
    )).fetchall()

    results = []

    for candidate in candidates:

        score = 0.0
        reasons = []

        # IMAGE 55%
        if (
            item["image"]
            and candidate["image"]
        ):

            image_score = image_similarity(
                os.path.join(
                    UPLOAD_DIR,
                    item["image"]
                ),
                os.path.join(
                    UPLOAD_DIR,
                    candidate["image"]
                )
            )

            score += image_score * 0.55

            if image_score >= 20:

                reasons.append(
                    f"Image similarity ({image_score}%)"
                )

        # MODEL NUMBER 20%
        model1 = normalize(
            item["model_number"]
        )

        model2 = normalize(
            candidate["model_number"]
        )

        if model1 and model2:

            if model1 == model2:

                score += 20

                reasons.append(
                    "Model Number matches"
                )

        # COLOUR 10%
        color1 = normalize(
            item["color"]
        )

        color2 = normalize(
            candidate["color"]
        )

        if color1 and color2:

            if color1 == color2:

                score += 10

                reasons.append(
                    "Colour matches"
                )

        # CATEGORY 8%
        category1 = normalize(
            item["category"]
        )

        category2 = normalize(
            candidate["category"]
        )

        if category1 and category2:

            if category1 == category2:

                score += 8

                reasons.append(
                    "Category matches"
                )

        # LOCATION 7%
        location1 = normalize(
            item["location"]
        )

        location2 = normalize(
            candidate["location"]
        )

        if location1 and location2:

            if location1 == location2:

                score += 7

                reasons.append(
                    "Location matches"
                )

        score = min(
            100,
            round(
                score,
                2
            )
        )

        results.append({
            "score": score,
            "item": candidate,
            "reasons": reasons
        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    con.close()

    return render_template(
        "matches.html",
        item=item,
        results=results[:10]
    )


# ============================================================
# SEARCH
# ============================================================

@app.route("/search")
def search():

    q = request.args.get(
        "q",
        ""
    ).strip()

    con = db()

    if q:

        search_value = f"%{q}%"

        rows = con.execute("""
            SELECT *
            FROM items
            WHERE item_name LIKE ?
            OR category LIKE ?
            OR color LIKE ?
            OR model_number LIKE ?
            OR location LIKE ?
            OR description LIKE ?
            ORDER BY id DESC
        """, (
            search_value,
            search_value,
            search_value,
            search_value,
            search_value,
            search_value
        )).fetchall()

    else:

        rows = con.execute("""
            SELECT *
            FROM items
            ORDER BY id DESC
        """).fetchall()

    con.close()

    return render_template(
        "search.html",
        rows=rows,
        q=q
    )


# ============================================================
# ADMIN
# ============================================================

@app.route("/admin")
def admin():

    if "uid" not in session:

        return redirect(
            url_for("login")
        )

    con = db()

    users = con.execute("""
        SELECT COUNT(*) AS c
        FROM users
    """).fetchone()["c"]

    items = con.execute("""
        SELECT COUNT(*) AS c
        FROM items
    """).fetchone()["c"]

    lost = con.execute("""
        SELECT COUNT(*) AS c
        FROM items
        WHERE item_type='Lost'
    """).fetchone()["c"]

    found = con.execute("""
        SELECT COUNT(*) AS c
        FROM items
        WHERE item_type='Found'
    """).fetchone()["c"]

    con.close()

    return render_template(
        "admin.html",
        users=users,
        items=items,
        lost=lost,
        found=found
    )


# ============================================================
# START DATABASE
# ============================================================

init_db()


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    app.run(
        host="0.0.0.0",
        port=int(
            os.environ.get(
                "PORT",
                5000
            )
        ),
        debug=True
    )
