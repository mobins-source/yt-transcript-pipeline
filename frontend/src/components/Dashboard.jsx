/**
 * Dashboard.jsx — In-app pipeline status overview.
 *
 * Shows live stats computed from index.json (already loaded in useTranscripts).
 * Accessible via the "📊" button in the header.
 */

export default function Dashboard({ videos, onSelectVideo, onClose }) {
  if (!videos || videos.length === 0) return null;

  // ── Compute stats ─────────────────────────────────────────────────────────

  const total = videos.length;

  // SRT status
  const srtApproved  = videos.filter(v => v.srt_status === "approved").length;
  const srtPending   = videos.filter(v => v.srt_status === "pending").length;
  const srtNeedsFix  = videos.filter(v => v.srt_status === "needs_fix").length;
  const noSrt        = videos.filter(v => !v.has_clean_srt).length;
  const withSrt      = total - noSrt;

  // Enrichment
  const enriched     = videos.filter(v => v.time_of_day).length;
  const notEnriched  = total - enriched;

  // Transcript availability
  const txAvailable  = videos.filter(v => v.has_transcript && v.duration_seconds > 5).length;
  const txUnavailable = videos.filter(v => !v.has_transcript || v.duration_seconds <= 5).length;

  // Content type breakdown (enriched only)
  const byType = {};
  videos.filter(v => v.content_type).forEach(v => {
    byType[v.content_type] = (byType[v.content_type] || 0) + 1;
  });

  // Hadith book breakdown
  const byBook = {};
  videos.filter(v => v.hadith_book).forEach(v => {
    byBook[v.hadith_book] = (byBook[v.hadith_book] || 0) + 1;
  });

  // Prayer time breakdown
  const byTime = { Fajr: 0, Zuhr: 0, Isha: 0 };
  videos.filter(v => v.time_of_day).forEach(v => {
    byTime[v.time_of_day] = (byTime[v.time_of_day] || 0) + 1;
  });

  // Catchy title coverage (June 2026)
  const withCatchyTitle    = videos.filter(v => v.catchy_title).length;
  const enrichedNoCatchy   = videos.filter(v => v.time_of_day && !v.catchy_title).length;

  // Videos needing attention
  const needsAttention = videos.filter(v =>
    v.has_transcript && v.duration_seconds > 5 && !v.has_clean_srt
  );
  const permanentFails = videos.filter(v =>
    !v.has_transcript || v.duration_seconds <= 5
  );

  // ── Helpers ───────────────────────────────────────────────────────────────

  function pct(n, d) {
    return d === 0 ? 0 : Math.round((n / d) * 100);
  }

  function titleFor(v) {
    return v.catchy_title || v.suggested_title || v.title;
  }

  const TYPE_COLORS = {
    Hadith:       "#5cc8a0",
    Quran:        "#4ea8de",
    Mixed:        "#94a3b8",
    General:      "#a78bfa",
    Announcement: "#f59e0b",
  };

  return (
    <div className="dashboard-overlay" onClick={onClose}>
      <div className="dashboard-panel" onClick={e => e.stopPropagation()}>

        {/* ── Header ── */}
        <div className="dash-header">
          <span className="dash-title">Pipeline Dashboard</span>
          <div className="dash-header-right">
            <span className="dash-subtitle">{total} videos · MCC Tucson</span>
            <button className="dash-close" onClick={onClose}>×</button>
          </div>
        </div>

        <div className="dash-body">

          {/* ── Top stat cards ── */}
          <div className="dash-stat-row">
            <StatCard label="Total videos"  value={total}        color="var(--text)" />
            <StatCard label="Transcripts"   value={txAvailable}  color="var(--green)" />
            <StatCard label="Clean SRTs"    value={withSrt}      color="var(--accent2)" />
            <StatCard label="SRT approved"  value={srtApproved}  color="var(--green)" />
            <StatCard label="SRT pending"   value={srtPending}   color="var(--orange)" />
            <StatCard label="Needs fix"     value={srtNeedsFix}  color="var(--red)" />
            <StatCard label="Not enriched"  value={notEnriched}  color="var(--muted)" />
          </div>

          {/* ── SRT review progress ── */}
          <Section title="SRT Review Progress">
            <div className="dash-progress-labels">
              <span style={{ color: "var(--green)" }}>✓ Approved {srtApproved}</span>
              <span style={{ color: "var(--orange)" }}>◌ Pending {srtPending}</span>
              <span style={{ color: "var(--red)" }}>✗ Needs fix {srtNeedsFix}</span>
              <span style={{ color: "var(--muted)" }}>— No SRT {noSrt}</span>
            </div>
            <div className="dash-progress-bar">
              <div className="dash-progress-seg" style={{ width: `${pct(srtApproved, total)}%`, background: "var(--green)" }} title={`Approved: ${srtApproved}`} />
              <div className="dash-progress-seg" style={{ width: `${pct(srtPending, total)}%`, background: "var(--orange)" }} title={`Pending: ${srtPending}`} />
              <div className="dash-progress-seg" style={{ width: `${pct(srtNeedsFix, total)}%`, background: "var(--red)" }} title={`Needs fix: ${srtNeedsFix}`} />
              <div className="dash-progress-seg" style={{ width: `${pct(noSrt, total)}%`, background: "var(--border)" }} title={`No SRT: ${noSrt}`} />
            </div>
            <div className="dash-progress-pct">
              {pct(srtApproved, withSrt || 1)}% of generated SRTs approved
            </div>
          </Section>

          {/* ── Catchy title coverage ── */}
          {enriched > 0 && (
            <Section title="Catchy Title Coverage">
              <div className="dash-progress-labels">
                <span style={{ color: "var(--green)" }}>✓ Have one {withCatchyTitle}</span>
                <span style={{ color: "var(--orange)" }}>◌ Missing {enrichedNoCatchy}</span>
              </div>
              <div className="dash-progress-bar">
                <div className="dash-progress-seg" style={{ width: `${pct(withCatchyTitle, enriched)}%`, background: "var(--green)" }} title={`Have catchy_title: ${withCatchyTitle}`} />
                <div className="dash-progress-seg" style={{ width: `${pct(enrichedNoCatchy, enriched)}%`, background: "var(--border)" }} title={`Missing: ${enrichedNoCatchy}`} />
              </div>
              {enrichedNoCatchy > 0 && (
                <div className="dash-run-hint">
                  Run <code>python3 generate_catchy_titles.py</code> to backfill the remaining {enrichedNoCatchy}
                </div>
              )}
            </Section>
          )}

          <div className="dash-two-col">

            {/* ── Content type breakdown ── */}
            <Section title="Content Type">
              {Object.entries(byType).sort((a, b) => b[1] - a[1]).map(([type, count]) => (
                <BarRow key={type} label={type} count={count} total={enriched}
                  color={TYPE_COLORS[type] || "var(--muted)"} />
              ))}
            </Section>

            {/* ── Prayer time breakdown ── */}
            <Section title="Prayer Time">
              {Object.entries(byTime).map(([time, count]) => (
                <BarRow key={time} label={time} count={count} total={enriched}
                  color={time === "Fajr" ? "#7dd3fc" : time === "Zuhr" ? "#fde68a" : "#c4b5fd"} />
              ))}
            </Section>
          </div>

          {/* ── Hadith book breakdown ── */}
          <Section title="Hadith Books">
            <div className="dash-book-grid">
              {Object.entries(byBook).sort((a, b) => b[1] - a[1]).map(([book, count]) => (
                <div key={book} className="dash-book-pill">
                  <span className="dash-book-name">{book}</span>
                  <span className="dash-book-count">{count}</span>
                </div>
              ))}
            </div>
          </Section>

          {/* ── Videos needing attention ── */}
          {needsAttention.length > 0 && (
            <Section title={`Needs Attention — ${needsAttention.length} videos (transcript available but no SRT)`}>
              <div className="dash-attention-list">
                {needsAttention.map(v => (
                  <div key={v.video_id} className="dash-attention-row"
                    onClick={() => { onSelectVideo(v); onClose(); }}>
                    <span className="dash-attention-date">{v.post_date || v.upload_date?.slice(0,4)+'-'+v.upload_date?.slice(4,6)+'-'+v.upload_date?.slice(6,8) || "—"}</span>
                    <span className="dash-attention-title">{titleFor(v)}</span>
                    <span className="dash-attention-badge needs-srt">no SRT</span>
                  </div>
                ))}
              </div>
              <div className="dash-run-hint">
                Run <code>python3 run.py --captions-only</code> to generate SRTs
              </div>
            </Section>
          )}

          {/* ── Permanent failures ── */}
          {permanentFails.length > 0 && (
            <Section title={`Permanent — ${permanentFails.length} videos (no transcript)`}>
              <div className="dash-attention-list">
                {permanentFails.map(v => (
                  <div key={v.video_id} className="dash-attention-row">
                    <span className="dash-attention-date">{v.post_date || "—"}</span>
                    <span className="dash-attention-title" style={{ color: "var(--muted)" }}>
                      {v.video_id}
                    </span>
                    <span className="dash-attention-badge perm-fail">
                      {v.duration_seconds <= 5 ? "disabled" : "no transcript"}
                    </span>
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* ── SRT pending list ── */}
          <Section title={`SRT Pending Review — ${srtPending} videos`}>
            <div className="dash-attention-list">
              {videos.filter(v => v.srt_status === "pending").map(v => (
                <div key={v.video_id} className="dash-attention-row"
                  onClick={() => { onSelectVideo(v); onClose(); }}>
                  <span className="dash-attention-date">{v.post_date || "—"}</span>
                  <span className="dash-attention-title">{titleFor(v)}</span>
                  <span className="dash-attention-badge srt-pending">pending</span>
                </div>
              ))}
            </div>
          </Section>

        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, color }) {
  return (
    <div className="dash-stat-card">
      <div className="dash-stat-value" style={{ color }}>{value}</div>
      <div className="dash-stat-label">{label}</div>
    </div>
  );
}

function Section({ title, children }) {
  return (
    <div className="dash-section">
      <div className="dash-section-title">{title}</div>
      {children}
    </div>
  );
}

function BarRow({ label, count, total, color }) {
  const width = total === 0 ? 0 : Math.round((count / total) * 100);
  return (
    <div className="dash-bar-row">
      <span className="dash-bar-label">{label}</span>
      <div className="dash-bar-track">
        <div className="dash-bar-fill" style={{ width: `${width}%`, background: color }} />
      </div>
      <span className="dash-bar-count">{count}</span>
    </div>
  );
}
