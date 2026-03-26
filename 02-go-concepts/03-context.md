# Context: Request Lifecycle and Cancellation Propagation

## Problem: Managing Request Timeouts and Cancellation

You're building a movie booking API where:
- A user initiates a checkout that must complete within 30 seconds
- The checkout involves: validate payment (10s timeout), lock seats (5s timeout), confirm booking (10s timeout)
- If any step times out, remaining steps should cancel immediately
- An upstream client disconnects mid-request; you must clean up in-flight database queries and API calls

The challenge: Go's `context.Context` is the mechanism for propagating cancellation, timeouts, and request-scoped values through the entire call stack. Misusing it causes resource leaks and unpredictable behavior.

---

## Part 1: Context Tree and Cancellation Propagation

### The Context Hierarchy

Every request has a context tree. When a parent context is cancelled, all children are cancelled automatically.

```
context.Background()
       ↓
context.WithTimeout(ctx, 30s)  [checkout context]
       ↓
├─ context.WithTimeout(ctx, 10s)  [payment validation]
├─ context.WithTimeout(ctx, 5s)   [seat locking]
└─ context.WithTimeout(ctx, 10s)  [confirmation]
```

When checkout timeout (30s) expires, all child contexts are cancelled automatically.

### The Context Interface

```go
type Context interface {
    Deadline() (deadline time.Time, ok bool)
    Done() <-chan struct{}
    Err() error
    Value(key interface{}) interface{}
}
```

- **Deadline()**: Returns the cancellation deadline (or zero if none)
- **Done()**: Returns a channel that closes when context is cancelled
- **Err()**: Returns the cancellation reason (context.Canceled or context.DeadlineExceeded)
- **Value()**: Returns request-scoped values (trace IDs, auth tokens, etc.)

### Implementing Cancellation

```go
type canceler interface {
    cancel(removeFromParent bool, err error)
    Done() <-chan struct{}
}

// Context with cancellation
ctx, cancel := context.WithCancel(context.Background())

// Somewhere else: signal cancellation
cancel()  // All operations using ctx should exit

// Downstream code
select {
case <-ctx.Done():
    return ctx.Err()  // context.Canceled
}
```

---

## Part 2: Context Constructors and When to Use Each

### context.Background() and context.TODO()

```go
// Use Background for top-level contexts (HTTP request, command-line app)
func main() {
    ctx := context.Background()
    server := &http.Server{
        Handler: myHandler,
    }
    server.ListenAndServe()
}

// Use TODO when you're unsure (code review comment)
func processItem(item Item) error {
    ctx := context.TODO()  // Caller should provide context
    return ctx.Err()
}
```

- Both are empty contexts (no deadline, no cancellation)
- Difference is semantic (TODO signals "add proper context later")
- **Never** use Background/TODO in goroutines; always pass parent context

### context.WithCancel

Allows manual cancellation without waiting for timeout.

```go
ctx, cancel := context.WithCancel(context.Background())

go func() {
    // Simulate user clicking "cancel"
    time.Sleep(5 * time.Second)
    cancel()  // Signal all downstream operations to stop
}()

result, err := longRunningOperation(ctx)
// If user cancels, operation returns immediately with context.Canceled
```

**Use case**: User-initiated cancellations (cancel button), graceful shutdown signals.

### context.WithTimeout

Cancels after a duration.

```go
ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
defer cancel()  // IMPORTANT: Prevents goroutine leak

result, err := fetchDataWithinTimeout(ctx)
if err == context.DeadlineExceeded {
    log.Printf("Operation timed out after 10s")
}
```

**Use case**: API calls, database queries, any operation with max execution time.

**Important**: Always call cancel() (even if operation completes) to prevent the timeout goroutine from lingering.

### context.WithDeadline

Like WithTimeout, but specifies absolute time.

```go
deadline := time.Now().Add(10 * time.Second)
ctx, cancel := context.WithDeadline(context.Background(), deadline)
defer cancel()
```

**Use case**: Rate-limiting (all requests before 5pm), deadline-based processing.

### context.WithValue

Attach request-scoped data.

```go
ctx := context.WithValue(context.Background(), "user_id", "user123")
ctx = context.WithValue(ctx, "trace_id", "trace-abc")

// Retrieve downstream
func getUser(ctx context.Context) {
    userID := ctx.Value("user_id").(string)
}
```

**Important**: Use custom types as keys, not strings. String keys can collide across packages.

```go
// GOOD: Type-safe key
type contextKey string
const userIDKey contextKey = "user_id"

ctx := context.WithValue(ctx, userIDKey, "user123")
userID := ctx.Value(userIDKey).(string)

// BAD: String key collision risk
ctx := context.WithValue(ctx, "user_id", "user123")
ctx = context.WithValue(ctx, "user_id", "user456")  // Overwrites previous!
```

---

## Part 3: Context in HTTP Servers

### How net/http Creates Context

`http.Server` creates a context for each request automatically.

```go
func MyHandler(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()  // Created by net/http for this request

    // Deadline: request timeout (from Server.ReadTimeout)
    // Done: closes when client disconnects or server shuts down
    // Value: contains request-specific data

    select {
    case <-ctx.Done():
        // Client disconnected or server shutting down
        http.Error(w, "Request cancelled", http.StatusServiceUnavailable)
        return
    }

    // Use ctx for all downstream operations
    result := slowOperation(ctx)
    json.NewEncoder(w).Encode(result)
}
```

### Graceful Shutdown

```go
func main() {
    server := &http.Server{
        Addr:         ":8080",
        Handler:      myRouter,
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 10 * time.Second,
        IdleTimeout:  60 * time.Second,
    }

    go func() {
        if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Fatal(err)
        }
    }()

    // Wait for shutdown signal
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
    <-sigChan

    // Graceful shutdown: stop accepting new requests, wait for in-flight requests
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    if err := server.Shutdown(ctx); err != nil {
        log.Printf("Shutdown error: %v", err)
    }
}
```

When `Shutdown()` is called:
1. Stop accepting new requests
2. Wait for in-flight requests' contexts to be cancelled
3. If timeout expires, force close remaining connections

---

## Part 4: Context in Database Operations

### pgx with Context

```go
import "github.com/jackc/pgx/v5"

// Query with timeout
ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
defer cancel()

rows, err := db.Query(ctx, "SELECT id, title FROM movies WHERE year = $1", 2024)
if err == context.DeadlineExceeded {
    log.Printf("Query timeout")
}

// Statement cache respects context (connection pooling)
var count int
err = db.QueryRow(ctx, "SELECT COUNT(*) FROM bookings").Scan(&count)
if err == context.Canceled {
    log.Printf("Query cancelled by client")
}

// Batch operations with context
batch := &pgx.Batch{}
batch.Queue("INSERT INTO bookings (user_id, movie_id) VALUES ($1, $2)", userID, movieID)
batch.Queue("UPDATE movies SET available = available - 1 WHERE id = $1", movieID)

results := db.SendBatch(ctx, batch)
defer results.Close()

for results.Next() {
    // Process result
}
```

### Timeout Cascade

When a parent timeout is shorter, it overrides child timeouts.

```go
func bookMovie(parentCtx context.Context) error {
    // Parent has 30-second timeout
    ctx, cancel := context.WithTimeout(parentCtx, 30*time.Second)
    defer cancel()

    // Step 1: Validate payment (5-second sub-timeout, but parent's 30s is longer)
    payCtx, _ := context.WithTimeout(ctx, 5*time.Second)
    if err := validatePayment(payCtx); err != nil {
        return err
    }

    // Step 2: Lock seats (10-second sub-timeout)
    lockCtx, _ := context.WithTimeout(ctx, 10*time.Second)
    if err := lockSeats(lockCtx); err != nil {
        return err
    }

    // Step 3: Confirm (remaining time from parent timeout)
    // If we've used 15s so far, only 15s remain. Sub-timeout is overridden.
    confirmCtx, _ := context.WithTimeout(ctx, 10*time.Second)
    if err := confirmBooking(confirmCtx); err != nil {
        return err
    }

    return nil
}

// Visualization
// Parent deadline: now + 30s
// Payment: min(now + 5s, parent_deadline) = now + 5s
// Lock:     min(now + 10s, parent_deadline) = now + 10s (from start of lock phase)
// Confirm:  min(now + 10s, parent_deadline) = now + 10s (but only 5-15s remaining depending on prior work)
```

---

## Part 5: Context in gRPC

### Metadata Propagation

```go
import (
    "google.golang.org/grpc"
    "google.golang.org/grpc/metadata"
)

// Server receives context with metadata
func (s *BookingService) BookMovie(ctx context.Context, req *BookingRequest) (*BookingResponse, error) {
    // Extract trace ID from metadata
    md, _ := metadata.FromIncomingContext(ctx)
    traceID := md.Get("x-trace-id")

    // Pass context to downstream services
    result, err := s.paymentService.Charge(ctx, req.Amount)
    if err != nil {
        return nil, err
    }

    return &BookingResponse{}, nil
}

// Client sends context with metadata
func callGRPC(ctx context.Context) {
    ctx = metadata.AppendToOutgoingContext(ctx, "x-trace-id", "trace-123")

    response, err := client.BookMovie(ctx, &BookingRequest{})
}
```

### Deadline Propagation

gRPC automatically propagates deadlines across service boundaries.

```go
// Service A calls Service B with context deadline
func ServiceA(ctx context.Context) error {
    // Deadline: 10 seconds from now
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    defer cancel()

    // This deadline is encoded in the gRPC request header
    response, err := grpcClient.Call(ctx, &Request{})
    return err
}

// Service B receives the same deadline
func ServiceB(ctx context.Context) {
    deadline, ok := ctx.Deadline()
    if ok {
        log.Printf("Request must complete by %v", deadline)
    }

    // If we exceed deadline, ctx.Done() closes automatically
    select {
    case <-ctx.Done():
        return ctx.Err()
    }
}
```

---

## Part 6: Context Values and Request-Scoped Data

### Pattern: Custom Context Keys

```go
// Define custom key type at package level
type contextKey string

const (
    userIDKey    contextKey = "user_id"
    traceIDKey   contextKey = "trace_id"
    tenantIDKey  contextKey = "tenant_id"
    authTokenKey contextKey = "auth_token"
)

// Attach values to context
func withUser(ctx context.Context, userID string) context.Context {
    return context.WithValue(ctx, userIDKey, userID)
}

func withTraceID(ctx context.Context, traceID string) context.Context {
    return context.WithValue(ctx, traceIDKey, traceID)
}

// Retrieve values
func userID(ctx context.Context) (string, bool) {
    id, ok := ctx.Value(userIDKey).(string)
    return id, ok
}

func traceID(ctx context.Context) string {
    id := ctx.Value(traceIDKey)
    if id == nil {
        return "unknown"
    }
    return id.(string)
}

// Usage
ctx := context.Background()
ctx = withUser(ctx, "user123")
ctx = withTraceID(ctx, "trace-abc")

// Downstream
uid, _ := userID(ctx)
tid := traceID(ctx)
```

### Anti-Pattern: Using String Keys

```go
// DANGEROUS: Collision risk
ctx := context.WithValue(ctx, "user_id", "user123")
ctx = context.WithValue(ctx, "user_id", "user456")  // Overwrites!

// Different libraries might use same string keys
// lib1: context.WithValue(ctx, "request_id", ...)
// lib2: context.WithValue(ctx, "request_id", ...)  // Collision!
```

### Anti-Pattern: Storing Complex Objects

```go
// BAD: Context values are immutable; changes to stored object won't propagate
type User struct {
    ID   string
    Name string
}

user := &User{ID: "1", Name: "Alice"}
ctx := context.WithValue(context.Background(), userIDKey, user)

// Modify user (happens in another goroutine)
user.Name = "Bob"

// Other goroutines see the modified user
// This is a race condition!
```

---

## Part 7: Production Code — Movie Booking with Timeout Cascade

Real-world scenario: Complex checkout with multiple phases, each with different timeouts.

```go
package booking

import (
    "context"
    "errors"
    "log"
    "time"

    "github.com/jackc/pgx/v5"
)

// Custom context keys
type contextKey string

const (
    userIDKey   contextKey = "user_id"
    traceIDKey  contextKey = "trace_id"
    tenantIDKey contextKey = "tenant_id"
)

// BookingRequest represents a movie ticket purchase
type BookingRequest struct {
    UserID   string
    MovieID  string
    SeatIDs  []string
    Amount   float64
}

// BookingService orchestrates the booking workflow
type BookingService struct {
    db                *pgx.Pool
    paymentService    PaymentService
    seatLockingService SeatLockingService
}

// PaymentService interface (injected)
type PaymentService interface {
    Charge(ctx context.Context, userID string, amount float64) (transactionID string, err error)
    Refund(ctx context.Context, transactionID string) error
}

// SeatLockingService interface
type SeatLockingService interface {
    LockSeats(ctx context.Context, movieID string, seatIDs []string) (lockID string, err error)
    UnlockSeats(ctx context.Context, lockID string) error
}

// Book orchestrates the entire booking workflow with timeout cascade
func (bs *BookingService) Book(ctx context.Context, req *BookingRequest) (bookingID string, err error) {
    // Attach request-scoped values
    ctx = context.WithValue(ctx, userIDKey, req.UserID)
    ctx = context.WithValue(ctx, traceIDKey, generateTraceID())

    // Overall timeout: 30 seconds for entire checkout
    ctx, cancel := context.WithTimeout(ctx, 30*time.Second)
    defer cancel()

    log.Printf("[%s] Starting booking for user %s", traceID(ctx), req.UserID)

    // Phase 1: Validate seats and check availability (5-second timeout)
    log.Printf("[%s] Phase 1: Validating seats", traceID(ctx))
    validateCtx, _ := context.WithTimeout(ctx, 5*time.Second)
    if err := bs.validateSeats(validateCtx, req.MovieID, req.SeatIDs); err != nil {
        return "", err
    }

    // Phase 2: Lock seats (10-second timeout)
    log.Printf("[%s] Phase 2: Locking seats", traceID(ctx))
    lockCtx, _ := context.WithTimeout(ctx, 10*time.Second)
    lockID, err := bs.seatLockingService.LockSeats(lockCtx, req.MovieID, req.SeatIDs)
    if err != nil {
        return "", err
    }
    defer func() {
        // Best-effort unlock if booking fails
        if err != nil {
            unlockCtx, unlockCancel := context.WithTimeout(context.Background(), 5*time.Second)
            defer unlockCancel()
            bs.seatLockingService.UnlockSeats(unlockCtx, lockID)
        }
    }()

    // Phase 3: Process payment (10-second timeout)
    log.Printf("[%s] Phase 3: Processing payment", traceID(ctx))
    payCtx, _ := context.WithTimeout(ctx, 10*time.Second)
    transactionID, err := bs.paymentService.Charge(payCtx, req.UserID, req.Amount)
    if err != nil {
        // Payment failed, unlock seats
        unlockCtx, _ := context.WithTimeout(context.Background(), 5*time.Second)
        bs.seatLockingService.UnlockSeats(unlockCtx, lockID)
        return "", err
    }
    defer func() {
        // If booking fails after payment, attempt refund
        if err != nil && transactionID != "" {
            refundCtx, refundCancel := context.WithTimeout(context.Background(), 10*time.Second)
            defer refundCancel()
            if refundErr := bs.paymentService.Refund(refundCtx, transactionID); refundErr != nil {
                log.Printf("[%s] Refund failed: %v", traceID(ctx), refundErr)
            }
        }
    }()

    // Phase 4: Store booking in database (remaining time from parent timeout)
    log.Printf("[%s] Phase 4: Storing booking", traceID(ctx))
    bookingID, err = bs.storeBooking(ctx, req, lockID, transactionID)
    if err != nil {
        return "", err
    }

    log.Printf("[%s] Booking successful: %s", traceID(ctx), bookingID)
    return bookingID, nil
}

// validateSeats checks seat availability
func (bs *BookingService) validateSeats(ctx context.Context, movieID string, seatIDs []string) error {
    const query = `
        SELECT COUNT(*) FROM seats
        WHERE movie_id = $1 AND seat_id = ANY($2) AND available = true
    `

    var count int
    err := bs.db.QueryRow(ctx, query, movieID, seatIDs).Scan(&count)
    if err != nil {
        if errors.Is(err, context.DeadlineExceeded) {
            return errors.New("seat validation timeout")
        }
        return err
    }

    if count != len(seatIDs) {
        return errors.New("some seats unavailable")
    }

    return nil
}

// storeBooking persists the booking record
func (bs *BookingService) storeBooking(ctx context.Context, req *BookingRequest, lockID, transactionID string) (string, error) {
    const query = `
        INSERT INTO bookings (user_id, movie_id, seat_ids, lock_id, transaction_id, created_at)
        VALUES ($1, $2, $3, $4, $5, NOW())
        RETURNING id
    `

    var bookingID string
    err := bs.db.QueryRow(ctx, query,
        req.UserID, req.MovieID, req.SeatIDs, lockID, transactionID).Scan(&bookingID)

    if err == context.DeadlineExceeded {
        return "", errors.New("booking storage timeout")
    }
    if err != nil {
        return "", err
    }

    return bookingID, nil
}

// Helper functions
func traceID(ctx context.Context) string {
    if id := ctx.Value(traceIDKey); id != nil {
        return id.(string)
    }
    return "unknown"
}

func generateTraceID() string {
    return "trace-" + time.Now().Format("20060102150405")
}

// HTTP Handler
func bookingHandler(bs *BookingService) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        var req BookingRequest
        if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
            http.Error(w, "Invalid request", http.StatusBadRequest)
            return
        }

        // Use request's context; client disconnect will cancel operation
        bookingID, err := bs.Book(r.Context(), &req)
        if err == context.DeadlineExceeded {
            http.Error(w, "Checkout timeout", http.StatusGatewayTimeout)
            return
        }
        if err != nil {
            http.Error(w, err.Error(), http.StatusInternalServerError)
            return
        }

        w.Header().Set("Content-Type", "application/json")
        json.NewEncoder(w).Encode(map[string]string{"booking_id": bookingID})
    }
}
```

---

## Part 8: What Breaks at Scale

### Issue 1: context.Background() Everywhere

```go
// DANGER: Ignores timeouts and cancellation from parent
func processRequest(parentCtx context.Context) {
    go func() {
        // This goroutine is NOT cancelled when parentCtx cancels
        slowOperation(context.Background())
    }()
}

// If parent request times out after 5s, this goroutine keeps running
```

Fix: Always pass parent context:

```go
func processRequest(parentCtx context.Context) {
    go func() {
        slowOperation(parentCtx)  // Respects parent timeout
    }()
}
```

### Issue 2: Ignoring context.Canceled

```go
// DANGER: Ignores cancellation, runs to completion
func worker(ctx context.Context, jobs <-chan Job) {
    for job := range jobs {
        processJob(job)  // If ctx cancels, keeps processing
    }
}

// FIXED: Check context
func worker(ctx context.Context, jobs <-chan Job) {
    for {
        select {
        case job, ok := <-jobs:
            if !ok {
                return
            }
            processJob(job)
        case <-ctx.Done():
            return  // Exit when context cancelled
        }
    }
}
```

### Issue 3: Storing Objects in Context Values

```go
// DANGER: Object is mutable; changes in one goroutine affect all
user := &User{ID: "1", Name: "Alice"}
ctx := context.WithValue(ctx, userKey, user)

// Somewhere else
user.Name = "Bob"  // This change is visible to all code using ctx

// Race condition!
```

Fix: Store immutable values:

```go
ctx := context.WithValue(ctx, userIDKey, "user1")  // Immutable string
ctx = context.WithValue(ctx, userNameKey, "Alice")
```

### Issue 4: Forgot to Call Cancel

```go
// DANGER: Timeout goroutine lingers waiting for deadline
func slowQuery(ctx context.Context) {
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    // Forgot: defer cancel()

    result := query(ctx)
    return result  // Timeout goroutine waits 10 seconds!
}

// FIXED
func slowQuery(ctx context.Context) {
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    defer cancel()  // Always call cancel

    result := query(ctx)
    return result
}
```

---

## Part 8: Context in Database Connection Pools

Database connection pools must respect context cancellation:

```go
import "github.com/jackc/pgx/v5/pgxpool"

type BookingRepository struct {
    pool *pgxpool.Pool
}

// Context timeout applies to connection acquisition AND query execution
func (br *BookingRepository) GetBooking(ctx context.Context, id string) (*Booking, error) {
    // If ctx is cancelled, Acquire() fails immediately
    conn, err := br.pool.Acquire(ctx)
    if err == context.Canceled {
        return nil, errors.New("context cancelled")
    }
    defer conn.Release()

    var booking Booking
    err = conn.QueryRow(ctx,
        "SELECT id, user_id, status FROM bookings WHERE id = $1",
        id,
    ).Scan(&booking.ID, &booking.UserID, &booking.Status)

    // If query takes longer than ctx deadline, it's cancelled
    if err == context.DeadlineExceeded {
        return nil, errors.New("query timeout")
    }

    return &booking, err
}

// Batch operations respect context
func (br *BookingRepository) GetMultiple(ctx context.Context, ids []string) ([]Booking, error) {
    rows, err := br.pool.Query(ctx,
        "SELECT id, user_id, status FROM bookings WHERE id = ANY($1)",
        ids,
    )
    if err == context.DeadlineExceeded {
        return nil, errors.New("query timeout")
    }
    defer rows.Close()

    var bookings []Booking
    for rows.Next() {
        var booking Booking
        if err := rows.Scan(&booking.ID, &booking.UserID, &booking.Status); err != nil {
            return nil, err
        }
        bookings = append(bookings, booking)
    }

    return bookings, rows.Err()
}
```

**Key insight**: Connection pool respects context timeouts. If you acquire a connection under a deadline, any operation on that connection must complete before the deadline.

---

## Part 9: Context.AfterFunc (Go 1.21+) and WithoutCancel (Go 1.21+)

### context.AfterFunc

Execute a function when context is cancelled, instead of checking Done():

```go
import "context"

ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
defer cancel()

// Execute callback when context cancels
stop := context.AfterFunc(ctx, func() {
    log.Println("Context cancelled, cleaning up resources")
    // Close connections, rollback transactions, etc.
})

// If context is cancelled before function returns, callback executes
longRunningOperation(ctx)

// Can also stop the callback manually
if stopped := stop(); stopped {
    log.Println("Callback not yet called, stopped it")
}
```

This replaces the pattern of spawning a goroutine watching ctx.Done().

### context.WithoutCancel

Create a new context that shares values but not cancellation:

```go
// Parent context with deadline
parentCtx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
defer cancel()

// Child context shares values but not deadline
childCtx := context.WithoutCancel(parentCtx)

// Deadline from parent is lost
if deadline, ok := childCtx.Deadline(); !ok {
    log.Println("No deadline on child context")
}

// But values are preserved
parentCtx = context.WithValue(parentCtx, traceIDKey, "trace-123")
childCtx = context.WithoutCancel(parentCtx)
fmt.Println(childCtx.Value(traceIDKey))  // "trace-123"

// Use case: Background cleanup task that must complete
// even if request context is cancelled
go func() {
    cleanup(context.WithoutCancel(requestCtx))
}()
```

---

## Part 10: Context in Middleware Chains

### Layered Middleware with Context

```go
// HTTP middleware chain that properly threads context
type Handler func(ctx context.Context, w http.ResponseWriter, r *http.Request) error

func authMiddleware(next Handler) Handler {
    return func(ctx context.Context, w http.ResponseWriter, r *http.Request) error {
        token := r.Header.Get("Authorization")
        if token == "" {
            return errors.New("missing auth token")
        }

        userID, err := validateToken(token)
        if err != nil {
            return err
        }

        // Attach user to context
        ctx = context.WithValue(ctx, userIDKey, userID)
        return next(ctx, w, r)
    }
}

func rateLimitMiddleware(next Handler) Handler {
    return func(ctx context.Context, w http.ResponseWriter, r *http.Request) error {
        userID := ctx.Value(userIDKey).(string)

        if !rateLimiter.Allow(userID) {
            return errors.New("rate limit exceeded")
        }

        return next(ctx, w, r)
    }
}

func loggingMiddleware(next Handler) Handler {
    return func(ctx context.Context, w http.ResponseWriter, r *http.Request) error {
        start := time.Now()
        err := next(ctx, w, r)
        duration := time.Since(start)

        logger.InfoContext(ctx, "request processed",
            slog.Float64("duration_ms", float64(duration.Milliseconds())),
            slog.String("error", fmt.Sprint(err)),
        )
        return err
    }
}

// Adapter to http.Handler
func adaptHandler(h Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        if err := h(r.Context(), w, r); err != nil {
            http.Error(w, err.Error(), http.StatusInternalServerError)
        }
    })
}

// Chain: auth -> rate limit -> logging -> actual handler
chain := loggingMiddleware(
    rateLimitMiddleware(
        authMiddleware(bookingHandler),
    ),
)

handler := adaptHandler(chain)
```

### Context Value Type Safety

```go
// Define unexported context keys to prevent collisions
type contextKey string

const (
    userIDKey    contextKey = "user_id"
    traceIDKey   contextKey = "trace_id"
    tenantIDKey  contextKey = "tenant_id"
)

// Helper functions for getting/setting
func withUserID(ctx context.Context, id string) context.Context {
    return context.WithValue(ctx, userIDKey, id)
}

func getUserID(ctx context.Context) (string, bool) {
    id, ok := ctx.Value(userIDKey).(string)
    return id, ok
}

// Safe usage
ctx = withUserID(context.Background(), "user123")
if id, ok := getUserID(ctx); ok {
    fmt.Println("User:", id)
}
```

---

## Interview Corner

### Q1: Explain context.Context and when to use each constructor.

**Model Answer**:
`context.Context` is an interface for propagating cancellation, deadlines, and request-scoped values. Constructors:

- **Background()**: Top-level context, never cancelled (use for main/tests)
- **TODO()**: Placeholder when context not yet available
- **WithCancel()**: Manual cancellation (user clicks cancel)
- **WithTimeout()**: Auto-cancellation after duration (API calls, DB queries)
- **WithDeadline()**: Auto-cancellation at absolute time (deadline-based processing)
- **WithValue()**: Attach request-scoped data (trace IDs, auth tokens)
- **AfterFunc()** (Go 1.21+): Execute callback when context cancels
- **WithoutCancel()** (Go 1.21+): Share values but not cancellation

Key rule: Always pass parent context to children; never use Background() in goroutines.

### Q2: Describe the timeout cascade pattern.

**Model Answer**:
When multiple operations have deadlines, the shortest deadline wins. Example:

```
Parent (30s) -> Payment (10s) -> Database query (5s)
Effective deadline for query: min(30, 10, 5) = 5s
```

This ensures if any upstream step times out, downstream steps fail immediately rather than waste resources.

### Q3: How does context propagate through gRPC calls?

**Model Answer**:
gRPC encodes the context deadline in request headers. The receiving service automatically enforces that deadline. If the deadline is shorter than the server's processing time, the request is cancelled mid-execution, freeing resources.

This enables distributed timeout propagation: a client with a 5-second deadline calls Service A, which calls Service B. Both services know the original 5-second deadline and can react appropriately (fail fast if unable to complete in time).

### Q4: What's the difference between context.Canceled and context.DeadlineExceeded?

**Model Answer**:
- **context.Canceled**: Context was explicitly cancelled via cancel() function
- **context.DeadlineExceeded**: Context was auto-cancelled because deadline passed

Both return from ctx.Done() and ctx.Err(). Important for diagnostics: canceled = expected interruption, deadline exceeded = timeout (resource constraint or service lag).

### Q5: Design a request logger middleware that uses context.

**Model Answer**:
```go
func loggingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        traceID := generateTraceID()
        ctx := context.WithValue(r.Context(), traceIDKey, traceID)

        log.Printf("[%s] %s %s", traceID, r.Method, r.URL)

        startTime := time.Now()
        next.ServeHTTP(w, r.WithContext(ctx))
        duration := time.Since(startTime)

        log.Printf("[%s] completed in %v", traceID, duration)
    })
}
```

The trace ID flows through the entire request and appears in all logs.

### Q6: When would you use context.WithoutCancel? Provide a real-world example.

**Model Answer**:
Use `WithoutCancel` when you need background cleanup that must complete even if the request times out.

```go
// Example: User uploads file, triggers async processing
func uploadHandler(w http.ResponseWriter, r *http.Request) {
    file := r.FormFile("file")

    // Request context has 30-second deadline
    // But file processing should continue even if user disconnects
    go func() {
        // Cleanup context: same values (user ID, trace ID) but no timeout
        bgCtx := context.WithoutCancel(r.Context())

        if err := processFile(bgCtx, file); err != nil {
            logger.ErrorContext(bgCtx, "async processing failed", slog.String("error", err.Error()))
        }
    }()

    w.WriteHeader(http.StatusAccepted)
}
```

Without `WithoutCancel`, the background processing would be cancelled when the request ends.

### Q7: Design a distributed request timeout strategy for a microservices system.

**Model Answer**:
```go
// Architecture: Client (5s) -> API (10s) -> DB (3s)
// Total allowed time: min(5, 10, 3) = 3s

func clientCall() {
    // Client sets aggressive timeout (5s for user responsiveness)
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    // Call API service
    response, err := apiClient.Call(ctx, request)
    if errors.Is(err, context.DeadlineExceeded) {
        log.Println("API timeout: client-side timeout")
    }
}

func apiHandler(w http.ResponseWriter, r *http.Request) {
    // API receives context from client (might have 3s left)
    ctx := r.Context()

    // API reserves 1s for response overhead
    deadline, ok := ctx.Deadline()
    if ok {
        remaining := time.Until(deadline) - 1*time.Second
        if remaining < 0 {
            http.Error(w, "Timeout", http.StatusGatewayTimeout)
            return
        }
        ctx, _ = context.WithDeadline(ctx, deadline.Add(-1*time.Second))
    }

    // DB call has 2s (remaining - 1s overhead)
    result, err := dbClient.Query(ctx, query)
    if errors.Is(err, context.DeadlineExceeded) {
        log.Println("DB timeout: API didn't have enough time")
    }
}

// Key principles:
// 1. Each layer knows deadline from upstream
// 2. Each layer reserves time for its work
// 3. Fail fast if not enough time remains
// 4. Distribute budget: client (aggressive) > API (moderate) > DB (tight)
```

### Q8: How would you implement a context-aware message queue consumer?

**Model Answer**:
```go
type MessageConsumer struct {
    queue  chan Message
    handler func(context.Context, Message) error
}

func (mc *MessageConsumer) ConsumeWithContext(ctx context.Context) error {
    for {
        select {
        case <-ctx.Done():
            return ctx.Err()  // Graceful shutdown

        case msg := <-mc.queue:
            // Create timeout for each message
            msgCtx, cancel := context.WithTimeout(ctx, 30*time.Second)

            // Handle with deadline
            if err := mc.handler(msgCtx, msg); err != nil {
                if errors.Is(err, context.DeadlineExceeded) {
                    log.Printf("Message processing timeout: %v", msg)
                    // Could retry, DLQ, etc.
                }
            }

            cancel()
        }
    }
}

// HTTP handler that uses consumer
func httpHandler(w http.ResponseWriter, r *http.Request) {
    // Use request context with shorter deadline
    msgCtx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
    defer cancel()

    if err := consumer.ConsumeWithContext(msgCtx); err != nil {
        http.Error(w, "Processing failed", http.StatusInternalServerError)
    }
}
```

**Model Answer**:
Use `WithoutCancel` when you need background cleanup that must complete even if the request times out.

```go
// Example: User uploads file, triggers async processing
func uploadHandler(w http.ResponseWriter, r *http.Request) {
    file := r.FormFile("file")

    // Request context has 30-second deadline
    // But file processing should continue even if user disconnects
    go func() {
        // Cleanup context: same values (user ID, trace ID) but no timeout
        bgCtx := context.WithoutCancel(r.Context())

        if err := processFile(bgCtx, file); err != nil {
            logger.ErrorContext(bgCtx, "async processing failed", slog.String("error", err.Error()))
        }
    }()

    w.WriteHeader(http.StatusAccepted)
}
```

Without `WithoutCancel`, the background processing would be cancelled when the request ends.

---

## Part 11: Real-World Context Propagation Patterns

### Multi-Tier Service Architecture

```go
// Outer service: Client deadline 10 seconds
func ClientCallsServiceA(ctx context.Context) {
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    defer cancel()

    // Call Service A
    response, err := serviceAClient.DoWork(ctx)
    // Service A has 10 seconds to complete
}

// Service A: Receives context, calls Service B with tight deadline
func ServiceAHandler(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()  // Deadline: 10s from now

    // Service A needs 2s for its own work
    deadline, _ := ctx.Deadline()
    b2Ctx, _ := context.WithDeadline(ctx, deadline.Add(-2*time.Second))

    // Call Service B with only 8 seconds remaining
    response, err := serviceBClient.DoWork(b2Ctx)
}

// Service B: Even tighter deadline
func ServiceBHandler(w http.ResponseWriter, r *http.Request) {
    ctx := r.Context()  // Deadline: 8s from now

    // Database call with only 6 seconds
    deadline, _ := ctx.Deadline()
    dbCtx, _ := context.WithDeadline(ctx, deadline.Add(-2*time.Second))

    results := db.Query(dbCtx)
}

// Result: Deadline propagates through the entire call chain
// Each service knows how much time it has and can fail fast if not enough
```

---

## Tradeoffs and Best Practices

### Context vs Channels
- **Context**: For cancellation and timeouts
- **Channels**: For data passing and coordination
- **Both**: Use together; context for cancellation, channels for data

### Value Storage in Context
- **Pros**: Request-scoped, available anywhere in call stack
- **Cons**: Type-unsafe, immutable, harder to test
- Best practice: Only store immutable, request-scoped data (IDs, tokens, trace IDs)

### Timeout Strategy
- **Parent timeout**: Global limit on entire operation
- **Child timeouts**: Per-step limits, shorter for fast operations
- Cascade ensures resources freed promptly if any step fails

### Context Creation
- **HTTP Server**: net/http creates context automatically
- **gRPC Server**: grpc creates context with deadline
- **Custom code**: Create with WithCancel, WithTimeout, or WithDeadline as needed

---

## Exercise

Build a **multi-step booking checkout** with:
1. Phase 1: Payment processing (10-second timeout)
2. Phase 2: Seat locking (8-second timeout)
3. Phase 3: Confirmation storage (remaining time from global 25-second deadline)
4. Proper cleanup on timeout or cancellation
5. Trace ID logging through all phases
6. Correct error handling for each failure mode

Requirements:
- Must respect context cancellation
- Must propagate timeouts correctly
- Must log with trace ID
- Must handle deadline exceeded errors
- Must clean up resources (refund, unlock seats) on failure

Bonus: Add HTTP handler that respects client disconnect (r.Context().Done()), and graceful shutdown that gives in-flight requests 10 seconds to complete.

