import React from 'react';

interface BadgeProps {
  status: string;
  className?: string;
}

export const StatusBadge: React.FC<BadgeProps> = ({ status, className = '' }) => {
  let color = 'bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 border-slate-200 dark:border-slate-700';

  switch (status) {
    case 'Active':
    case 'Approved':
    case 'Paid':
    case 'Completed':
    case 'FullyRecovered':
      color = 'bg-emerald-50 dark:bg-emerald-950/70 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-800/80';
      break;
    case 'Pending':
    case 'Draft':
      color = 'bg-amber-50 dark:bg-amber-950/70 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-800/80';
      break;
    case 'PartiallyPaid':
    case 'PartiallyRecovered':
      color = 'bg-sky-50 dark:bg-sky-950/70 text-sky-700 dark:text-sky-300 border-sky-200 dark:border-sky-800/80';
      break;
    case 'Overdue':
    case 'Declined':
    case 'Rejected':
    case 'BadDebt':
    case 'WrittenOff':
    case 'Blacklisted':
      color = 'bg-rose-50 dark:bg-rose-950/70 text-rose-700 dark:text-rose-300 border-rose-200 dark:border-rose-800/80';
      break;
    case 'Closed':
    case 'RolledOver':
    case 'Inactive':
      color = 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-700';
      break;
  }

  return (
    <span
      className={`inline-flex items-center px-2.5 py-1 rounded-md text-xs font-semibold border ${color} ${className}`}
    >
      {status}
    </span>
  );
};

