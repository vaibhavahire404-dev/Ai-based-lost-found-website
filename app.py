
from flask import Flask, render_template, request, redirect, url_for, session, flash
import sqlite3, os, uuid, cv2
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-key")
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE_DIR, "lostfound.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED = {"png", "jpg", "jpeg"}

def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS items(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, item_type TEXT NOT NULL, item_name TEXT NOT NULL,
        category TEXT, location TEXT, date TEXT, description TEXT,
        image TEXT, status TEXT DEFAULT 'Active',
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS matches(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lost_id INTEGER, found_id INTEGER, score REAL,
        FOREIGN KEY(lost_id) REFERENCES items(id),
        FOREIGN KEY(found_id) REFERENCES items(id)
    );
    """)
    con.commit(); con.close()

def allowed(filename):
    return "." in filename and filename.rsplit(".",1)[1].lower() in ALLOWED

def image_similarity(a, b):
    """OpenCV ORB feature matching. Returns a percentage-like score."""
    try:
        img1 = cv2.imread(a, cv2.IMREAD_GRAYSCALE)
        img2 = cv2.imread(b, cv2.IMREAD_GRAYSCALE)
        if img1 is None or img2 is None: return 0.0
        orb = cv2.ORB_create(nfeatures=800)
        k1,d1 = orb.detectAndCompute(img1,None)
        k2,d2 = orb.detectAndCompute(img2,None)
        if d1 is None or d2 is None: return 0.0
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
        matches = matcher.match(d1,d2)
        if not matches: return 0.0
        good = [m for m in matches if m.distance < 65]
        return round(min(100.0, (len(good) / max(12, min(len(k1),len(k2)))) * 100), 2)
    except Exception:
        return 0.0

@app.route("/")
def home():
    con=db()
    lost=con.execute("SELECT * FROM items WHERE item_type='Lost' ORDER BY id DESC").fetchall()
    found=con.execute("SELECT * FROM items WHERE item_type='Found' ORDER BY id DESC").fetchall()
    con.close()
    return render_template("index.html", lost=lost, found=found)

@app.route("/register", methods=["GET","POST"])
def register():
    if request.method=="POST":
        name=request.form["name"].strip(); email=request.form["email"].strip().lower(); pw=request.form["password"]
        try:
            con=db(); con.execute("INSERT INTO users(name,email,password) VALUES(?,?,?)",(name,email,pw)); con.commit(); con.close()
            flash("Registration successful. Please login.")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Email already registered.")
    return render_template("register.html")

@app.route("/login", methods=["GET","POST"])
def login():
    if request.method=="POST":
        email=request.form["email"].strip().lower(); pw=request.form["password"]
        con=db(); u=con.execute("SELECT * FROM users WHERE email=? AND password=?",(email,pw)).fetchone(); con.close()
        if u:
            session["uid"]=u["id"]; session["name"]=u["name"]; return redirect(url_for("dashboard"))
        flash("Invalid email or password.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear(); return redirect(url_for("home"))

@app.route("/report/<kind>", methods=["GET","POST"])
def report(kind):
    if "uid" not in session: return redirect(url_for("login"))
    if kind not in ("lost","found"): return redirect(url_for("home"))
    if request.method=="POST":
        image=request.files.get("image")
        filename=""
        if image and image.filename:
            if not allowed(image.filename):
                flash("Only JPG, JPEG and PNG images are allowed."); return redirect(request.url)
            ext=image.filename.rsplit(".",1)[1].lower()
            filename=f"{uuid.uuid4().hex}.{ext}"
            image.save(os.path.join(UPLOAD_DIR, filename))
        con=db()
        con.execute("""INSERT INTO items(user_id,item_type,item_name,category,location,date,description,image)
                       VALUES(?,?,?,?,?,?,?,?)""",
                    (session["uid"],kind.title(),request.form["item_name"],request.form["category"],
                     request.form["location"],request.form["date"],request.form["description"],filename))
        con.commit(); con.close()
        flash(f"{kind.title()} item reported successfully.")
        return redirect(url_for("dashboard"))
    return render_template("report.html", kind=kind.title())

@app.route("/dashboard")
def dashboard():
    if "uid" not in session: return redirect(url_for("login"))
    con=db()
    items=con.execute("SELECT * FROM items WHERE user_id=? ORDER BY id DESC",(session["uid"],)).fetchall()
    con.close()
    return render_template("dashboard.html", items=items)

@app.route("/matches/<int:item_id>")
def matches(item_id):
    con=db()
    item=con.execute("SELECT * FROM items WHERE id=?",(item_id,)).fetchone()
    if not item: con.close(); return redirect(url_for("home"))
    opposite="Found" if item["item_type"]=="Lost" else "Lost"
    candidates=con.execute("SELECT * FROM items WHERE item_type=? AND status='Active'",(opposite,)).fetchall()
    results=[]
    for c in candidates:
        score=image_similarity(os.path.join(UPLOAD_DIR,item["image"]), os.path.join(UPLOAD_DIR,c["image"])) if item["image"] and c["image"] else 0
        # Add small metadata boosts to make practical matching more useful.
        if item["category"] and c["category"] and item["category"].lower()==c["category"].lower(): score += 12
        if item["location"] and c["location"] and item["location"].lower()==c["location"].lower(): score += 8
        score=min(100, round(score,2))
        results.append((score,c))
    results.sort(key=lambda x:x[0], reverse=True)
    con.close()
    return render_template("matches.html", item=item, results=results[:10])

@app.route("/search")
def search():
    q=request.args.get("q","").strip()
    con=db()
    rows=con.execute("""SELECT * FROM items WHERE item_name LIKE ? OR category LIKE ? OR location LIKE ?
                        ORDER BY id DESC""",(f"%{q}%",f"%{q}%",f"%{q}%")).fetchall()
    con.close()
    return render_template("search.html", rows=rows, q=q)

@app.route("/admin")
def admin():
    con=db()
    users=con.execute("SELECT COUNT(*) c FROM users").fetchone()["c"]
    items=con.execute("SELECT COUNT(*) c FROM items").fetchone()["c"]
    lost=con.execute("SELECT COUNT(*) c FROM items WHERE item_type='Lost'").fetchone()["c"]
    found=con.execute("SELECT COUNT(*) c FROM items WHERE item_type='Found'").fetchone()["c"]
    con.close()
    return render_template("admin.html",users=users,items=items,lost=lost,found=found)

init_db()

if __name__ == "__main__":
    app.run()
