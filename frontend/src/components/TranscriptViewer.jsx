import { useState, useEffect, useRef, useCallback } from "react";
import EditPanel from "./EditPanel";
import { parseSRT } from "../hooks/useSrtStatus";

function formatTime(secs) {
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function formatDuration(secs) {
  if (!secs || secs === 0) return null;
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = secs % 60;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}

function formatStreamTime(postTime) {
  // post_time is "YYYY-MM-DDTHH:MM:SS" already in Tucson local time — parse directly
  if (!postTime) return null;
  const timePart = postTime.split("T")[1];
  if (!timePart) return null;
  const [h, min] = timePart.split(":").map(Number);
  const period = h >= 12 ? "PM" : "AM";
  const hour12 = h % 12 || 12;
  return `${hour12}:${String(min).padStart(2, "0")} ${period}`;
}

const CONTENT_COLORS = {
  Quran:        "#4ea8de",
  Hadith:       "#5cc8a0",
  General:      "#a78bfa",
  Announcement: "#f59e0b",
  Mixed:        "#94a3b8",
};

const SRT_STATUS_LABELS = {
  pending:   { label: "Pending review", color: "#f59e0b", bg: "rgba(245,158,11,0.1)" },
  approved:  { label: "Approved",       color: "#5cc8a0", bg: "rgba(92,200,160,0.1)" },
  needs_fix: { label: "Needs fix",      color: "#e05c5c", bg: "rgba(224,92,92,0.1)"  },
};

function RawSegmentRow({ seg, videoUrl }) {
  return (
    <div className="srt-row">
      <a className="srt-time" href={`${videoUrl}&t=${Math.floor(seg.start)}`}
         target="_blank" rel="noreferrer" title="Open in YouTube">
        {formatTime(seg.start)}
      </a>
      <span className="srt-text">{seg.text}</span>
    </div>
  );
}

function CleanSegmentRow({ seg }) {
  if (seg.isArabic) return (
    <div className="srt-row srt-row-arabic">
      <span className="srt-time">{seg.start.replace(",", ".")}</span>
      <span className="srt-text"><span className="arabic-marker">{seg.text}</span></span>
    </div>
  );
  if (seg.isSilence) return (
    <div className="srt-row srt-row-silence">
      <span className="srt-time">{seg.start.replace(",", ".")}</span>
      <span className="srt-text"><span className="silence-marker">{seg.text}</span></span>
    </div>
  );
  return (
    <div className="srt-row">
      <span className="srt-time">{seg.start.replace(",", ".")}</span>
      <span className="srt-text">{seg.text}</span>
    </div>
  );
}

function CleanEditRow({ seg, onChange }) {
  const isSpecial = seg.isArabic || seg.isSilence;
  return (
    <div className={`srt-row srt-edit-row ${seg.isArabic ? "srt-row-arabic" : ""} ${seg.isSilence ? "srt-row-silence" : ""}`}>
      <span className="srt-time srt-time-locked">{seg.start.replace(",", ".")}</span>
      <input
        className={`srt-edit-input ${isSpecial ? "srt-edit-input-special" : ""}`}
        value={seg.text}
        onChange={e => onChange(seg.index, e.target.value)}
        spellCheck={!isSpecial}
      />
    </div>
  );
}

function SplitCaptionsView({ rawSegments, srtSegments, editedSegs, captionEditing, onSegmentChange, videoUrl }) {
  const leftRef  = useRef(null);
  const rightRef = useRef(null);
  const syncing  = useRef(false);

  const syncScroll = useCallback((source, target) => {
    if (syncing.current || !source || !target) return;
    syncing.current = true;
    const maxSource = source.scrollHeight - source.clientHeight;
    const maxTarget = target.scrollHeight - target.clientHeight;
    if (maxSource > 0 && maxTarget > 0)
      target.scrollTop = (source.scrollTop / maxSource) * maxTarget;
    requestAnimationFrame(() => { syncing.current = false; });
  }, []);

  const onLeftScroll  = useCallback(() => syncScroll(leftRef.current,  rightRef.current), [syncScroll]);
  const onRightScroll = useCallback(() => syncScroll(rightRef.current, leftRef.current),  [syncScroll]);
  const displaySegs   = captionEditing ? editedSegs : srtSegments;

  return (
    <div className="split-view">
      <div className="split-panel">
        <div className="split-panel-header">
          <span>Original transcript</span>
          <span className="split-panel-hint">click timestamp → YouTube</span>
        </div>
        <div className="split-panel-body" ref={leftRef} onScroll={onLeftScroll}>
          {rawSegments.map((seg, i) => <RawSegmentRow key={i} seg={seg} videoUrl={videoUrl} />)}
        </div>
      </div>
      <div className="split-divider" />
      <div className="split-panel">
        <div className="split-panel-header">
          <span>Clean captions</span>
          {captionEditing && (
            <span className="split-panel-hint">
              type <code>[Arabic recitation]</code> or <code>[Silence]</code>
            </span>
          )}
        </div>
        <div className="split-panel-body" ref={rightRef} onScroll={onRightScroll}>
          {captionEditing
            ? displaySegs.map((seg, i) => <CleanEditRow key={i} seg={seg} onChange={onSegmentChange} />)
            : displaySegs.map((seg, i) => <CleanSegmentRow key={i} seg={seg} />)
          }
        </div>
      </div>
    </div>
  );
}

function CleanTranscriptBody({ text }) {
  if (!text) return null;
  return (
    <div className="tx-body">
      {text.split("\n\n").filter(Boolean).map((para, i) => {
        if (para === "[Arabic recitation]")
          return <p key={i}><span className="arabic-marker">[Arabic recitation]</span></p>;
        if (para === "[Silence]")
          return <p key={i}><span className="silence-marker">[Silence]</span></p>;
        return <p key={i}>{para}</p>;
      })}
    </div>
  );
}

export default function TranscriptViewer({
  video, transcript, loading,
  onSaveOverride, saving, saveResult, hasPendingOverride, serverUp,
  srtContent, srtLoading, cleanTxt,
  onUpdateSrtStatus, statusSaving, statusResult,
  onSaveEdits, editSaving, editResult,
}) {
  const [view, setView]                     = useState("summary");
  const [editing, setEditing]               = useState(false);
  const [captionEditing, setCaptionEditing] = useState(false);
  const [editedSegs, setEditedSegs]         = useState([]);
  const [copied, setCopied]                 = useState(false);

  useEffect(() => { setEditing(false); setCaptionEditing(false); setView("summary"); }, [video?.video_id]);
  useEffect(() => { setEditedSegs(parseSRT(srtContent)); setCaptionEditing(false); }, [srtContent]);

  function startCaptionEdit()  { setEditedSegs(parseSRT(srtContent)); setCaptionEditing(true); }
  function cancelCaptionEdit() { setEditedSegs(parseSRT(srtContent)); setCaptionEditing(false); }

  function handleSegmentChange(index, newText) {
    setEditedSegs(prev => prev.map(s =>
      s.index === index
        ? { ...s, text: newText, isArabic: newText === "[Arabic recitation]", isSilence: newText === "[Silence]" }
        : s
    ));
  }

  async function handleSaveEdits() {
    const ok = await onSaveEdits(video, editedSegs.map(s => ({ index: s.index, start: s.start, end: s.end, text: s.text })));
    if (ok) setCaptionEditing(false);
  }

  function copyText() {
    navigator.clipboard.writeText(cleanTxt || transcript?.clean_text || "").then(() => {
      setCopied(true); setTimeout(() => setCopied(false), 1800);
    });
  }

  if (!video) {
    return (
      <div className="viewer-placeholder">
        <span className="placeholder-icon">▷</span>
        <p>Select a video to view its transcript</p>
      </div>
    );
  }

  const tx              = transcript;
  const hasAI           = tx && (tx.summary || tx.content_type);
  const pending         = hasPendingOverride?.(video.video_id);
  const hasSrt          = video.has_clean_srt;
  const hasCleanTxt     = video.has_clean_txt || !!cleanTxt;
  const srtStatus       = video.srt_status;
  const srtInfo         = SRT_STATUS_LABELS[srtStatus] || null;
  const isApproved      = srtStatus === "approved";
  const hasFullTranscript = hasCleanTxt || tx?.clean_text;
  const srtSegments     = parseSRT(srtContent);
  const rawSegments     = tx?.segments || [];

  // Computed display values
  const streamTime = formatStreamTime(video.post_time);
  const duration   = formatDuration(video.duration_seconds);

  return (
    <div className="transcript-viewer">
      {/* ── Header ── */}
      <div className="viewer-header">
        <div className="viewer-header-left">
          <h2 className="viewer-title">{tx?.suggested_title || video.title}</h2>
          {tx?.suggested_title && video.title !== tx.suggested_title && (
            <div className="original-title">Original: {video.title}</div>
          )}

          {/* Row 1: date · time · duration · slot */}
          <div className="viewer-sub">
            <span>{video.channel_name}</span>
            {video.post_date  && <><span className="dot">·</span><span>{video.post_date}</span></>}
            {streamTime       && <><span className="dot">·</span><span className="stream-time">{streamTime}</span></>}
            {duration         && <><span className="dot">·</span><span className="stream-duration">{duration}</span></>}
            {video.month_year && <><span className="dot">·</span><span>{video.month_year}</span></>}
            {video.time_slot  && <><span className="dot">·</span><span className="slot-label">{video.time_slot}</span></>}
            {tx?.word_count   && <><span className="dot">·</span><span>{tx.word_count.toLocaleString()} words</span></>}
          </div>

          <div className="viewer-cats">
            {video.content_type && (
              <span className="cat-pill" style={{ borderColor: CONTENT_COLORS[video.content_type] || "#555", color: CONTENT_COLORS[video.content_type] || "#94a3b8" }}>
                {video.content_type}
              </span>
            )}
            {video.time_of_day    && <span className="cat-pill">{video.time_of_day}</span>}
            {video.hadith_book    && <span className="cat-pill cat-pill-book">{video.hadith_book}</span>}
            {video.hadith_chapter && <span className="cat-pill cat-pill-chapter">Ch: {video.hadith_chapter}</span>}
            {pending && <span className="cat-pill cat-pill-pending">override pending</span>}
            {hasSrt && srtInfo && (
              <span className="cat-pill" style={{ borderColor: srtInfo.color, color: srtInfo.color }}>
                SRT: {srtInfo.label}
              </span>
            )}
          </div>

          {video.topic_tags?.length > 0 && (
            <div className="viewer-tags">
              {video.topic_tags.map(tag => <span key={tag} className="tag">#{tag}</span>)}
            </div>
          )}
        </div>

        <div className="viewer-actions">
          <a href={video.url} target="_blank" rel="noreferrer" className="action-btn">↗ YouTube</a>
          {hasFullTranscript && (
            <button className="action-btn" onClick={copyText}>{copied ? "✓ Copied" : "⎘ Copy"}</button>
          )}
          {serverUp && (
            <button className={`action-btn ${editing ? "action-btn-active" : ""}`} onClick={() => setEditing(e => !e)}>✎ Edit</button>
          )}
          {serverUp === false && <span className="action-btn-disabled">✎ Edit (server offline)</span>}
        </div>
      </div>

      {editing && (
        <EditPanel video={video} transcript={tx}
          onSave={row => onSaveOverride(row)} onClose={() => setEditing(false)}
          saving={saving} saveResult={saveResult} />
      )}

      {loading && <div className="tx-loading"><span className="spinner" /> Loading…</div>}
      {!loading && !video.has_transcript && !hasSrt && <div className="tx-unavailable">No transcript available.</div>}
      {!loading && tx?.error && <div className="tx-unavailable">Error: {tx.error}</div>}

      {!loading && !editing && (tx || hasSrt) && (
        <>
          <div className="view-tabs">
            {hasAI && <button className={`tab ${view === "summary" ? "active" : ""}`} onClick={() => setView("summary")}>Summary</button>}
            {hasFullTranscript && (
              <button className={`tab ${view === "clean" ? "active" : ""}`} onClick={() => setView("clean")}>
                Full transcript {hasCleanTxt && <span className="tab-dot tab-dot-green" />}
              </button>
            )}
            {tx?.segments?.length > 0 && (
              <button className={`tab ${view === "segments" ? "active" : ""}`} onClick={() => setView("segments")}>Timestamped</button>
            )}
            {hasSrt && (
              <button className={`tab ${view === "captions" ? "active" : ""}`} onClick={() => setView("captions")}>
                Clean captions
                {srtStatus === "pending"   && <span className="tab-dot tab-dot-orange" />}
                {srtStatus === "needs_fix" && <span className="tab-dot tab-dot-red" />}
                {srtStatus === "approved"  && <span className="tab-dot tab-dot-green" />}
              </button>
            )}
          </div>

          {/* Summary */}
          {view === "summary" && hasAI && (
            <div className="tx-body">
              {tx.summary
                ? tx.summary.split("\n").filter(Boolean).map((p, i) => <p key={i}>{p}</p>)
                : <p className="muted">Summary not yet generated.</p>
              }
              <div className="meta-grid">
                {video.post_date      && <MetaCard label="Date"          value={video.post_date} />}
                {streamTime           && <MetaCard label="Stream start"  value={streamTime} />}
                {duration             && <MetaCard label="Duration"      value={duration} />}
                {tx.content_type      && <MetaCard label="Content type"  value={tx.content_type} />}
                {tx.hadith_book       && <MetaCard label="Hadith book"   value={tx.hadith_book} />}
                {tx.hadith_chapter    && <MetaCard label="Chapter"       value={tx.hadith_chapter} />}
                {tx.time_of_day       && <MetaCard label="Prayer time"   value={tx.time_of_day} />}
                {tx.day_of_week       && <MetaCard label="Day"           value={tx.day_of_week} />}
                {tx.time_slot         && <MetaCard label="Session"       value={tx.time_slot} />}
                {tx.month_year        && <MetaCard label="Month / year"  value={tx.month_year} />}
                {tx.manually_reviewed && <MetaCard label="Reviewed"      value="✓ Yes" highlight />}
              </div>
            </div>
          )}

          {/* Full transcript */}
          {view === "clean" && (
            cleanTxt
              ? <CleanTranscriptBody text={cleanTxt} />
              : tx?.paragraphs?.length
                ? <div className="tx-body">{tx.paragraphs.map((p, i) => <p key={i}>{p}</p>)}</div>
                : tx?.clean_text
                  ? <div className="tx-body"><p>{tx.clean_text}</p></div>
                  : null
          )}

          {/* Timestamped */}
          {view === "segments" && (
            <div className="tx-segments">
              {tx?.segments?.map((seg, i) => (
                <div key={i} className="segment-row">
                  <a className="timestamp" href={`${video.url}&t=${Math.floor(seg.start)}`} target="_blank" rel="noreferrer">
                    {formatTime(seg.start)}
                  </a>
                  <span className="segment-text">{seg.text}</span>
                </div>
              ))}
            </div>
          )}

          {/* Clean captions */}
          {view === "captions" && hasSrt && (
            <div className="captions-view">
              {serverUp && (
                <div className="srt-toolbar">
                  <div className="srt-toolbar-left">
                    {srtInfo && !captionEditing && (
                      <span className="srt-status-pill" style={{ background: srtInfo.bg, color: srtInfo.color }}>{srtInfo.label}</span>
                    )}
                    {captionEditing && (
                      <span className="srt-status-pill" style={{ background: "rgba(78,168,222,0.1)", color: "var(--accent2)" }}>Editing…</span>
                    )}
                    {statusResult === "ok"    && <span className="status-msg ok">✓ Status saved</span>}
                    {statusResult === "error" && <span className="status-msg error">✗ Save failed</span>}
                    {editResult   === "ok"    && <span className="status-msg ok">✓ Captions saved</span>}
                    {editResult   === "error" && <span className="status-msg error">✗ Save failed</span>}
                  </div>
                  <div className="srt-toolbar-right">
                    {!captionEditing ? (
                      <>
                        <button className="srt-btn srt-btn-approve" disabled={statusSaving || isApproved} onClick={() => onUpdateSrtStatus(video, "approved")}>✓ Approve</button>
                        <button className="srt-btn srt-btn-fix"     disabled={statusSaving || srtStatus === "needs_fix"} onClick={() => onUpdateSrtStatus(video, "needs_fix")}>✗ Needs fix</button>
                        <button className="srt-btn srt-btn-reset"   disabled={statusSaving || srtStatus === "pending"}   onClick={() => onUpdateSrtStatus(video, "pending")}>↺ Reset</button>
                        <button className="srt-btn srt-btn-edit"    disabled={isApproved}   onClick={startCaptionEdit}>✎ Edit captions</button>
                      </>
                    ) : (
                      <>
                        <button className="srt-btn srt-btn-cancel-edit" onClick={cancelCaptionEdit} disabled={editSaving}>Cancel</button>
                        <button className="srt-btn srt-btn-save-edit"   onClick={handleSaveEdits}   disabled={editSaving}>
                          {editSaving ? "Saving…" : "Save captions"}
                        </button>
                      </>
                    )}
                  </div>
                </div>
              )}
              {srtLoading && <div className="tx-loading"><span className="spinner" /> Loading captions…</div>}
              {!srtLoading && (
                <SplitCaptionsView
                  rawSegments={rawSegments} srtSegments={srtSegments}
                  editedSegs={editedSegs} captionEditing={captionEditing}
                  onSegmentChange={handleSegmentChange} videoUrl={video.url}
                />
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function MetaCard({ label, value, highlight }) {
  return (
    <div className={`meta-card ${highlight ? "meta-card-highlight" : ""}`}>
      <div className="meta-label">{label}</div>
      <div className="meta-value">{value}</div>
    </div>
  );
}
