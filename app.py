from flask import Flask, request, session, redirect, url_for, render_template, flash, make_response, Response
import psycopg2
import psycopg2.extras
import re
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import functools
from ultralytics import YOLO
import cv2
import easyocr
import os
import base64
from flask import jsonify

app = Flask(__name__)
app.secret_key = secrets.token_hex(16)

MODEL_PATH = "model/best.pt"
model = YOLO(MODEL_PATH)
reader = easyocr.Reader(['en', 'ar'])
UPLOAD_FOLDER = os.path.join(app.root_path, 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
uploads_dir = os.path.join(app.root_path, 'uploads')
os.makedirs(uploads_dir, exist_ok=True)

DB_HOST = "localhost"
DB_NAME = "sampledb"
DB_USER = "postgres"
DB_PASS = "postgre"

conn = psycopg2.connect(dbname=DB_NAME, user=DB_USER, password=DB_PASS, host=DB_HOST)
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def nocache(view):
    @functools.wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, public, max-age=0"
        response.headers["Expires"] = "0"
        response.headers["Pragma"] = "no-cache"
        return response
    return no_cache

@app.route('/')
def landing():
    return render_template('landing.html')

@app.route('/home')
@nocache
def home():
    if 'loggedin' in session:
        return redirect(url_for('index'))
    return redirect(url_for('login'))

@app.route('/login/', methods=['GET', 'POST'])
@nocache
def login():
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form:
        username = request.form['username']
        password = request.form['password']
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()
        if account:
            password_rs = account['password']
            if check_password_hash(password_rs, password):
                session['loggedin'] = True
                session['id'] = account['id']
                session['username'] = account['username']
                return redirect(url_for('profile'))
            else:
                flash('Incorrect username/password')
        else:
            flash('Incorrect username/password')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
@nocache
def register():
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    if request.method == 'POST' and 'username' in request.form and 'password' in request.form and 'email' in request.form:
        fullname = request.form['fullname']
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']
        _hashed_password = generate_password_hash(password)
        cursor.execute('SELECT * FROM users WHERE username = %s', (username,))
        account = cursor.fetchone()
        if account:
            flash('Account already exists!')
        elif not re.match(r'[^@]+@[^@]+\.[^@]+', email):
            flash('Invalid email address!')
        elif not re.match(r'[A-Za-z0-9]+', username):
            flash('Username must contain only characters and numbers!')
        elif not username or not password or not email:
            flash('Please fill out the form!')
        else:
            cursor.execute("INSERT INTO users (fullname, username, password, email) VALUES (%s,%s,%s,%s)", (fullname, username, _hashed_password, email))
            conn.commit()
            flash('You have successfully registered!')
    elif request.method == 'POST':
        flash('Please fill out the form!')
    return render_template('register.html')

@app.route('/logout')
@nocache
def logout():
    session.pop('loggedin', None)
    session.pop('id', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/profile')
@nocache
def profile():
    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    if 'loggedin' in session:
        cursor.execute('SELECT * FROM users WHERE id = %s', [session['id']])
        account = cursor.fetchone()
        return render_template('profile.html', account=account)
    return redirect(url_for('login'))

@app.route('/home.html')
@nocache
def index():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute("SELECT id_camera FROM cameras")
        camera_ids = cur.fetchall()  
        cur.execute("SELECT * FROM Detections")
        list_detections = cur.fetchall()
        cur.close()
        return render_template('home.html', list_detections=list_detections, camera_ids=camera_ids)
    except psycopg2.Error as e:
        flash('Error fetching detections from database: {}'.format(str(e)))
        return render_template('home.html', list_detections=[], camera_ids=[])

@app.route('/add_detection', methods=['POST'])
@nocache
def add_detection():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    try:
        cur = conn.cursor()
        if request.method == 'POST':
            id_camera = request.form['id_camera']
            matricule = request.form['matricule']
            cur.execute("INSERT INTO Detections (id_camera, matricule, date_heure) VALUES (%s, %s, NOW())", (id_camera, matricule))
            conn.commit()
            flash('Detection added successfully')
            return redirect(url_for('index'))
    except psycopg2.Error as e:
        flash('Error adding detection: {}'.format(str(e)))
    finally:
        cur.close()

@app.route('/edit/<int:id_detection>', methods=['GET', 'POST'])
@nocache
def edit_detection(id_detection):
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute('SELECT * FROM detections WHERE id_detection = %s', (id_detection,))
        detection = cur.fetchone()
        cur.close()
        if detection:
            return render_template('edit.html', detection=detection)
        else:
            flash('Detection not found')
            return redirect(url_for('index'))
    except psycopg2.Error as e:
        flash('Error fetching detection: {}'.format(str(e)))
        return redirect(url_for('index'))

@app.route('/update/<int:id_detection>', methods=['POST'])
@nocache
def update_detection(id_detection):
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    try:
        cur = conn.cursor()
        if request.method == 'POST':
            id_camera = request.form['id_camera']
            matricule = request.form['matricule']
            cur.execute("UPDATE detections SET id_camera = %s, matricule = %s WHERE id_detection = %s", (id_camera, matricule, id_detection))
            conn.commit()
            flash('Detection updated successfully')
            return redirect(url_for('index'))
    except psycopg2.Error as e:
        flash('Error updating detection: {}'.format(str(e)))
    finally:
        cur.close()

@app.route('/delete/<int:id_detection>', methods=['POST'])
@nocache
def delete_detection(id_detection):
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    try:
        cur = conn.cursor()
        cur.execute('DELETE FROM detections WHERE id_detection = %s', (id_detection,))
        conn.commit()
        flash('Detection deleted successfully')
    except psycopg2.Error as e:
        flash('Error deleting detection: {}'.format(str(e)))
    finally:
        cur.close()
    return redirect(url_for('index'))

@app.route('/update_password', methods=['POST'])
@nocache
def update_password():
    if 'loggedin' not in session:
        return redirect(url_for('login'))

    current_password = request.form['current_password']
    new_password = request.form['new_password']
    repeat_password = request.form['repeat_password']

    if new_password != repeat_password:
        flash('New passwords do not match', 'error')
        return redirect(url_for('profile'))

    cursor = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
    cursor.execute('SELECT password FROM users WHERE id = %s', (session['id'],))
    user = cursor.fetchone()
    if user and check_password_hash(user['password'], current_password):
        hashed_password = generate_password_hash(new_password)
        cursor.execute("UPDATE users SET password = %s WHERE id = %s", (hashed_password, session['id']))
        conn.commit()
        flash('Password updated successfully', 'success')
    else:
        flash('Incorrect current password', 'error')

    return redirect(url_for('profile'))
    
@app.route('/cameras', methods=['GET', 'POST'])
@nocache
def cameras():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        id_port = request.form['id_port']
        type_camera = request.form['type_camera']
        
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO cameras (id_port, type_camera) VALUES (%s, %s)", (id_port, type_camera))
            conn.commit()
            flash('New camera added successfully', 'success')
        except psycopg2.Error as e:
            flash('Error adding camera: {}'.format(str(e)), 'error')
        finally:
            cur.close()

        return redirect(url_for('cameras'))
    
    return render_template('cameras.html')

@app.route('/add_new_camera', methods=['POST'])
def add_new_camera():
    if 'loggedin' not in session:
        return redirect(url_for('login'))
    
    if request.method == 'POST':
        id_port = request.form['id_port']
        type_camera = request.form['type_camera']
        
        try:
            cur = conn.cursor()
            cur.execute("INSERT INTO cameras (id_port, type_camera) VALUES (%s, %s)", (id_port, type_camera))
            conn.commit()
            flash('New camera added successfully', 'success_camera')
        except psycopg2.Error as e:
            flash('Error adding camera: {}'.format(str(e)), 'error')
        finally:
            cur.close()

        return redirect(url_for('cameras'))

@app.route('/check_error')
def check_error():
    try:
        cur = conn.cursor()
        cur.execute("INSERT INTO cameras (id_port, type_camera) VALUES (%s, %s)", (1, "test"))
        conn.commit()
        flash('Test camera added successfully', 'success')
    except psycopg2.Error as e:
        flash('Error adding test camera: {}'.format(str(e)), 'error')
    finally:
        cur.close()

    return redirect(url_for('cameras'))

@app.route('/detect', methods=['POST'])
def detect_license_plate():
    if 'image' not in request.files:
        return jsonify({"text": "Aucun fichier téléchargé"})

    image = request.files['image']
    img_path = os.path.join(uploads_dir, image.filename)
    image.save(img_path)

    img = cv2.imread(img_path)

    modelRes = model(img)

    for res in modelRes:
        for r in res.boxes.xyxy:
            x1, y1, x2, y2 = map(int, r[:4])
            plate_img = img[y1:y2, x1:x2]
            gray_plate_img = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
            plate_text = reader.readtext(gray_plate_img)
            if plate_text:
                plate_text_only = plate_text[0][1]
                
                _, img_encoded = cv2.imencode('.png', plate_img)
                plate_img_base64 = base64.b64encode(img_encoded).decode('utf-8')
                
                return jsonify({"text": plate_text_only, "plate_image": "data:image/png;base64," + plate_img_base64})

    return jsonify({"text": "Plaque d'immatriculation non détectée"})
@app.route('/livedetection')
def livedetection():
    return render_template('livedetection.html')
cap = cv2.VideoCapture(0)

def gen_frames():  
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Erreur lors de la lecture de la frame")
            break

        modelRes = model(frame)

        for r in modelRes:
            platBox = r.boxes
            if len(platBox) != 0:
                x1, y1, x2, y2 = platBox.xyxy[0]

                x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)

                plate_img = frame[y1:y2, x1:x2]

                plate_img_copy = plate_img.copy()

                gray_plate_img = cv2.cvtColor(plate_img_copy, cv2.COLOR_BGR2GRAY)

                plate_text = reader.readtext(gray_plate_img)

                if plate_text:
                  
                    plate_text_only = plate_text[0][1] 
                    print("Texte de la plaque d'immatriculation:", plate_text_only)

                  
                    font_path = "chemin/vers/votre/police_arabe.ttf"
                    font = cv2.FONT_HERSHEY_SIMPLEX
                    font_scale = 0.9
                    font_color = (0, 255, 0)

                    cv2.putText(frame, plate_text_only, (x1, y1 - 10), font, font_scale, font_color, 2)

                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

        ret, buffer = cv2.imencode('.jpg', frame)
        frame = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n') 
@app.route('/video_feed')
@nocache
def video_feed():
    return Response(gen_frames(), mimetype='multipart/x-mixed-replace; boundary=frame')


if __name__ == '__main__':
    app.run(debug=True)
