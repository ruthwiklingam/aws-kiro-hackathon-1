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

const STATUS_CONFIG = {
  'Pending': { index: 0, color: '#64748b', bg: '#f1f5f9', border: '#cbd5e1', next: 'Assigned to Advisor', nextAction: 'Assign Advisor' },
  'Assigned to Advisor': { index: 1, color: '#2563eb', bg: '#eff6ff', border: '#bfdbfe', next: 'Outreach Sent', nextAction: 'Log Outreach Sent' },
  'Outreach Sent': { index: 2, color: '#7c3aed', bg: '#f5f3ff', border: '#ddd6fe', next: 'Meeting Completed', nextAction: 'Mark Meeting Completed' },
  'Meeting Completed': { index: 3, color: '#d97706', bg: '#fffbeb', border: '#fde68a', next: 'Resolved / Improved', nextAction: 'Mark Resolved' },
  'Resolved / Improved': { index: 4, color: '#16a34a', bg: '#f0fdf4', border: '#bbf7d0', next: null, nextAction: 'Reopen Intervention' },
};

const STAGES = [
  'Pending',
  'Assigned to Advisor',
  'Outreach Sent',
  'Meeting Completed',
  'Resolved / Improved',
];

export default function StudentDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { student, loading, error, mutate } = useStudent(id);
  const [recommending, setRecommending] = useState(false);
  const [recommendations, setRecommendations] = useState(null);
  const [recommendError, setRecommendError] = useState('');
  const [updatingId, setUpdatingId] = useState(null);
  const [activeNoteModal, setActiveNoteModal] = useState(null); // recId
  const [noteText, setNoteText] = useState('');
  const [advisorName, setAdvisorName] = useState('');
  const [emailModalRec, setEmailModalRec] = useState(null);

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

      const recs = data.recommendations || data;
      setRecommendations(recs);
      if (mutate) mutate();
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

  async function handleUpdateInterventionStatus(recId, nextStatus, newNote = null) {
    setUpdatingId(recId);
    setRecommendError('');
    try {
      const session = await fetchAuthSession();
      const token = session.tokens?.idToken?.toString();

      const payload = {
        interventionId: recId,
        status: nextStatus,
        assignedTo: advisorName || student?.advisor || 'Academic Advisor',
      };
      if (newNote) {
        payload.note = newNote;
      }

      const { data } = await axios.patch(
        `${API_BASE}/students/${id}/recommend`,
        payload,
        {
          headers: {
            Authorization: `Bearer ${token}`,
            'Content-Type': 'application/json',
          },
        }
      );

      const updatedRecs = data.recommendations || data;
      setRecommendations(updatedRecs);
      setActiveNoteModal(null);
      setNoteText('');
      if (mutate) mutate();
    } catch (err) {
      console.error('Update intervention error:', err);
      setRecommendError('Failed to update intervention status. Please try again.');
    } finally {
      setUpdatingId(null);
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

  // Normalize recommendations to ensure every object has lifecycle fields
  const rawRecs = recommendations ?? student?.recommendations ?? null;
  const displayRecs = rawRecs
    ? rawRecs.map((rec, i) => ({
        ...rec,
        id: rec.id || `rec-${i}`,
        status: rec.status && STATUS_CONFIG[rec.status] ? rec.status : 'Pending',
        notes: rec.notes || [],
        history: rec.history || [],
      }))
    : null;

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
                  <div className={styles.advisorLine}>Assigned Advisor: <strong>{student.advisor}</strong></div>
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

              {/* Recommendations & Intervention Case Management */}
              <div className={styles.recsCard}>
                <div className={styles.recsHeader}>
                  <div>
                    <h2 className={styles.sectionTitle}>Targeted Interventions & Tracking</h2>
                    <span className={styles.recsSubtitle}>
                      Track execution lifecycle: Pending ➔ Assigned ➔ Outreach ➔ Meeting ➔ Resolved
                    </span>
                  </div>
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
                      '⚡ Generate / Refresh AI Interventions'
                    )}
                  </button>
                </div>

                {recommendError && (
                  <div className={styles.recError} role="alert">{recommendError}</div>
                )}

                {recommending && (
                  <div className={styles.recGenerating}>
                    Asking Amazon Bedrock for tailored academic interventions…
                  </div>
                )}

                {!recommending && displayRecs && displayRecs.length > 0 && (
                  <div className={styles.recList}>
                    {displayRecs.map((rec, i) => {
                      const urgencyStyle = URGENCY_COLORS[rec.urgency?.toUpperCase()] || URGENCY_COLORS.LOW;
                      const currentStatus = rec.status || 'Pending';
                      const statusInfo = STATUS_CONFIG[currentStatus] || STATUS_CONFIG.Pending;
                      const currentIdx = statusInfo.index;
                      const isUpdating = updatingId === rec.id;

                      return (
                        <div key={rec.id || i} className={styles.recCard}>
                          {/* Top Header */}
                          <div className={styles.recCardHeader}>
                            <div className={styles.recTitleGroup}>
                              <span className={styles.recTitle}>{rec.title}</span>
                              {rec.assignedTo && (
                                <span className={styles.assignedBadge}>
                                  👤 {rec.assignedTo}
                                </span>
                              )}
                            </div>
                            <div className={styles.recBadges}>
                              <span
                                className={styles.statusBadge}
                                style={{
                                  background: statusInfo.bg,
                                  color: statusInfo.color,
                                  borderColor: statusInfo.border,
                                }}
                              >
                                ● {currentStatus}
                              </span>
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

                          {/* Description */}
                          {rec.description && (
                            <p className={styles.recDescription}>{rec.description}</p>
                          )}

                          {/* Interactive Execution Stepper */}
                          <div className={styles.stepperContainer}>
                            <div className={styles.stepperTrack}>
                              {STAGES.map((stg, sIdx) => {
                                const isCompleted = sIdx < currentIdx;
                                const isCurrent = sIdx === currentIdx;
                                return (
                                  <div
                                    key={stg}
                                    className={`${styles.stepNode} ${isCompleted ? styles.stepCompleted : ''} ${isCurrent ? styles.stepCurrent : ''}`}
                                    onClick={() => !isUpdating && handleUpdateInterventionStatus(rec.id, stg)}
                                    title={`Click to switch status to ${stg}`}
                                  >
                                    <div className={styles.stepCircle}>
                                      {isCompleted ? '✓' : sIdx + 1}
                                    </div>
                                    <span className={styles.stepLabel}>{stg}</span>
                                  </div>
                                );
                              })}
                            </div>
                          </div>

                          {/* Action Toolbar */}
                          <div className={styles.recActionsRow}>
                            <div className={styles.actionButtonsLeft}>
                              {statusInfo.next && (
                                <button
                                  className={styles.advanceBtn}
                                  disabled={isUpdating}
                                  onClick={() => handleUpdateInterventionStatus(rec.id, statusInfo.next)}
                                >
                                  {isUpdating ? 'Updating…' : `→ ${statusInfo.nextAction}`}
                                </button>
                              )}
                              {currentStatus === 'Resolved / Improved' && (
                                <button
                                  className={styles.reopenBtn}
                                  disabled={isUpdating}
                                  onClick={() => handleUpdateInterventionStatus(rec.id, 'Assigned to Advisor')}
                                >
                                  ↺ Reopen
                                </button>
                              )}
                              <button
                                className={styles.draftEmailBtn}
                                onClick={() => setEmailModalRec(rec)}
                              >
                                ✉️ Draft Outreach Email
                              </button>
                              <button
                                className={styles.addNoteBtn}
                                onClick={() => {
                                  setActiveNoteModal(activeNoteModal === rec.id ? null : rec.id);
                                  setNoteText('');
                                }}
                              >
                                📝 {activeNoteModal === rec.id ? 'Close Notes' : 'Add Note / Log'}
                              </button>
                            </div>
                          </div>

                          {/* Inline Note & History Box */}
                          {activeNoteModal === rec.id && (
                            <div className={styles.noteInputBox}>
                              <h4 className={styles.noteBoxTitle}>Log Advisor Action or Meeting Note</h4>
                              <textarea
                                value={noteText}
                                onChange={(e) => setNoteText(e.target.value)}
                                placeholder="Enter details: meeting notes, student response, tutoring session scheduled, etc."
                                className={styles.noteTextarea}
                                rows={3}
                              />
                              <div className={styles.noteBoxActions}>
                                <button
                                  className={styles.saveNoteBtn}
                                  disabled={!noteText.trim() || isUpdating}
                                  onClick={() => handleUpdateInterventionStatus(rec.id, currentStatus, noteText.trim())}
                                >
                                  {isUpdating ? 'Saving…' : 'Save Note to Student Record'}
                                </button>
                              </div>
                            </div>
                          )}

                          {/* Notes and Audit History list */}
                          {rec.notes && rec.notes.length > 0 && (
                            <div className={styles.notesHistoryList}>
                              <span className={styles.notesSectionLabel}>Advisor Case Notes:</span>
                              {rec.notes.map((n, nIdx) => (
                                <div key={n.id || nIdx} className={styles.noteItem}>
                                  <div className={styles.noteHeader}>
                                    <strong>{n.author || 'Advisor'}</strong>
                                    <span className={styles.noteTime}>
                                      {new Date(n.timestamp).toLocaleDateString()} {new Date(n.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                                    </span>
                                  </div>
                                  <p className={styles.noteBody}>{n.text}</p>
                                </div>
                              ))}
                            </div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                )}

                {!recommending && (!displayRecs || displayRecs.length === 0) && !recommendError && (
                  <div className={styles.noRecs}>
                    No interventions active. Click "Generate / Refresh AI Interventions" to generate personalized, trackable retention recommendations.
                  </div>
                )}
              </div>
            </div>

            {/* Email Draft Modal */}
            {emailModalRec && (
              <div className={styles.modalBackdrop} onClick={() => setEmailModalRec(null)}>
                <div className={styles.modalCard} onClick={(e) => e.stopPropagation()}>
                  <div className={styles.modalHeader}>
                    <h3 className={styles.modalTitle}>✉️ Student Outreach Email Draft</h3>
                    <button className={styles.modalCloseBtn} onClick={() => setEmailModalRec(null)}>✕</button>
                  </div>
                  <div className={styles.modalBody}>
                    <label className={styles.modalLabel}>Recipient</label>
                    <input
                      type="text"
                      readOnly
                      className={styles.modalInput}
                      value={`${student.studentId}@university.edu`}
                    />
                    <label className={styles.modalLabel}>Subject</label>
                    <input
                      type="text"
                      readOnly
                      className={styles.modalInput}
                      value={`Support & Advising Check-in: ${emailModalRec.title}`}
                    />
                    <label className={styles.modalLabel}>Email Content</label>
                    <textarea
                      readOnly
                      rows={7}
                      className={styles.modalTextarea}
                      value={`Dear Student,\n\nI am reaching out regarding your academic progress in the ${student.major || 'department'} program. Based on your recent coursework, we would like to collaborate on the following action step:\n\n• ${emailModalRec.title}: ${emailModalRec.description}\n\nPlease reply to this email or drop by during advisor office hours so we can set you up for success this semester.\n\nWarm regards,\n${student.advisor || 'Academic Advising Team'}`}
                    />
                  </div>
                  <div className={styles.modalFooter}>
                    <a
                      href={`mailto:${student.studentId}@university.edu?subject=${encodeURIComponent(`Support & Advising Check-in: ${emailModalRec.title}`)}&body=${encodeURIComponent(`Dear Student,\n\nI am reaching out regarding your academic progress in the ${student.major || 'department'} program. Based on your recent coursework, we would like to collaborate on the following action step:\n\n• ${emailModalRec.title}: ${emailModalRec.description}\n\nPlease reply to this email or drop by during advisor office hours so we can set you up for success this semester.\n\nWarm regards,\n${student.advisor || 'Academic Advising Team'}`)}`}
                      className={styles.sendEmailBtn}
                      onClick={() => {
                        handleUpdateInterventionStatus(emailModalRec.id, 'Outreach Sent', 'Outreach email drafted and launched to student email client.');
                        setEmailModalRec(null);
                      }}
                    >
                      🚀 Open in Email Client & Mark "Outreach Sent"
                    </a>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
