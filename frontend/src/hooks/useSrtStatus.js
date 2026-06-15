import { useState, useCallback } from "react";

export function useSrtStatus(serverUp, refreshIndex) {
  const [srtContent, setSrtContent]     = useState(null);
  const [srtLoading, setSrtLoading]     = useState(false);
  const [cleanTxt, setCleanTxt]         = useState(null);
  const [statusSaving, setStatusSaving] = useState(false);
  const [statusResult, setStatusResult] = useState(null);
  const [editSaving, setEditSaving]     = useState(false);
  const [editResult, setEditResult]     = useState(null);

  const loadSrt = useCallback(async (video) => {
    setSrtContent(null);
    setCleanTxt(null);
    if (!video?.channel_id) return;

    if (video.has_clean_srt) {
      setSrtLoading(true);
      try {
        const r = await fetch(
          `/data/transcripts/${video.channel_id}/${video.video_id}.clean_en.srt?t=${Date.now()}`
        );
        if (r.ok) setSrtContent(await r.text());
      } catch (e) { /* silent */ }
      finally { setSrtLoading(false); }
    }

    if (video.has_clean_txt) {
      try {
        const r = await fetch(
          `/data/transcripts/${video.channel_id}/${video.video_id}.clean_en.txt?t=${Date.now()}`
        );
        if (r.ok) setCleanTxt(await r.text());
      } catch (e) { /* silent */ }
    }
  }, []);

  const reloadSrt = useCallback(async (video) => {
    if (!video?.channel_id) return;
    try {
      const r = await fetch(
        `/data/transcripts/${video.channel_id}/${video.video_id}.clean_en.srt?t=${Date.now()}`
      );
      if (r.ok) setSrtContent(await r.text());
    } catch (e) { /* silent */ }
    try {
      const r = await fetch(
        `/data/transcripts/${video.channel_id}/${video.video_id}.clean_en.txt?t=${Date.now()}`
      );
      if (r.ok) setCleanTxt(await r.text());
    } catch (e) { /* silent */ }
  }, []);

  const updateStatus = useCallback(async (video, status) => {
    if (!serverUp || !video) return;
    setStatusSaving(true);
    setStatusResult(null);
    try {
      const resp = await fetch(`/api/srt-status/${video.video_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: video.channel_id, status }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setStatusResult("ok");
      // Refresh index so the video list + header reflect the new status immediately
      await refreshIndex?.();
      setTimeout(() => setStatusResult(null), 2500);
    } catch (e) {
      setStatusResult("error");
      setTimeout(() => setStatusResult(null), 3000);
    } finally {
      setStatusSaving(false);
    }
  }, [serverUp, refreshIndex]);

  const saveEdits = useCallback(async (video, segments) => {
    if (!serverUp || !video) return false;
    setEditSaving(true);
    setEditResult(null);
    try {
      const resp = await fetch(`/api/srt/${video.video_id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ channel_id: video.channel_id, segments }),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setEditResult("ok");
      await reloadSrt(video);
      await refreshIndex?.();
      setTimeout(() => setEditResult(null), 2500);
      return true;
    } catch (e) {
      setEditResult("error");
      setTimeout(() => setEditResult(null), 3000);
      return false;
    } finally {
      setEditSaving(false);
    }
  }, [serverUp, reloadSrt, refreshIndex]);

  return {
    srtContent, srtLoading, cleanTxt,
    loadSrt, reloadSrt,
    statusSaving, statusResult, updateStatus,
    editSaving, editResult, saveEdits,
  };
}

export function parseSRT(text) {
  if (!text) return [];
  return text
    .trim()
    .split(/\n\n+/)
    .map(block => {
      const lines = block.trim().split("\n");
      const timeMatch = lines[1]?.match(
        /(\d{2}:\d{2}:\d{2},\d{3}) --> (\d{2}:\d{2}:\d{2},\d{3})/
      );
      if (!timeMatch) return null;
      const segText = lines.slice(2).join("\n").trim();
      return {
        index:     parseInt(lines[0]) || 0,
        start:     timeMatch[1],
        end:       timeMatch[2],
        text:      segText,
        isArabic:  segText === "[Arabic recitation]",
        isSilence: segText === "[Silence]",
      };
    })
    .filter(Boolean);
}
