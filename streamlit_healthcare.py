# app.py
import streamlit as st
import oracledb
import hashlib
from datetime import datetime
from blockchain import Blockchain

# ---------------- Oracle DB Credentials ----------------
DB_USER = "system"
DB_PASSWORD = "system"
DB_DSN = "localhost/XE"

# ---------------- Blockchain ----------------
blockchain = Blockchain()

# ---------------- Streamlit App ----------------
st.set_page_config(page_title="Healthcare Management System", layout="wide")
st.title("Healthcare Management System")

# ---------------- Login ----------------
if 'login_status' not in st.session_state:
    st.session_state.login_status = False
    st.session_state.user_type = None

if not st.session_state.login_status:
    st.subheader("Login")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    role = st.selectbox("Role", ["Admin", "User"])

    if st.button("Login"):
        # Simple hardcoded credentials for demonstration
        if role == "Admin" and username == "admin" and password == "admin123":
            st.session_state.login_status = True
            st.session_state.user_type = "Admin"
        elif role == "User" and username == "user" and password == "user123":
            st.session_state.login_status = True
            st.session_state.user_type = "User"
        else:
            st.error("Invalid username or password")

else:
    st.sidebar.write(f"Logged in as: {st.session_state.user_type}")
    if st.sidebar.button("Logout"):
        st.session_state.login_status = False
        st.session_state.user_type = None
        st.experimental_rerun()

# ---------------- Connect to Oracle ----------------
try:
    conn = oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)
    cursor = conn.cursor()
except oracledb.DatabaseError as e:
    st.error(f"Database connection failed: {e}")
    st.stop()

# ---------------- Admin Dashboard ----------------
if st.session_state.get('login_status') and st.session_state.user_type == "Admin":
    st.subheader("Admin Dashboard")
    menu = st.selectbox("Choose Action", [
        "View Patients", "Add Patient", "Update Patient", "Delete Patient",
        "View Doctors", "Add Doctor", "Update Doctor", "Delete Doctor"
    ])

    if menu == "View Patients":
        cursor.execute("SELECT * FROM Patients")
        data = cursor.fetchall()
        st.dataframe(data)
        st.subheader("Verify Data Integrity")
        for row in data:
            data_str = str(row)
            verified = blockchain.verify(hashlib.sha256(data_str.encode()).hexdigest())
            st.write(f"Patient ID {row[0]} Verified: {verified}")

    elif menu == "Add Patient":
        st.subheader("Add Patient")
        first_name = st.text_input("First Name")
        last_name = st.text_input("Last Name")
        dob = st.date_input("Date of Birth")
        gender = st.selectbox("Gender", ["Male", "Female", "Other"])
        contact = st.text_input("Contact")
        if st.button("Add"):
            cursor.execute(
                "INSERT INTO Patients (first_name, last_name, dob, gender, contact) VALUES (:1,:2,:3,:4,:5)",
                (first_name, last_name, dob, gender, contact)
            )
            conn.commit()
            st.success("Patient added successfully!")
            blockchain.add_block(hashlib.sha256(f"{first_name}{last_name}{dob}{gender}{contact}".encode()).hexdigest())

    # --- Similar CRUD for Update/Delete Patients, Doctors can be added here ---

# ---------------- User Dashboard ----------------
elif st.session_state.get('login_status') and st.session_state.user_type == "User":
    st.subheader("User Dashboard")
    cursor.execute("SELECT patient_id, first_name, last_name, dob, gender, contact FROM Patients")
    data = cursor.fetchall()
    st.dataframe(data)
    st.subheader("View Patient Details")
    patient_id = st.number_input("Patient ID", min_value=1)
    if st.button("View"):
        cursor.execute("SELECT * FROM Patients WHERE patient_id=:1", (patient_id,))
        patient = cursor.fetchone()
        if patient:
            st.write(patient)
        else:
            st.warning("Patient not found.")

# ---------------- Close Connection ----------------
conn.close()
