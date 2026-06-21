const CONTENT_COLORS = {
  Quran:        "#4ea8de",
  Hadith:       "#5cc8a0",
  General:      "#a78bfa",
  Announcement: "#f59e0b",
  Mixed:        "#94a3b8",
};

const TIME_COLORS = {
  Fajr: "#7dd3fc",
  Zuhr: "#fde68a",
  Isha: "#c4b5fd",
};

function formatDuration(secs) {
  if (!secs) return "";
  const m = Math.floor(secs / 60);
  const s = secs % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function TranscriptBadge({ status, hasTranscript }) {
  if (status === "unavailable")
    return <span className="tx-badge retry">retry pending</span>;
  if (status === "available" || hasTranscript)
    return <span className="tx-badge has">transcript</span>;
  return <span className="tx-badge missing">no transcript</span>;
}

export default function VideoList({ videos, selectedId, onSelect, hasPendingOverride }) {
  if (videos.length === 0) {
    return (
      <div className="empty-state">
        <span className="empty-icon">◌</span>
        <p>No videos match your filters</p>
      </div>
    );
  }

  return (
    <ul className="video-list">
      {videos.map(v => (
        <li
          key={v.video_id}
          className={`video-item ${v.video_id === selectedId ? "active" : ""}`}
          onClick={() => onSelect(v)}
        >
          <div className="video-title">
            {v.catchy_title || v.suggested_title || v.title || v.video_id}
          </div>

          <div className="video-badges">
            {v.time_slot && <span className="badge badge-slot">{v.time_slot}</span>}
            {v.time_of_day && (
              <span className="badge" style={{ color: TIME_COLORS[v.time_of_day] || "#94a3b8", background: "rgba(255,255,255,0.05)" }}>
                {v.time_of_day}
              </span>
            )}
            {v.content_type && (
              <span className="badge" style={{ color: CONTENT_COLORS[v.content_type] || "#94a3b8", background: "rgba(255,255,255,0.05)" }}>
                {v.content_type}
              </span>
            )}
            {v.hadith_book && <span className="badge badge-book">{v.hadith_book}</span>}
            {hasPendingOverride?.(v.video_id) && <span className="badge badge-override">override pending</span>}
          </div>

          <div className="video-meta">
            {v.post_date
              ? <span className="date">{v.post_date}</span>
              : v.upload_date?.length >= 8
                ? <span className="date">{v.upload_date.slice(0,4)}-{v.upload_date.slice(4,6)}-{v.upload_date.slice(6,8)}</span>
                : null
            }
            {v.month_year && <span className="month-year">{v.month_year}</span>}
            {v.duration_seconds > 0 && <span className="duration">{formatDuration(v.duration_seconds)}</span>}
            <TranscriptBadge status={v.transcript_status} hasTranscript={v.has_transcript} />
          </div>

          {v.topic_tags?.length > 0 && (
            <div className="video-tags">
              {v.topic_tags.slice(0, 5).map(tag => (
                <span key={tag} className="tag">#{tag}</span>
              ))}
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
