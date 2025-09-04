import streamlit as st
import oracledb
import hashlib
from datetime import datetime, date
import pandas as pd
import traceback
from typing import Optional, List, Dict, Any
import time

# Configure Streamlit page
st.set_page_config(
    page_title="Hospital Management System",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ---------------- CONFIGURATION ----------------
DB_CONFIG = {
    "user": "system",
    "password": "system",
    "dsn": "localhost/XEPDB1",
    "connection_timeout": 10,  # 10 seconds timeout
    "query_timeout": 30  # 30 seconds for queries
}

# Authentication credentials
AUTH_CONFIG = {
    "admin": {"password": "admin123", "type": "Admin"},
    "user": {"password": "user123", "type": "User"}
}

# Default table structures (fallback)
DEFAULT_TABLE_SCHEMAS = {
    "PATIENTS": ["patient_id", "first_name", "last_name", "dob", "gender", "contact", "address"],
    "DOCTORS": ["doctor_id", "first_name", "last_name", "specialization", "contact", "department_id"],
    "STAFF": ["staff_id", "first_name", "last_name", "role", "contact", "department_id"],
    "APPOINTMENTS": ["appointment_id", "patient_id", "doctor_id", "staff_id", "appointment_date", "status", "notes"],
    "MEDICALRECORDS": ["record_id", "patient_id", "doctor_id", "diagnosis", "treatment", "created_at"],
    "PRESCRIPTIONS": ["prescription_id", "record_id", "medicine_name", "dosage", "duration", "notes"],
    "BILLING": ["bill_id", "patient_id", "appointment_id", "amount", "status", "created_at"],
    "INVENTORY": ["item_id", "name", "category", "quantity", "unit", "expiry_date", "created_at"]
}


# ---------------- SESSION STATE INITIALIZATION ----------------
def initialize_session_state():
    """Initialize all session state variables safely"""
    defaults = {
        'logged_in': False,
        'user_type': None,
        'db_connection': None,
        'blockchain': None,
        'connection_status': 'disconnected',
        'available_tables': [],
        'table_schemas': {},
        'last_error': None,
        'current_record': None,
        'app_initialized': False
    }

    for key, default_value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_value


# ---------------- DATABASE CONNECTION MANAGEMENT ----------------
class DatabaseManager:
    """Handles all database operations safely"""

    @staticmethod
    def create_connection() -> Optional[oracledb.Connection]:
        """Create database connection with timeout and error handling"""
        try:
            # Set connection timeout
            connection = oracledb.connect(
                user=DB_CONFIG["user"],
                password=DB_CONFIG["password"],
                dsn=DB_CONFIG["dsn"]
            )

            # Test connection with simple query
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1 FROM DUAL")
                cursor.fetchone()

            return connection

        except oracledb.DatabaseError as e:
            st.error(f"Database connection failed: {str(e)}")
            return None
        except Exception as e:
            st.error(f"Unexpected connection error: {str(e)}")
            return None

    @staticmethod
    def ensure_connection() -> bool:
        """Ensure database connection is active"""
        try:
            if st.session_state.db_connection is None:
                st.session_state.db_connection = DatabaseManager.create_connection()

            # Test existing connection
            if st.session_state.db_connection:
                with st.session_state.db_connection.cursor() as cursor:
                    cursor.execute("SELECT 1 FROM DUAL")
                    cursor.fetchone()
                st.session_state.connection_status = 'connected'
                return True

        except Exception as e:
            st.session_state.connection_status = 'disconnected'
            st.session_state.db_connection = None
            st.error(f"Database connection lost: {str(e)}")

        return False

    @staticmethod
    def execute_query(query: str, params: tuple = None, fetch_one: bool = False, fetch_all: bool = True) -> Any:
        """Execute query safely with error handling"""
        if not DatabaseManager.ensure_connection():
            return None

        try:
            with st.session_state.db_connection.cursor() as cursor:
                if params:
                    cursor.execute(query, params)
                else:
                    cursor.execute(query)

                if fetch_one:
                    return cursor.fetchone()
                elif fetch_all:
                    return cursor.fetchall()
                else:
                    st.session_state.db_connection.commit()
                    return cursor.rowcount

        except oracledb.DatabaseError as e:
            st.error(f"Database query error: {str(e)}")
            return None
        except Exception as e:
            st.error(f"Unexpected query error: {str(e)}")
            return None

    @staticmethod
    def get_table_columns(table_name: str) -> List[str]:
        """Get actual table columns from database"""
        try:
            query = """
                    SELECT column_name
                    FROM user_tab_columns
                    WHERE table_name = UPPER(:1)
                    ORDER BY column_id \
                    """

            result = DatabaseManager.execute_query(query, (table_name,))

            if result:
                columns = [row[0].lower() for row in result]
                # Cache the schema
                st.session_state.table_schemas[table_name] = columns
                return columns
            else:
                # Return fallback schema
                return DEFAULT_TABLE_SCHEMAS.get(table_name, [])

        except Exception as e:
            st.warning(f"Could not get columns for {table_name}: {str(e)}")
            return DEFAULT_TABLE_SCHEMAS.get(table_name, [])

    @staticmethod
    def get_available_tables() -> List[str]:
        """Get list of available tables"""
        try:
            query = """
                    SELECT table_name
                    FROM user_tables
                    WHERE table_name IN ('PATIENTS', 'DOCTORS', 'STAFF', 'APPOINTMENTS',
                                         'MEDICALRECORDS', 'PRESCRIPTIONS', 'BILLING', 'INVENTORY')
                    ORDER BY table_name \
                    """

            result = DatabaseManager.execute_query(query)

            if result:
                tables = [row[0] for row in result]
                st.session_state.available_tables = tables
                return tables
            else:
                return []

        except Exception as e:
            st.warning(f"Could not fetch available tables: {str(e)}")
            return []


# ---------------- BLOCKCHAIN MANAGEMENT ----------------
class BlockchainManager:
    """Handles blockchain operations safely and efficiently"""

    def __init__(self):
        self.chain = []
        self.initialized = False

    def lazy_init(self) -> bool:
        """Initialize blockchain only when needed"""
        if self.initialized:
            return True

        try:
            if not DatabaseManager.ensure_connection():
                return False

            # Check if blockchain table exists
            table_check = DatabaseManager.execute_query(
                "SELECT COUNT(*) FROM user_tables WHERE table_name = 'BLOCKCHAIN'",
                fetch_one=True
            )

            if table_check and table_check[0] > 0:
                self.load_chain()

            self.initialized = True
            return True

        except Exception as e:
            st.warning(f"Blockchain initialization failed: {str(e)}")
            return False

    def load_chain(self, limit: int = 1000) -> None:
        """Load blockchain with limit to prevent blocking"""
        try:
            query = """
                    SELECT block_index, table_name, record_id, data_hash, block_hash, previous_hash
                    FROM BlockChain
                    ORDER BY block_index DESC
                        FETCH FIRST :1 ROWS ONLY \
                    """

            result = DatabaseManager.execute_query(query, (limit,))

            if result:
                self.chain = []
                for row in reversed(result):  # Reverse to get chronological order
                    self.chain.append({
                        'index': row[0],
                        'table_name': row[1],
                        'record_id': row[2],
                        'data_hash': row[3],
                        'block_hash': row[4],
                        'previous_hash': row[5],
                        'created_at': datetime.now()
                    })

        except Exception as e:
            st.warning(f"Could not load blockchain: {str(e)}")
            self.chain = []

    def add_block(self, table_name: str, record_id: int, data_hash: str) -> bool:
        """Add new block to blockchain"""
        if not self.lazy_init():
            return False

        try:
            index = len(self.chain) + 1
            previous_hash = self.chain[-1]['block_hash'] if self.chain else "0"
            block_hash = hashlib.sha256(
                (str(index) + previous_hash + data_hash).encode()
            ).hexdigest()

            block = {
                'index': index,
                'table_name': table_name,
                'record_id': record_id,
                'data_hash': data_hash,
                'block_hash': block_hash,
                'previous_hash': previous_hash,
                'created_at': datetime.now()
            }

            # Insert into database
            query = """
                    INSERT INTO BlockChain (block_index, table_name, record_id, data_hash, block_hash, previous_hash)
                    VALUES (:1, :2, :3, :4, :5, :6) \
                    """

            rowcount = DatabaseManager.execute_query(
                query,
                (index, table_name, record_id, data_hash, block_hash, previous_hash),
                fetch_all=False
            )

            if rowcount and rowcount > 0:
                self.chain.append(block)
                return True

        except Exception as e:
            st.error(f"Failed to add blockchain block: {str(e)}")

        return False

    def verify_record(self, table_name: str, record_id: int, data_hash: str) -> bool:
        """Verify if record exists in blockchain"""
        if not self.lazy_init():
            return False

        for block in self.chain:
            if (block['table_name'] == table_name and
                    str(block['record_id']) == str(record_id) and
                    block['data_hash'] == data_hash):
                return True
        return False

    def get_recent_blocks(self, limit: int = 10) -> List[Dict]:
        """Get recent blockchain blocks"""
        if not self.lazy_init():
            return []

        return self.chain[-limit:] if self.chain else []


# ---------------- UTILITY FUNCTIONS ----------------
def compute_data_hash(table_name: str, row: tuple, columns: List[str]) -> str:
    """Compute hash of row data safely"""
    try:
        data = {col: val for col, val in zip(columns, row)}
        data_str = str(sorted(data.items()))
        return hashlib.sha256(data_str.encode()).hexdigest()
    except Exception as e:
        st.warning(f"Hash computation failed: {str(e)}")
        return hashlib.sha256(str(row).encode()).hexdigest()


def get_next_id(table_name: str, pk_column: str) -> Optional[int]:
    """Get next ID using sequence with error handling"""
    try:
        seq_name = f"{table_name}_{pk_column}_SEQ".upper()

        # Check if sequence exists
        check_query = """
                      SELECT COUNT(*) \
                      FROM user_sequences \
                      WHERE sequence_name = :1 \
                      """

        result = DatabaseManager.execute_query(check_query, (seq_name,), fetch_one=True)

        if result and result[0] == 0:
            # Create sequence
            create_seq = f"CREATE SEQUENCE {seq_name} START WITH 1 INCREMENT BY 1 NOCACHE"
            DatabaseManager.execute_query(create_seq, fetch_all=False)

        # Get next value
        next_val_query = f"SELECT {seq_name}.NEXTVAL FROM DUAL"
        result = DatabaseManager.execute_query(next_val_query, fetch_one=True)

        if result:
            return result[0]

    except Exception as e:
        st.warning(f"Could not generate ID for {table_name}: {str(e)}")

    return None


def safe_date_input(label: str, value=None) -> str:
    """Safe date input handling"""
    try:
        date_val = st.date_input(label, value=value)
        if date_val:
            return date_val.strftime('%Y-%m-%d')
        return ''
    except Exception as e:
        st.warning(f"Date input error: {str(e)}")
        return ''


# ---------------- AUTHENTICATION ----------------
def show_login():
    """Display login interface"""
    st.title("🏥 Hospital Management System")

    col1, col2, col3 = st.columns([1, 2, 1])

    with col2:
        st.subheader("Login")

        with st.form("login_form"):
            user_type = st.selectbox("Login as:", ["Select", "Admin", "User"])
            password = st.text_input("Password", type="password")

            if st.form_submit_button("Login", use_container_width=True):
                try:
                    user_key = user_type.lower()

                    if (user_key in AUTH_CONFIG and
                            password == AUTH_CONFIG[user_key]["password"]):

                        st.session_state.logged_in = True
                        st.session_state.user_type = AUTH_CONFIG[user_key]["type"]
                        st.success(f"Welcome, {st.session_state.user_type}!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error("Invalid credentials!")

                except Exception as e:
                    st.error(f"Login error: {str(e)}")


# ---------------- ADMIN DASHBOARD ----------------
def show_admin_dashboard():
    """Display admin dashboard"""
    st.title("🔧 Admin Dashboard")

    # Sidebar
    with st.sidebar:
        st.write(f"**Logged in as:** {st.session_state.user_type}")

        if st.button("🔄 Refresh Connection"):
            st.session_state.db_connection = None
            DatabaseManager.ensure_connection()
            st.rerun()

        if st.button("🚪 Logout"):
            logout_user()

        # Connection status
        status_color = "🟢" if st.session_state.connection_status == 'connected' else "🔴"
        st.write(f"**DB Status:** {status_color} {st.session_state.connection_status}")

    # Main tabs
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
    """Table management interface"""
    st.subheader("Table Management")

    if not DatabaseManager.ensure_connection():
        st.error("Database connection required for table management")
        return

    # Get available tables
    available_tables = DatabaseManager.get_available_tables()

    if not available_tables:
        st.warning("No tables found. Please ensure database tables are created.")
        if st.button("🔄 Refresh Tables"):
            st.rerun()
        return

    selected_table = st.selectbox("Select Table", available_tables)

    if not selected_table:
        return

    # Get table schema
    columns = DatabaseManager.get_table_columns(selected_table)

    if not columns:
        st.error(f"Could not retrieve schema for table {selected_table}")
        return

    st.info(
        f"**Table:** {selected_table} | **Columns:** {len(columns)} | **Primary Key:** {columns[0] if columns else 'Unknown'}")

    # Operations
    operation = st.radio("Operation", ["View", "Add", "Update", "Delete"], horizontal=True)

    if operation == "View":
        show_table_records(selected_table, columns)
    elif operation == "Add":
        add_record(selected_table, columns)
    elif operation == "Update":
        update_record(selected_table, columns)
    elif operation == "Delete":
        delete_record(selected_table, columns[0] if columns else None)


def show_table_records(table_name: str, columns: List[str]):
    """Display table records with pagination"""
    st.subheader(f"Records from {table_name}")

    # Pagination controls
    col1, col2, col3 = st.columns([1, 1, 2])

    with col1:
        page_size = st.selectbox("Records per page", [10, 25, 50, 100], index=0)

    with col2:
        page_num = st.number_input("Page", min_value=1, value=1)

    offset = (page_num - 1) * page_size

    try:
        # Get total count
        count_query = f"SELECT COUNT(*) FROM {table_name}"
        count_result = DatabaseManager.execute_query(count_query, fetch_one=True)
        total_records = count_result[0] if count_result else 0

        # Get paginated records
        query = f"""
            SELECT * FROM {table_name}
            OFFSET {offset} ROWS
            FETCH NEXT {page_size} ROWS ONLY
        """

        result = DatabaseManager.execute_query(query)

        if result:
            df = pd.DataFrame(result, columns=columns)

            with col3:
                st.write(f"**Total Records:** {total_records} | **Showing:** {len(result)}")

            st.dataframe(df, use_container_width=True)
        else:
            st.info("No records found")

    except Exception as e:
        st.error(f"Error fetching records: {str(e)}")


def add_record(table_name: str, columns: List[str]):
    """Add new record interface"""
    st.subheader(f"Add New Record to {table_name}")

    if not columns:
        st.error("No columns available for this table")
        return

    with st.form(f"add_{table_name}"):
        values = []
        pk_column = columns[0]

        # Auto-generate ID for primary key
        new_id = get_next_id(table_name, pk_column)
        if new_id:
            st.success(f"**{pk_column}:** {new_id} (auto-generated)")
            values.append(new_id)
        else:
            new_id = st.number_input(f"{pk_column} (manual)", min_value=1, value=1)
            values.append(new_id)

        # Input fields for other columns
        for col in columns[1:]:
            if 'date' in col.lower():
                val = safe_date_input(f"{col.replace('_', ' ').title()}")
                values.append(val)
            elif 'id' in col.lower():
                val = st.number_input(f"{col.replace('_', ' ').title()}", min_value=1, value=1)
                values.append(val)
            elif col.lower() in ['amount', 'quantity']:
                val = st.number_input(f"{col.replace('_', ' ').title()}", min_value=0.0, value=0.0)
                values.append(val)
            else:
                val = st.text_input(f"{col.replace('_', ' ').title()}")
                values.append(val)

        if st.form_submit_button("Add Record"):
            try:
                placeholders = ', '.join([f":{i + 1}" for i in range(len(values))])
                query = f"INSERT INTO {table_name} ({', '.join(columns)}) VALUES ({placeholders})"

                rowcount = DatabaseManager.execute_query(query, tuple(values), fetch_all=False)

                if rowcount and rowcount > 0:
                    # Add to blockchain
                    if st.session_state.blockchain:
                        data_hash = compute_data_hash(table_name, tuple(values), columns)
                        st.session_state.blockchain.add_block(table_name, new_id, data_hash)

                    st.success(f"Record added successfully with ID: {new_id}")
                else:
                    st.error("Failed to add record")

            except Exception as e:
                st.error(f"Error adding record: {str(e)}")


def update_record(table_name: str, columns: List[str]):
    """Update record interface"""
    st.subheader(f"Update Record in {table_name}")

    if not columns:
        st.error("No columns available for this table")
        return

    pk_column = columns[0]

    col1, col2 = st.columns([1, 1])

    with col1:
        record_id = st.number_input(f"Enter {pk_column} to update", min_value=1)

    with col2:
        if st.button("🔍 Load Record"):
            try:
                query = f"SELECT * FROM {table_name} WHERE {pk_column} = :1"
                result = DatabaseManager.execute_query(query, (record_id,), fetch_one=True)

                if result:
                    st.session_state.current_record = dict(zip(columns, result))
                    st.success("Record loaded successfully")
                else:
                    st.error("Record not found")

            except Exception as e:
                st.error(f"Error loading record: {str(e)}")

    # Update form
    if st.session_state.current_record:
        with st.form("update_form"):
            updates = {}

            st.write(f"**Updating Record ID:** {record_id}")

            for col in columns[1:]:  # Skip primary key
                current_val = st.session_state.current_record.get(col, '')

                if 'date' in col.lower():
                    try:
                        current_date = datetime.strptime(str(current_val), '%Y-%m-%d').date() if current_val else None
                        new_val = safe_date_input(f"{col.replace('_', ' ').title()}", value=current_date)
                    except:
                        new_val = safe_date_input(f"{col.replace('_', ' ').title()}")
                else:
                    new_val = st.text_input(
                        f"{col.replace('_', ' ').title()}",
                        value=str(current_val) if current_val else ""
                    )

                if new_val and new_val != str(current_val):
                    updates[col] = new_val

            if st.form_submit_button("Update Record"):
                if updates:
                    try:
                        set_clause = ', '.join([f"{col} = :{i + 1}" for i, col in enumerate(updates.keys())])
                        query = f"UPDATE {table_name} SET {set_clause} WHERE {pk_column} = :{len(updates) + 1}"

                        rowcount = DatabaseManager.execute_query(
                            query,
                            tuple(list(updates.values()) + [record_id]),
                            fetch_all=False
                        )

                        if rowcount and rowcount > 0:
                            st.success("Record updated successfully!")
                            st.session_state.current_record = None
                        else:
                            st.error("No records updated")

                    except Exception as e:
                        st.error(f"Error updating record: {str(e)}")
                else:
                    st.warning("No changes detected")


def delete_record(table_name: str, pk_column: str):
    """Delete record interface"""
    st.subheader(f"Delete Record from {table_name}")

    if not pk_column:
        st.error("Primary key column not identified")
        return

    with st.form("delete_form"):
        record_id = st.number_input(f"Enter {pk_column} to delete", min_value=1)

        st.warning("⚠️ This action cannot be undone!")

        if st.form_submit_button("Delete Record", type="secondary"):
            try:
                query = f"DELETE FROM {table_name} WHERE {pk_column} = :1"
                rowcount = DatabaseManager.execute_query(query, (record_id,), fetch_all=False)

                if rowcount and rowcount > 0:
                    st.success(f"Record with ID {record_id} deleted successfully!")
                else:
                    st.error("Record not found or could not be deleted")

            except Exception as e:
                st.error(f"Error deleting record: {str(e)}")


def show_blockchain_management():
    """Blockchain management interface"""
    st.subheader("🔗 Blockchain Management")

    if not st.session_state.blockchain:
        st.session_state.blockchain = BlockchainManager()

    blockchain = st.session_state.blockchain

    # Initialize blockchain if needed
    if not blockchain.initialized and st.button("🚀 Initialize Blockchain"):
        if blockchain.lazy_init():
            st.success("Blockchain initialized successfully!")
            st.rerun()
        else:
            st.error("Failed to initialize blockchain")

    if not blockchain.initialized:
        st.info("Click 'Initialize Blockchain' to start using blockchain features")
        return

    # Stats
    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Total Blocks", len(blockchain.chain))

    with col2:
        if st.button("📊 Sync Existing Records"):
            sync_blockchain_with_existing_data()

    with col3:
        if st.button("🔄 Refresh Chain"):
            blockchain.load_chain()
            st.rerun()

    # Recent blocks
    recent_blocks = blockchain.get_recent_blocks(20)

    if recent_blocks:
        st.subheader("Recent Blockchain Entries")

        blockchain_data = []
        for block in reversed(recent_blocks):  # Show newest first
            blockchain_data.append({
                'Block': block['index'],
                'Table': block['table_name'],
                'Record ID': block['record_id'],
                'Data Hash': block['data_hash'][:16] + '...',
                'Block Hash': block['block_hash'][:16] + '...',
            })

        df = pd.DataFrame(blockchain_data)
        st.dataframe(df, use_container_width=True)
    else:
        st.info("No blockchain entries found")


def sync_blockchain_with_existing_data():
    """Sync blockchain with existing database records"""
    if not DatabaseManager.ensure_connection():
        st.error("Database connection required")
        return

    blockchain = st.session_state.blockchain
    available_tables = DatabaseManager.get_available_tables()

    if not available_tables:
        st.warning("No tables found to sync")
        return

    progress_bar = st.progress(0)
    status_text = st.empty()

    total_records = 0
    synced_records = 0

    for i, table_name in enumerate(available_tables):
        status_text.text(f"Processing {table_name}...")

        try:
            columns = DatabaseManager.get_table_columns(table_name)
            if not columns:
                continue

            # Get records in batches to avoid memory issues
            query = f"SELECT * FROM {table_name} FETCH FIRST 100 ROWS ONLY"
            result = DatabaseManager.execute_query(query)

            if result:
                for row in result:
                    total_records += 1
                    data_hash = compute_data_hash(table_name, row, columns)

                    # Check if already in blockchain
                    if not blockchain.verify_record(table_name, row[0], data_hash):
                        if blockchain.add_block(table_name, row[0], data_hash):
                            synced_records += 1

        except Exception as e:
            st.warning(f"Could not process table {table_name}: {str(e)}")

        progress_bar.progress((i + 1) / len(available_tables))

    status_text.text(f"Sync complete! {synced_records}/{total_records} records added to blockchain")


def show_analytics():
    """Analytics dashboard"""
    st.subheader("📈 System Analytics")

    if not DatabaseManager.ensure_connection():
        st.error("Database connection required for analytics")
        return

    available_tables = DatabaseManager.get_available_tables()

    if not available_tables:
        st.warning("No tables available for analytics")
        return

    # Table record counts
    st.write("**Table Record Counts**")

    cols = st.columns(min(4, len(available_tables)))

    for i, table_name in enumerate(available_tables):
        try:
            query = f"SELECT COUNT(*) FROM {table_name}"
            result = DatabaseManager.execute_query(query, fetch_one=True)
            count = result[0] if result else 0

            with cols[i % 4]:
                st.metric(table_name.title(), count)

        except Exception as e:
            with cols[i % 4]:
                st.metric(table_name.title(), "Error", help=str(e))

    # Blockchain stats
    if st.session_state.blockchain and st.session_state.blockchain.initialized:
        st.write("**Blockchain Statistics**")

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("Total Blocks", len(st.session_state.blockchain.chain))

        with col2:
            # Count unique tables in blockchain
            unique_tables = len(set(block['table_name'] for block in st.session_state.blockchain.chain))
            st.metric("Tables in Chain", unique_tables)

        with col3:
            # Count recent blocks (last 24 hours)
            recent_blocks = sum(1 for block in st.session_state.blockchain.chain
                                if block.get('created_at') and
                                (datetime.now() - block['created_at']).days < 1)
            st.metric("Recent Blocks (24h)", recent_blocks)


def show_settings():
    """System settings and configuration"""
    st.subheader("⚙️ System Settings")

    # Database Configuration
    st.write("**Database Configuration**")

    col1, col2 = st.columns(2)

    with col1:
        st.code(f"""
Host: {DB_CONFIG['dsn']}
User: {DB_CONFIG['user']}
Connection Timeout: {DB_CONFIG['connection_timeout']}s
Query Timeout: {DB_CONFIG['query_timeout']}s
        """)

    with col2:
        status_color = "🟢 Connected" if st.session_state.connection_status == 'connected' else "🔴 Disconnected"
        st.code(f"""
Status: {status_color}
Available Tables: {len(st.session_state.available_tables)}
Schemas Cached: {len(st.session_state.table_schemas)}
        """)

    # Blockchain Configuration
    st.write("**Blockchain Configuration**")

    if st.session_state.blockchain:
        blockchain_status = "Initialized" if st.session_state.blockchain.initialized else "Not Initialized"
        block_count = len(st.session_state.blockchain.chain)
    else:
        blockchain_status = "Not Created"
        block_count = 0

    st.code(f"""
Status: {blockchain_status}
Blocks in Chain: {block_count}
Hash Algorithm: SHA-256
    """)

    # Database Table Inspector
    st.subheader("🔍 Database Table Inspector")

    if st.button("🔍 Inspect All Tables"):
        inspect_all_tables()


def inspect_all_tables():
    """Inspect all database tables for debugging"""
    available_tables = DatabaseManager.get_available_tables()

    if not available_tables:
        st.warning("No tables found to inspect")
        return

    for table_name in available_tables:
        with st.expander(f"📋 Table: {table_name}"):
            try:
                # Get actual columns
                actual_columns = DatabaseManager.get_table_columns(table_name)

                # Get fallback columns
                fallback_columns = DEFAULT_TABLE_SCHEMAS.get(table_name, [])

                # Get row count
                count_query = f"SELECT COUNT(*) FROM {table_name}"
                count_result = DatabaseManager.execute_query(count_query, fetch_one=True)
                row_count = count_result[0] if count_result else 0

                # Display information
                col1, col2, col3 = st.columns(3)

                with col1:
                    st.write("**Actual Schema:**")
                    for i, col in enumerate(actual_columns, 1):
                        st.write(f"{i}. {col}")

                with col2:
                    st.write("**Expected Schema:**")
                    for i, col in enumerate(fallback_columns, 1):
                        st.write(f"{i}. {col}")

                with col3:
                    st.write("**Statistics:**")
                    st.write(f"Row Count: {row_count}")
                    st.write(f"Actual Columns: {len(actual_columns)}")
                    st.write(f"Expected Columns: {len(fallback_columns)}")

                # Highlight issues
                if len(actual_columns) != len(fallback_columns):
                    st.warning(f"⚠️ Column count mismatch: {len(actual_columns)} vs {len(fallback_columns)}")

                if set(actual_columns) != set(fallback_columns):
                    missing_cols = set(fallback_columns) - set(actual_columns)
                    extra_cols = set(actual_columns) - set(fallback_columns)

                    if missing_cols:
                        st.error(f"❌ Missing columns: {', '.join(missing_cols)}")
                    if extra_cols:
                        st.info(f"➕ Extra columns: {', '.join(extra_cols)}")

                if row_count == 0:
                    st.info("ℹ️ Table is empty")

            except Exception as e:
                st.error(f"❌ Error inspecting table {table_name}: {str(e)}")


# ---------------- USER DASHBOARD ----------------
def show_user_dashboard():
    """Display user dashboard"""
    st.title("👤 Patient Portal")

    # Sidebar
    with st.sidebar:
        st.write(f"**Logged in as:** {st.session_state.user_type}")

        if st.button("🚪 Logout"):
            logout_user()

        # Connection status
        status_color = "🟢" if st.session_state.connection_status == 'connected' else "🔴"
        st.write(f"**DB Status:** {status_color} {st.session_state.connection_status}")

    # Patient ID input
    col1, col2 = st.columns([2, 1])

    with col1:
        patient_id = st.number_input("Enter Your Patient ID", min_value=1, value=1)

    with col2:
        if st.button("🔍 View My Records", use_container_width=True):
            show_patient_records(patient_id)


def show_patient_records(patient_id: int):
    """Display patient records"""
    if not DatabaseManager.ensure_connection():
        st.error("Database connection required to view records")
        return

    try:
        # Check if patient exists
        patient_columns = DatabaseManager.get_table_columns("PATIENTS")

        if not patient_columns:
            st.error("Cannot access patient table")
            return

        query = "SELECT * FROM PATIENTS WHERE patient_id = :1"
        patient_result = DatabaseManager.execute_query(query, (patient_id,), fetch_one=True)

        if not patient_result:
            st.warning(f"Patient with ID {patient_id} not found!")
            return

        patient_data = dict(zip(patient_columns, patient_result))

        # Patient Information Section
        st.subheader("👤 Patient Information")

        col1, col2 = st.columns(2)

        with col1:
            st.write(f"**Name:** {patient_data.get('first_name', 'N/A')} {patient_data.get('last_name', 'N/A')}")
            st.write(f"**Gender:** {patient_data.get('gender', 'N/A')}")
            st.write(f"**Contact:** {patient_data.get('contact', 'N/A')}")

        with col2:
            st.write(f"**Date of Birth:** {patient_data.get('dob', 'N/A')}")
            st.write(f"**Address:** {patient_data.get('address', 'N/A')}")

        # Available tables check
        available_tables = DatabaseManager.get_available_tables()

        # Show related records in tabs
        tabs = []
        tab_names = []

        if "APPOINTMENTS" in available_tables:
            tab_names.append("📅 Appointments")
        if "MEDICALRECORDS" in available_tables:
            tab_names.append("📋 Medical Records")
        if "PRESCRIPTIONS" in available_tables:
            tab_names.append("💊 Prescriptions")
        if "BILLING" in available_tables:
            tab_names.append("💰 Billing")

        if tab_names:
            tabs = st.tabs(tab_names)

            tab_index = 0

            if "APPOINTMENTS" in available_tables:
                with tabs[tab_index]:
                    show_patient_appointments(patient_id)
                tab_index += 1

            if "MEDICALRECORDS" in available_tables:
                with tabs[tab_index]:
                    show_patient_medical_records(patient_id)
                tab_index += 1

            if "PRESCRIPTIONS" in available_tables:
                with tabs[tab_index]:
                    show_patient_prescriptions(patient_id)
                tab_index += 1

            if "BILLING" in available_tables:
                with tabs[tab_index]:
                    show_patient_billing(patient_id)
                tab_index += 1
        else:
            st.info("No additional record tables available")

    except Exception as e:
        st.error(f"Error loading patient records: {str(e)}")


def show_patient_appointments(patient_id: int):
    """Show patient appointments"""
    try:
        query = """
                SELECT a.appointment_id, \
                       a.appointment_date, \
                       a.status, \
                       a.notes,
                       COALESCE(d.first_name || ' ' || d.last_name, 'Unknown') AS doctor_name,
                       COALESCE(s.first_name || ' ' || s.last_name, 'Unknown') AS staff_name
                FROM APPOINTMENTS a
                         LEFT JOIN DOCTORS d ON a.doctor_id = d.doctor_id
                         LEFT JOIN STAFF s ON a.staff_id = s.staff_id
                WHERE a.patient_id = :1
                ORDER BY a.appointment_date DESC
                    FETCH FIRST 20 ROWS ONLY \
                """

        result = DatabaseManager.execute_query(query, (patient_id,))

        if result:
            df = pd.DataFrame(result, columns=[
                'Appointment ID', 'Date', 'Status', 'Notes', 'Doctor', 'Staff'
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No appointments found")

    except Exception as e:
        st.error(f"Error loading appointments: {str(e)}")


def show_patient_medical_records(patient_id: int):
    """Show patient medical records"""
    try:
        query = """
                SELECT mr.record_id, \
                       mr.diagnosis, \
                       mr.treatment, \
                       mr.created_at,
                       COALESCE(d.first_name || ' ' || d.last_name, 'Unknown') AS doctor_name
                FROM MEDICALRECORDS mr
                         LEFT JOIN DOCTORS d ON mr.doctor_id = d.doctor_id
                WHERE mr.patient_id = :1
                ORDER BY mr.created_at DESC
                    FETCH FIRST 10 ROWS ONLY \
                """

        result = DatabaseManager.execute_query(query, (patient_id,))

        if result:
            df = pd.DataFrame(result, columns=[
                'Record ID', 'Diagnosis', 'Treatment', 'Date', 'Doctor'
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No medical records found")

    except Exception as e:
        st.error(f"Error loading medical records: {str(e)}")


def show_patient_prescriptions(patient_id: int):
    """Show patient prescriptions"""
    try:
        query = """
                SELECT pr.prescription_id, pr.medicine_name, pr.dosage, pr.duration, pr.notes
                FROM PRESCRIPTIONS pr
                         JOIN MEDICALRECORDS mr ON pr.record_id = mr.record_id
                WHERE mr.patient_id = :1
                ORDER BY pr.prescription_id DESC
                    FETCH FIRST 20 ROWS ONLY \
                """

        result = DatabaseManager.execute_query(query, (patient_id,))

        if result:
            df = pd.DataFrame(result, columns=[
                'Prescription ID', 'Medicine', 'Dosage', 'Duration', 'Notes'
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No prescriptions found")

    except Exception as e:
        st.error(f"Error loading prescriptions: {str(e)}")


def show_patient_billing(patient_id: int):
    """Show patient billing records"""
    try:
        query = """
                SELECT bill_id, appointment_id, amount, status, created_at
                FROM BILLING
                WHERE patient_id = :1
                ORDER BY created_at DESC
                    FETCH FIRST 20 ROWS ONLY \
                """

        result = DatabaseManager.execute_query(query, (patient_id,))

        if result:
            df = pd.DataFrame(result, columns=[
                'Bill ID', 'Appointment ID', 'Amount', 'Status', 'Date'
            ])
            st.dataframe(df, use_container_width=True)
        else:
            st.info("No billing records found")

    except Exception as e:
        st.error(f"Error loading billing records: {str(e)}")


# ---------------- UTILITY FUNCTIONS ----------------
def logout_user():
    """Safely logout user"""
    try:
        # Close database connection
        if st.session_state.db_connection:
            st.session_state.db_connection.close()

        # Reset session state
        st.session_state.logged_in = False
        st.session_state.user_type = None
        st.session_state.db_connection = None
        st.session_state.blockchain = None
        st.session_state.connection_status = 'disconnected'
        st.session_state.current_record = None

        st.success("Logged out successfully!")
        time.sleep(1)
        st.rerun()

    except Exception as e:
        st.error(f"Logout error: {str(e)}")
        st.rerun()


def handle_app_error(error: Exception):
    """Handle application-level errors"""
    error_msg = str(error)

    st.error("⚠️ Application Error")

    with st.expander("Error Details"):
        st.code(error_msg)
        st.code(traceback.format_exc())

    st.info("Please try refreshing the page or contact support if the issue persists.")

    # Reset problematic session state
    if "database" in error_msg.lower():
        st.session_state.db_connection = None
        st.session_state.connection_status = 'disconnected'

    if st.button("🔄 Reset Application"):
        # Clear all session state except login
        keys_to_keep = ['logged_in', 'user_type']
        keys_to_clear = [key for key in st.session_state.keys() if key not in keys_to_keep]

        for key in keys_to_clear:
            del st.session_state[key]

        st.rerun()


# ---------------- MAIN APPLICATION ----------------
def main():
    """Main application entry point"""
    try:
        # Initialize session state
        initialize_session_state()

        # Mark app as initialized
        if not st.session_state.app_initialized:
            st.session_state.app_initialized = True

        # Show appropriate interface based on login status
        if not st.session_state.logged_in:
            show_login()
        else:
            # Ensure database connection for logged-in users
            if not DatabaseManager.ensure_connection():
                st.error("⚠️ Database connection failed. Some features may not work.")

                if st.button("🔄 Retry Connection"):
                    st.rerun()

            # Initialize blockchain for logged-in users
            if not st.session_state.blockchain:
                st.session_state.blockchain = BlockchainManager()

            # Show dashboard based on user type
            if st.session_state.user_type == "Admin":
                show_admin_dashboard()
            elif st.session_state.user_type == "User":
                show_user_dashboard()
            else:
                st.error("Invalid user type. Please log in again.")
                logout_user()

    except Exception as e:
        handle_app_error(e)


# ---------------- APPLICATION STARTUP ----------------
if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        st.error("❌ Critical application error occurred")
        st.code(f"Error: {str(e)}")

        if st.button("🔄 Restart Application"):
            # Clear all session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            st.rerun()