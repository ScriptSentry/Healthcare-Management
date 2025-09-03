# blockchain.py
import hashlib
from datetime import datetime

class Blockchain:
    def __init__(self):
        self.chain = []

    def add_block(self, data_hash):
        index = len(self.chain) + 1
        previous_hash = self.chain[-1]['block_hash'] if self.chain else "0"
        block_hash = hashlib.sha256((str(index) + previous_hash + data_hash).encode()).hexdigest()
        block = {
            'index': index,
            'previous_hash': previous_hash,
            'data_hash': data_hash,
            'block_hash': block_hash,
            'created_at': datetime.now()
        }
        self.chain.append(block)
        return block

    def verify(self, data_hash):
        for block in self.chain:
            if block['data_hash'] == data_hash:
                return True
        return False
