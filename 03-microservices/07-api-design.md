# API Design and Versioning

## Problem

Your movie booking API starts as `/api/bookings`. Six months later, you need to change the response format to include pricing. Existing clients break. You create `/api/v2/bookings` but now you maintain two versions. A client requests "get all bookings for user 42"—your API returns 10,000 bookings, client apps crash. Another client needs custom fields (just `id` and `title`, not full movie object). Your API returns everything, wasting bandwidth. A client tries to book the same seat twice (network glitch, retry). First succeeds, second fails. No idempotency. Pagination breaks at scale—cursor at offset 1M is slow and incorrect when data changes.

API design at scale means building for versioning, pagination, filtering, idempotency, and backward compatibility. This lesson covers REST, gRPC, and the tradeoffs.

## Theory

### REST API Design Principles

REST isn't just HTTP. It's architecture:

**Resources** are the entities. `/movies` is a resource. `/movies/42` is a specific resource.

**HTTP methods** have semantics:
- `GET`: retrieve, safe (no side effects), idempotent
- `POST`: create, not idempotent (retry creates duplicates unless idempotency key used)
- `PUT`: replace, idempotent (PUT twice = PUT once)
- `PATCH`: partial update, sometimes idempotent (depends on operation)
- `DELETE`: remove, idempotent

**Status codes** convey meaning:
- `200 OK`: success
- `201 Created`: resource created (POST success)
- `204 No Content`: success, no response body
- `400 Bad Request`: client error (malformed request)
- `401 Unauthorized`: auth required
- `403 Forbidden`: auth OK but not allowed
- `404 Not Found`: resource doesn't exist
- `409 Conflict`: state conflict (overselling)
- `429 Too Many Requests`: rate limited
- `500 Internal Server Error`: server error
- `503 Service Unavailable`: temporarily down

**HATEOAS** (Hypermedia As The Engine Of Application State): response includes links to related resources, enabling client navigation without hardcoding URLs.

```json
{
  "id": 42,
  "title": "Inception",
  "links": [
    {"rel": "self", "href": "/movies/42"},
    {"rel": "screenings", "href": "/movies/42/screenings"},
    {"rel": "reviews", "href": "/movies/42/reviews"}
  ]
}
```

HATEOAS is rare in practice but useful for evolving APIs (client can discover new endpoints).

### API Versioning Strategies and Tradeoffs

**URL path versioning**: `/v1/bookings`, `/v2/bookings`

Pros: explicit, easy to route
Cons: duplicates code, hard to maintain

**Header versioning**: `Accept: application/vnd.booking.v2+json`

Pros: clean URLs, versions live in headers
Cons: clients often forget headers, harder to test (curl must specify header)

**Query param**: `/bookings?version=2`

Pros: easy for client
Cons: easily forgotten, pollutes URL semantics

**Best practice**: use URL path versioning for major versions (breaking changes), deprecate old versions with sunset headers.

```
GET /v1/bookings/42
Sunset: Sun, 31 Dec 2025 23:59:59 GMT
Deprecated: true
Link: </v2/bookings/42>; rel="successor-version"
```

Clients have time to migrate before v1 is removed.

### Pagination: Offset vs Cursor

**Offset-based**:
```
GET /bookings?offset=0&limit=10
GET /bookings?offset=10&limit=10
GET /bookings?offset=20&limit=10
```

Request 1000 items with offset=990. Easy but:
- If data changes between requests, items duplicate or missing
- Offset=1000000 scans 1M rows (slow)

**Cursor-based** (keyset pagination):
```
GET /bookings?limit=10
-> {"items": [...], "next_cursor": "abc123def456"}

GET /bookings?limit=10&cursor=abc123def456
-> {"items": [...], "next_cursor": "xyz789"}
```

Cursor is opaque (base64-encoded key value). Uses index efficiently: `WHERE id > last_id LIMIT 10`. Constant O(1) cost per page. Handles concurrent inserts correctly.

Implementation:
```json
{
  "items": [...],
  "pagination": {
    "has_more": true,
    "cursor": "eyJpZCI6IDQyLCAiY3JlYXRlZF9hdCI6ICIyMDI1LTAzLTI2VDAwOjAwOjAwWiJ9"
  }
}
```

Cursor is `base64(json_encode({"id": 42, "created_at": "2025-03-26T00:00:00Z"}))`. Client returns opaque cursor, server decodes and uses `WHERE id > 42` to find next page.

### Filtering, Sorting, Field Selection

**Filtering**:
```
GET /movies?genre=Action&year=2024&rating_min=8.0
```

Server parses query params, applies WHERE clauses. Validate and sanitize input (no SQL injection).

**Sorting**:
```
GET /movies?sort=-rating,title
```

Sort by rating descending (minus prefix), then title ascending. Limit fields sortable (prevent index misuse). Validate sort fields in whitelist.

**Sparse fieldsets** (field selection):
```
GET /movies/42?fields=title,year,rating
```

Return only requested fields. Reduces bandwidth, latency (might skip expensive JOINs).

Implementation: parse fields param, build SELECT with only those columns.

### Idempotency

`POST /bookings` creates a booking. If network glitches and client retries, POST happens twice. Two bookings created.

Solution: **idempotency keys**. Client generates UUID and sends with request:

```
POST /bookings
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000

{"user_id": 42, "movie_id": 1, "seats": 2}
```

Server stores mapping: `idempotency_key -> response`. On retry with same key, return cached response without executing again.

Implementation:
```go
// Check if idempotency key seen before
cached, ok := idempotencyCache[key]
if ok {
  return cached // Return cached response
}

// Execute booking
bookingID, err := bookService.Book(...)
response := BookingResponse{ID: bookingID}

// Cache
idempotencyCache[key] = response
return response
```

Keys should expire (after 24 hours). Store in database for durability.

### Rate Limiting API Design

Standard rate limit headers:

```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 487
X-RateLimit-Reset: 1640899200
```

When limit exceeded:
```
HTTP 429 Too Many Requests
Retry-After: 60
```

Strategies:
- **Token bucket**: bucket has N tokens, refills per second. Each request costs 1 token. Full? Rate limit.
- **Sliding window**: track requests in last 60s window. > limit? Rate limit.

For APIs, token bucket is standard (predictable, fair).

Design client backoff:
```go
for retries := 0; retries < 3; retries++ {
  resp, err := http.Post(...)
  if resp.StatusCode == 429 {
    retryAfter := resp.Header.Get("Retry-After")
    time.Sleep(time.Duration(retryAfter) * time.Second)
    continue
  }
  return resp
}
```

### gRPC API Design

gRPC uses protobuf (binary, schema-driven) instead of JSON.

```protobuf
service BookingService {
  rpc Book(BookRequest) returns (BookResponse);
  rpc ListBookings(ListBookingsRequest) returns (ListBookingsResponse);
}

message BookRequest {
  int64 user_id = 1;
  int64 movie_id = 2;
  int32 seat_count = 3;
  string idempotency_key = 4;
}

message BookResponse {
  int64 booking_id = 1;
  string status = 2;
}
```

Advantages:
- Binary: 3-10x smaller than JSON
- Typed: schema enforces types
- Streaming: server or client streams data
- Multiplexing: HTTP/2 allows concurrent requests on one connection

Disadvantages:
- Not human-readable (need tools to debug)
- Requires code generation
- Less suitable for public APIs (clients must generate stubs)

**Backward compatibility** in protobuf:
- Field numbers never change (they're the wire format)
- Adding optional fields is safe (old clients ignore)
- Removing fields breaks old clients
- Renaming fields is safe (just re-encoding, old code still works)

### GraphQL Overview

GraphQL is a query language. Client specifies exactly what fields it needs:

```graphql
query GetMovieWithScreenings {
  movie(id: 42) {
    id
    title
    year
    screenings {
      id
      time
      available_seats
    }
  }
}
```

Server returns exactly that:
```json
{
  "movie": {
    "id": 42,
    "title": "Inception",
    "year": 2010,
    "screenings": [...]
  }
}
```

No over-fetching (extra fields), no under-fetching (missing data).

**N+1 problem**: for each screening, query database for bookings count. If movie has 10 screenings, 11 queries (1 for movie, 10 for screenings).

Solution: **dataloaders**. Batch requests: collect all `screening_id` needed, fetch all bookings counts in one query, cache, distribute to resolvers.

GraphQL is best for:
- **BFF** (Backend For Frontend): mobile app needs different fields than web app. GraphQL endpoint serves both.
- **Complex queries**: joins across many tables, deeply nested resources.

Avoid if:
- API is simple CRUD (overkill)
- Clients are public (harder to version, breaking changes affect many clients)
- Performance is critical (N+1 is easy to introduce accidentally)

### API Authentication and Authorization

**JWT (JSON Web Token)**:
```
Header.Payload.Signature

eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiI0MiIsImlhdCI6MTYwMDAwMDAwMH0.signature
```

Claims (payload) are base64-encoded JSON:
```json
{
  "sub": "42",
  "iat": 1600000000,
  "exp": 1600003600,
  "scope": "booking:write"
}
```

Server verifies signature using secret key. No database query needed (stateless).

Issue: if secret leaked, attacker signs arbitrary tokens. Mitigate: short TTL (15 min), refresh tokens (issued with long TTL, only used to get new access token).

**OAuth 2.0**: delegated auth.

```
1. Client redirects user to auth server
2. User logs in, grants permission
3. Auth server redirects back to client with code
4. Client exchanges code for access token (backend-to-backend)
5. Client uses token to call API
```

Use for third-party integrations (user grants app permission to their data).

**API keys**: simple but stateless.

```
X-API-Key: sk_live_abc123def456
```

Server has database of valid keys. Issue: key compromise means attacker has access. Mitigate: rotate regularly, restrict scopes.

For SaaS: use OAuth for user auth (browser), API keys for service-to-service.

### Error Response Design

Structured errors, not just text:

```json
{
  "error": {
    "code": "INSUFFICIENT_SEATS",
    "message": "Only 2 seats available, 5 requested",
    "status": 409,
    "details": [
      {
        "field": "seats",
        "issue": "exceeds availability"
      }
    ]
  }
}
```

Clients can handle by error code (not string matching, which breaks on message change).

**RFC 7807** (Problem Details):
```json
{
  "type": "https://api.example.com/errors/insufficient-seats",
  "title": "Insufficient Seats",
  "status": 409,
  "detail": "Only 2 seats available, 5 requested",
  "instance": "/bookings/42"
}
```

Standardized, allows linking to docs.

## Production Code

### Complete REST API with Versioning, Pagination, Idempotency

```go
package main

import (
	"context"
	"crypto/sha256"
	"database/sql"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type BookingAPI struct {
	db *pgxpool.Pool
	// In production, use Redis for idempotency cache
	idempotencyCache map[string]interface{}
}

// PaginationCursor encodes the keyset for pagination
type PaginationCursor struct {
	ID        int64     `json:"id"`
	CreatedAt time.Time `json:"created_at"`
}

func (pc PaginationCursor) Encode() string {
	data, _ := json.Marshal(pc)
	return base64.StdEncoding.EncodeToString(data)
}

func DecodeCursor(encoded string) (PaginationCursor, error) {
	data, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil {
		return PaginationCursor{}, err
	}
	var pc PaginationCursor
	err = json.Unmarshal(data, &pc)
	return pc, err
}

// BookingRequest for POST /v1/bookings
type BookingRequest struct {
	UserID         int64  `json:"user_id"`
	MovieID        int64  `json:"movie_id"`
	SeatCount      int32  `json:"seat_count"`
	IdempotencyKey string `json:"idempotency_key"` // Client-provided
}

// BookingResponseV1 - v1 response format
type BookingResponseV1 struct {
	ID        int64     `json:"id"`
	UserID    int64     `json:"user_id"`
	MovieID   int64     `json:"movie_id"`
	Status    string    `json:"status"`
	CreatedAt time.Time `json:"created_at"`
}

// BookingResponseV2 - v2 response format (includes pricing)
type BookingResponseV2 struct {
	ID           int64     `json:"id"`
	UserID       int64     `json:"user_id"`
	MovieID      int64     `json:"movie_id"`
	SeatCount    int32     `json:"seat_count"`
	Status       string    `json:"status"`
	TotalPrice   float64   `json:"total_price"`
	PricePerSeat float64   `json:"price_per_seat"`
	CreatedAt    time.Time `json:"created_at"`
	Links        []Link    `json:"_links"`
}

// Link for HATEOAS
type Link struct {
	Rel  string `json:"rel"`
	Href string `json:"href"`
}

// ListBookingsResponse with cursor-based pagination
type ListBookingsResponse struct {
	Items      []BookingResponseV2 `json:"items"`
	Pagination struct {
		HasMore    bool   `json:"has_more"`
		NextCursor string `json:"next_cursor,omitempty"`
	} `json:"pagination"`
}

// ErrorResponse for structured errors
type ErrorResponse struct {
	Error struct {
		Code    string `json:"code"`
		Message string `json:"message"`
		Status  int    `json:"status"`
	} `json:"error"`
}

// PostBooking creates a booking with idempotency support
func (api *BookingAPI) PostBooking(w http.ResponseWriter, r *http.Request) {
	var req BookingRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "invalid request", http.StatusBadRequest)
		return
	}

	// Version from URL path
	version := extractVersion(r.URL.Path)

	// Idempotency: check if key seen before
	if req.IdempotencyKey != "" {
		if cached, ok := api.idempotencyCache[req.IdempotencyKey]; ok {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusCreated)
			json.NewEncoder(w).Encode(cached)
			return
		}
	}

	ctx := r.Context()

	// Begin transaction
	tx, err := api.db.BeginTx(ctx, pgx.TxOptions{IsoLevel: pgx.Serializable})
	if err != nil {
		sendError(w, "DB_ERROR", err.Error(), http.StatusInternalServerError)
		return
	}
	defer tx.Rollback(ctx)

	// Check seat availability
	var available int32
	err = tx.QueryRow(ctx, `
		SELECT COUNT(*) FROM seats
		WHERE movie_id = $1 AND is_available = true
	`, req.MovieID).Scan(&available)
	if err != nil {
		sendError(w, "CHECK_FAILED", err.Error(), http.StatusInternalServerError)
		return
	}

	if available < req.SeatCount {
		sendError(w, "INSUFFICIENT_SEATS", fmt.Sprintf("only %d available", available), http.StatusConflict)
		return
	}

	// Create booking
	var bookingID int64
	var status string
	var createdAt time.Time
	var totalPrice float64
	err = tx.QueryRow(ctx, `
		INSERT INTO bookings (user_id, movie_id, seat_count, status, created_at)
		VALUES ($1, $2, $3, 'CONFIRMED', NOW())
		RETURNING id, status, created_at, seat_count * 12.99 as total_price
	`, req.UserID, req.MovieID, req.SeatCount).Scan(&bookingID, &status, &createdAt, &totalPrice)
	if err != nil {
		sendError(w, "INSERT_FAILED", err.Error(), http.StatusInternalServerError)
		return
	}

	// Mark seats as booked
	_, err = tx.Exec(ctx, `
		UPDATE seats SET is_available = false
		WHERE movie_id = $1 AND is_available = true
		LIMIT $2
	`, req.MovieID, req.SeatCount)
	if err != nil {
		sendError(w, "UPDATE_FAILED", err.Error(), http.StatusInternalServerError)
		return
	}

	err = tx.Commit(ctx)
	if err != nil {
		if strings.Contains(err.Error(), "SERIALIZATION") {
			sendError(w, "SERIALIZATION_CONFLICT", "Concurrent booking conflict", http.StatusConflict)
			return
		}
		sendError(w, "COMMIT_FAILED", err.Error(), http.StatusInternalServerError)
		return
	}

	// Build response based on version
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)

	var response interface{}
	if version == "v2" {
		response = BookingResponseV2{
			ID:           bookingID,
			UserID:       req.UserID,
			MovieID:      req.MovieID,
			SeatCount:    req.SeatCount,
			Status:       status,
			TotalPrice:   totalPrice,
			PricePerSeat: totalPrice / float64(req.SeatCount),
			CreatedAt:    createdAt,
			Links: []Link{
				{Rel: "self", Href: fmt.Sprintf("/v2/bookings/%d", bookingID)},
				{Rel: "user", Href: fmt.Sprintf("/v2/users/%d", req.UserID)},
				{Rel: "movie", Href: fmt.Sprintf("/v2/movies/%d", req.MovieID)},
			},
		}
	} else {
		response = BookingResponseV1{
			ID:        bookingID,
			UserID:    req.UserID,
			MovieID:   req.MovieID,
			Status:    status,
			CreatedAt: createdAt,
		}
	}

	// Cache response for idempotency
	if req.IdempotencyKey != "" {
		api.idempotencyCache[req.IdempotencyKey] = response
		// In production, set expiry (24 hours)
	}

	json.NewEncoder(w).Encode(response)
}

// GetBookings with cursor-based pagination and sparse fieldsets
func (api *BookingAPI) GetBookings(w http.ResponseWriter, r *http.Request) {
	userID := extractUserID(r)
	limit := extractLimit(r)
	cursor := r.URL.Query().Get("cursor")
	fields := strings.Split(r.URL.Query().Get("fields"), ",")

	ctx := r.Context()

	// Pagination using cursor
	var whereClause string
	var args []interface{}
	var startID int64

	if cursor != "" {
		decodedCursor, err := DecodeCursor(cursor)
		if err != nil {
			sendError(w, "INVALID_CURSOR", err.Error(), http.StatusBadRequest)
			return
		}
		whereClause = "WHERE user_id = $1 AND (id, created_at) > ($2, $3)"
		startID = decodedCursor.ID
		args = []interface{}{userID, decodedCursor.ID, decodedCursor.CreatedAt}
	} else {
		whereClause = "WHERE user_id = $1"
		args = []interface{}{userID}
	}

	// Build SELECT with sparse fieldsets
	selectClause := "id, user_id, movie_id, seat_count, status, total_price, price_per_seat, created_at"
	if len(fields) > 0 && fields[0] != "" {
		// Whitelist allowed fields
		allowed := map[string]bool{"id": true, "status": true, "created_at": true, "total_price": true}
		var selectedFields []string
		for _, field := range fields {
			if allowed[field] {
				selectedFields = append(selectedFields, field)
			}
		}
		if len(selectedFields) > 0 {
			selectClause = strings.Join(selectedFields, ", ")
		}
	}

	// Query with limit+1 to detect if there are more results
	query := fmt.Sprintf(`
		SELECT %s FROM bookings
		%s
		ORDER BY id, created_at
		LIMIT %d
	`, selectClause, whereClause, limit+1)

	rows, err := api.db.Query(ctx, query, args...)
	if err != nil {
		sendError(w, "QUERY_FAILED", err.Error(), http.StatusInternalServerError)
		return
	}
	defer rows.Close()

	var items []BookingResponseV2
	var lastID int64
	var lastCreatedAt time.Time

	for rows.Next() && len(items) < int(limit) {
		var id, userID, movieID int64
		var seatCount int32
		var status string
		var totalPrice, pricePerSeat float64
		var createdAt time.Time

		err := rows.Scan(&id, &userID, &movieID, &seatCount, &status, &totalPrice, &pricePerSeat, &createdAt)
		if err != nil {
			continue
		}

		items = append(items, BookingResponseV2{
			ID:           id,
			UserID:       userID,
			MovieID:      movieID,
			SeatCount:    seatCount,
			Status:       status,
			TotalPrice:   totalPrice,
			PricePerSeat: pricePerSeat,
			CreatedAt:    createdAt,
		})

		lastID = id
		lastCreatedAt = createdAt
	}

	// Check if there are more results
	hasMore := rows.Next()

	response := ListBookingsResponse{}
	response.Items = items
	response.Pagination.HasMore = hasMore
	if hasMore {
		response.Pagination.NextCursor = PaginationCursor{ID: lastID, CreatedAt: lastCreatedAt}.Encode()
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(response)
}

// Rate limiter middleware
type RateLimiter struct {
	tokens    int32
	capacity  int32
	refillRate int32 // tokens per second
}

func (rl *RateLimiter) Allow() (bool, int32) {
	if rl.tokens > 0 {
		rl.tokens--
		return true, rl.tokens
	}
	return false, 0
}

func (rl *RateLimiter) RefillTicker() {
	ticker := time.NewTicker(time.Second)
	for range ticker.C {
		if rl.tokens < rl.capacity {
			rl.tokens += rl.refillRate
			if rl.tokens > rl.capacity {
				rl.tokens = rl.capacity
			}
		}
	}
}

func RateLimitMiddleware(rl *RateLimiter) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			allowed, remaining := rl.Allow()

			w.Header().Set("X-RateLimit-Limit", "1000")
			w.Header().Set("X-RateLimit-Remaining", fmt.Sprint(remaining))
			w.Header().Set("X-RateLimit-Reset", fmt.Sprint(time.Now().Add(time.Second).Unix()))

			if !allowed {
				w.Header().Set("Retry-After", "1")
				http.Error(w, "rate limited", http.StatusTooManyRequests)
				return
			}

			next.ServeHTTP(w, r)
		})
	}
}

func extractVersion(path string) string {
	if strings.Contains(path, "/v2/") {
		return "v2"
	}
	return "v1"
}

func extractUserID(r *http.Request) int64 {
	// Parse from URL or auth token
	return 42 // stub
}

func extractLimit(r *http.Request) int32 {
	limit := r.URL.Query().Get("limit")
	if limit == "" {
		return 10
	}
	l, _ := strconv.ParseInt(limit, 10, 32)
	if l > 100 {
		l = 100 // cap at 100
	}
	return int32(l)
}

func sendError(w http.ResponseWriter, code, message string, status int) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)

	resp := ErrorResponse{}
	resp.Error.Code = code
	resp.Error.Message = message
	resp.Error.Status = status

	json.NewEncoder(w).Encode(resp)
}

func main() {
	db, _ := pgxpool.New(context.Background(), "postgres://...")
	api := &BookingAPI{
		db:                   db,
		idempotencyCache:     make(map[string]interface{}),
	}

	mux := http.NewServeMux()

	// V1 endpoints
	mux.HandleFunc("POST /v1/bookings", api.PostBooking)
	mux.HandleFunc("GET /v1/bookings", api.GetBookings)

	// V2 endpoints (same handlers, different response format)
	mux.HandleFunc("POST /v2/bookings", api.PostBooking)
	mux.HandleFunc("GET /v2/bookings", api.GetBookings)

	// Apply rate limiting
	rl := &RateLimiter{tokens: 100, capacity: 100, refillRate: 10}
	go rl.RefillTicker()
	handler := RateLimitMiddleware(rl)(mux)

	http.ListenAndServe(":8080", handler)
}
```

## Tradeoffs and What Breaks

### Breaking Changes

Changing response format breaks clients. Always version APIs. Deprecate old versions with sunset headers, giving clients 6+ months to migrate.

### Missing Pagination

If clients request all 10M bookings at once, they timeout or crash. Always paginate. Cursor-based is better than offset (scalable, handles concurrent data changes).

### Chatty APIs

Client needs user + all their bookings + movie details. Client makes 3 API calls (user, bookings, movie). For mobile, this is expensive (latency multiplies). Solution: GraphQL or BFF endpoint that returns composed data.

### Over-fetching

API returns full object when client only needs `id` and `title`. Solution: sparse fieldsets or GraphQL.

### Missing Idempotency

Retry safety is critical for payments. Every POST should have idempotency key support.

## Interview Corner

**Q1: You're versioning an API from v1 to v2 with breaking changes. How do you roll out without breaking clients?**

A: Use sunset headers:
```
Sunset: Sun, 31 Dec 2025 23:59:59 GMT
Deprecated: true
Link: </v2/bookings>; rel="successor-version"
```

Timeline:
- Month 1-2: v2 available, log all v1 requests
- Month 2-3: announce deprecation via email, blog post
- Month 3-6: migrate internal clients (web, mobile, partners)
- Month 6+: monitor v1 traffic
- Month 8: if < 5% traffic on v1, schedule removal
- Month 9: remove v1 (with final notice)

Alternatively, support both versions indefinitely (harder, but Google/Facebook do this—v1 and v2 coexist for years).

**Q2: Client requests 10,000 bookings. API times out. How do you enforce pagination?**

A: Add hard limit on page size:
```go
limit := r.URL.Query().Get("limit")
l, _ := strconv.ParseInt(limit, 10, 32)
if l <= 0 || l > 100 {
  l = 100 // clamp to 100
}
```

Return early with 400 error if limit > cap:
```go
if limit > 100 {
  http.Error(w, "limit must be <= 100", http.StatusBadRequest)
  return
}
```

For backward compatibility, default is 10 (not unlimited). Clients using the API must specify limit explicitly.

For UI, return 404 or empty list if cursor is invalid (too old, row deleted).

**Q2: Pagination at scale: offset-based hits 1M records slowly. How do you switch to cursor-based without breaking clients?**

A: Support both. Offset still works but is slower. New clients use cursor. Eventually deprecate offset.

Cursor format should be opaque (client can't guess). Use base64(json) so you can encode any fields needed for ordering.

**Q3: GraphQL vs REST: when would you use GraphQL?**

A: GraphQL for:
- BFF (Backend For Frontend): web app and mobile app need different fields
- Complex queries: many related resources, client decides what to fetch
- Rapidly evolving API: clients specify fields, server can add fields without breaking them

Avoid GraphQL if:
- API is simple CRUD
- Clients are public (versioning harder)
- Performance critical (N+1 easy to introduce)

**Q4: How do you prevent N+1 in REST API?**

A: Options:
1. Use includes: `GET /movies/42?include=screenings,reviews`
2. Return IDs only: `GET /movies/42` returns `{"id": 42, "screening_ids": [...]}`, client fetches separately
3. Batch endpoint: `POST /batch?requests=[{"id": 1}, {"id": 2}]`

For simple cases, make eager loading the default (JOIN in query). For complex cases, use GraphQL or batch.

**Q5: Rate limiting: how do you handle clients that accidentally hit limits?**

A: Generous limits (1000 req/min for authenticated users). Provide X-RateLimit headers so clients see limits and back off.

For critical clients (partners), increase limits or use separate pool.

For bad actors, stricter limits or IP-based blocking.

Implement graceful degradation: if rate limit exceeded, serve stale cache (if available) with warning header. Better than 429 error.

**Q6: Idempotency: a booking request succeeded but response didn't reach the client. Client retries. How do you prevent double-booking?**

A: Client must include `Idempotency-Key` header (UUID):
```
POST /bookings
Idempotency-Key: 550e8400-e29b-41d4-a716-446655440000
{"user_id": 42, "movie_id": 1}
```

Server logic:
```go
// Check if we've seen this key before
cached, exists := idempotencyStore.Get(key)
if exists {
  return cached // Return cached response (same HTTP status, body)
}

// Execute business logic
result, err := bookMovie(...)

// Cache for 24 hours
idempotencyStore.Set(key, result, 24*time.Hour)
return result
```

Idempotency cache must be durable (Redis or database). If lost, rerunning same key executes again (double-booking).

For key expiry: store in database with created_at, delete older than 24h. For safety, query: "has this key been seen AND execution completed successfully?" before returning cached.

**Q7: API consumers complain about over-fetching (you return 50 fields, they use 5). How do you optimize?**

A: Sparse fieldsets (field selection):
```
GET /movies/42?fields=title,year,rating
```

Implement:
1. Parse fields param: split by comma
2. Whitelist allowed fields (prevent accidentally expensive fields)
3. Build SELECT with only those columns

```go
allowed := map[string]bool{"id": true, "title": true, "year": true, "rating": true}
fields := strings.Split(r.URL.Query().Get("fields"), ",")
var selectedFields []string
for _, f := range fields {
  if allowed[f] {
    selectedFields = append(selectedFields, f)
  }
}
query := "SELECT " + strings.Join(selectedFields, ",") + " FROM movies WHERE id = $1"
```

Alternatively, use projections in response filtering (query full row, filter in app). Sparse fieldsets are better (saves bandwidth and DB I/O).

## Exercise

Build a complete movie API with:

1. `POST /v1/bookings` - create booking, with idempotency key support
2. `GET /v1/bookings` - list bookings with cursor pagination, sparse fieldsets
3. `POST /v2/bookings` - v2 with pricing included
4. Rate limiting middleware (100 req/min)
5. Proper error responses with codes
6. HATEOAS links in responses
7. Backward-compatible upgrade path

Bonus: implement WhatsApp-like message API with pagination for message history (most recent first, cursor backward pagination).

---

