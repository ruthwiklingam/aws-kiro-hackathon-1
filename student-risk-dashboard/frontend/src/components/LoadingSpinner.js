import React from 'react';
import styles from './LoadingSpinner.module.css';

/**
 * LoadingSpinner — centered CSS spinner.
 * @param {string} message  - optional label below the spinner
 * @param {boolean} inline  - when true, renders inline (no full-page centering)
 */
export default function LoadingSpinner({ message, inline = false }) {
  return (
    <div className={inline ? styles.inline : styles.overlay} role="status" aria-live="polite">
      <div className={styles.spinner} />
      {message && <p className={styles.message}>{message}</p>}
    </div>
  );
}
