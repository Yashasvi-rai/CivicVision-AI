"""CivicVision AI complaint management application.

Handles image classification, GPS/manual location processing, complaint
registration, administration, analytics, and email notifications.
"""

import csv
import hashlib
import io
import os
import random
import re
import shutil
import smtplib
import ssl
import threading
import time
from datetime import datetime
from email.message import EmailMessage
from functools import wraps

import cv2
import numpy as np
import piexif
import pytesseract
import requests
from dotenv import load_dotenv
from flask import Flask, Response, flash, jsonify, make_response, redirect, render_template, request, send_from_directory, session, url_for
from flask_sqlalchemy import SQLAlchemy
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable
from geopy.geocoders import Nominatim
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS
from sqlalchemy import func
from tensorflow.keras.models import load_model
from tensorflow.keras.preprocessing import image
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

load_dotenv()

# =====================================================
# TESSERACT OCR CONFIGURATION
# =====================================================

_tesseract_candidates = [
    shutil.which("tesseract"),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe\tesseract.exe",
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"
]

TESSERACT_CONFIGURED = False

for _tesseract_path in _tesseract_candidates:
    if _tesseract_path and os.path.isfile(_tesseract_path):
        pytesseract.pytesseract.tesseract_cmd = _tesseract_path
        TESSERACT_CONFIGURED = True
        print("Tesseract OCR configured:", _tesseract_path)
        break

if not TESSERACT_CONFIGURED:
    print("WARNING: Tesseract OCR executable not found.")

# =====================================================
# FLASK APP
# =====================================================

app = Flask(__name__)

app.secret_key = os.getenv("FLASK_SECRET_KEY", "urban_ai_secret_key")

UPLOAD_FOLDER = os.path.join(app.root_path, "uploads")
app.config['UPLOAD_FOLDER'] = os.getenv("UPLOAD_FOLDER", UPLOAD_FOLDER)

os.makedirs(
    app.config['UPLOAD_FOLDER'],
    exist_ok=True
)


# CivicVision AI sender account. Keep credentials only in .env.
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "").strip()

# Google displays App Passwords with spaces. Remove spaces before login.
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "").replace(" ", "").strip()

SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_SSL_PORT = 465

# Prevent simultaneous Gmail AUTH sessions from the duplicate frontend requests.
EMAIL_SEND_LOCK = threading.Lock()

# Idempotency protection: the same uploaded image from the same user is treated
# as one submission for a short window. This protects the database and email flow
# even if the browser sends /predict twice.
PREDICT_DEDUPE_LOCK = threading.Lock()
PREDICT_DEDUPE = {}
PREDICT_DEDUPE_WINDOW = 60

# =====================================================
# GOOGLE MAPS GEOCODING CONFIGURATION
# =====================================================
# Keep the API key in .env. Do NOT hard-code it in app.py.
GOOGLE_MAPS_API_KEY = os.getenv(
    "GOOGLE_MAPS_API_KEY",
    ""
).strip()
GOOGLE_GEOCODING_URL = "https://maps.googleapis.com/maps/api/geocode/json"

def _validate_email_configuration():
    """Validate the Gmail sender configuration."""
    if not EMAIL_ADDRESS:
        raise RuntimeError("EMAIL_ADDRESS is missing from the .env file.")

    if not EMAIL_PASSWORD:
        raise RuntimeError("EMAIL_PASSWORD is missing from the .env file.")

    if len(EMAIL_PASSWORD) != 16:
        raise RuntimeError(
            "EMAIL_PASSWORD does not look like a 16-character Gmail App Password. "
            "Generate an App Password for the sender Gmail account."
        )


def _send_email_via_gmail(message):
    """Send an email through Gmail using the same TLS sequence verified by smtp_test.py."""
    _validate_email_configuration()

    context = ssl.create_default_context()
    first_error = None

    # Serialize SMTP authentication. This is important because the frontend
    # was submitting /predict twice at the same time.
    with EMAIL_SEND_LOCK:
        try:
            print("Trying Gmail SMTP STARTTLS on port 587...")

            with smtplib.SMTP(
                SMTP_SERVER,
                SMTP_PORT,
                timeout=120
            ) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(message)

            print("Gmail SMTP STARTTLS send successful.")
            return

        except Exception as error:
            first_error = error
            print("Gmail port 587 failed:", repr(error))

        try:
            print("Trying Gmail SMTP SSL on port 465...")

            with smtplib.SMTP_SSL(
                SMTP_SERVER,
                SMTP_SSL_PORT,
                timeout=120,
                context=context
            ) as server:
                server.ehlo()
                server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
                server.send_message(message)

            print("Gmail SMTP SSL send successful.")
            return

        except Exception as second_error:
            print("Gmail port 465 failed:", repr(second_error))
            raise RuntimeError(
                "Gmail email sending failed on both SMTP ports 587 and 465. "
                f"Port 587 error: {repr(first_error)} | "
                f"Port 465 error: {repr(second_error)}"
            ) from second_error

def send_test_email():
    """Send a test email to the CivicVision sender account."""
    msg = EmailMessage()

    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = "CivicVision AI Test"

    msg.set_content(
        "This is a test email from CivicVision AI. "
        "The Gmail email system is working successfully."
    )

    _send_email_via_gmail(msg)

    print("Test email sent successfully!")


def send_complaint_email(
    recipient_email,
    complaint_ref,
    issue,
    confidence,
    description,
    department,
    authority,
    address,
    latitude,
    longitude,
    image_path
):
    """
    Send the complete complaint notification to the email address
    stored for the currently logged-in registered user.
    """

    recipient_email = (recipient_email or "").strip()

    if not recipient_email:
        raise ValueError("Complaint recipient email is empty.")

    msg = EmailMessage()

    # Sender = CivicVision system Gmail.
    msg["From"] = EMAIL_ADDRESS

    # Recipient = registered/logged-in user's Gmail.
    msg["To"] = recipient_email

    msg["Subject"] = (
        f"CivicVision AI Complaint Notification - {complaint_ref}"
    )

    body = f"""
CIVICVISION AI - COMPLAINT NOTIFICATION

Dear CivicVision AI User,

Your complaint has been successfully registered.

Complaint Reference:
{complaint_ref}

Issue:
{issue}

AI Confidence:
{confidence:.2f}%

AI Generated Description:
{description}

Assigned Department:
{department}

Authority:
{authority}

Detected Location:
{address}

Latitude:
{latitude}

Longitude:
{longitude}

Current Status:
Pending

This complaint was automatically generated and registered by CivicVision AI.

Please keep the complaint reference number for tracking:
{complaint_ref}

Regards,
CivicVision AI
Smart Complaint Management System
"""

    msg.set_content(body)

    # Attach a compressed copy of the uploaded complaint image.
    # GPS-camera photos can be very large; sending the original file can
    # cause Gmail SMTP DATA transmission to stall or time out. The original
    # upload is still preserved in the uploads folder/database.
    if image_path and os.path.exists(image_path):
        try:
            with Image.open(image_path) as original_image:
                if original_image.mode not in ("RGB", "L"):
                    original_image = original_image.convert("RGB")

                # Keep the email attachment reasonably small while retaining
                # enough detail for the complaint reviewer.
                max_dimension = 1600
                if max(original_image.size) > max_dimension:
                    scale = max_dimension / float(max(original_image.size))
                    new_size = (
                        max(1, int(original_image.width * scale)),
                        max(1, int(original_image.height * scale))
                    )
                    original_image = original_image.resize(
                        new_size,
                        Image.LANCZOS
                    )

                buffer = io.BytesIO()
                original_image.save(
                    buffer,
                    format="JPEG",
                    quality=78,
                    optimize=True
                )
                image_data = buffer.getvalue()

            print(
                "Email image attachment size:",
                f"{len(image_data) / 1024:.1f} KB"
            )

            msg.add_attachment(
                image_data,
                maintype="image",
                subtype="jpeg",
                filename=os.path.splitext(
                    os.path.basename(image_path)
                )[0] + ".jpg"
            )

        except Exception as attachment_error:
            # The complaint itself is already stored. Do not prevent the
            # notification email from being sent if image compression fails.
            print(
                "Email attachment preparation failed:",
                repr(attachment_error)
            )

    print("=" * 60)
    print("STARTING COMPLAINT EMAIL")
    print("Sender:", EMAIL_ADDRESS)
    print("Recipient:", recipient_email)
    print("Complaint Reference:", complaint_ref)
    print("=" * 60)

    _send_email_via_gmail(msg)

    print(
        "✓ Complaint email sent successfully to:",
        recipient_email
    )


# =====================================================
# SERVE UPLOADED IMAGES
# =====================================================

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

# =====================================================
# DATABASE CONFIGURATION
# =====================================================

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///complaints.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# =====================================================
# LOAD CNN MODEL
# =====================================================
model = load_model("best_model.h5")

# =====================================================
# CLASS NAMES
# =====================================================

class_names = [
    "drainage_issue",
    "garbage",
    "pothole"
]

# =====================================================
# DATABASE MODEL
# =====================================================

class Complaint(db.Model):

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    issue = db.Column(
        db.String(100)
    )

    description = db.Column(
        db.String(500)
    )

    department = db.Column(
        db.String(200)
    )

    authority = db.Column(
        db.String(100)
    )

    location = db.Column(
        db.String(500)
    )

    latitude = db.Column(
        db.Float
    )

    longitude = db.Column(
        db.Float
    )

    priority = db.Column(
        db.String(50)
    )

    status = db.Column(
        db.String(100)
    )

    remarks = db.Column(
        db.String(500)
    )

    image_path = db.Column(
        db.String(500)
    )
    reference_id = db.Column(
    db.String(50),
    unique=True
    )
    created_at = db.Column(
        db.DateTime,
        default=datetime.utcnow
    )

    resolved_at = db.Column(
        db.DateTime,
        nullable=True
    )


# =====================================================
# IMAGE PREDICTION FUNCTION
# =====================================================

def predict_image(img_path):

    img = image.load_img(
        img_path,
        target_size=(224, 224)
    )

    img_array = image.img_to_array(img)

    img_array = np.expand_dims(
        img_array,
        axis=0
    )

    img_array = img_array / 255.0

    prediction = model.predict(img_array)

    predicted_class = np.argmax(prediction)

    confidence = float(np.max(prediction))

    label = class_names[predicted_class]

    return label, confidence
#=====================================================
# IMAGE PREDICTION FUNCTION
# =====================================================


def get_gps_coordinates(filepath):

    exif = piexif.load(filepath)

    gps = exif["GPS"]

    if not gps:
        return None

    lat = gps[piexif.GPSIFD.GPSLatitude]
    lat_ref = gps[piexif.GPSIFD.GPSLatitudeRef].decode()

    lon = gps[piexif.GPSIFD.GPSLongitude]
    lon_ref = gps[piexif.GPSIFD.GPSLongitudeRef].decode()

    def convert(value):

        d = value[0][0] / value[0][1]

        m = value[1][0] / value[1][1]

        s = value[2][0] / value[2][1]

        return d + (m / 60) + (s / 3600)

    latitude = convert(lat)

    longitude = convert(lon)

    if lat_ref == "S":
        latitude = -latitude

    if lon_ref == "W":
        longitude = -longitude

    return latitude, longitude
# =====================================================
# AI COMPLAINT DESCRIPTION
# =====================================================

def generate_description(label):

    descriptions = {

        "garbage": [
            "An accumulation of garbage has been detected at the reported location. The waste may create an unhygienic environment, attract insects and stray animals, and affect the cleanliness of the surrounding public area. Municipal sanitation and waste collection action is recommended.",
            "The uploaded image indicates a garbage accumulation problem in the reported area. Uncollected waste can lead to unpleasant surroundings, sanitation concerns, and obstruction of public spaces. The issue should be inspected and appropriate waste removal measures should be taken.",
            "AI analysis has identified visible garbage accumulation at the complaint location. The presence of unmanaged waste may affect public hygiene and the cleanliness of the surrounding environment. Timely collection and proper disposal are recommended to prevent further accumulation.",
            "A waste accumulation issue has been detected from the submitted image. The condition may contribute to poor sanitation, unpleasant surroundings, and possible environmental concerns if it remains unattended. The concerned sanitation department should inspect and address the reported location."
        ],

        "pothole": [
            "A road pothole has been detected at the reported location. The damaged road surface may create a safety risk for motorists, cyclists, pedestrians, and other road users, particularly during low visibility or wet conditions. Road maintenance and repair are recommended.",
            "The image indicates a pothole or significant road-surface depression at the reported location. Such damage can affect vehicle movement and may increase the possibility of accidents or vehicle damage. The concerned road maintenance authority should inspect the site and arrange suitable repairs.",
            "AI analysis has identified road damage in the form of a pothole. The damaged section may interfere with normal traffic movement and pose a potential hazard to road users. Prompt inspection, filling, and restoration of the affected road surface are recommended.",
            "A visible pothole has been detected on the roadway shown in the submitted image. Continued exposure to traffic and weather conditions may increase the size of the damaged area. The concerned road maintenance department should verify the issue and undertake necessary corrective work."
        ],

        "drainage_issue": [
            "A drainage-related problem has been detected at the reported location. The condition may result in water stagnation, restricted water flow, or localized flooding and can create sanitation concerns if left unattended. The drainage department should inspect the area and take appropriate corrective action.",
            "The uploaded image indicates a possible drainage blockage or water-flow problem. Accumulated water around the affected area may inconvenience pedestrians and residents and could contribute to unhygienic conditions. Cleaning and restoration of the drainage flow are recommended.",
            "AI analysis has identified a drainage issue at the complaint location. The observed condition may indicate blocked or inadequate drainage and could lead to water accumulation during rainfall. The concerned department should inspect the drainage system and clear any obstruction if required.",
            "A potential drainage blockage or overflow condition has been detected in the submitted image. If the issue remains unresolved, standing water may persist and affect nearby roads or public areas. Timely inspection and maintenance of the drainage infrastructure are recommended."
        ]
    }

    options = descriptions.get(
        label,
        [
            "An urban infrastructure issue has been detected from the submitted image. The reported location should be inspected by the concerned authority to verify the condition and determine the appropriate corrective action."
        ]
    )

    return random.choice(options)
class User(db.Model):

    id = db.Column(db.Integer, primary_key=True)

    name = db.Column(db.String(100), nullable=False)

    email = db.Column(db.String(120), unique=True, nullable=False)

    password = db.Column(db.String(200), nullable=False)

    role = db.Column(db.String(20), default="user")

    
# =====================================================
# AUTHORITY DETECTION
# =====================================================

def detect_authority(address):
    """Determine the responsible authority from an address.

    Highway abbreviations are matched as standalone route markers so that
    normal words containing ``nh`` or ``sh`` (for example, ``Dakshina``)
    do not incorrectly trigger Central or State authority.
    """
    address = re.sub(r"\s+", " ", (address or "").strip().lower())

    central_highway = (
        "national highway" in address
        or bool(re.search(r"\bnh\s*[-/]?\s*\d+\b", address))
        or bool(re.search(r"\bnh\b", address))
    )

    if central_highway:
        return "Central Authority"

    state_highway = (
        "state highway" in address
        or bool(re.search(r"\bsh\s*[-/]?\s*\d+\b", address))
        or bool(re.search(r"\bsh\b", address))
    )

    if state_highway:
        return "State Authority"

    return "Municipal Authority"

# =====================================================
# DEPARTMENT ASSIGNMENT
# =====================================================

def assign_department(label, authority):

    # =================================================
    # CENTRAL AUTHORITY
    # =================================================

    if authority == "Central Authority":

        if label == "pothole":

            return (
                "National Highway Authority"
            )

        elif label == "garbage":

            return (
                "Central Sanitation Department"
            )

        elif label == "drainage_issue":

            return (
                "Central Drainage Department"
            )

    # =================================================
    # STATE AUTHORITY
    # =================================================

    elif authority == "State Authority":

        if label == "pothole":

            return (
                "State Public Works Department"
            )

        elif label == "garbage":

            return (
                "State Waste Management Department"
            )

        elif label == "drainage_issue":

            return (
                "State Drainage Department"
            )

    # =================================================
    # MUNICIPAL AUTHORITY
    # =================================================

    else:

        if label == "pothole":

            return (
                "Municipal Road Maintenance Department"
            )

        elif label == "garbage":

            return (
                "Municipal Waste Management Department"
            )

        elif label == "drainage_issue":

            return (
                "Municipal Drainage Department"
            )

    return "Municipal Department"
# =====================================================
# PRIORITY ASSIGNMENT
# =====================================================

def assign_priority(issue):

    if issue == "pothole":
        return "High"

    elif issue == "drainage_issue":
        return "Medium"

    elif issue == "garbage":
        return "Low"

    return "Low"
# =====================================================
# HOME PAGE
# =====================================================

@app.route("/", methods=["GET", "POST"])
def home():

    if request.method == "POST":

        file = request.files.get("file")

        if file:

            return "Upload received successfully"

    return render_template("home.html")


# =====================================================
# ADMIN DASHBOARD
# =====================================================

@app.route("/admin")
def admin():

    if "user_id" not in session:

        return redirect(url_for("login"))

    if session["role"] != "admin":

        return "Access Denied"

    # ==========================
    # SEARCH & FILTER
    # ==========================

    search = request.args.get("search", "")

    status = request.args.get("status", "")

    query = Complaint.query

    # Search by Reference ID, Issue or Department
    if search:

        query = query.filter(

            (Complaint.reference_id.ilike(f"%{search}%")) |

            (Complaint.issue.ilike(f"%{search}%")) |

            (Complaint.department.ilike(f"%{search}%"))

        )

    # Filter by Status
    if status:

        query = query.filter(
            Complaint.status == status
        )

    complaints = query.all()

    # ==========================
    # DASHBOARD STATISTICS
    # ==========================

    total = Complaint.query.count()

    pending = Complaint.query.filter_by(
        status="Pending"
    ).count()

    progress = Complaint.query.filter_by(
        status="In Progress"
    ).count()

    resolved = Complaint.query.filter_by(
        status="Resolved"
    ).count()

    # ==========================
    # CATEGORY STATISTICS
    # ==========================

    category_data = (

        db.session.query(

            Complaint.issue,

            func.count(Complaint.id)

        )

        .group_by(Complaint.issue)

        .all()

    )

    category_labels = [row[0] for row in category_data]

    category_counts = [row[1] for row in category_data]

    # ==========================
    # RENDER DASHBOARD
    # ==========================

    return render_template(

        "admin/dashboard.html",

        complaints=complaints,

        total=total,

        pending=pending,

        progress=progress,

        resolved=resolved,

        category_labels=category_labels,

        category_counts=category_counts

    )


# ================================
# ADMIN LOGIN
# ================================

@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":

        email = request.form.get("email")
        password = request.form.get("password")

        user = User.query.filter_by(
            email=email
        ).first()

        if user and check_password_hash(
            user.password,
            password
        ):

            session["user_id"] = user.id
            session["username"] = user.name
            session["role"] = user.role

            if user.role == "admin":
                return redirect(url_for("admin"))

            return redirect(url_for("home"))

        return "Invalid Email or Password"

    return render_template("login.html")

@app.route("/logout")
def logout():

    session.clear()

    return redirect(url_for("login"))
# =====================================================
# EXPORT COMPLAINT REPORT
# =====================================================

@app.route("/admin/export")
def export_complaints():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        return "Access Denied"

    complaints = Complaint.query.order_by(
        Complaint.created_at.desc()
    ).all()

    def generate():

        data = csv.writer(Echo())

        yield data.writerow([
            "Reference ID",
            "Issue",
            "Department",
            "Authority",
            "Priority",
            "Status",
            "Location",
            "Latitude",
            "Longitude",
            "Created At",
            "Resolved At"
        ])

        for c in complaints:

            yield data.writerow([
                c.reference_id,
                c.issue,
                c.department,
                c.authority,
                c.priority,
                c.status,
                c.location,
                c.latitude,
                c.longitude,
                c.created_at,
                c.resolved_at
            ])

    return Response(
        generate(),
        mimetype="text/csv",
        headers={
            "Content-Disposition":
            "attachment; filename=complaints_report.csv"
        }
    )


class Echo:
    def write(self, value):
        return value
# =====================================================
# MAP VIEW
# =====================================================

@app.route("/map")
def map_view():

    complaints = Complaint.query.all()

    return render_template(
        "map.html",
        complaints=complaints
    )# ====================================
# EXPORT COMPLAINTS
# ====================================

@app.route("/export")
def export():

    complaints = Complaint.query.all()

    data = []

    for c in complaints:

        data.append({
            "ID": c.id,
            "Issue": c.issue,
            "Status": c.status,
            "Priority": c.priority,
            "Department": c.department,
            "Location": c.location
        })

    import pandas as pd

    df = pd.DataFrame(data)

    filepath = "complaints_report.xlsx"

    df.to_excel(
        filepath,
        index=False
    )

    from flask import send_file

    return send_file(
        filepath,
        as_attachment=True
    )
# ==========================================
# ANALYTICS PAGE
# ==========================================

@app.route("/analytics")
def analytics():

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        return "Access Denied"

    # Total complaints
    total_complaints = Complaint.query.count()

    # Issue statistics
    pothole = Complaint.query.filter_by(issue="pothole").count()
    garbage = Complaint.query.filter_by(issue="garbage").count()
    drainage = Complaint.query.filter_by(issue="drainage_issue").count()

    # Status statistics
    pending = Complaint.query.filter_by(status="Pending").count()
    in_progress = Complaint.query.filter_by(status="In Progress").count()
    resolved = Complaint.query.filter_by(status="Resolved").count()

    return render_template(
        "analytics.html",
        total_complaints=total_complaints,
        pothole=pothole,
        garbage=garbage,
        drainage=drainage,
        pending=pending,
        in_progress=in_progress,
        resolved=resolved
    )


# =====================================================
# UPDATE COMPLAINT STATUS
# =====================================================

@app.route("/update_status/<int:id>", methods=["POST"])
def update_status(id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        return "Access Denied"

    complaint = Complaint.query.get_or_404(id)

    new_status = request.form.get("status")

    complaint.status = new_status

    if new_status == "Resolved":
        complaint.resolved_at = datetime.utcnow()
    else:
        complaint.resolved_at = None

    db.session.commit()

    flash("Complaint status updated successfully!", "success")

    return redirect(url_for("admin"))
@app.route("/track", methods=["GET", "POST"])
def track():

    complaint = None

    if request.method == "POST":

        reference_id = request.form.get("reference_id", "").strip()

        print("Entered:", reference_id)

        complaint = Complaint.query.filter(
            Complaint.reference_id == reference_id
        ).first()

        print("Found:", complaint)

    return render_template(
        "track.html",
        complaint=complaint
    )
@app.route("/register", methods=["GET", "POST"])
def register():

    if request.method == "POST":

        name = request.form["name"]
        email = request.form["email"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            return "Passwords do not match."

        existing_user = User.query.filter_by(email=email).first()

        if existing_user:
            return "Email already registered."

        hashed_password = generate_password_hash(password)

        new_user = User(
            name=name,
            email=email,
            password=hashed_password,
            role="user"
        )

        db.session.add(new_user)
        db.session.commit()

        return "Registration Successful!"

    return render_template("register.html")
# =====================================================
# COMPLAINT DETAILS
# =====================================================
@app.route("/complaint/<int:id>")
def complaint_details(id):

    if "user_id" not in session:
        return redirect(url_for("login"))

    if session["role"] != "admin":
        return "Access Denied"

    complaint = Complaint.query.get_or_404(id)

    return render_template(
        "admin/complaint_details.html",
        complaint=complaint
    )
# =====================================================
# GPS MAP CAMERA ADDRESS OCR
# =====================================================

def extract_geotag_address_from_image(filepath):
    """
    Read the printed address from a GPS Map Camera/geotag image.

    The GPS coordinates in EXIF tell us the position, but reverse
    geocoding may only return a broad locality such as "Puttur".
    GPS Map Camera also prints the detailed address directly on the
    image. OCR is used here so the displayed/printed address becomes
    the complaint location.
    """
    try:
        img = cv2.imread(filepath)

        if img is None:
            print("OCR: unable to read image")
            return None

        height, width = img.shape[:2]

        # GPS Map Camera normally places its information block at the
        # bottom of the photograph. Keep a large enough area so that
        # different layouts are supported.
        crop = img[int(height * 0.55):height, :]

        # Upscale for better OCR accuracy.
        crop = cv2.resize(
            crop,
            None,
            fx=2.5,
            fy=2.5,
            interpolation=cv2.INTER_CUBIC
        )

        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)

        # Improve contrast.
        gray = cv2.createCLAHE(
            clipLimit=2.0,
            tileGridSize=(8, 8)
        ).apply(gray)

        # Two OCR versions: original grayscale and thresholded.
        threshold = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]

        ocr_outputs = []

        for processed in (gray, threshold):
            for psm in (6, 11):
                try:
                    result = pytesseract.image_to_string(
                        processed,
                        config=f"--oem 3 --psm {psm}",
                        lang="eng"
                    )
                    if result:
                        ocr_outputs.append(result)
                except Exception as ocr_error:
                    print("OCR pass error:", ocr_error)

        # Build clean OCR lines while preserving the text content.
        lines = []

        for output in ocr_outputs:
            for raw_line in output.splitlines():
                line = re.sub(r"\s+", " ", raw_line).strip()

                if len(line) >= 4:
                    lines.append(line)

        # Remove exact duplicate OCR lines.
        unique_lines = []
        seen = set()

        for line in lines:
            key = line.lower()
            if key not in seen:
                seen.add(key)
                unique_lines.append(line)

        print("OCR detected lines:")
        for line in unique_lines:
            print("   ", line)

        if not unique_lines:
            return None

        # ---------------------------------------------------------
        # GPS Map Camera prints the detailed street/address line together
        # with a 6-digit Indian PIN. Prefer that line and never combine it
        # with the broad locality line (for example, "Puttur, Karnataka").
        # ---------------------------------------------------------
        pin_candidates = [
            line for line in unique_lines
            if re.search(r"\b\d{6}\b", line)
            and "gmt" not in line.lower()
            and "latitude" not in line.lower()
            and "longitude" not in line.lower()
        ]

        def address_score(line):
            lower = line.lower()
            score = 0

            if re.search(r"\b\d{6}\b", line):
                score += 100

            for keyword in (
                "india", "karnataka", "kerala", "tamil nadu",
                "andhra", "telangana", "maharashtra", "puttur",
                "road", "street", "main", "nagar", "layout",
                "village", "taluk", "district"
            ):
                if keyword in lower:
                    score += 10

            score += min(line.count(","), 5) * 3

            if "gmt" in lower or "latitude" in lower or "longitude" in lower:
                score -= 100

            if re.search(r"\b\d{1,2}[:/]\d{1,2}", line):
                score -= 50

            return score

        if pin_candidates:
            best_line = max(pin_candidates, key=address_score)
        else:
            address_candidates = [
                line for line in unique_lines
                if "india" in line.lower() and "gmt" not in line.lower()
            ]
            if not address_candidates:
                print("OCR: no reliable address found")
                return None
            best_line = max(address_candidates, key=address_score)

        # Clean common OCR artefacts.
        best_line = re.sub(r"\s*,\s*", ", ", best_line)
        best_line = re.sub(r"\s{2,}", " ", best_line)
        best_line = best_line.strip(" ,.-=|\"“”‘’")
        best_line = re.sub(r"^[,;:|\-]+\s*", "", best_line)
        best_line = re.sub(r"\s*(?:[=|]+)\s*$", "", best_line)

        # Require reasonable evidence that this is an address.
        lower_best = best_line.lower()

        has_pin = bool(re.search(r"\b\d{6}\b", best_line))
        has_country = "india" in lower_best
        has_state = "karnataka" in lower_best
        has_address_signal = (
            "," in best_line
            or has_pin
            or has_country
            or has_state
        )

        if not has_address_signal or len(best_line) < 8:
            print("OCR: no reliable address found")
            return None

        print("OCR selected geotag address:", best_line)

        return best_line

    except Exception as e:
        print("Geotag OCR error:", e)
        return None

# =====================================================
# GOOGLE GEOCODING HELPERS
# =====================================================

def google_geocode_address(address):
    """
    Convert a manually entered address into latitude/longitude.

    Uses Google Geocoding first and then Nominatim.
    Several progressively simpler address queries are attempted so
    that addresses such as:

        Vivekananda College, Nehru Nagar, Puttur, Karnataka

    can still be resolved even if the exact POI string is not indexed.
    """

    address = re.sub(
        r"\s+",
        " ",
        (address or "").strip()
    )

    if not address:
        return None

    # -----------------------------------------------------
    # Build multiple useful search variations
    # -----------------------------------------------------

    base_address = address.strip(" ,")

    if "india" not in base_address.lower():
        full_address = f"{base_address}, India"
    else:
        full_address = base_address

    search_queries = []

    # 1. Exact address entered by user
    search_queries.append(full_address)

    # 2. Normalized comma spacing
    normalized = re.sub(
        r"\s*,\s*",
        ", ",
        full_address
    )

    if normalized not in search_queries:
        search_queries.append(normalized)

    # -----------------------------------------------------
    # Extract useful location components
    # -----------------------------------------------------

    parts = [
        p.strip()
        for p in re.split(
            r",",
            base_address
        )
        if p.strip()
    ]

    # Example:
    #
    # Vivekananda College
    # Nehru Nagar
    # Puttur
    # Karnataka
    #
    # We progressively remove the POI and keep the locality.

    if len(parts) >= 2:

        # Last 2 components
        query_last_two = (
            ", ".join(parts[-2:]) +
            ", India"
        )

        search_queries.append(
            query_last_two
        )

    if len(parts) >= 3:

        # Last 3 components
        query_last_three = (
            ", ".join(parts[-3:]) +
            ", India"
        )

        search_queries.append(
            query_last_three
        )

    # -----------------------------------------------------
    # Explicit Puttur/Karnataka fallback
    # -----------------------------------------------------

    lower_address = base_address.lower()

    if "puttur" in lower_address:

        search_queries.append(
            "Puttur, Karnataka, India"
        )

    # Remove duplicates while preserving order
    search_queries = list(
        dict.fromkeys(search_queries)
    )

    print("=" * 60)
    print("MANUAL LOCATION GEOCODING")
    print("Original address:", address)
    print("Search queries:")

    for q in search_queries:
        print("   ", q)

    print("=" * 60)

    # =====================================================
    # 1. GOOGLE GEOCODING
    # =====================================================

    google_error = None

    api_key = (
        GOOGLE_MAPS_API_KEY or ""
    ).strip()

    if api_key:

        for query in search_queries:

            try:

                params = {
                    "address": query,
                    "key": api_key,
                    "language": "en",
                    "region": "in"
                }

                response = requests.get(
                    GOOGLE_GEOCODING_URL,
                    params=params,
                    timeout=10
                )

                response.raise_for_status()

                data = response.json()

                status = data.get("status")

                print(
                    "Google query:",
                    query
                )

                print(
                    "Google status:",
                    status
                )

                if data.get("error_message"):

                    print(
                        "Google error:",
                        data.get("error_message")
                    )

                if (
                    status == "OK"
                    and data.get("results")
                ):

                    result = data["results"][0]

                    geometry = result.get(
                        "geometry",
                        {}
                    )

                    location = geometry.get(
                        "location"
                    )

                    if location:

                        latitude = float(
                            location["lat"]
                        )

                        longitude = float(
                            location["lng"]
                        )

                        formatted_address = (
                            result.get(
                                "formatted_address"
                            )
                            or query
                        )

                        print("=" * 60)
                        print(
                            "GOOGLE GEOCODING SUCCESS"
                        )
                        print(
                            "Query:",
                            query
                        )
                        print(
                            "Address:",
                            formatted_address
                        )
                        print(
                            "Latitude:",
                            latitude
                        )
                        print(
                            "Longitude:",
                            longitude
                        )
                        print("=" * 60)

                        return {
                            "latitude": latitude,
                            "longitude": longitude,
                            "formatted_address":
                                formatted_address
                        }

                google_error = (
                    data.get("error_message")
                    or status
                    or "No result"
                )

            except requests.RequestException as e:

                google_error = str(e)

                print(
                    "Google request error:",
                    repr(e)
                )

                # Try Nominatim instead of stopping.

            except Exception as e:

                google_error = str(e)

                print(
                    "Google geocoding exception:",
                    repr(e)
                )

    else:

        google_error = (
            "GOOGLE_MAPS_API_KEY is missing"
        )

        print(
            "WARNING:",
            google_error
        )

    # =====================================================
    # 2. NOMINATIM FALLBACK
    # =====================================================

    print("=" * 60)
    print("TRYING NOMINATIM FALLBACK")
    print("=" * 60)

    try:

        geolocator = Nominatim(
            user_agent="CivicVisionAI/1.0"
        )

        for query in search_queries:

            try:

                print(
                    "Nominatim query:",
                    query
                )

                location = geolocator.geocode(
                    query,
                    exactly_one=True,
                    language="en",
                    addressdetails=True,
                    timeout=15
                )

                if location:

                    latitude = float(
                        location.latitude
                    )

                    longitude = float(
                        location.longitude
                    )

                    formatted_address = (
                        getattr(
                            location,
                            "address",
                            None
                        )
                        or query
                    )

                    print("=" * 60)
                    print(
                        "NOMINATIM GEOCODING SUCCESS"
                    )
                    print(
                        "Query:",
                        query
                    )
                    print(
                        "Address:",
                        formatted_address
                    )
                    print(
                        "Latitude:",
                        latitude
                    )
                    print(
                        "Longitude:",
                        longitude
                    )
                    print("=" * 60)

                    return {
                        "latitude": latitude,
                        "longitude": longitude,
                        "formatted_address":
                            formatted_address
                    }

            except (
                GeocoderTimedOut,
                GeocoderUnavailable
            ) as e:

                print(
                    "Nominatim unavailable:",
                    repr(e)
                )

            except Exception as e:

                print(
                    "Nominatim query error:",
                    repr(e)
                )

    except Exception as e:

        print(
            "Nominatim initialization error:",
            repr(e)
        )

    # =====================================================
    # NOTHING FOUND
    # =====================================================

    print("=" * 60)
    print("MANUAL LOCATION COULD NOT BE GEOCODED")
    print("Original address:", address)
    print("Google error:", google_error)
    print("=" * 60)

    return None

def google_reverse_geocode(latitude, longitude):
    """
    Convert GPS coordinates to a readable address.

    Google is the primary geocoder. If Google does not return a usable
    address, fall back to Nominatim so that valid GPS coordinates are not
    discarded just because reverse geocoding failed.
    """
    google_error = None

    if GOOGLE_MAPS_API_KEY:
        try:
            params = {
                "latlng": f"{latitude},{longitude}",
                "key": GOOGLE_MAPS_API_KEY,
                "language": "en"
            }

            response = requests.get(
                GOOGLE_GEOCODING_URL,
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            print(
                "Google reverse geocoding status:",
                data.get("status")
            )

            if data.get("error_message"):
                print(
                    "Google reverse geocoding error:",
                    data.get("error_message")
                )

            if data.get("status") == "OK" and data.get("results"):
                address = data["results"][0].get("formatted_address")
                if address:
                    return address

            google_error = (
                data.get("error_message")
                or data.get("status")
                or "No Google address returned"
            )

        except Exception as e:
            google_error = str(e)
            print("Google reverse geocoding exception:", e)
    else:
        google_error = "GOOGLE_MAPS_API_KEY is missing"

    # -------------------------------------------------
    # Fallback reverse geocoding using OpenStreetMap
    # -------------------------------------------------
    try:
        geolocator = Nominatim(
            user_agent="CivicVisionAI/1.0"
        )

        location = geolocator.reverse(
            (latitude, longitude),
            exactly_one=True,
            language="en",
            timeout=10
        )

        if location and location.address:
            print("Using Nominatim fallback address:", location.address)
            return location.address

    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        print("Nominatim geocoding unavailable:", e)
    except Exception as e:
        print("Nominatim fallback error:", e)

    print(
        "Reverse geocoding failed. Google result:",
        google_error
    )

    # Last-resort readable location. The GPS coordinates remain valid.
    return f"GPS Location ({latitude:.6f}, {longitude:.6f})"

# =====================================================
# PREDICT REQUEST DEDUPLICATION
# =====================================================

def deduplicate_predict_requests(view_func):
    """Return the first result when the browser submits the same image twice."""
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        upload = request.files.get("file")
        user_id = session.get("user_id", "anonymous")

        if upload is None:
            return view_func(*args, **kwargs)

        try:
            current_pos = upload.stream.tell()
            data = upload.read()
            upload.stream.seek(current_pos)
        except Exception:
            return view_func(*args, **kwargs)

        signature = hashlib.sha256(data).hexdigest()
        key = f"{user_id}:{signature}"
        now = time.time()

        with PREDICT_DEDUPE_LOCK:
            # Remove entries older than the deduplication window.
            stale = [
                k for k, v in PREDICT_DEDUPE.items()
                if now - v["time"] > PREDICT_DEDUPE_WINDOW
            ]
            for stale_key in stale:
                PREDICT_DEDUPE.pop(stale_key, None)

            entry = PREDICT_DEDUPE.get(key)

            if entry is None:
                entry = {
                    "time": now,
                    "lock": threading.Lock(),
                    "response": None
                }
                PREDICT_DEDUPE[key] = entry

        # The second request waits for the first request to finish, then
        # receives the exact same successful response instead of creating
        # another complaint/email.
        with entry["lock"]:
            if entry["response"] is not None:
                body, status, content_type = entry["response"]
                return Response(body, status=status, content_type=content_type)

            result = view_func(*args, **kwargs)
            response = make_response(result)

            # Cache only successful prediction responses. Failed requests can
            # be retried normally.
            if response.status_code == 200:
                entry["response"] = (
                    response.get_data(),
                    response.status_code,
                    response.content_type
                )

            return response

    return wrapped

# =====================================================
# PREDICT ROUTE
# =====================================================

@app.route("/predict", methods=["POST"])
@deduplicate_predict_requests
def predict():

    try:

        if "file" not in request.files:

            return jsonify({
                "success": False,
                "message": "File not received"
            }), 400

        file = request.files["file"]

        # =================================================
        # SAVE IMAGE
        # =================================================

        filename = (
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{secure_filename(file.filename)}"
        )

        filepath = os.path.join(
            app.config['UPLOAD_FOLDER'],
            filename
        )

        file.save(filepath)

        filepath = filepath.replace("\\", "/")

        # =================================================
        # AI IMAGE PREDICTION
        # =================================================

        try:
            label, confidence = predict_image(filepath)
            description = generate_description(label)

            print("Predicted Issue:", label)
            print("Confidence:", confidence)
            print("AI Description:", description)

        except Exception as prediction_error:

            import traceback
            traceback.print_exc()

            return jsonify({
                "success": False,
                "message": f"Unable to analyse the uploaded image: {prediction_error}"
            }), 500

        # =================================================
        # LOCATION INPUT
        # =================================================
        # auto   = use GPS metadata from the uploaded image
        # manual = use the location typed by the user
        # Manual mode can also override image GPS when needed.

        manual_address = request.form.get("manual_address", "").strip()
        location_mode = request.form.get("location_mode", "auto").strip().lower()

        gps_coordinates = None
        try:
            gps_coordinates = get_gps_coordinates(filepath)
        except Exception as gps_error:
            print("GPS extraction error:", gps_error)

        gps_available = (
            gps_coordinates is not None
            and gps_coordinates[0] is not None
            and gps_coordinates[1] is not None
        )

        if location_mode == "manual":
            if not manual_address:
                return jsonify({
                    "success": False,
                    "message": "Please enter a location/address."
                }), 400

            try:
                manual_result = google_geocode_address(manual_address)
            except requests.RequestException as e:
                print("Google geocoding request error:", e)
                return jsonify({
                    "success": False,
                    "message": "The location service is temporarily unavailable. Please try again."
                }), 503
            except Exception as e:
                print("Manual geocoding error:", e)
                return jsonify({
                    "success": False,
                    "message": "Unable to process the entered location."
                }), 400

            if not manual_result:

                return jsonify({
                    "success": False,
                    "error": (
                        "Location not found. "
                        "Please enter a more complete address, "
                        "area, city or PIN code."
                    ),
                    "message": (
                        "Location not found. "
                        "Please enter a more complete address, "
                        "area, city or PIN code."
                    )
                }), 400

            lat = manual_result["latitude"]
            lng = manual_result["longitude"]
            address = manual_result["formatted_address"]
            location_source = "Manual Address"

        elif location_mode == "auto":
            if not gps_available:
                return jsonify({
                    "success": False,
                    "message": "This image does not contain GPS location data. Please select manual location and enter the address."
                }), 400

            # GPS coordinates are authoritative location data from the image.
            # Do NOT fail the complete prediction just because reverse
            # geocoding cannot produce a street address.
            lat, lng = gps_coordinates

            # -------------------------------------------------
            # IMPORTANT:
            # For GPS Map Camera images, the detailed address printed
            # ON THE IMAGE is the preferred location. Reverse geocoding
            # can return only a broad place such as "Puttur".
            # -------------------------------------------------
            geotag_address = extract_geotag_address_from_image(filepath)

            if geotag_address:
                address = geotag_address
                location_source = "Geotag Image Address"
                print("Using exact address printed in geotag image:", address)

            else:
                # OCR could not read the printed address, so retain the
                # GPS coordinates and use reverse geocoding as fallback.
                try:
                    reverse_address = google_reverse_geocode(lat, lng)
                except Exception as e:
                    # This is only a geocoding failure. Prediction,
                    # complaint registration and email should still continue.
                    print("Reverse geocoding error:", e)
                    reverse_address = None

                if reverse_address:
                    address = reverse_address
                else:
                    address = f"GPS Location ({lat:.6f}, {lng:.6f})"

                location_source = "Image GPS"

            print("GPS coordinates retained:", lat, lng)
            print("Resolved location:", address)

        else:
            return jsonify({
                "success": False,
                "message": "Invalid location mode."
            }), 400

        lat = float(lat)
        lng = float(lng)

        print("Latitude:", lat)
        print("Longitude:", lng)
        print("Final Address:", address)
        print("Location Source:", location_source)

        # =================================================
        # AUTHORITY DETECTION
        # =================================================

        authority = detect_authority(
            address
        )

        print(
            "Authority:",
            authority
        )

        # =================================================
        # DEPARTMENT ASSIGNMENT
        # =================================================

        department = assign_department(
            label,
            authority
        )

        print(
            "Department:",
            department
        )

        # =================================================
        # PRIORITY
        # =================================================

        priority = assign_priority(
            label
        )

        print(
            "Priority:",
            priority
        )

        # =================================================
        # CREATE COMPLAINT REFERENCE
        # =================================================

        complaint_ref = (
            f"CVA-"
            f"{datetime.now().strftime('%Y%m%d')}-"
            f"{random.randint(1000, 9999)}"
        )

        print(
            "Complaint Reference:",
            complaint_ref
        )

        # =================================================
        # CREATE DATABASE RECORD
        # =================================================

        new_complaint = Complaint(

            reference_id=complaint_ref,

            issue=label,

            description=description,

            department=department,

            authority=authority,

            location=address,

            latitude=lat,

            longitude=lng,

            priority=priority,

            status="Pending",

            remarks="",

            image_path=filename
        )

        db.session.add(
            new_complaint
        )

        db.session.commit()

        print(
            "Complaint stored in database"
        )
        # =================================================
        # SEND COMPLAINT EMAIL TO LOGGED-IN USER
        # =================================================
        #
        # EMAIL_ADDRESS from .env is the CivicVision sender account.
        # The recipient is the email stored for the logged-in
        # registered user.
        # =================================================

        email_status = "Failed"

        try:

            user_id = session.get("user_id")

            if not user_id:
                return jsonify({
                    "success": False,
                    "message": "Please login before submitting a complaint."
                }), 401

            # SQLAlchemy 2.x compatible user lookup.
            user = db.session.get(User, user_id)

            if not user:
                return jsonify({
                    "success": False,
                    "message": "Logged-in user could not be found."
                }), 401

            # This is the email entered during registration.
            user_email = (user.email or "").strip()

            if not user_email:
                raise ValueError(
                    "Registered user's email address is empty."
                )

            print(
                "Complaint email recipient:",
                user_email
            )

            send_complaint_email(
                recipient_email=user_email,
                complaint_ref=complaint_ref,
                issue=label,
                confidence=confidence * 100,
                description=description,
                department=department,
                authority=authority,
                address=address,
                latitude=lat,
                longitude=lng,
                image_path=filepath
            )

            email_status = "Sent"

        except Exception as email_error:

            import traceback

            traceback.print_exc()

            print(
                "EMAIL ERROR:",
                repr(email_error)
            )

            # Complaint is already stored in the database.
            # Email failure does not delete or roll back the complaint.
            email_status = "Failed"

        # =================================================
        # FINAL RESPONSE
        # =================================================

        return jsonify({

            "success": True,

            "prediction": label,

            "confidence": round(
                confidence * 100,
                2
            ),

            "description": description,

            "department": department,

            "authority": authority,

            "location": address,

            "latitude": lat,

            "longitude": lng,

            "location_source": location_source,

            "reference_id": complaint_ref,

            "email_status": email_status

        }), 200

    # =====================================================
    # GENERAL ERROR HANDLING
    # =====================================================

    except Exception as e:

        import traceback

        traceback.print_exc()

        return jsonify({

            "success": False,

            "message": str(e)

        }), 500

# =====================================================
# RUN FLASK APP
# =====================================================

if __name__ == "__main__":
    app.run(
        debug=True,
        use_reloader=False
    )