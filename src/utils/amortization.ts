import { InterestMethod, RatePeriod, RepaymentFrequency, RepaymentScheduleItem } from '../types';
import { roundMoney } from './money';

export function addPeriod(dateStr: string, frequency: RepaymentFrequency, n: number = 1): string {
  const d = new Date(dateStr);
  if (isNaN(d.getTime())) return dateStr;

  if (frequency === 'weekly') {
    d.setDate(d.getDate() + n * 7);
  } else if (frequency === 'biweekly') {
    d.setDate(d.getDate() + n * 14);
  } else {
    // monthly
    const targetMonth = d.getMonth() + n;
    d.setMonth(targetMonth);
  }
  return d.toISOString().split('T')[0];
}

export function nextDueDate(disbursementDate: string, frequency: RepaymentFrequency): string {
  return addPeriod(disbursementDate, frequency, 1);
}

export function calculateSchedule(
  principal: number,
  interestRate: number,
  interestMethod: InterestMethod,
  ratePeriod: RatePeriod,
  termPeriods: number,
  firstDueDate: string,
  frequency: RepaymentFrequency = 'monthly',
  loanId: number = 0
): RepaymentScheduleItem[] {
  const schedule: RepaymentScheduleItem[] = [];
  const safeTerm = Math.max(1, termPeriods || 1);

  if (interestMethod === 'flat') {
    let totalInterest = 0;
    if (ratePeriod === 'loan_term') {
      totalInterest = principal * (interestRate / 100.0);
    } else if (ratePeriod === 'year') {
      totalInterest = principal * (interestRate / 100.0) * (safeTerm / 12.0);
    } else {
      // per month flat
      totalInterest = principal * (interestRate / 100.0) * safeTerm;
    }

    const principalPerPeriod = roundMoney(principal / safeTerm);
    const interestPerPeriod = roundMoney(totalInterest / safeTerm);

    let runningPrincipal = 0;
    let runningInterest = 0;

    for (let i = 1; i <= safeTerm; i++) {
      const dueDate = addPeriod(firstDueDate, frequency, i - 1);
      let p = principalPerPeriod;
      let it = interestPerPeriod;

      if (i === safeTerm) {
        p = roundMoney(principal - runningPrincipal);
        it = roundMoney(totalInterest - runningInterest);
      }

      runningPrincipal = roundMoney(runningPrincipal + p);
      runningInterest = roundMoney(runningInterest + it);

      schedule.push({
        id: i,
        loanId,
        installmentNo: i,
        dueDate,
        principalDue: p,
        interestDue: it,
        totalDue: roundMoney(p + it),
        principalPaid: 0,
        interestPaid: 0,
        penaltyCharged: 0,
        penaltyPaid: 0,
        status: 'Pending',
      });
    }
  } else if (interestMethod === 'interest_only_balloon') {
    const rateDecimal = (interestRate / 100.0);
    const interestPerPeriod = roundMoney(principal * rateDecimal);

    for (let i = 1; i <= safeTerm; i++) {
      const dueDate = addPeriod(firstDueDate, frequency, i - 1);
      const isFinal = i === safeTerm;
      const p = isFinal ? principal : 0;
      const it = interestPerPeriod;

      schedule.push({
        id: i,
        loanId,
        installmentNo: i,
        dueDate,
        principalDue: p,
        interestDue: it,
        totalDue: roundMoney(p + it),
        principalPaid: 0,
        interestPaid: 0,
        penaltyCharged: 0,
        penaltyPaid: 0,
        status: 'Pending',
      });
    }
  } else if (interestMethod === 'reducing_balance') {
    const r = (interestRate / 100.0);
    const pmt = r === 0 
      ? principal / safeTerm 
      : (principal * (r * Math.pow(1 + r, safeTerm))) / (Math.pow(1 + r, safeTerm) - 1);
    
    let remainingPrincipal = principal;
    for (let i = 1; i <= safeTerm; i++) {
      const dueDate = addPeriod(firstDueDate, frequency, i - 1);
      const it = roundMoney(remainingPrincipal * r);
      let p = roundMoney(pmt - it);
      if (i === safeTerm || p > remainingPrincipal) {
        p = remainingPrincipal;
      }
      remainingPrincipal = roundMoney(Math.max(0, remainingPrincipal - p));

      schedule.push({
        id: i,
        loanId,
        installmentNo: i,
        dueDate,
        principalDue: p,
        interestDue: it,
        totalDue: roundMoney(p + it),
        principalPaid: 0,
        interestPaid: 0,
        penaltyCharged: 0,
        penaltyPaid: 0,
        status: 'Pending',
      });
    }
  } else {
    // default flat fallback
    return calculateSchedule(principal, interestRate, 'flat', ratePeriod, termPeriods, firstDueDate, frequency, loanId);
  }

  return schedule;
}

export interface AllocationResult {
  principalPaid: number;
  interestPaid: number;
  penaltyPaid: number;
  remainingAmount: number;
  updatedSchedule: RepaymentScheduleItem[];
}

export function allocateRepaymentWaterfall(
  schedule: RepaymentScheduleItem[],
  paymentAmount: number
): AllocationResult {
  let remaining = roundMoney(paymentAmount);
  let principalPaidTotal = 0;
  let interestPaidTotal = 0;
  let penaltyPaidTotal = 0;

  const newSchedule = schedule.map(item => ({ ...item }));

  for (const inst of newSchedule) {
    if (remaining <= 0) break;
    if (inst.status === 'Paid') continue;

    const penaltyOwed = roundMoney(inst.penaltyCharged - inst.penaltyPaid);
    const interestOwed = roundMoney(inst.interestDue - inst.interestPaid);
    const principalOwed = roundMoney(inst.principalDue - inst.principalPaid);

    // 1. Penalty
    const payPenalty = Math.min(remaining, Math.max(0, penaltyOwed));
    remaining = roundMoney(remaining - payPenalty);

    // 2. Interest
    const payInterest = remaining > 0 ? Math.min(remaining, Math.max(0, interestOwed)) : 0;
    remaining = roundMoney(remaining - payInterest);

    // 3. Principal
    const payPrincipal = remaining > 0 ? Math.min(remaining, Math.max(0, principalOwed)) : 0;
    remaining = roundMoney(remaining - payPrincipal);

    inst.penaltyPaid = roundMoney(inst.penaltyPaid + payPenalty);
    inst.interestPaid = roundMoney(inst.interestPaid + payInterest);
    inst.principalPaid = roundMoney(inst.principalPaid + payPrincipal);

    const fullyPaid =
      inst.principalPaid >= inst.principalDue &&
      inst.interestPaid >= inst.interestDue &&
      inst.penaltyPaid >= inst.penaltyCharged;

    inst.status = fullyPaid
      ? 'Paid'
      : (inst.penaltyPaid + inst.interestPaid + inst.principalPaid > 0 ? 'PartiallyPaid' : inst.status);

    principalPaidTotal = roundMoney(principalPaidTotal + payPrincipal);
    interestPaidTotal = roundMoney(interestPaidTotal + payInterest);
    penaltyPaidTotal = roundMoney(penaltyPaidTotal + payPenalty);
  }

  return {
    principalPaid: principalPaidTotal,
    interestPaid: interestPaidTotal,
    penaltyPaid: penaltyPaidTotal,
    remainingAmount: remaining,
    updatedSchedule: newSchedule,
  };
}
