import React from 'react';

const RISK_STYLES = {
  HIGH: {
    background: '#fef2f2',
    color: '#dc2626',
    border: '1px solid #fca5a5',
  },
  MEDIUM: {
    background: '#fffbeb',
    color: '#d97706',
    border: '1px solid #fcd34d',
  },
  LOW: {
    background: '#f0fdf4',
    color: '#16a34a',
    border: '1px solid #86efac',
  },
};

/**
 * RiskBadge — colored pill label for HIGH / MEDIUM / LOW risk levels.
 * @param {string} level  - 'HIGH' | 'MEDIUM' | 'LOW'
 * @param {boolean} large - render a larger badge (for detail page headers)
 */
export default function RiskBadge({ level, large = false }) {
  const style = RISK_STYLES[level] || RISK_STYLES.LOW;

  return (
    <span
      style={{
        display: 'inline-block',
        padding: large ? '6px 16px' : '3px 10px',
        borderRadius: 9999,
        fontSize: large ? '0.95rem' : '0.75rem',
        fontWeight: 700,
        letterSpacing: '0.04em',
        textTransform: 'uppercase',
        ...style,
      }}
      aria-label={`Risk level: ${level}`}
    >
      {level}
    </span>
  );
}
