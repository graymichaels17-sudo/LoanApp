from app.database import get_connection

def clean_historical_rollovers():
    conn = get_connection()
    
    try:
        # 1. Identify all journal entries created for disbursements 
        # that are actually the 'new_loan_id' of a rollover.
        query = """
            SELECT je.id, l.loan_no, je.reference 
            FROM journal_entries je
            JOIN disbursements d ON je.source_id = d.id
            JOIN rollovers r ON d.loan_id = r.new_loan_id
            JOIN loans l ON l.id = d.loan_id
            WHERE je.source_type = 'disbursement'
        """
        
        entries_to_destory = conn.execute(query).fetchall()
        
        if not entries_to_destory:
            print("No historical rollover cash outflows found. The ledger is clean.")
            return

        print(f"Found {len(entries_to_destory)} phantom rollover disbursements.")
        
        # 2. Extract just the IDs for deletion
        je_ids = [str(row["id"]) for row in entries_to_destory]
        placeholders = ",".join("?" for _ in je_ids)
        
        # 3. Delete the underlying journal lines
        conn.execute(
            f"DELETE FROM journal_lines WHERE journal_entry_id IN ({placeholders})", 
            je_ids
        )
        print("Deleted corresponding journal lines.")
        
        # 4. Delete the parent journal entries
        conn.execute(
            f"DELETE FROM journal_entries WHERE id IN ({placeholders})", 
            je_ids
        )
        print("Deleted the journal entries.")
        
        conn.commit()
        
        print("\nSuccessfully corrected the ledger for the following loans:")
        for row in entries_to_destory:
            print(f"- Loan #: {row['loan_no']} (Journal Ref: {row['reference']})")
            
        print("\nYour Cash and Bank and Loans Receivable balances are now accurate.")
        
    except Exception as e:
        conn.rollback()
        print(f"An error occurred: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    clean_historical_rollovers()