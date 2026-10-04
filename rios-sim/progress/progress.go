// Package progress contains the shared, pure-data solve progress wire contract.
package progress

// Snapshot reports real search work, not a predicted percentage.
// Evaluated is cumulative successful simulations. Completed includes failed
// attempts in the current depth; Total is that depth's known state count.
// Candidates is the geometric candidate count and Kept is the latest beam size.
// Early stopping can finish with Completed < Total. A zero-star BestLine is valid.
type Snapshot struct {
	RequestID      int     `json:"request_id"`
	Phase          string  `json:"phase"`
	Depth          int     `json:"depth"`
	MaxDepth       int     `json:"max_depth"`
	Evaluated      int     `json:"evaluated"`
	Completed      int     `json:"completed"`
	Total          int     `json:"total"`
	Candidates     int     `json:"candidates"`
	Kept           int     `json:"kept"`
	BestStars      int     `json:"best_stars"`
	BestLine       string  `json:"best_line"`
	ElapsedSeconds float64 `json:"elapsed_seconds"`
	Message        string  `json:"message"`
}
