import mediapipe as mp
from deepface import DeepFace
from flask import Flask, request, render_template, redirect, url_for, session, jsonify
import mysql.connector
from mysql.connector import Error
from datetime import datetime, time
import cv2
import numpy as np
import os
import base64
import threading  # To handle image capture and authentication in the background

app = Flask(__name__)
app.secret_key = '3b0b9e8f9e1c4bfc9f8c7a2d8c0d1e6c'  # Use a strong, unique secret key

# Set allowed network prefix (for your specific Wi-Fi network)
ALLOWED_NETWORK_PREFIX = "192.168.93."  # Update to your Wi-Fi network prefix

# Function to check if the user's IP belongs to the allowed network
def validate_network(ip):
    return ip.startswith(ALLOWED_NETWORK_PREFIX)

# Function to validate credentials against the database
def validate_credentials(roll_no, student_id):
    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='attendance',
            user='root',
            password=''
        )
        if connection.is_connected():
            cursor = connection.cursor(dictionary=True)
            query = "SELECT * FROM student_details WHERE roll_no = %s AND student_id = %s"
            cursor.execute(query, (roll_no, student_id))
            user = cursor.fetchone()
            return user
    except Error as e:
        print(f"Error: {e}")
        return None
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# Function to save the captured image
def store_captured_image(image_data, roll_no):
    try:
        captured_image_path = f"captured_images/{roll_no}.jpg"
        
        # Decode the base64 image data
        image_bytes = base64.b64decode(image_data.split(",")[1])
        
        # Check the size of the decoded image
        print(f"Decoded image size: {len(image_bytes)} bytes")
        
        with open(captured_image_path, "wb") as image_file:
            image_file.write(image_bytes)
        return captured_image_path
    except Exception as e:
        print(f"Error storing image: {e}")
        return None

# Function to authenticate the captured face image
def authenticate_face(captured_image_path, roll_no):
    stored_image_path = f"face_img/{roll_no}.jpg"
    
    if not os.path.exists(stored_image_path):
        print(f"Stored image for roll number {roll_no} not found.")
        return False

    captured_image = cv2.imread(captured_image_path)
    stored_image = cv2.imread(stored_image_path)

    if captured_image is None or stored_image is None:
        print("Error loading images for face recognition.")
        return False

    gray_captured = cv2.cvtColor(captured_image, cv2.COLOR_BGR2GRAY)
    gray_stored = cv2.cvtColor(stored_image, cv2.COLOR_BGR2GRAY)

    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    
    faces_captured = face_cascade.detectMultiScale(gray_captured, scaleFactor=1.1, minNeighbors=5)
    faces_stored = face_cascade.detectMultiScale(gray_stored, scaleFactor=1.1, minNeighbors=5)

    if len(faces_captured) == 0 or len(faces_stored) == 0:
        print("No faces detected in one or both images.")
        return False

    (x, y, w, h) = faces_stored[0]
    stored_face = gray_stored[y:y+h, x:x+w]

    (x, y, w, h) = faces_captured[0]
    captured_face = gray_captured[y:y+h, x:x+w]

    face_recognizer = cv2.face.LBPHFaceRecognizer_create()
    face_recognizer.train([stored_face], np.array([0]))

    label, confidence = face_recognizer.predict(captured_face)
    print(f"Prediction: Label = {label}, Confidence = {confidence}")

    return confidence < 100

# Route for the login page
@app.route('/')
def wifi_page():
    return render_template('wifi.html')

# Route to handle login validation
@app.route('/submit-login', methods=['POST'])
def login():
    roll_no = request.form.get('rollno')
    student_id = request.form.get('student_id')
    user_ip = request.remote_addr

    if not validate_network(user_ip):
        return redirect(url_for('error_page'))

    user = validate_credentials(roll_no, student_id)

    if user:
        session['roll_no'] = roll_no
        session['student_id'] = student_id
        return redirect(url_for('success_page'))
    else:
        return redirect(url_for('error_page'))

# Route for the result page (successful login)
@app.route('/success')
def success_page():
    roll_no = session.get('roll_no')
    student_id = session.get('student_id')
    student_name = "Student_name"  # Retrieve actual student name if available
    return render_template('result.html', roll_no=roll_no, student_id=student_id, student_name=student_name)

# Route for marking attendance
@app.route('/mark-attendance', methods=['POST'])
def mark_attendance():
    roll_no = session.get('roll_no')
    image_data = request.json.get('image_data')  # Base64 image data

    # Call the function to store the captured image
    captured_image_path = store_captured_image(image_data, roll_no)
    if not captured_image_path:
        return jsonify(success=False, message="Error storing image. Please try again."), 500

    # Run face authentication in a background thread
    def handle_authentication():
        authenticated = authenticate_face(captured_image_path, roll_no)
        if authenticated:
            mark_attendance_in_db(roll_no)
            return "success"
        else:
            return "failure"

    thread = threading.Thread(target=handle_authentication)
    thread.start()

    return jsonify(success=True, message="Processing attendance...")

# Function to mark attendance in the database
def mark_attendance_in_db(roll_no):
    current_time = datetime.now().time()

    if time(9, 30) <= current_time <= time(12, 0):
        status = 'present'
        timestamp = datetime.now()
        column_name = 'FN_status'
        timestamp_column = 'FN_timestamp'
    elif time(14, 0) <= current_time <= time(16, 0):
        status = 'present'
        timestamp = datetime.now()
        column_name = 'AN_status'
        timestamp_column = 'AN_timestamp'
    else:
        status = 'absent'
        timestamp = None
        column_name = 'AN_status'
        timestamp_column = 'AN_timestamp'

    try:
        connection = mysql.connector.connect(
            host='localhost',
            database='attendance',
            user='root',
            password=''
        )
        
        if connection.is_connected():
            cursor = connection.cursor()
            query = f"""
            UPDATE student_details 
            SET {column_name} = %s, {timestamp_column} = %s 
            WHERE roll_no = %s
            """
            cursor.execute(query, (status, timestamp, roll_no))
            connection.commit()

    except Error as e:
        print(f"Error: {e}")
    finally:
        if connection.is_connected():
            cursor.close()
            connection.close()

# Route for the attendance success page
@app.route('/attendance-success')
def attendance_success_page():
    return render_template('attendance_success.html')  # Create this template

# Route for the attendance unsuccessful page
@app.route('/attendance-unsuccessful')
def attendance_unsuccessful_page():
    return render_template('attendance_unsuccessful.html')  # Create this template

# Route for the error page (incorrect network or credentials)
@app.route('/error')
def error_page():
    return render_template('error.html')  # This will show error message

# Run the app with SSL enabled
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, ssl_context=('C:\\Users\\praha\\OneDrive\\Desktop\\newatten\\cert\\ssl\\certs\\cert.pem', 'C:\\Users\\praha\\OneDrive\\Desktop\\newatten\\privatekey\\ssl\\private\\key.pem'))
