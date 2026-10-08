import { useState, useEffect } from 'react';
import axios from 'axios';
import { fetchAuthSession } from 'aws-amplify/auth';

const API_BASE = process.env.REACT_APP_API_URL;

/**
 * useStudent — fetch a single student by ID.
 * Returns { student, loading, error }
 */
export default function useStudent(studentId) {
  const [student, setStudent] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    if (!studentId) return;

    let cancelled = false;

    async function fetchStudent() {
      setLoading(true);
      setError(null);
      try {
        const session = await fetchAuthSession();
        const token = session.tokens?.idToken?.toString();

        const { data } = await axios.get(`${API_BASE}/students/${studentId}`, {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        });

        if (!cancelled) {
          setStudent(data.student || data);
        }
      } catch (err) {
        console.error(`Failed to fetch student ${studentId}:`, err);
        if (!cancelled) {
          setError(err.response?.data?.message || err.message || 'Failed to load student');
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }

    fetchStudent();
    return () => { cancelled = true; };
  }, [studentId]);

  return { student, loading, error };
}
