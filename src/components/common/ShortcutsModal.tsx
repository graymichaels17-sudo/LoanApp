import React from 'react';
import { Modal } from './Modal';

interface ShortcutsModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const ShortcutsModal: React.FC<ShortcutsModalProps> = ({ isOpen, onClose }) => {
  const SHORTCUTS = [
    { key: 'Ctrl + K / ⌘K', desc: 'Open Command Palette & Global Search' },
    { key: 'Alt + 1', desc: 'Jump to Portfolio Dashboard' },
    { key: 'Alt + 2', desc: 'Jump to Client Registry' },
    { key: 'Alt + 3', desc: 'Jump to Loans & Disbursals' },
    { key: 'Alt + 4', desc: 'Jump to Loan Rollovers' },
    { key: 'Alt + 5', desc: 'Jump to Bad Debts & Recovery' },
    { key: 'Alt + 6', desc: 'Jump to Portfolio Reports & Aging' },
    { key: 'Alt + 7', desc: 'Jump to Double-Entry General Ledger' },
    { key: 'Alt + 8', desc: 'Jump to Statutory Payroll' },
    { key: 'Alt + 9', desc: 'Jump to System Settings & Backups' },
    { key: 'Alt + 0', desc: 'Jump to SQLite Database Studio' },
    { key: '?', desc: 'Show this keyboard shortcuts guide' },
    { key: 'Esc', desc: 'Close any active modal or command palette' },
  ];

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="Keyboard Accelerators & Shortcuts" maxWidth="md">
      <div className="space-y-4">
        <p className="text-xs text-slate-500 dark:text-slate-400">
          Work faster with desktop-style keyboard shortcuts designed for high-speed loan officers and cashiers.
        </p>

        <div className="divide-y divide-slate-100 dark:divide-slate-800">
          {SHORTCUTS.map((s) => (
            <div key={s.key} className="py-2.5 flex items-center justify-between text-xs">
              <span className="text-slate-700 dark:text-slate-200 font-medium">{s.desc}</span>
              <kbd className="font-mono text-[11px] font-semibold bg-slate-100 dark:bg-slate-800 text-slate-800 dark:text-slate-200 px-2 py-0.5 rounded-md border border-slate-200 dark:border-slate-700 shadow-2xs">
                {s.key}
              </kbd>
            </div>
          ))}
        </div>

        <div className="pt-2 text-center">
          <button
            onClick={onClose}
            className="w-full py-2 bg-slate-100 hover:bg-slate-200 dark:bg-slate-800 dark:hover:bg-slate-700 text-slate-800 dark:text-slate-200 rounded-xl text-xs font-semibold transition-colors"
          >
            Got it
          </button>
        </div>
      </div>
    </Modal>
  );
};
