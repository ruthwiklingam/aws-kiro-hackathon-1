import React, { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import {
  PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid,
} from 'recharts';
import useStudents from '../hooks/useStudents';
import RiskBadge from '../components/RiskBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import styles from './Dashboard.module.css';

const PAGE_SIZE = 20;

const RISK_COLORS = {
  HIGH: '#dc2626',
  MEDIUM: '#d97706',
  LOW: '#16a34a',
};

function gpaRange(gpa) {
  if (gpa < 2.0) return '<2.0';
  if (gpa < 2.5) return '2.0–2.5';
  if (gpa < 3.0) return '2.5–3.0';
  return '3.0+';
}

export default function Dashboard() {
  const navigate = useNavigate();
  const { students, loading, error, refetch } = useStudents();
  const [riskFilter, setRiskFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(1);

  // Stats
  const stats = useMemo(() => ({
    total: students.length,
    high: students.filter(s => s.riskLevel === 'HIGH').length,
    medium: students.filter(s => s.riskLevel === 'MEDIUM').length,
    low: students.filter(s => s.riskLevel === 'LOW').length,
  }), [students]);

  // Chart data
  const pieData = useMemo(() => [
    { name: 'HIGH', value: stats.high },
    { name: 'MEDIUM', value: stats.medium },
    { name: 'LOW', value: stats.low },
  ].filter(d => d.value > 0), [stats]);

  const barData = useMemo(() => {
    const buckets = { '<2.0': 0, '2.0–2.5': 0, '2.5–3.0': 0, '3.0+': 0 };
    students.forEach(s => {
      const bucket = gpaRange(s.gpa ?? 0);
      buckets[bucket] = (buckets[bucket] || 0) + 1;
    });
    return Object.entries(buckets).map(([range, count]) => ({ range, count }));
  }, [students]);

  // Filtered & paginated
  const filtered = useMemo(() => {
    return students
      .filter(s => riskFilter === 'All' || s.riskLevel === riskFilter)
      .filter(s => {
        if (!search.trim()) return true;
        const q = search.toLowerCase();
        return (
          (s.name || '').toLowerCase().includes(q) ||
          (s.studentId || '').toLowerCase().includes(q)
        );
      });
  }, [students, riskFilter, search]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const pageItems = filtered.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE);

  function handleFilterChange(level) {
    setRiskFilter(level);
    setPage(1);
  }

  function handleSearch(e) {
    setSearch(e.target.value);
    setPage(1);
  }

  async function handleSignOut() {
    try {
      await signOut();
      navigate('/login');
    } catch (err) {
      console.error('Sign out error:', err);
    }
  }

  return (
    <div className={styles.page}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <span className={styles.logoText}>SRD</span>
          <h1 className={styles.pageTitle}>Student Risk Dashboard</h1>
        </div>
        <button onClick={handleSignOut} className={styles.signOutBtn}>Sign Out</button>
      </header>

      <main className={styles.main}>
        {loading && <LoadingSpinner message="Loading students…" />}

        {error && (
          <div className={styles.errorBanner} role="alert">
            <strong>Error:</strong> {error}
            <button onClick={refetch} className={styles.retryBtn}>Retry</button>
          </div>
        )}

        {!loading && !error && (
          <>
            {/* Stats bar */}
            <div className={styles.statsBar}>
              <div className={styles.statCard}>
                <span className={styles.statValue}>{stats.total}</span>
                <span className={styles.statLabel}>Total Students</span>
              </div>
              <div className={`${styles.statCard} ${styles.statHigh}`}>
                <span className={styles.statValue}>{stats.high}</span>
                <span className={styles.statLabel}>High Risk</span>
              </div>
              <div className={`${styles.statCard} ${styles.statMedium}`}>
                <span className={styles.statValue}>{stats.medium}</span>
                <span className={styles.statLabel}>Medium Risk</span>
              </div>
              <div className={`${styles.statCard} ${styles.statLow}`}>
                <span className={styles.statValue}>{stats.low}</span>
                <span className={styles.statLabel}>Low Risk</span>
              </div>
            </div>

            {/* Charts row */}
            <div className={styles.chartsRow}>
              <div className={styles.chartCard}>
                <h2 className={styles.chartTitle}>Risk Distribution</h2>
                <ResponsiveContainer width="100%" height={240}>
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      outerRadius={90}
                      dataKey="value"
                      label={({ name, percent }) =>
                        `${name} ${(percent * 100).toFixed(0)}%`
                      }
                    >
                      {pieData.map(entry => (
                        <Cell key={entry.name} fill={RISK_COLORS[entry.name]} />
                      ))}
                    </Pie>
                    <Tooltip />
                    <Legend />
                  </PieChart>
                </ResponsiveContainer>
              </div>

              <div className={styles.chartCard}>
                <h2 className={styles.chartTitle}>GPA Distribution</h2>
                <ResponsiveContainer width="100%" height={240}>
                  <BarChart data={barData} margin={{ top: 8, right: 16, left: -8, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis dataKey="range" tick={{ fontSize: 12 }} />
                    <YAxis tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip />
                    <Bar dataKey="count" fill="#1d4ed8" radius={[4, 4, 0, 0]} name="Students" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            {/* Filter / search bar */}
            <div className={styles.filterBar}>
              <div className={styles.riskFilters} role="group" aria-label="Filter by risk level">
                {['All', 'HIGH', 'MEDIUM', 'LOW'].map(level => (
                  <button
                    key={level}
                    onClick={() => handleFilterChange(level)}
                    className={`${styles.filterBtn} ${riskFilter === level ? styles.filterBtnActive : ''} ${level !== 'All' ? styles[`filter${level}`] : ''}`}
                    aria-pressed={riskFilter === level}
                  >
                    {level}
                  </button>
                ))}
              </div>
              <input
                type="search"
                className={styles.searchInput}
                placeholder="Search by name or ID…"
                value={search}
                onChange={handleSearch}
                aria-label="Search students"
              />
            </div>

            {/* Results count */}
            <div className={styles.resultsInfo}>
              Showing {pageItems.length} of {filtered.length} students
              {filtered.length !== students.length && ` (filtered from ${students.length})`}
            </div>

            {/* Student grid */}
            {pageItems.length === 0 ? (
              <div className={styles.emptyState}>No students match the current filters.</div>
            ) : (
              <div className={styles.studentsGrid}>
                {pageItems.map(student => (
                  <div key={student.studentId || student.id} className={styles.studentCard}>
                    <div className={styles.studentCardHeader}>
                      <span className={styles.studentName}>{student.name}</span>
                      <RiskBadge level={student.riskLevel} />
                    </div>
                    <div className={styles.studentMeta}>
                      <span className={styles.metaItem}>{student.major || '—'}</span>
                    </div>
                    <div className={styles.studentStats}>
                      <div className={styles.studentStat}>
                        <span className={styles.statItemLabel}>GPA</span>
                        <span className={styles.statItemValue}>
                          {student.gpa != null ? student.gpa.toFixed(2) : '—'}
                        </span>
                      </div>
                      <div className={styles.studentStat}>
                        <span className={styles.statItemLabel}>Attendance</span>
                        <span className={styles.statItemValue}>
                          {student.attendanceRate != null
                            ? `${(student.attendanceRate * 100).toFixed(0)}%`
                            : '—'}
                        </span>
                      </div>
                    </div>
                    {student.advisor && (
                      <div className={styles.advisorLine}>
                        Advisor: <strong>{student.advisor}</strong>
                      </div>
                    )}
                    <button
                      className={styles.viewBtn}
                      onClick={() => navigate(`/students/${student.studentId || student.id}`)}
                    >
                      View Detail →
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Pagination */}
            {totalPages > 1 && (
              <div className={styles.pagination} role="navigation" aria-label="Pagination">
                <button
                  className={styles.pageBtn}
                  onClick={() => setPage(p => Math.max(1, p - 1))}
                  disabled={safePage === 1}
                  aria-label="Previous page"
                >
                  ← Prev
                </button>
                <span className={styles.pageInfo}>
                  Page {safePage} of {totalPages}
                </span>
                <button
                  className={styles.pageBtn}
                  onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                  disabled={safePage === totalPages}
                  aria-label="Next page"
                >
                  Next →
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
