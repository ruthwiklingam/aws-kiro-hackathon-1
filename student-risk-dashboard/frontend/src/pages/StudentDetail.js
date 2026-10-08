import React, { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { signOut } from 'aws-amplify/auth';
import { fetchAuthSession } from 'aws-amplify/auth';
import axios from 'axios';
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis, PolarRadiusAxis,
  ResponsiveContainer, Tooltip,
} from 'recharts';
import useStudent from '../hooks/useStudent';
import RiskBadge from '../components/RiskBadge';
import LoadingSpinner from '../components/LoadingSpinner';
import styles from './StudentDetail.module.css';

const API_BASE = process.env.REACT_APP_API_URL;

const URGENCY_COLORS = {
  HIGH: { bg: '#fef2f2', color: '#dc2626', border: '#fca5a5' },
  MEDIUM: { bg: '#fffbeb', color: '#d97706', border: '#fcd34d' },
  LOW: { bg: '#f0fdf4', color: '#16a34a', border: '#86efac' },
};

export default function StudentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { student, loading, error } = useStudent(id);
  const [recommending, setRecommending] = useState(false);
  const [recommendations, setRecommendations] = useState(null);
  const [recommendError, setRecommendError] = useState('');

  // Build radar chart data from normalized student metrics
  function buildRadarData(s) {
    const normalize = (val, min, max) => {
      if (val == null) return 0;
      return Math.min(100, Math.max(0, Math.round(((Number(val) - min) / (max - min)) * 100)));
    };
    return [
      { metric: 'GPA',        value: normalize(s.currentGpa, 0, 4) },
      { metric: 'Attendance', value: normalize(s.attendancePct, 0, 100) },
      { metric: 'Advising',   value: normalize(s.advisingVisitCount, 0, 10) },
      { metric: 'LMS Activity', value: normalize(s.lmsActivityScore, 0, 100) },
    ];
  }

  async function handleGenerateRecommendations() {
    setRecommending(true);
    setRecommendError('');
    try {
      const session = await fetchAuthSession();
      const token = session.tokens?.idToken?.toString();

      const { data } = await axios.post(
        `${API_BASE}/students/${id}/recommend`,
        {},
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
          timeout: 60000, // Bedrock can take 5-10s
        }
      );

      setRecommendations(data.recommendations || data);
    } catch (err) {
      console.error('Generate recommendations error:', err);
      setRecommendError(
        err.response?.data?.message ||
        err.message ||
        'Failed to generate recommendations. Please try again.'
      );
    } finally {
      setRecommending(false);
    }
  }

  async function handleSignOut() {
    try {
      await signOut();
      navigate('/login');
    } catch (err) {
      console.error('Sign out error:', err);
    }
  }

  // Use recommendations from student record if not freshly generated
  const displayRecs = recommendations ?? student?.recommendations ?? null;

  return (
    <div className={styles.page}>
      {/* Header */}
      <header className={styles.header}>
        <div className={styles.headerLeft}>
          <button onClick={() => navigate('/')} className={styles.backBtn} aria-label="Back to dashboard">
            ← Dashboard
          </button>
          {student && (
            <div className={styles.studentHeaderInfo}>
              <span className={styles.studentName}>{student.studentId}</span>
              <span className={styles.studentId}>ID: {student.studentId || id}</span>
              <RiskBadge level={student.riskLevel} large />
            </div>
          )}
        </div>
        <button onClick={handleSignOut} className={styles.signOutBtn}>Sign Out</button>
      </header>

      <main className={styles.main}>
        {loading && <LoadingSpinner message="Loading student…" />}

        {error && (
          <div className={styles.errorBanner} role="alert">
            <strong>Error:</strong> {error}
          </div>
        )}

        {!loading && !error && student && (
          <>
            {/* Student subheader */}
            <div className={styles.subHeader}>
              <div>
                <div className={styles.majorLine}>{student.major || 'Undeclared'}</div>
                {student.advisor && (
                  <div className={styles.advisorLine}>Advisor: <strong>{student.advisor}</strong></div>
                )}
              </div>
            </div>

            {/* Financial aid warning */}
            {student.financialAidIssues && (
              <div className={styles.financialAidBanner} role="alert">
                ⚠️ <strong>Financial Aid Issue Flagged</strong> — This student has an active financial aid concern. Coordinate with the financial aid office.
              </div>
            )}

            {/* Stats grid */}
            <div className={styles.statsGrid}>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Current GPA</span>
                <span className={styles.statTileValue}>
                  {student.currentGpa != null ? Number(student.currentGpa).toFixed(2) : '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Previous GPA</span>
                <span className={styles.statTileValue}>
                  {student.previousGpa != null ? Number(student.previousGpa).toFixed(2) : '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Attendance %</span>
                <span className={styles.statTileValue}>
                  {student.attendancePct != null
                    ? `${Number(student.attendancePct).toFixed(0)}%`
                    : '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Missed Classes</span>
                <span className={`${styles.statTileValue} ${(student.missedClasses ?? 0) > 5 ? styles.valueRed : ''}`}>
                  {student.missedClasses ?? '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Missing Assignments</span>
                <span className={`${styles.statTileValue} ${(student.missingAssignments ?? 0) > 3 ? styles.valueRed : ''}`}>
                  {student.missingAssignments ?? '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>LMS Activity Score</span>
                <span className={styles.statTileValue}>
                  {student.lmsActivityScore != null ? Number(student.lmsActivityScore).toFixed(0) : '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Advising Visits</span>
                <span className={styles.statTileValue}>{student.advisingVisitCount ?? '—'}</span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Days Since Last Advising</span>
                <span className={`${styles.statTileValue} ${(student.daysSinceLastAdvising ?? 0) > 60 ? styles.valueAmber : ''}`}>
                  {student.daysSinceLastAdvising ?? '—'}
                </span>
              </div>
              <div className={styles.statTile}>
                <span className={styles.statTileLabel}>Retention Status</span>
                <span className={styles.statTileValue}>{student.retentionStatus ?? '—'}</span>
              </div>
            </div>

            {/* Radar chart + recommendations side by side */}
            <div className={styles.contentRow}>
              <div className={styles.radarCard}>
                <h2 className={styles.sectionTitle}>Risk Profile</h2>
                <ResponsiveContainer width="100%" height={280}>
                  <RadarChart data={buildRadarData(student)} margin={{ top: 10, right: 30, bottom: 10, left: 30 }}>
                    <PolarGrid stroke="#e2e8f0" />
                    <PolarAngleAxis dataKey="metric" tick={{ fontSize: 12, fill: '#475569' }} />
                    <PolarRadiusAxis angle={90} domain={[0, 100]} tick={{ fontSize: 10 }} tickCount={4} />
                    <Radar
                      name="Score"
                      dataKey="value"
                      stroke="#1d4ed8"
                      fill="#1d4ed8"
                      fillOpacity={0.2}
                      strokeWidth={2}
                    />
                    <Tooltip formatter={(v) => [`${v}%`, 'Score']} />
                  </RadarChart>
                </ResponsiveContainer>
              </div>

              {/* Recommendations */}
              <div className={styles.recsCard}>
                <div className={styles.recsHeader}>
                  <h2 className={styles.sectionTitle}>Recommendations</h2>
                  <button
                    onClick={handleGenerateRecommendations}
                    disabled={recommending}
                    className={styles.generateBtn}
                  >
                    {recommending ? (
                      <>
                        <LoadingSpinner inline />
                        Generating…
                      </>
                    ) : (
                      'Generate Recommendations'
                    )}
                  </button>
                </div>

                {recommendError && (
                  <div className={styles.recError} role="alert">{recommendError}</div>
                )}

                {recommending && (
                  <div className={styles.recGenerating}>
                    Asking Bedrock for personalized recommendations… this may take a few seconds.
                  </div>
                )}

                {!recommending && displayRecs && displayRecs.length > 0 && (
                  <div className={styles.recList}>
                    {displayRecs.map((rec, i) => {
                      const urgencyStyle = URGENCY_COLORS[rec.urgency] || URGENCY_COLORS.LOW;
                      return (
                        <div key={i} className={styles.recCard}>
                          <div className={styles.recCardHeader}>
                            <span className={styles.recTitle}>{rec.title}</span>
                            <div className={styles.recBadges}>
                              {rec.urgency && (
                                <span
                                  className={styles.urgencyBadge}
                                  style={{
                                    background: urgencyStyle.bg,
                                    color: urgencyStyle.color,
                                    border: `1px solid ${urgencyStyle.border}`,
                                  }}
                                >
                                  {rec.urgency}
                                </span>
                              )}
                              {rec.category && (
                                <span className={styles.categoryBadge}>{rec.category}</span>
                              )}
                            </div>
                          </div>
                          {rec.description && (
                            <p className={styles.recDescription}>{rec.description}</p>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {!recommending && (!displayRecs || displayRecs.length === 0) && !recommendError && (
                  <div className={styles.noRecs}>
                    No recommendations yet. Click "Generate Recommendations" to get AI-powered suggestions from Amazon Bedrock.
                  </div>
                )}
              </div>
            </div>
          </>
        )}
      </main>
    </div>
  );
}
