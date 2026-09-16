export const CURRENCY_SYMBOL = '$';

export function roundMoney(val: number): number {
  return Math.round((val + Number.EPSILON) * 100) / 100;
}

export function formatMoney(amount: number | null | undefined, showSymbol: boolean = true): string {
  if (amount === null || amount === undefined || isNaN(amount)) {
    return showSymbol ? `${CURRENCY_SYMBOL}0.00` : '0.00';
  }
  const rounded = roundMoney(amount);
  const formatted = new Intl.NumberFormat('en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Math.abs(rounded));

  const sign = rounded < 0 ? '-' : '';
  return showSymbol ? `${sign}${CURRENCY_SYMBOL}${formatted}` : `${sign}${formatted}`;
}

export function parseMoney(val: string | number | null | undefined): number {
  if (val === null || val === undefined) return 0;
  if (typeof val === 'number') return isNaN(val) ? 0 : roundMoney(val);
  const cleaned = val.toString().replace(/[^0-9.-]+/g, '');
  const num = parseFloat(cleaned);
  return isNaN(num) ? 0 : roundMoney(num);
}
