export default function FilterPanel({
  days, timesOfDay, contentTypes, hadithBooks, allTags, years, months,
  dayFilter, setDay,
  timeOfDayFilter, setTimeOfDay,
  contentFilter, setContent,
  bookFilter, setBook,
  tagFilter, setTag,
  yearFilter, setYear,
  monthFilter, setMonth,
  hasActiveFilters, clearFilters,
}) {
  return (
    <div className="filter-panel">
      <div className="filter-header">
        <span className="filter-title">Filters</span>
        {hasActiveFilters && (
          <button className="clear-filters" onClick={clearFilters}>Clear all</button>
        )}
      </div>

      <FilterGroup label="Content Type" value={contentFilter}    onChange={setContent}    options={contentTypes} />
      <FilterGroup label="Hadith Book"  value={bookFilter}       onChange={setBook}       options={hadithBooks} />
      <FilterGroup label="Topic Tag"    value={tagFilter}        onChange={setTag}        options={allTags} />

      <div className="filter-row">
        <FilterGroup label="Day"  value={dayFilter}       onChange={setDay}       options={days}       compact />
        <FilterGroup label="Time" value={timeOfDayFilter} onChange={setTimeOfDay} options={timesOfDay} compact />
      </div>

      <div className="filter-row">
        <FilterGroup label="Year"  value={yearFilter}  onChange={(v) => { setYear(v); setMonth("all"); }} options={years}  compact />
        <FilterGroup label="Month" value={monthFilter} onChange={setMonth} options={months} compact />
      </div>
    </div>
  );
}

function FilterGroup({ label, value, onChange, options, compact }) {
  if (!options.length) return null;
  return (
    <div className={`filter-group ${compact ? "filter-group-compact" : ""}`}>
      <div className="filter-label">{label}</div>
      <select className="filter-select" value={value} onChange={e => onChange(e.target.value)}>
        <option value="all">All</option>
        {options.map(o => <option key={o} value={o}>{o}</option>)}
      </select>
    </div>
  );
}
