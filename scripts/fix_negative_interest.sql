-- ============================================================================
-- Correction script for the recalculate_interest_only_balloon_schedule() bug
-- (interest_due recomputed below already-recorded interest_paid).
--
-- Run each section IN ORDER. Take a backup of microfinance.db before running
-- anything that writes (Sections 2+).
-- ============================================================================


-- ----------------------------------------------------------------------------
-- SECTION 1: Inspect exactly what you're about to change (read-only)
-- ----------------------------------------------------------------------------
SELECT rs.loan_id, l.loan_no, rs.installment_no, rs.due_date,
       rs.principal_due, rs.principal_paid,
       rs.interest_due, rs.interest_paid,
       rs.penalty_charged, rs.penalty_paid,
       rs.total_due, rs.status
FROM repayment_schedule rs
JOIN loans l ON l.id = rs.loan_id
WHERE rs.interest_due < rs.interest_paid
ORDER BY rs.loan_id, rs.installment_no;

-- Expected (from your screenshot): loan_id 140 (inst 1), 179 (inst 1),
-- 182 (inst 1), and 285 / RN-00031 (inst 1-4).


-- ----------------------------------------------------------------------------
-- SECTION 2: Find which of 140/179/182 was rolled into 285 (RN-00031)
-- ----------------------------------------------------------------------------
SELECT r.id AS rollover_id, r.original_loan_id, lo.loan_no AS original_loan_no,
       r.new_loan_id, ln.loan_no AS new_loan_no, r.rollover_date, r.status
FROM rollovers r
JOIN loans lo ON lo.id = r.original_loan_id
JOIN loans ln ON ln.id = r.new_loan_id
WHERE r.new_loan_id = 285;

-- Whichever of 140/179/182 shows up as original_loan_id here is the true
-- root cause loan for RN-00031. Fix THAT one in Section 3, then handle
-- RN-00031 itself via Section 4 (reverse + redo) rather than patching 285
-- directly - 285's numbers are a downstream symptom, not the source.


-- ----------------------------------------------------------------------------
-- SECTION 3: Correct the source loan's broken row(s)
-- Only run this for 140, 179, 182 (NOT for 285/RN-00031 - see Section 4).
--
-- Logic: the balance was genuinely paid down to (near) zero by a curtailment,
-- so the true remaining interest on that row is $0, not negative. Setting
-- interest_due = interest_paid makes "remaining" exactly 0 and lets the
-- row's status settle correctly based on principal too.
-- ----------------------------------------------------------------------------

-- Replace :LOAN_ID and :INSTALLMENT_NO with each broken row from Section 1,
-- one at a time (SQLite doesn't take named params in a plain script - swap
-- in literal values, e.g. loan_id = 140 AND installment_no = 1).

UPDATE repayment_schedule
SET interest_due = interest_paid,
    total_due    = round(principal_due + interest_paid, 2),
    status = CASE
        WHEN principal_paid >= principal_due - 0.01
         AND interest_paid  >= interest_paid - 0.01   -- always true now
         AND penalty_paid   >= penalty_charged - 0.01
        THEN 'Paid'
        ELSE 'PartiallyPaid'
    END
WHERE loan_id = 140 AND installment_no = 1;

UPDATE repayment_schedule
SET interest_due = interest_paid,
    total_due    = round(principal_due + interest_paid, 2),
    status = CASE
        WHEN principal_paid >= principal_due - 0.01
         AND interest_paid  >= interest_paid - 0.01
         AND penalty_paid   >= penalty_charged - 0.01
        THEN 'Paid'
        ELSE 'PartiallyPaid'
    END
WHERE loan_id = 179 AND installment_no = 1;

UPDATE repayment_schedule
SET interest_due = interest_paid,
    total_due    = round(principal_due + interest_paid, 2),
    status = CASE
        WHEN principal_paid >= principal_due - 0.01
         AND interest_paid  >= interest_paid - 0.01
         AND penalty_paid   >= penalty_charged - 0.01
        THEN 'Paid'
        ELSE 'PartiallyPaid'
    END
WHERE loan_id = 182 AND installment_no = 1;

-- After running these three, re-check each loan's overall status - a loan
-- that's now fully settled by this correction should move to 'Closed'.
-- Don't do this in raw SQL: call close_loan_if_settled(conn, loan_id) from
-- Python for 140, 179, and 182 instead, so it goes through the same
-- outstanding_balance() logic the rest of the app relies on:
--
--   from app.loans import close_loan_if_settled
--   for loan_id in (140, 179, 182):
--       close_loan_if_settled(conn, loan_id)


-- ----------------------------------------------------------------------------
-- SECTION 4: Fix RN-00031 (loan 285) itself
-- ----------------------------------------------------------------------------
-- Do NOT patch 285's rows directly with the same UPDATE as Section 3 - its
-- negative interest_rate is a downstream calculation error inherited from
-- the source loan at the moment of rollover, not a standalone bad row. Once
-- Section 3 has fixed the source loan:
--
--   1. Check whether 285 has any repayments yet:
--        SELECT * FROM repayments WHERE loan_id = 285;
--
--   2a. If NO repayments exist on 285 yet:
--       Call reverse_rollover(conn, rollover_id) using the rollover_id from
--       Section 2. This deletes loan 285 entirely and restores the source
--       loan to Active with its now-corrected numbers. Then redo the
--       rollover (request_rollover + approve_rollover) - it will now
--       compute a correct, positive effective_rate.
--
--   2b. If repayments already exist on 285:
--       Reversing is blocked (reverse_rollover raises if repayments exist
--       after the rollover date). You'll need to manually recompute what
--       the effective_rate SHOULD have been:
--
--         old_arrears_corrected = <source loan's corrected interest+penalty
--                                   remaining, from outstanding_balance()>
--         new_added_interest    = <original rollover_rate the loan officer
--                                   entered> * outstanding_principal / 100
--         total_new_loan_interest = old_arrears_corrected + new_added_interest
--         corrected_rate = total_new_loan_interest / outstanding_principal * 100
--
--       Then in Python:
--         update_loan(conn, 285, {"interest_rate": corrected_rate})
--         rebuild_schedule_and_reapply_repayments(conn, 285, {})
--
--       rebuild_schedule_and_reapply_repayments regenerates 285's schedule
--       with the corrected rate and correctly replays any repayments already
--       made against it.
