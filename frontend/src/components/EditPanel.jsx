import { useState, useEffect } from "react";

const CONTENT_TYPES = ["Quran", "Hadith", "General", "Announcement", "Mixed"];
const HADITH_BOOKS  = [
  "Sahih Bukhari", "Sahih Muslim", "Sunan Abu Dawud",
  "Jami al-Tirmidhi", "Sunan al-Nasai", "Sunan Ibn Majah",
  "Riyadul Saliheen", "Al-Wajeez", "Other",
];
const TIMES_OF_DAY  = ["Fajr", "Zuhr", "Isha"];
const DAYS          = ["Sunday","Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"];

function recomputeSlot(day, tod) {
  if (day === "Friday" && tod === "Zuhr") return "Jumaa Khutba";
  return day && tod ? `${day}-${tod}` : "";
}

export default function EditPanel({ video, transcript, onSave, onClose, saving, saveResult }) {
  const [form, setForm] = useState({
    suggested_title: "",
    catchy_title:    "",
    content_type:    "",
    hadith_book:     "",
    hadith_chapter:  "",
    topic_tags:      "",
    time_of_day:     "",
    day_of_week:     "",
    time_slot:       "",
    notes:           "",
    reviewed:        "",
  });

  // Pre-fill from transcript / video on open
  useEffect(() => {
    const src = transcript || video || {};
    const tags = Array.isArray(src.topic_tags)
      ? src.topic_tags.join(", ")
      : (src.topic_tags || "");
    setForm({
      suggested_title: src.suggested_title || video?.suggested_title || "",
      catchy_title:    src.catchy_title    || video?.catchy_title    || "",
      content_type:    src.content_type    || video?.content_type    || "",
      hadith_book:     src.hadith_book     || video?.hadith_book     || "",
      hadith_chapter:  src.hadith_chapter  || video?.hadith_chapter  || "",
      topic_tags:      tags,
      time_of_day:     src.time_of_day     || video?.time_of_day     || "",
      day_of_week:     src.day_of_week     || video?.day_of_week     || "",
      time_slot:       src.time_slot       || video?.time_slot       || "",
      notes:           src.notes           || "",
      reviewed:        src.reviewed        || "",
    });
  }, [video?.video_id, transcript]);

  function set(field, value) {
    setForm(prev => {
      const next = { ...prev, [field]: value };
      // Auto-recompute time_slot when day or time changes
      if ((field === "day_of_week" || field === "time_of_day") && !prev.time_slot_manual) {
        next.time_slot = recomputeSlot(
          field === "day_of_week" ? value : prev.day_of_week,
          field === "time_of_day" ? value : prev.time_of_day,
        );
      }
      return next;
    });
  }

  function handleSave() {
    if (!video) return;
    onSave({
      video_id:        video.video_id,
      channel_id:      video.channel_id || "",
      title:           video.title || "",
      post_date:       video.post_date || "",
      ...form,
    });
  }

  if (!video) return null;

  return (
    <div className="edit-panel">
      <div className="edit-panel-header">
        <span className="edit-panel-title">Edit metadata</span>
        <div className="edit-panel-header-actions">
          {saveResult === "ok"    && <span className="save-status ok">✓ Saved to overrides.csv</span>}
          {saveResult === "error" && <span className="save-status error">✗ Save failed — is server.py running?</span>}
          <button className="edit-close" onClick={onClose}>×</button>
        </div>
      </div>

      <div className="edit-fields">
        {/* Catchy title + Suggested title */}
        <div className="edit-row-2">
          <Field label="Catchy title" hint="public headline">
            <input
              className="edit-input"
              value={form.catchy_title}
              onChange={e => set("catchy_title", e.target.value)}
              placeholder="e.g. When the Earth Swallowed a Billionaire"
            />
          </Field>
          <Field label="Suggested title" hint="descriptive / AI">
            <input
              className="edit-input"
              value={form.suggested_title}
              onChange={e => set("suggested_title", e.target.value)}
              placeholder="Leave blank to keep current value"
            />
          </Field>
        </div>

        {/* Content type + Hadith book on same row */}
        <div className="edit-row-2">
          <Field label="Content type">
            <select className="edit-select" value={form.content_type} onChange={e => set("content_type", e.target.value)}>
              <option value="">— unchanged —</option>
              {CONTENT_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Hadith book">
            <select className="edit-select" value={form.hadith_book} onChange={e => set("hadith_book", e.target.value)}>
              <option value="">— unchanged —</option>
              {HADITH_BOOKS.map(b => <option key={b} value={b}>{b}</option>)}
            </select>
          </Field>
        </div>

        {/* Hadith chapter */}
        <Field label="Hadith chapter">
          <input
            className="edit-input"
            value={form.hadith_chapter}
            onChange={e => set("hadith_chapter", e.target.value)}
            placeholder="e.g. Chapter 4: Truthfulness"
          />
        </Field>

        {/* Topic tags */}
        <Field label="Topic tags" hint="comma separated">
          <input
            className="edit-input"
            value={form.topic_tags}
            onChange={e => set("topic_tags", e.target.value)}
            placeholder="e.g. prayer, isha, patience"
          />
        </Field>

        {/* Time of day + Day of week + Time slot */}
        <div className="edit-row-3">
          <Field label="Time of day">
            <select className="edit-select" value={form.time_of_day} onChange={e => set("time_of_day", e.target.value)}>
              <option value="">— unchanged —</option>
              {TIMES_OF_DAY.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </Field>
          <Field label="Day of week">
            <select className="edit-select" value={form.day_of_week} onChange={e => set("day_of_week", e.target.value)}>
              <option value="">— unchanged —</option>
              {DAYS.map(d => <option key={d} value={d}>{d}</option>)}
            </select>
          </Field>
          <Field label="Time slot">
            <input
              className="edit-input"
              value={form.time_slot}
              onChange={e => set("time_slot", e.target.value)}
              placeholder="auto-computed"
            />
          </Field>
        </div>

        {/* Notes + Reviewed */}
        <div className="edit-row-2">
          <Field label="Notes">
            <input
              className="edit-input"
              value={form.notes}
              onChange={e => set("notes", e.target.value)}
              placeholder="Your review notes (not applied to JSON)"
            />
          </Field>
          <Field label="Reviewed">
            <select className="edit-select" value={form.reviewed} onChange={e => set("reviewed", e.target.value)}>
              <option value="">— unchanged —</option>
              <option value="yes">Yes</option>
              <option value="no">No</option>
            </select>
          </Field>
        </div>
      </div>

      <div className="edit-panel-footer">
        <span className="edit-hint">
          Blank fields keep their current values. Changes saved to <code>overrides.csv</code> — run <code>python3 overrides.py apply</code> to commit.
        </span>
        <div className="edit-footer-actions">
          <button className="edit-btn-cancel" onClick={onClose}>Cancel</button>
          <button className="edit-btn-save" onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save to overrides.csv"}
          </button>
        </div>
      </div>
    </div>
  );
}

function Field({ label, hint, children }) {
  return (
    <div className="edit-field">
      <label className="edit-label">
        {label}
        {hint && <span className="edit-hint-inline">{hint}</span>}
      </label>
      {children}
    </div>
  );
}
