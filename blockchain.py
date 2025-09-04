import hashlib
from datetime import datetime
import oracledb

class Blockchain:
    def __init__(self, db_user, db_password, db_dsn):
        # Connect to Oracle DB
        self.conn = oracledb.connect(user=db_user, password=db_password, dsn=db_dsn)
        self.cursor = self.conn.cursor()
        self.chain = self._load_chain_from_db()

    def _load_chain_from_db(self):
        """Load existing blockchain from DB into memory"""
        self.cursor.execute("SELECT block_index, previous_hash, data_hash, block_hash, created_at FROM BlockChain ORDER BY block_index")
        rows = self.cursor.fetchall()
        chain = []
        for row in rows:
            chain.append({
                'index': row[0],
                'previous_hash': row[1],
                'data_hash': row[2],
                'block_hash': row[3],
                'created_at': row[4]
            })
        return chain

    def add_block(self, data_hash):
        """Add a new block and insert into Oracle DB"""
        previous_hash = self.chain[-1]['block_hash'] if self.chain else "0"
        index = len(self.chain) + 1  # used only for hash calculation
        block_hash = hashlib.sha256((str(index) + previous_hash + data_hash).encode()).hexdigest()
        created_at = datetime.now()

        # Insert into Oracle using sequence for block_index
        self.cursor.execute("""
            INSERT INTO BlockChain (block_index, previous_hash, data_hash, block_hash, created_at)
            VALUES (block_seq.NEXTVAL, :1, :2, :3, :4)
        """, (previous_hash, data_hash, block_hash, created_at))

        self.conn.commit()

        # Append to local chain
        block = {
            'index': index,
            'previous_hash': previous_hash,
            'data_hash': data_hash,
            'block_hash': block_hash,
            'created_at': created_at
        }
        self.chain.append(block)
        return block

    def verify(self, data_hash):
        """Verify if a data_hash exists in the blockchain"""
        for block in self.chain:
            if block['data_hash'] == data_hash:
                return True
        return False

    def close(self):
        """Close DB connection"""
        self.cursor.close()
        self.conn.close()
