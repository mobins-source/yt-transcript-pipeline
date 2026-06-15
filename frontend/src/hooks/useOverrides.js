import { useState, useEffect, useCallback } from "react";

/**
 * useOverrides
 * Loads all pending overrides from the local API server.
 * Re-fetches whenever the browser window regains focus so the badge
 * clears automatically after running `python3 overrides.py apply`.
 */
export function useOverrides() {
  const [overrides, setOverrides]   = useState({});  // video_id → row
  const [serverUp, setServerUp]     = useState(null);
  const [saving, setSaving]         = useState(false);
  const [saveResult, setSaveResult] = useState(null);

  const fetchOverrides = useCallback(async () => {
    try {
      const r = await fetch(`/api/overrides?t=${Date.now()}`);
      if (!r.ok) throw new Error();
      const rows = await r.json();
      const map = {};
      rows.forEach(r => { if (r.video_id) map[r.video_id] = r; });
      setOverrides(map);
      setServerUp(true);
    } catch {
      setServerUp(false);
    }
  }, []);

  // Initial load
  useEffect(() => { fetchOverrides(); }, [fetchOverrides]);

  // Re-fetch when window regains focus (e.g. after running apply in terminal)
  useEffect(() => {
    const onFocus = () => fetchOverrides();
    window.addEventListener("focus", onFocus);
    return () => window.removeEventListener("focus", onFocus);
  }, [fetchOverrides]);

  const saveOverride = useCallback(async (row) => {
    setSaving(true);
    setSaveResult(null);
    try {
      const resp = await fetch("/api/overrides", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(row),
      });
      if (!resp.ok) throw new Error(await resp.text());
      setOverrides(prev => ({ ...prev, [row.video_id]: row }));
      setSaveResult("ok");
      setTimeout(() => setSaveResult(null), 3000);
    } catch {
      setSaveResult("error");
      setTimeout(() => setSaveResult(null), 4000);
    } finally {
      setSaving(false);
    }
  }, []);

  const deleteOverride = useCallback(async (video_id) => {
    try {
      await fetch(`/api/overrides/${video_id}`, { method: "DELETE" });
      setOverrides(prev => {
        const next = { ...prev };
        delete next[video_id];
        return next;
      });
    } catch (e) {
      console.error("Delete override failed", e);
    }
  }, []);

  return {
    overrides,
    serverUp,
    saving,
    saveResult,
    saveOverride,
    deleteOverride,
    hasPendingOverride: (video_id) => !!overrides[video_id],
  };
}
