import { useState, useEffect, useMemo, useCallback } from "react";

const INDEX_URL = "/data/metadata/index.json";

const DAY_ORDER = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

export function useTranscripts() {
  const [index, setIndex]               = useState(null);
  const [loading, setLoading]           = useState(true);
  const [error, setError]               = useState(null);
  const [query, setQuery]               = useState("");
  const [channelFilter, setChannel]     = useState("all");
  const [dayFilter, setDay]             = useState("all");
  const [timeOfDayFilter, setTimeOfDay] = useState("all");
  const [contentFilter, setContent]     = useState("all");
  const [bookFilter, setBook]           = useState("all");
  const [tagFilter, setTag]             = useState("all");
  const [yearFilter, setYear]           = useState("all");
  const [monthFilter, setMonth]         = useState("all");
  const [selected, setSelected]         = useState(null);
  const [transcript, setTranscript]     = useState(null);
  const [txLoading, setTxLoading]       = useState(false);

  const fetchIndex = useCallback(async () => {
    try {
      const r = await fetch(`${INDEX_URL}?t=${Date.now()}`);
      if (!r.ok) throw new Error(`Failed to load index (${r.status})`);
      const data = await r.json();
      setIndex(data);
      return data;
    } catch (err) {
      setError(err.message);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    fetchIndex().finally(() => setLoading(false));
  }, [fetchIndex]);

  const refreshIndex = useCallback(async () => {
    await fetchIndex();
  }, [fetchIndex]);

  const channels = useMemo(() => {
    if (!index) return [];
    return [...new Set(index.videos.map(v => v.channel_name))].filter(Boolean).sort();
  }, [index]);

  const days = useMemo(() => {
    if (!index) return [];
    const present = new Set(index.videos.map(v => v.day_of_week).filter(Boolean));
    return DAY_ORDER.filter(d => present.has(d));
  }, [index]);

  const timesOfDay = useMemo(() => {
    if (!index) return [];
    const order = ["Fajr", "Zuhr", "Isha"];
    const present = new Set(index.videos.map(v => v.time_of_day).filter(Boolean));
    return order.filter(t => present.has(t));
  }, [index]);

  const contentTypes = useMemo(() => {
    if (!index) return [];
    return [...new Set(index.videos.map(v => v.content_type).filter(Boolean))].sort();
  }, [index]);

  const hadithBooks = useMemo(() => {
    if (!index) return [];
    return [...new Set(index.videos.map(v => v.hadith_book).filter(Boolean))].sort();
  }, [index]);

  const allTags = useMemo(() => {
    if (!index) return [];
    const tagSet = new Set();
    index.videos.forEach(v => (v.topic_tags || []).forEach(t => tagSet.add(t)));
    return [...tagSet].sort();
  }, [index]);

  const years = useMemo(() => {
    if (!index) return [];
    return [...new Set(index.videos.map(v => v.year).filter(Boolean))]
      .sort((a, b) => b - a).map(String);
  }, [index]);

  const months = useMemo(() => {
    if (!index) return [];
    const relevant = yearFilter === "all"
      ? index.videos
      : index.videos.filter(v => String(v.year) === yearFilter);
    const seen = new Map();
    relevant.forEach(v => { if (v.month && v.month_num) seen.set(v.month, v.month_num); });
    return [...seen.entries()].sort((a, b) => a[1] - b[1]).map(([name]) => name);
  }, [index, yearFilter]);

  // Filtered videos shown in the sidebar
  const videos = useMemo(() => {
    if (!index) return [];
    let list = index.videos;
    if (channelFilter !== "all")   list = list.filter(v => v.channel_name === channelFilter);
    if (dayFilter !== "all")       list = list.filter(v => v.day_of_week === dayFilter);
    if (timeOfDayFilter !== "all") list = list.filter(v => v.time_of_day === timeOfDayFilter);
    if (contentFilter !== "all")   list = list.filter(v => v.content_type === contentFilter);
    if (bookFilter !== "all")      list = list.filter(v => v.hadith_book === bookFilter);
    if (tagFilter !== "all")       list = list.filter(v => (v.topic_tags || []).includes(tagFilter));
    if (yearFilter !== "all")      list = list.filter(v => String(v.year) === yearFilter);
    if (monthFilter !== "all")     list = list.filter(v => v.month === monthFilter);
    if (query.trim()) {
      const q = query.toLowerCase();
      list = list.filter(v =>
        v.title?.toLowerCase().includes(q) ||
        v.suggested_title?.toLowerCase().includes(q) ||
        v.channel_name?.toLowerCase().includes(q) ||
        v.summary?.toLowerCase().includes(q) ||
        (v.topic_tags || []).some(t => t.includes(q))
      );
    }
    return [...list].sort((a, b) =>
      (b.post_date || b.upload_date || "").localeCompare(a.post_date || a.upload_date || "")
    );
  }, [index, query, channelFilter, dayFilter, timeOfDayFilter, contentFilter,
      bookFilter, tagFilter, yearFilter, monthFilter]);

  // All videos unfiltered — for the dashboard so stats are always accurate
  const allVideos = useMemo(() => {
    if (!index) return [];
    return [...index.videos].sort((a, b) =>
      (b.post_date || b.upload_date || "").localeCompare(a.post_date || a.upload_date || "")
    );
  }, [index]);

  const selectVideo = useCallback(async (video) => {
    if (!video) { setSelected(null); setTranscript(null); return; }
    setSelected(video.video_id);
    setTranscript(null);
    if (!video.has_transcript) return;
    setTxLoading(true);
    try {
      const r = await fetch(`/data/transcripts/${video.channel_id}/${video.video_id}.json?t=${Date.now()}`);
      if (!r.ok) throw new Error(`Transcript not found (${r.status})`);
      setTranscript(await r.json());
    } catch (e) {
      setTranscript({ error: e.message });
    } finally {
      setTxLoading(false);
    }
  }, []);

  const clearFilters = useCallback(() => {
    setQuery(""); setChannel("all"); setDay("all"); setTimeOfDay("all");
    setContent("all"); setBook("all"); setTag("all"); setYear("all"); setMonth("all");
  }, []);

  const hasActiveFilters = query || channelFilter !== "all" || dayFilter !== "all" ||
    timeOfDayFilter !== "all" || contentFilter !== "all" || bookFilter !== "all" ||
    tagFilter !== "all" || yearFilter !== "all" || monthFilter !== "all";

  return {
    loading, error,
    channels, days, timesOfDay, contentTypes, hadithBooks, allTags, years, months,
    videos, allVideos,
    query, setQuery,
    channelFilter, setChannel,
    dayFilter, setDay,
    timeOfDayFilter, setTimeOfDay,
    contentFilter, setContent,
    bookFilter, setBook,
    tagFilter, setTag,
    yearFilter, setYear,
    monthFilter, setMonth,
    clearFilters, hasActiveFilters,
    selected, selectVideo,
    transcript, txLoading,
    refreshIndex,
    updatedAt: index?.updated_at ?? "",
  };
}
