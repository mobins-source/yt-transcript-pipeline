export default function SearchBar({ query, onQuery }) {
  return (
    <div className="search-bar">
      <div className="search-input-wrap">
        <span className="search-icon">⌕</span>
        <input
          type="text"
          placeholder="Search videos, topics, summaries…"
          value={query}
          onChange={(e) => onQuery(e.target.value)}
          className="search-input"
          autoFocus
        />
        {query && (
          <button className="clear-btn" onClick={() => onQuery("")}>×</button>
        )}
      </div>
    </div>
  );
}
