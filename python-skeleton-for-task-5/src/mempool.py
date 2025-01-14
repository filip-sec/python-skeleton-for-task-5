import copy
import sqlite3

import constants as const
import objects

# get expanded object for 
def fetch_object(oid, cur):
    cur.execute("SELECT data FROM objects WHERE id=?", (oid,))
    row = cur.fetchone()
    if row:
        return objects.Object.deserialize(row[0])
    return None

# get utxo for block
def fetch_utxo(bid, cur):
    def fetch_utxo(bid, cur):
        cur.execute("SELECT utxo FROM utxos WHERE block_id=?", (bid,))
        row = cur.fetchone()
        if row:
            return objects.UTXO.deserialize(row[0])
        return None

# returns (blockid, intermediate_blocks)
def find_lca_and_intermediate_blocks(tip, blockids, cur):
    cur.execute("SELECT parent_id FROM blocks WHERE id=?", (tip,))
    parent_id = cur.fetchone()
    if not parent_id:
        return None, []

    parent_id = parent_id[0]
    intermediate_blocks = []

    while parent_id not in blockids:
        intermediate_blocks.append(parent_id)
        cur.execute("SELECT parent_id FROM blocks WHERE id=?", (parent_id,))
        parent_id = cur.fetchone()
        if not parent_id:
            return None, []

        parent_id = parent_id[0]

    return parent_id, intermediate_blocks

# return a list of transactions by index
def find_all_txs(txids):
    def find_all_txs(txids, cur):
        txs = []
        for txid in txids:
            cur.execute("SELECT data FROM transactions WHERE id=?", (txid,))
            row = cur.fetchone()
            if row:
                txs.append(objects.Transaction.deserialize(row[0]))
        return txs

# return a list of transactions in blocks
def get_all_txids_in_blocks(blocks):
    def get_all_txids_in_blocks(blocks, cur):
        txids = []
        for block in blocks:
            cur.execute("SELECT txid FROM block_transactions WHERE block_id=?", (block,))
            rows = cur.fetchall()
            txids.extend([row[0] for row in rows])
        return txids

# get (id of lca, list of old blocks from lca, list of new blocks from lca) 
def get_lca_and_intermediate_blocks(old_tip: str, new_tip: str):
    with sqlite3.connect(const.DB_PATH) as conn:
        cur = conn.cursor()
        old_lca, old_intermediate_blocks = find_lca_and_intermediate_blocks(old_tip, {old_tip}, cur)
        new_lca, new_intermediate_blocks = find_lca_and_intermediate_blocks(new_tip, {new_tip}, cur)

        if old_lca != new_lca:
            return None, [], []

        return old_lca, old_intermediate_blocks, new_intermediate_blocks

def rebase_mempool(old_tip, new_tip, mptxids):
    with sqlite3.connect(const.DB_PATH) as conn:
        cur = conn.cursor()

        # Get LCA and intermediate blocks
        lca, old_blocks, new_blocks = get_lca_and_intermediate_blocks(old_tip, new_tip)

        if lca is None:
            return []

        # Get all transaction IDs in old and new blocks
        old_txids = get_all_txids_in_blocks(old_blocks, cur)
        new_txids = get_all_txids_in_blocks(new_blocks, cur)

        # Find all transactions in the mempool
        mempool_txs = find_all_txs(mptxids, cur)

        # Remove transactions that are in the old blocks
        mempool_txs = [tx for tx in mempool_txs if tx.id not in old_txids]

        # Add transactions that are in the new blocks
        new_txs = find_all_txs(new_txids, cur)
        mempool_txs.extend(new_txs)

        return mempool_txs

class Mempool:
    def __init__(self, bbid: str, butxo: dict):
        self.base_block_id = bbid
        self.utxo = butxo
        self.txs = []

    def try_add_tx(self, tx: dict) -> bool:
        # Check if transaction inputs are in the UTXO set
        for txin in tx['inputs']:
            if txin['outpoint'] not in self.utxo:
             return False

        # Add transaction to the mempool
        self.txs.append(tx)

        # Update the UTXO set
        for txin in tx['inputs']:
            del self.utxo[txin['outpoint']]
        for idx, txout in enumerate(tx['outputs']):
            self.utxo[(tx['id'], idx)] = txout

        return True

    def rebase_to_block(self, bid: str):
        with sqlite3.connect(const.DB_PATH) as conn:
            cur = conn.cursor()

            # Get the UTXO for the new block
            new_utxo = fetch_utxo(bid, cur)
            if new_utxo is None:
                return False

            # Rebase the mempool to the new block
            self.base_block_id = bid
            self.utxo = new_utxo

            # Remove transactions that are no longer valid
            valid_txs = []
            for tx in self.txs:
                if all(txin['outpoint'] in self.utxo for txin in tx['inputs']):
                    valid_txs.append(tx)
                    for txin in tx['inputs']:
                        del self.utxo[txin['outpoint']]
                    for idx, txout in enumerate(tx['outputs']):
                        self.utxo[(tx['id'], idx)] = txout

            self.txs = valid_txs
            return True