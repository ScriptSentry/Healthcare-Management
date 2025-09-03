import streamlit as st
import oracledb
import hashlib
from datetime import datetime
import pandas as pd

# Configure Streamlit page
st.set_page_config(page_title="Hospital Management System", layout="wide")

# ---------------- DB Credentials ----------------
DB_USER = "system"
DB_PASSWORD = "system"
DB_DSN = "localhost/XEPDB1"

# ---------------- Session State Management ----------------
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'user_type' not in st.session_state:
    st.session_state.user_type = None
if 'db_connection' not in st.session_state:
    st.session_state.db_connection = None
if 'blockchain' not in st.session_state:
    st.session_state.blockchain = None


# ---------------- Database Connection ----------------
@st.cache_resource
def get_db_connection():
    try:
        conn = oracledb.connect(user=DB_USER, password=DB_PASSWORD, dsn=DB_DSN)
        return conn
    except oracledb.DatabaseError as e:
        st.error(f"Database connection failed: {e}")
        return None


# ---------------- Utility Functions for Database Schema ----------------
def get_table_columns(conn, table_name):
    """Get actual column names from database table"""
    try:
        with conn.cursor() as cursor:
            # Query to get column information
            cursor.execute(f"""
                SELECT column_name 
                FROM user_tab_columns 
                WHERE table_name = UPPER('{table_name}')
                ORDER BY column_id
            """)
            columns = [row[0].lower() for row in cursor.fetchall()]

            # Fallback: If no columns found, try to get them from a dummy query
            if not columns:
                cursor.execute(f"SELECT * FROM {table_name} WHERE ROWNUM <= 0")
                columns = [desc[0].lower() for desc in cursor.description]

            return columns
    except oracledb.DatabaseError as e:
        st.error(f"Error getting columns for {table_name}: {e}")
        return []


def get_available_tables(conn):
    """Get list of available tables in the database"""
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                           SELECT table_name
                           FROM user_tables
                           WHERE table_name IN ('PATIENTS', 'DOCTORS', 'STAFF', 'APPOINTMENTS',
                                                'MEDICALRECORDS', 'PRESCRIPTIONS', 'BILLING', 'INVENTORY')
                           ORDER BY table_name
                           """)
            tables = [row[0] for row in cursor.fetchall()]
            return tables
    except oracledb.DatabaseError as e:
        st.error(f"Error getting tables: {e}")
        return []


# ---------------- Blockchain Class ----------------
class Blockchain:
    def __init__(self, conn):
        self.chain = []
        self.conn = conn
        self.load_chain()

    def add_block(self, table_name, record_id, data_hash):
        with self.conn.cursor() as cursor:
            index = len(self.chain) + 1
            previous_hash = self.chain[-1]['block_hash'] if self.chain else "0"
            block_hash = hashlib.sha256((str(index) + previous_hash + data_hash).encode()).hexdigest()

            block = {
                'index': index,
                'table_name': table_name,
                'record_id': record_id,
                'data_hash': data_hash,
                'block_hash': block_hash,
                'previous_hash': previous_hash,
                'created_at': datetime.now()
            }

            self.chain.append(block)

            # Persist in DB
            try:
                cursor.execute("""
                               INSERT INTO BlockChain (block_index, table_name, record_id, data_hash, block_hash,
                                                       previous_hash)
                               VALUES (:1, :2, :3, :4, :5, :6)
                               """, (index, table_name, record_id, data_hash, block_hash, previous_hash))
                self.conn.commit()
            except oracledb.DatabaseError as e:
                st.error(f"Blockchain insertion failed: {e}")

            return block

    def verify(self, table_name, record_id, data_hash):
        for block in self.chain:
            if (block['table_name'] == table_name and
                    str(block['record_id']) == str(record_id) and
                    block['data_hash'] == data_hash):
                return True
        return False

    def load_chain(self):
        try:
            with self.conn.cursor() as cursor:
                cursor.execute("""
                               SELECT block_index, table_name, record_id, data_hash, block_hash, previous_hash
                               FROM BlockChain
                               ORDER BY block_index
                               """)
                rows = cursor.fetchall()

                self.chain = []
                for row in rows:
                    self.chain.append({
                        'index': row[0],
                        'table_name': row[1],
                        'record_id': row[2],
                        'data_hash': row[3],
                        'block_hash': row[4],
                        'previous_hash': row[5],
                        'created_at': None
                    })
        except oracledb.DatabaseError:
            # Table might not exist yet
            pass


# ---------------- Table Configurations (Fallback) ----------------
TABLE_COLUMNS = {
    "PATIENTS": ["patient_id", "first_name", "last_name", "dob", "gender", "contact", "address"],
    "DOCTORS": ["doctor_id", "first_name", "last_name", "specialization", "contact", "department_id"],
    "STAFF": ["staff_id", "first_name", "last_name", "role", "contact", "department_id"],
    "APPOINTMENTS": ["appointment_id", "patient_id", "doctor_id", "staff_id", "appointment_date", "status", "notes"],
    "MEDICALRECORDS": ["record_id", "patient_id", "doctor_id", "diagnosis", "treatment", "created_at"],
    "PRESCRIPTIONS": ["prescription_id", "record_id", "medicine_name", "dosage", "duration", "notes"],
    "BILLING": ["bill_id", "patient_id", "appointment_id", "amount", "status", "created_at"],
    "INVENTORY": ["item_id", "name", "category", "quantity", "unit", "expiry_date", "created_at"]
}


# ---------------- Utility Functions ----------------
def compute_data_hash(table_name, row, columns):
    """Compute hash of row data"""
    data = {col: val for col, val in zip(columns, row)}
    data_str = str(sorted(data.items()))
    return hashlib.sha256(data_str.encode()).hexdigest()


def get_next_id(conn, table_name, pk_column):
    """Get next ID using sequence"""
    seq_name = f"{table_name}_{pk_column}_SEQ".upper()

    with conn.cursor() as cursor:
        # Check if sequence exists
        cursor.execute("""
                       SELECT COUNT(*)
                       FROM user_sequences
                       WHERE sequence_name = :1
                       """, (seq_name,))

        if cursor.fetchone()[0] == 0:
            try:
                cursor.execute(f"CREATE SEQUENCE {seq_name} START WITH 1 INCREMENT BY 1 NOCACHE")
                conn.commit()
            except oracledb.DatabaseError:
                pass

        cursor.execute(f"SELECT {seq_name}.NEXTVAL FROM DUAL")
        return cursor.fetchone()[0]


# ---------------- Authentication ----------------
def show_login():
    st.title("🏥 Hospital Management System")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.subheader("Login")
        user_type = st.selectbox("Login as:", ["Select", "Admin", "User"])
        password = st.text_input("Password", type="password")

        if st.button("Login", use_container_width=True):
            ADMIN_PASSWORD = "admin123"
            USER_PASSWORD = "user123"

            if user_type == "Admin" and password == ADMIN_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.user_type = "Admin"
                st.rerun()
            elif user_type == "User" and password == USER_PASSWORD:
                st.session_state.logged_in = True
                st.session_state.user_type = "User"
                st.rerun()
            else:
                st.error("Invalid credentials!")


# ---------------- Admin Functions ----------------
def show_admin_dashboard():
    st.title("🔧 Admin Dashboard")

    # Sidebar for logout
    with st.sidebar:
        st.write(f"Logged in as: **{st.session_state.user_type}**")
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user_type = None
            st.rerun()

    # Main content
    tab1, tab2, tab3, tab4 = st.tabs(["📊 Tables", "🔗 Blockchain", "📈 Analytics", "⚙️ Settings"])

    with tab1:
        show_table_management()

    with tab2:
        show_blockchain_management()

    with tab3:
        show_analytics()

    with tab4:
        show_settings()


def show_table_management():
    st.subheader("Table Management")

    conn = st.session_state.db_connection

    # Get available tables dynamically
    available_tables = get_available_tables(conn)

    if not available_tables:
        st.warning("No tables found in database. Please ensure tables are created.")
        return

    selected_table = st.selectbox("Select Table", available_tables)

    # Get actual columns from database
    actual_columns = get_table_columns(conn, selected_table)

    if not actual_columns:
        st.error(f"Could not retrieve columns for table {selected_table}")
        return

    st.info(
        f"Table: {selected_table} | Columns: {len(actual_columns)} | {', '.join(actual_columns[:5])}{'...' if len(actual_columns) > 5 else ''}")

    pk_column = actual_columns[0]  # Assume first column is primary key

    # CRUD Operations
    operation = st.radio("Operation", ["View", "Add", "Update", "Delete"], horizontal=True)

    if operation == "View":
        show_table_records(conn, selected_table, actual_columns)

    elif operation == "Add":
        add_record(conn, selected_table, actual_columns)

    elif operation == "Update":
        update_record(conn, selected_table, actual_columns)

    elif operation == "Delete":
        delete_record(conn, selected_table, pk_column)


def show_table_records(conn, table_name, columns):
    """Fixed version that uses actual database columns"""
    try:
        with conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table_name}")
            rows = cursor.fetchall()

            if rows:
                # Use actual columns from database, not hardcoded ones
                df = pd.DataFrame(rows, columns=columns)

                st.write(f"**Records found:** {len(rows)}")
                st.dataframe(df, use_container_width=True)

                # Show column info for debugging
                with st.expander("Column Information"):
                    st.write(f"**Columns ({len(columns)}):** {columns}")
                    st.write(f"**Sample row columns:** {len(rows[0]) if rows else 0}")

            else:
                st.info("No records found")
    except oracledb.DatabaseError as e:
        st.error(f"Error fetching records from {table_name}: {e}")
    except Exception as e:
        st.error(f"Unexpected error: {e}")


def add_record(conn, table_name, columns):
    st.subheader(f"Add New Record to {table_name}")

    with st.form(f"add_{table_name}"):
        values = []

        # Auto-generate ID for primary key (assuming first column is PK)
        pk_column = columns[0]
        try:
            new_id = get_next_id(conn, table_name, pk_column)
            values.append(new_id)
            st.write(f"{pk_column}: {new_id} (auto-generated)")
        except Exception as e:
            st.error(f"Could not generate ID: {e}")
            new_id = st.number_input(f"{pk_column}", min_value=1, value=1)
            values[0] = new_id

        # Input fields for other columns
        for col in columns[1:]:
            if 'date' in col.lower():
                val = st.date_input(f"{col.replace('_', ' ').title()}")
                values.append(val.strftime('%Y-%m-%d') if val else '')
            elif 'id' in col.lower() and col != columns[0]:
                val = st.number_input(f"{col.replace('_', ' ').title()}", min_value=1, value=1)
                values.append(val)
            else:
                val = st.text_input(f"{col.replace('_', ' ').title()}")
                values.append(val)

        if st.form_submit_button("Add Record"):
            try:
                with conn.cursor() as cursor:
                    placeholders = ', '.join([f":{i + 1}" for i in range(len(values))])
                    cursor.execute(f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})", values)
                    conn.commit()

                # Add to blockchain
                row_hash = compute_data_hash(table_name, values, columns)
                st.session_state.blockchain.add_block(table_name, new_id, row_hash)

                st.success(f"Record added successfully with ID: {new_id}")

            except oracledb.DatabaseError as e:
                st.error(f"Error adding record: {e}")


def update_record(conn, table_name, columns):
    st.subheader(f"Update Record in {table_name}")

    pk_column = columns[0]
    record_id = st.number_input(f"Enter {pk_column} to update", min_value=1)

    if st.button("Load Record"):
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {table_name} WHERE {pk_column} = :1", (record_id,))
                record = cursor.fetchone()

                if record:
                    st.session_state.current_record = dict(zip(columns, record))
                else:
                    st.error("Record not found")
        except oracledb.DatabaseError as e:
            st.error(f"Error loading record: {e}")

    if 'current_record' in st.session_state:
        with st.form("update_form"):
            updates = {}
            for col in columns[1:]:  # Skip primary key
                current_val = st.session_state.current_record[col]
                new_val = st.text_input(f"{col.replace('_', ' ').title()}",
                                        value=str(current_val) if current_val else "")
                if new_val and new_val != str(current_val):
                    updates[col] = new_val

            if st.form_submit_button("Update Record"):
                if updates:
                    try:
                        with conn.cursor() as cursor:
                            set_clause = ', '.join([f"{col} = :{i + 1}" for i, col in enumerate(updates.keys())])
                            cursor.execute(
                                f"UPDATE {table_name} SET {set_clause} WHERE {pk_column} = :{len(updates) + 1}",
                                list(updates.values()) + [record_id])
                            conn.commit()

                        # Update blockchain
                        with conn.cursor() as cursor:
                            cursor.execute(f"SELECT * FROM {table_name} WHERE {pk_column} = :1", (record_id,))
                            updated_record = cursor.fetchone()
                        row_hash = compute_data_hash(table_name, updated_record, columns)
                        st.session_state.blockchain.add_block(table_name, record_id, row_hash)

                        st.success("Record updated successfully!")
                        del st.session_state.current_record

                    except oracledb.DatabaseError as e:
                        st.error(f"Error updating record: {e}")
                else:
                    st.warning("No changes detected")


def delete_record(conn, table_name, pk_column):
    st.subheader(f"Delete Record from {table_name}")

    record_id = st.number_input(f"Enter {pk_column} to delete", min_value=1)

    if st.button("Delete Record", type="secondary"):
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table_name} WHERE {pk_column} = :1", (record_id,))
                if cursor.rowcount > 0:
                    conn.commit()
                    st.success("Record deleted successfully!")
                else:
                    st.error("Record not found")
        except oracledb.DatabaseError as e:
            st.error(f"Error deleting record: {e}")


def show_blockchain_management():
    st.subheader("Blockchain Management")

    blockchain = st.session_state.blockchain

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Total Blocks", len(blockchain.chain))

    with col2:
        if st.button("Initialize Blockchain for Existing Records"):
            initialize_blockchain()

    # Show blockchain
    if blockchain.chain:
        st.subheader("Blockchain History")
        blockchain_data = []
        for block in blockchain.chain[-10:]:  # Show last 10 blocks
            blockchain_data.append({
                'Index': block['index'],
                'Table': block['table_name'],
                'Record ID': block['record_id'],
                'Data Hash': block['data_hash'][:16] + '...',
                'Block Hash': block['block_hash'][:16] + '...',
            })

        df = pd.DataFrame(blockchain_data)
        st.dataframe(df, use_container_width=True)


def initialize_blockchain():
    conn = st.session_state.db_connection
    blockchain = st.session_state.blockchain

    # Get available tables instead of using hardcoded ones
    available_tables = get_available_tables(conn)

    if not available_tables:
        st.warning("No tables found to initialize blockchain")
        return

    progress_bar = st.progress(0)
    status_text = st.empty()

    total_tables = len(available_tables)

    for i, table_name in enumerate(available_tables):
        status_text.text(f"Processing {table_name}...")

        # Get actual columns for this table
        columns = get_table_columns(conn, table_name)

        if not columns:
            continue

        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT * FROM {table_name}")
                rows = cursor.fetchall()

                for row in rows:
                    data_hash = compute_data_hash(table_name, row, columns)
                    if not blockchain.verify(table_name, row[0], data_hash):
                        blockchain.add_block(table_name, row[0], data_hash)

        except oracledb.DatabaseError as e:
            st.warning(f"Could not process table {table_name}: {e}")

        progress_bar.progress((i + 1) / total_tables)

    status_text.text("Blockchain initialization complete!")
    st.success("Blockchain initialized for all existing records!")


def show_analytics():
    st.subheader("System Analytics")

    conn = st.session_state.db_connection
    available_tables = get_available_tables(conn)

    # Dynamic analytics based on available tables
    cols = st.columns(min(4, len(available_tables)))

    for i, table_name in enumerate(available_tables[:4]):
        try:
            with conn.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                count = cursor.fetchone()[0]

            with cols[i % 4]:
                st.metric(table_name.title(), count)
        except:
            with cols[i % 4]:
                st.metric(table_name.title(), "N/A")


def show_settings():
    st.subheader("System Settings")

    st.write("**Database Configuration**")
    st.code(f"""
    Host: {DB_DSN}
    User: {DB_USER}
    Connection Status: {'Connected' if st.session_state.db_connection else 'Disconnected'}
    """)

    st.write("**Blockchain Configuration**")
    st.code(f"""
    Blocks in Chain: {len(st.session_state.blockchain.chain) if st.session_state.blockchain else 0}
    Hash Algorithm: SHA-256
    """)

    # Database Table Inspector
    st.subheader("Database Table Inspector")

    if st.button("Inspect All Tables"):
        conn = st.session_state.db_connection
        available_tables = get_available_tables(conn)

        for table_name in available_tables:
            with st.expander(f"Table: {table_name}"):
                try:
                    # Get actual structure
                    actual_columns = get_table_columns(conn, table_name)

                    # Get fallback structure
                    fallback_columns = TABLE_COLUMNS.get(table_name, [])

                    # Get row count
                    with conn.cursor() as cursor:
                        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
                        row_count = cursor.fetchone()[0]

                    col1, col2 = st.columns(2)

                    with col1:
                        st.write("**Actual Columns:**")
                        for i, col in enumerate(actual_columns):
                            st.write(f"{i + 1}. {col}")

                    with col2:
                        st.write("**Fallback Columns:**")
                        for i, col in enumerate(fallback_columns):
                            st.write(f"{i + 1}. {col}")

                    st.write(f"**Row Count:** {row_count}")

                    # Highlight mismatches
                    if len(actual_columns) != len(fallback_columns):
                        st.warning(
                            f"Column count difference! Actual: {len(actual_columns)}, Fallback: {len(fallback_columns)}")

                except oracledb.DatabaseError as e:
                    st.error(f"Table {table_name} not accessible: {e}")


# ---------------- User Functions ----------------
def show_user_dashboard():
    st.title("👤 Patient Portal")

    # Sidebar for logout
    with st.sidebar:
        st.write(f"Logged in as: **{st.session_state.user_type}**")
        if st.button("Logout"):
            st.session_state.logged_in = False
            st.session_state.user_type = None
            st.rerun()

    patient_id = st.number_input("Enter Your Patient ID", min_value=1, value=1)

    if st.button("View My Records"):
        show_patient_records(patient_id)


def show_patient_records(patient_id):
    conn = st.session_state.db_connection

    try:
        # Get actual column names for patients table
        patient_columns = get_table_columns(conn, "PATIENTS")

        with conn.cursor() as cursor:
            # Get patient info
            cursor.execute("SELECT * FROM PATIENTS WHERE patient_id = :1", (patient_id,))
            patient = cursor.fetchone()

            if not patient:
                st.warning("Patient not found!")
                return

            # Patient Information
            st.subheader("👤 Patient Information")
            patient_data = dict(zip(patient_columns, patient))

            col1, col2 = st.columns(2)
            with col1:
                st.write(f"**Name:** {patient_data.get('first_name', '')} {patient_data.get('last_name', '')}")
                st.write(f"**Gender:** {patient_data.get('gender', 'N/A')}")
                st.write(f"**Contact:** {patient_data.get('contact', 'N/A')}")
            with col2:
                st.write(f"**Date of Birth:** {patient_data.get('dob', 'N/A')}")
                st.write(f"**Address:** {patient_data.get('address', 'N/A')}")

            # Show other related records if tables exist
            available_tables = get_available_tables(conn)

            if "APPOINTMENTS" in available_tables:
                show_patient_appointments(conn, patient_id)

            if "MEDICALRECORDS" in available_tables:
                show_patient_medical_records(conn, patient_id)

            if "PRESCRIPTIONS" in available_tables:
                show_patient_prescriptions(conn, patient_id)

            if "BILLING" in available_tables:
                show_patient_billing(conn, patient_id)

    except oracledb.DatabaseError as e:
        st.error(f"Database error: {e}")


def show_patient_appointments(conn, patient_id):
    st.subheader("📅 Appointments")
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                           SELECT a.*,
                                  d.first_name || ' ' || d.last_name AS doctor_name,
                                  s.first_name || ' ' || s.last_name AS staff_name
                           FROM APPOINTMENTS a
                                    LEFT JOIN DOCTORS d ON a.doctor_id = d.doctor_id
                                    LEFT JOIN STAFF s ON a.staff_id = s.staff_id
                           WHERE a.patient_id = :1
                           ORDER BY a.appointment_date DESC
                           """, (patient_id,))

            appointments = cursor.fetchall()
            if appointments:
                # Get column names dynamically
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(appointments, columns=columns)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No appointments found")
    except oracledb.DatabaseError as e:
        st.error(f"Error fetching appointments: {e}")


def show_patient_medical_records(conn, patient_id):
    st.subheader("📋 Medical Records")
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                           SELECT mr.*, d.first_name || ' ' || d.last_name AS doctor_name
                           FROM MEDICALRECORDS mr
                                    LEFT JOIN DOCTORS d ON mr.doctor_id = d.doctor_id
                           WHERE mr.patient_id = :1
                           ORDER BY mr.created_at DESC
                           """, (patient_id,))

            records = cursor.fetchall()
            if records:
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(records, columns=columns)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No medical records found")
    except oracledb.DatabaseError as e:
        st.error(f"Error fetching medical records: {e}")


def show_patient_prescriptions(conn, patient_id):
    st.subheader("💊 Prescriptions")
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                           SELECT pr.*
                           FROM PRESCRIPTIONS pr
                                    JOIN MEDICALRECORDS mr ON pr.record_id = mr.record_id
                           WHERE mr.patient_id = :1
                           ORDER BY pr.prescription_id DESC
                           """, (patient_id,))

            prescriptions = cursor.fetchall()
            if prescriptions:
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(prescriptions, columns=columns)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No prescriptions found")
    except oracledb.DatabaseError as e:
        st.error(f"Error fetching prescriptions: {e}")


def show_patient_billing(conn, patient_id):
    st.subheader("💰 Billing")
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                           SELECT *
                           FROM BILLING
                           WHERE patient_id = :1
                           ORDER BY created_at DESC
                           """, (patient_id,))

            billing = cursor.fetchall()
            if billing:
                columns = [desc[0] for desc in cursor.description]
                df = pd.DataFrame(billing, columns=columns)
                st.dataframe(df, use_container_width=True)
            else:
                st.info("No billing records found")
    except oracledb.DatabaseError as e:
        st.error(f"Error fetching billing records: {e}")


# ---------------- Main Application ----------------
def main():
    # Initialize database connection
    if not st.session_state.db_connection:
        st.session_state.db_connection = get_db_connection()
        if not st.session_state.db_connection:
            st.stop()

    # Initialize blockchain
    if not st.session_state.blockchain:
        st.session_state.blockchain = Blockchain(st.session_state.db_connection)

    # Show appropriate interface based on login status
    if not st.session_state.logged_in:
        show_login()
    else:
        if st.session_state.user_type == "Admin":
            show_admin_dashboard()
        else:
            show_user_dashboard()


if __name__ == "__main__":
    main()