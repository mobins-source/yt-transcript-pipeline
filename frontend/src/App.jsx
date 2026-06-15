import { useState, useEffect } from "react";
import { useTranscripts } from "./hooks/useTranscripts";
import { useOverrides } from "./hooks/useOverrides";
import { useSrtStatus } from "./hooks/useSrtStatus";
import SearchBar from "./components/SearchBar";
import FilterPanel from "./components/FilterPanel";
import VideoList from "./components/VideoList";
import TranscriptViewer from "./components/TranscriptViewer";
import Dashboard from "./components/Dashboard";
import "./app.css";

export default function App() {
  const {
    loading, error,
    days, timesOfDay, contentTypes, hadithBooks, allTags, years, months,
    videos, allVideos, query, setQuery,
    dayFilter, setDay, timeOfDayFilter, setTimeOfDay,
    contentFilter, setContent, bookFilter, setBook,
    tagFilter, setTag, yearFilter, setYear, monthFilter, setMonth,
    clearFilters, hasActiveFilters,
    selected, selectVideo, transcript, txLoading,
    refreshIndex, updatedAt,
  } = useTranscripts();

  const {
    overrides, serverUp, saving, saveResult,
    saveOverride, hasPendingOverride,
  } = useOverrides();

  const {
    srtContent, srtLoading, cleanTxt,
    loadSrt,
    statusSaving, statusResult, updateStatus,
    editSaving, editResult, saveEdits,
  } = useSrtStatus(serverUp, refreshIndex);

  const [showDashboard, setShowDashboard] = useState(false);

  const selectedVideo = videos.find(v => v.video_id === selected)
    ?? (allVideos.find(v => v.video_id === selected))
    ?? (selected ? { video_id: selected } : null);

  useEffect(() => {
    if (selectedVideo) loadSrt(selectedVideo);
  }, [selected, loadSrt]);

  const pendingOverrides = Object.keys(overrides).length;

  return (
    <div className="app">
      <header className="app-header">
        <div className="header-inner">
          <div className="wordmark">
            <span className="wm-prefix">YT</span>
            <span className="wm-slash">/</span>
            <span className="wm-suffix">transcripts</span>
          </div>
          <div className="header-right">
            {serverUp === true  && <span className="server-badge online">● server online</span>}
            {serverUp === false && <span className="server-badge offline">● server offline</span>}
            {pendingOverrides > 0 && (
              <span className="override-count">
                {pendingOverrides} override{pendingOverrides !== 1 ? "s" : ""} pending
              </span>
            )}
            {updatedAt && <div className="last-updated">updated {new Date(updatedAt).toLocaleDateString()}</div>}
            <div className="video-count">{allVideos.length} videos</div>
            <button
              className={`dash-toggle-btn ${showDashboard ? "dash-toggle-active" : ""}`}
              onClick={() => setShowDashboard(d => !d)}
              title="Pipeline dashboard"
            >
              📊 Dashboard
            </button>
          </div>
        </div>
      </header>

      <main className="app-body">
        <aside className="sidebar">
          <SearchBar query={query} onQuery={setQuery} />
          <FilterPanel
            days={days} timesOfDay={timesOfDay}
            contentTypes={contentTypes} hadithBooks={hadithBooks}
            allTags={allTags} years={years} months={months}
            dayFilter={dayFilter} setDay={setDay}
            timeOfDayFilter={timeOfDayFilter} setTimeOfDay={setTimeOfDay}
            contentFilter={contentFilter} setContent={setContent}
            bookFilter={bookFilter} setBook={setBook}
            tagFilter={tagFilter} setTag={setTag}
            yearFilter={yearFilter} setYear={setYear}
            monthFilter={monthFilter} setMonth={setMonth}
            hasActiveFilters={hasActiveFilters} clearFilters={clearFilters}
          />
          <div className="results-count">
            {loading ? "Loading…" : `${videos.length} video${videos.length !== 1 ? "s" : ""}`}
          </div>
          {error && <div className="error-banner">⚠ {error}</div>}
          {!loading && (
            <VideoList videos={videos} selectedId={selected} onSelect={selectVideo}
              hasPendingOverride={hasPendingOverride} />
          )}
        </aside>

        <section className="content">
          <TranscriptViewer
            video={selectedVideo} transcript={transcript} loading={txLoading}
            onSaveOverride={saveOverride} saving={saving} saveResult={saveResult}
            hasPendingOverride={hasPendingOverride} serverUp={serverUp}
            srtContent={srtContent} srtLoading={srtLoading} cleanTxt={cleanTxt}
            onUpdateSrtStatus={updateStatus} statusSaving={statusSaving} statusResult={statusResult}
            onSaveEdits={saveEdits} editSaving={editSaving} editResult={editResult}
          />
        </section>
      </main>

      {showDashboard && (
        <Dashboard
          videos={allVideos}
          onSelectVideo={(v) => { selectVideo(v); setShowDashboard(false); }}
          onClose={() => setShowDashboard(false)}
        />
      )}
    </div>
  );
}
