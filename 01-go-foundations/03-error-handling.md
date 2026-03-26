# Error Handling: The Go Philosophy and Production Patterns

## The Problem

Coming from JavaScript/TypeScript's exceptions and try-catch, Go's explicit error returns feel verbose. But that verbosity is intentional: it forces you to **handle** errors, not just let them propagate through a stack unwinding.

At senior backend positions, you must:
- Understand error wrapping with `%w` and the unwrap chain
- Use `errors.Is()` and `errors.As()` correctly for error matching
- Design custom error types for domain-specific failures
- Know when to panic vs return error
- Handle errors in concurrent code (errgroup, goroutine error collection)
- Implement structured error logging for observability
- Know what panics look like in production (goroutine crashes)
- Avoid swallowing errors and error-string-matching antipatterns
- Handle database transactions with proper rollback

This lesson covers Go's error model from first principles to production patterns.

## Theory: The Error Model

### errors.New vs fmt.Errorf with %w: Error Wrapping Semantics

The basic error types:

```go
// Simple error: no context, no chain
var ErrNotFound = errors.New("movie not found")

// Wrapped error: preserves the original error in a chain
err := someOperation()
if err != nil {
	return fmt.Errorf("operation failed: %w", err)  // %w wraps
}

// Error message: no wrapping, just formatting (legacy pattern)
return fmt.Errorf("operation failed: %v", err)  // %v formats
```

The difference: `%w` creates an error that preserves the underlying error for later inspection with `errors.Is()` or `errors.As()`. The `%v` verb creates a formatted string message—you lose the original error type and can't inspect it.

```go
// With %w: chain preserved for inspection
origErr := sql.ErrNoRows
wrappedErr := fmt.Errorf("user query: %w", origErr)

if errors.Is(wrappedErr, sql.ErrNoRows) {
	fmt.Println("found original error")  // Prints! Chain is intact
}

// With %v: chain broken, just a string
wrappedErr2 := fmt.Errorf("user query: %v", origErr)
if errors.Is(wrappedErr2, sql.ErrNoRows) {
	fmt.Println("found original error")  // Never prints. origErr is buried in a string
}

// What wrappedErr2 becomes: "user query: no rows in result set"
// The sql.ErrNoRows is gone; it's now just text
```

Internally, `%w` sets the `Unwrap()` method on the error:

```go
// When you use %w, fmt.Errorf creates a type with Unwrap()
type wrapError struct {
	msg string
	err error
}

func (e *wrapError) Error() string {
	return e.msg
}

func (e *wrapError) Unwrap() error {
	return e.err  // This is what errors.Is and errors.As use
}

// When you use %v, it just calls Error() on the original and builds a string
// No Unwrap method, no way to get the original
```

**Rule**: Use `%w` when wrapping errors you want to inspect later. Use `%v` (or other verbs) when you're creating a formatted message without chaining.

**When NOT to wrap**: If an error is already wrapped with context from a lower layer, don't wrap it again. Too many layers make the error message unreadable:

```go
// BAD: Too many layers
err := database.Query(...)  // Returns "connection timeout"
err = fmt.Errorf("booking query: %w", err)  // "booking query: connection timeout"
err = fmt.Errorf("create booking: %w", err)  // "create booking: booking query: connection timeout"
err = fmt.Errorf("handle request: %w", err)  // "handle request: create booking: booking query: connection timeout"

// GOOD: Wrap once at boundaries
err := database.Query(...)
if err != nil {
	return fmt.Errorf("create booking: %w", err)  // One wrapping
}

// Caller can still inspect with errors.Is to find the root cause
```

### errors.Is and errors.As: Walking the Error Chain

When you wrap an error with `%w`, Go builds a chain. This chain is what gives error handling in Go its power.

```
fmt.Errorf("service: %w", fmt.Errorf("db: %w", sql.ErrNoRows))

Chain structure:
  ┌─────────────────────────────────┐
  │ msg: "service: db: no rows"     │
  │ Unwrap() → next error           │
  └─────────────────────────────────┘
           ↓
  ┌─────────────────────────────────┐
  │ msg: "db: no rows"              │
  │ Unwrap() → next error           │
  └─────────────────────────────────┘
           ↓
  ┌─────────────────────────────────┐
  │ sql.ErrNoRows (sentinel value)  │
  │ Unwrap() → nil (end of chain)   │
  └─────────────────────────────────┘
```

**errors.Is()** walks this chain looking for an exact value match:

```go
err := fmt.Errorf("service: %w", fmt.Errorf("db: %w", sql.ErrNoRows))

// errors.Is walks the chain:
// 1. errors.Unwrap(err) → fmt.Errorf("db: ...")
// 2. errors.Unwrap(fmt.Errorf("db: ...")) → sql.ErrNoRows
// 3. errors.Unwrap(sql.ErrNoRows) → nil
// Found sql.ErrNoRows in the chain!

if errors.Is(err, sql.ErrNoRows) {
	fmt.Println("found!")  // Prints
}

// Looks for ErrNotFound (not in chain)
if errors.Is(err, ErrNotFound) {
	fmt.Println("not found")  // Never prints
}
```

This is why sentinel errors (`var ErrNotFound = errors.New(...)`) work with `errors.Is()`. They're compared by identity (pointer equality).

**errors.As()** walks the chain looking for a type match (for custom error types with structured data):

```go
type ValidationError struct {
	Field string
	Message string
	StatusCode int
}

func (e *ValidationError) Error() string {
	return fmt.Sprintf("%s: %s", e.Field, e.Message)
}

// Create wrapped error
err := fmt.Errorf("booking: %w", &ValidationError{
	Field: "seats",
	Message: "invalid seat selection",
	StatusCode: 400,
})

// Extract the custom type from the chain
var valErr *ValidationError
if errors.As(err, &valErr) {
	fmt.Printf("field: %s, code: %d\n", valErr.Field, valErr.StatusCode)
	// field: seats, code: 400
}
```

The `errors.As()` call walks the chain and type-asserts each error:
1. Check if err is `*ValidationError` → yes! Extract and assign to valErr
2. If no match, unwrap and continue
3. Return false if chain exhausted

**Key differences**:
- `errors.Is()`: Exact value match (sentinel errors). Uses `==` comparison.
- `errors.As()`: Type match (custom error types). Uses type assertion.

**Rule of thumb**:
- Use `errors.Is()` with sentinel errors: `if errors.Is(err, sql.ErrNoRows) { ... }`
- Use `errors.As()` with custom types: `var valErr *ValidationError; if errors.As(err, &valErr) { ... }`

**Common mistake**: Using `==` instead of `errors.Is()`:

```go
// BAD: Fragile
if err == sql.ErrNoRows {
	// Won't match if err is "query: %w" wrapping sql.ErrNoRows
}

// GOOD: Walks the chain
if errors.Is(err, sql.ErrNoRows) {
	// Matches even if wrapped
}
```

### Sentinel Errors vs Custom Types vs Wrapped Errors

There are three error patterns. When to use each:

**1. Sentinel Errors**: Simple flags for specific conditions

```go
var (
	ErrNotFound = errors.New("not found")
	ErrUnauthorized = errors.New("unauthorized")
	ErrRateLimited = errors.New("rate limited")
)

func GetMovie(id string) (*Movie, error) {
	// ...
	return nil, ErrNotFound
}

// Check in caller
if errors.Is(err, ErrNotFound) {
	w.WriteHeader(http.StatusNotFound)
}
```

**Use when**: Binary condition, no additional data needed, needs to be package-level constant.

**2. Custom Error Types**: Structured errors with metadata

```go
type MovieError struct {
	Code    string  // "SEATS_UNAVAILABLE", "PAYMENT_DECLINED"
	Message string
	StatusCode int
	Retry   bool
}

func (e *MovieError) Error() string {
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func CreateBooking(ctx context.Context, seats []string) error {
	if unavailable(seats) {
		return &MovieError{
			Code: "SEATS_UNAVAILABLE",
			Message: "A1, A2 are no longer available",
			StatusCode: 409,
			Retry: true,
		}
	}
	return nil
}

// Check in caller
var movErr *MovieError
if errors.As(err, &movErr) {
	if movErr.Retry {
		// retry the request
	}
	w.WriteHeader(movErr.StatusCode)
}
```

**Use when**: Need to return structured data (codes, status, retry info) that callers need to inspect.

**3. Wrapped Errors**: Context layering with %w

```go
err := database.QueryUser(ctx, userID)
if err != nil {
	return fmt.Errorf("create booking: query user: %w", err)
}
```

**Use when**: Adding context as errors bubble up the call stack.

### When to Panic vs Return Error

Go doesn't use exceptions. It has `panic` (runtime crash) and explicit error returns.

**Panic is for programmer bugs that should never happen**:

```go
// BAD: Using panic for operational errors
if !userExists {
	panic("user must exist")  // No, user might not exist
}

// GOOD: Return error for operational failures
if !userExists {
	return fmt.Errorf("user not found: %s", userID)
}

// GOOD: Panic for impossible conditions
if userPointer == nil {
	panic("BUG: user pointer is nil after database query")
}
```

**When to panic**:
1. Initialize code (init, main): if config can't be read, panic
2. Programmer bugs: invariant violations that should never happen in production
3. Severe runtime issues: out of memory (not recoverable anyway)

**When to return error**:
1. User input is invalid
2. External service is unavailable
3. Database connection failed
4. File not found
5. Anything that could happen in normal operation

**Rule**: If a user could cause it, don't panic. Return an error.

### Error Handling in Concurrent Code

When multiple goroutines work together, you need to collect errors:

```go
package payment

import (
	"context"
	"fmt"
	"sync"
)

// Charge multiple movies in parallel, collect errors
func ChargeBatch(ctx context.Context, gateway PaymentGateway, bookings []Booking) error {
	var wg sync.WaitGroup
	errChan := make(chan error, len(bookings))

	for _, booking := range bookings {
		wg.Add(1)
		go func(b Booking) {
			defer wg.Done()
			_, err := gateway.Charge(ctx, b.ID, b.AmountCents)
			if err != nil {
				errChan <- fmt.Errorf("booking %s: %w", b.ID, err)
			}
		}(booking)
	}

	wg.Wait()
	close(errChan)

	// Collect all errors
	var errs []error
	for err := range errChan {
		errs = append(errs, err)
	}

	if len(errs) > 0 {
		return fmt.Errorf("batch charge failed: %v", errs)
	}

	return nil
}
```

**Better: use errgroup**:

```go
import "golang.org/x/sync/errgroup"

func ChargeBatch(ctx context.Context, gateway PaymentGateway, bookings []Booking) error {
	g, ctx := errgroup.WithContext(ctx)

	for _, booking := range bookings {
		booking := booking  // Capture for closure
		g.Go(func() error {
			_, err := gateway.Charge(ctx, booking.ID, booking.AmountCents)
			if err != nil {
				return fmt.Errorf("booking %s: %w", booking.ID, err)
			}
			return nil
		})
	}

	return g.Wait()  // Returns first error, or nil
}
```

`errgroup.WithContext()` cancels remaining goroutines if one fails.

### Error Handling with Database Transactions: The Defer Pattern

A transaction must either commit (all changes are permanent) or rollback (all changes are discarded). This is a fundamental property of ACID databases. Handling errors correctly is critical:

```go
func CreateBookingWithTransfer(ctx context.Context, conn *pgx.Conn, from, to string, amountCents int) error {
	// 1. Start transaction
	tx, err := conn.Begin(ctx)
	if err != nil {
		return fmt.Errorf("begin tx: %w", err)
	}

	// 2. Defer rollback (default: rollback on any error)
	defer tx.Rollback(ctx)  // Safe no-op if already committed

	// 3. Do work
	if err := debitUser(ctx, tx, from, amountCents); err != nil {
		return fmt.Errorf("debit user: %w", err)  // Rollback happens automatically
	}

	if err := creditUser(ctx, tx, to, amountCents); err != nil {
		return fmt.Errorf("credit user: %w", err)  // Rollback happens automatically
	}

	// 4. Commit if all operations succeeded
	if err := tx.Commit(ctx); err != nil {
		return fmt.Errorf("commit tx: %w", err)
	}

	return nil
}
```

Why the defer pattern?

1. **Simplicity**: No explicit rollback needed on every error. One defer handles all paths.
2. **Safety**: If an error occurs anywhere, rollback is guaranteed.
3. **Idempotence**: Calling Rollback after Commit is a no-op, so the defer is safe.

The execution flow:

```
Begin tx
  ↓
Defer Rollback (set up, not executed yet)
  ↓
Try: Debit
  ↓ (success)
Try: Credit
  ↓ (success)
Try: Commit
  ↓ (success)
Return nil
  ↓
Deferred Rollback executed (no-op, already committed)


---OR in case of error---

Begin tx
  ↓
Defer Rollback (set up)
  ↓
Try: Debit
  ↓ (FAILS)
Return error
  ↓
Deferred Rollback executed (ROLLBACK, no commit happened)
```

**Common mistake**: Not using defer, explicitly rolling back:

```go
// BAD: Easy to forget rollback
tx, _ := conn.Begin(ctx)
if err := debit(ctx, tx, ...); err != nil {
	tx.Rollback(ctx)  // Easy to forget
	return err
}
if err := credit(ctx, tx, ...); err != nil {
	tx.Rollback(ctx)  // Easy to forget
	return err
}
err := tx.Commit(ctx)
if err != nil {
	tx.Rollback(ctx)  // Need rollback after failed commit?
}
return err
```

With defer, you don't have to think about it.

## Production Code: Structured Movie Booking Errors

A realistic error handling system for movie bookings:

```go
package booking

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	"github.com/jackc/pgx/v5"
)

// Domain error codes
const (
	ErrCodeSeatsUnavailable = "SEATS_UNAVAILABLE"
	ErrCodePaymentDeclined = "PAYMENT_DECLINED"
	ErrCodeShowFull = "SHOW_FULL"
	ErrCodeInvalidSeat = "INVALID_SEAT"
	ErrCodeUserNotFound = "USER_NOT_FOUND"
	ErrCodeDatabaseError = "DATABASE_ERROR"
)

// BookingError is the structured error type for booking domain
type BookingError struct {
	Code string
	Message string
	StatusCode int
	Retryable bool
	Details map[string]any
	Cause error
}

func (e *BookingError) Error() string {
	if e.Cause != nil {
		return fmt.Sprintf("%s: %s (caused by: %v)", e.Code, e.Message, e.Cause)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}

func (e *BookingError) Unwrap() error {
	return e.Cause
}

// Sentinel error for specific conditions
var ErrShowNotFound = errors.New("show not found")

// Constructor functions for cleaner error creation
func NewSeatsUnavailableError(seats []string, cause error) *BookingError {
	return &BookingError{
		Code: ErrCodeSeatsUnavailable,
		Message: fmt.Sprintf("seats not available: %v", seats),
		StatusCode: 409,
		Retryable: true,
		Details: map[string]any{"seats": seats},
		Cause: cause,
	}
}

func NewPaymentDeclinedError(reason string) *BookingError {
	return &BookingError{
		Code: ErrCodePaymentDeclined,
		Message: fmt.Sprintf("payment declined: %s", reason),
		StatusCode: 402,
		Retryable: false,  // Don't retry payment failures
		Details: map[string]any{"reason": reason},
	}
}

// BookingService with comprehensive error handling
type BookingService struct {
	db *pgx.Conn
	gateway PaymentGateway
	logger *slog.Logger
}

func NewBookingService(db *pgx.Conn, gateway PaymentGateway, logger *slog.Logger) *BookingService {
	return &BookingService{db: db, gateway: gateway, logger: logger}
}

func (bs *BookingService) CreateBooking(ctx context.Context, userID string, seatNums []string) (string, error) {
	// Verify user exists
	var userExists bool
	err := bs.db.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM users WHERE id=$1)", userID).Scan(&userExists)
	if err != nil {
		bs.logger.Error("user query failed", slog.String("user_id", userID), slog.Any("err", err))
		return "", &BookingError{
			Code: ErrCodeDatabaseError,
			Message: "failed to verify user",
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}

	if !userExists {
		return "", &BookingError{
			Code: ErrCodeUserNotFound,
			Message: fmt.Sprintf("user not found: %s", userID),
			StatusCode: 404,
			Retryable: false,
		}
	}

	// Get seats with transaction
	tx, err := bs.db.Begin(ctx)
	if err != nil {
		return "", &BookingError{
			Code: ErrCodeDatabaseError,
			Message: "failed to start transaction",
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}
	defer tx.Rollback(ctx)

	// Check seat availability
	var available []string
	rows, _ := tx.Query(ctx, "SELECT seat_number FROM seats WHERE status='available' AND seat_number=ANY($1) ORDER BY seat_number", seatNums)
	available, _ = pgx.CollectRows(rows, pgx.RowToStructByName[struct{ SeatNumber string }])
	if len(available) < len(seatNums) {
		bs.logger.Warn("insufficient seats", slog.String("user_id", userID), slog.Int("requested", len(seatNums)), slog.Int("available", len(available)))
		return "", NewSeatsUnavailableError(seatNums, nil)
	}

	// Calculate cost and charge
	totalCents := len(seatNums) * 1500
	txn, err := bs.gateway.Charge(ctx, fmt.Sprintf("booking_%s", userID), totalCents)
	if err != nil {
		var payErr *PaymentError
		if errors.As(err, &payErr) && payErr.StatusCode == 402 {
			return "", NewPaymentDeclinedError(payErr.Message)
		}
		return "", &BookingError{
			Code: ErrCodePaymentDeclined,
			Message: fmt.Sprintf("payment failed: %s", err.Error()),
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}

	// Insert booking
	var bookingID string
	err = tx.QueryRow(ctx, `
		INSERT INTO bookings (user_id, transaction_id, total_amount_cents, created_at)
		VALUES ($1, $2, $3, NOW())
		RETURNING id
	`, userID, txn.ID, totalCents).Scan(&bookingID)
	if err != nil {
		return "", &BookingError{
			Code: ErrCodeDatabaseError,
			Message: "failed to insert booking",
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}

	// Mark seats as sold
	_, err = tx.Exec(ctx, `
		UPDATE seats SET status='sold', booking_id=$1 WHERE seat_number=ANY($2)
	`, bookingID, seatNums)
	if err != nil {
		return "", &BookingError{
			Code: ErrCodeDatabaseError,
			Message: "failed to mark seats as sold",
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}

	if err := tx.Commit(ctx); err != nil {
		return "", &BookingError{
			Code: ErrCodeDatabaseError,
			Message: "failed to commit transaction",
			StatusCode: 500,
			Retryable: true,
			Cause: err,
		}
	}

	bs.logger.Info("booking created",
		slog.String("booking_id", bookingID),
		slog.String("user_id", userID),
		slog.Int("seats", len(seatNums)),
		slog.Int("amount_cents", totalCents),
	)

	return bookingID, nil
}

// Error middleware for HTTP handlers
func ErrorMiddleware(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Capture response to check status
		next.ServeHTTP(w, r)
	})
}

// HTTP error response
func HandleBookingError(w http.ResponseWriter, logger *slog.Logger, err error) {
	var bookErr *BookingError
	if errors.As(err, &bookErr) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(bookErr.StatusCode)
		// Return structured error response
		json.NewEncoder(w).Encode(map[string]any{
			"error": bookErr.Code,
			"message": bookErr.Message,
			"retryable": bookErr.Retryable,
		})
		logger.Error("booking error", slog.String("code", bookErr.Code), slog.Any("err", bookErr))
		return
	}

	// Generic error
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusInternalServerError)
	json.NewEncoder(w).Encode(map[string]string{
		"error": "INTERNAL_ERROR",
		"message": "an internal error occurred",
	})
	logger.Error("unexpected error", slog.Any("err", err))
}
```

## Structured Error Logging

Use `log/slog` for structured errors that can be aggregated and searched:

```go
logger := slog.New(slog.NewJSONHandler(os.Stdout, nil))

// Good: structured fields
logger.Error("booking creation failed",
	slog.String("user_id", userID),
	slog.String("error_code", bookErr.Code),
	slog.Any("error", bookErr),
	slog.Bool("retryable", bookErr.Retryable),
)

// Bad: unstructured message
logger.Error(fmt.Sprintf("User %s booking failed: %v", userID, bookErr))
```

The structured approach allows log aggregation systems (Datadog, ELK, Honeycomb) to:
- Filter by error_code
- Group by user_id
- Alert on non-retryable errors
- Measure error rates over time

## Panic Recovery and Defer: Go's Exception-Like Mechanism

`recover()` is Go's way to catch a panic, and it **only works inside a deferred function**. This constraint is intentional—panics are meant to be exceptional.

```go
// Worker goroutine with panic recovery
func (bs *BookingService) ProcessPaymentsWorker(jobs <-chan PaymentJob) {
	defer func() {
		if r := recover(); r != nil {
			bs.logger.Error("payment worker panicked",
				slog.Any("panic", r),
				slog.String("stack", debug.Stack()),  // Get the stack trace
			)
			// Could restart worker, alert on-call, send to error tracking service
			// bs.alerting.NotifyOncall("payment worker crashed", r)
		}
	}()

	for job := range jobs {
		// If Charge panics, it's caught by the deferred recover above
		_ = bs.gateway.Charge(context.Background(), job.BookingID, job.AmountCents)
	}
}
```

**Critical behavior**: A panic in one goroutine only kills that goroutine; it doesn't crash the entire program. Other goroutines continue running:

```go
func main() {
	go func() {
		fmt.Println("G1 starting")
		panic("oops")  // This goroutine panics
		fmt.Println("G1 done")  // Never executes
	}()

	go func() {
		fmt.Println("G2 starting")
		time.Sleep(1 * time.Second)
		fmt.Println("G2 done")  // This DOES execute, panic doesn't affect it
	}()

	time.Sleep(2 * time.Second)
	fmt.Println("Main continuing")  // Program doesn't crash
}

// Output:
// G1 starting
// G2 starting
// G2 done
// Main continuing
```

This is why background workers and server handlers must recover panics. Without recovery, a panicked goroutine silently disappears and no one knows it crashed.

**Recovering is expensive**: Using recover has performance implications:

```go
// Benchmark: recover vs no panic
func BenchmarkRecover(b *testing.B) {
	for i := 0; i < b.N; i++ {
		func() {
			defer func() {
				_ = recover()
			}()
			// No panic, but defer is set up
		}()
	}
}
// Result: ~200ns per call (defer + recover overhead)

func BenchmarkNoDeferNoRecover(b *testing.B) {
	for i := 0; i < b.N; i++ {
		func() {
			// No defer, no recover
		}()
	}
}
// Result: ~10ns per call
```

So you shouldn't use recover in hot loops. Only use it at boundaries: goroutine entry, HTTP handler, RPC receiver.

**When to panic vs return error**: Go intentionally makes panics the exception, not the rule. The heuristic:

```go
// Panic for programmer errors (should never happen in production)
func (m Movie) GetDirector() *Director {
	if m.director == nil {
		panic("BUG: movie must have a director")  // This is a bug in the code
	}
	return m.director
}

// Return error for operational failures (might happen)
func GetMovieByID(ctx context.Context, db *pgx.Conn, id string) (*Movie, error) {
	// User might ask for a movie that doesn't exist
	// Database might be down
	// Network might be slow
	// These are operational failures, not bugs
	return db.QueryRow(ctx, "SELECT ... FROM movies WHERE id=$1", id).Scan(&m)
}

// Panic for initialization failures (can't recover)
func init() {
	if os.Getenv("DATABASE_URL") == "" {
		panic("DATABASE_URL environment variable not set")
		// Can't proceed; the program is misconfigured
	}
}
```

**Design principle**: If a user could cause it (invalid input, missing resource), return an error. If only a programmer bug could cause it (impossible invariant, code that's never supposed to execute), panic. If you can't recover (initialization failure), panic in init().

## Common Antipatterns and How to Avoid Them

**Antipattern 1: Silently ignoring errors**

```go
// BAD: Error silently ignored; no one knows this failed
_ = database.CreateBooking(ctx, booking)

// WORSE: Even worse to swallow and return success
if err := database.CreateBooking(ctx, booking); err != nil {
	// Silently log and return nil
	logger.Error("creation failed", slog.Any("err", err))
	return nil  // Caller thinks it succeeded!
}

// GOOD: Propagate errors up
if err := database.CreateBooking(ctx, booking); err != nil {
	return fmt.Errorf("create booking: %w", err)
}
```

Silent errors cause cascading failures. User thinks their booking was created, but it wasn't. They get confused, databases have inconsistent state.

**Antipattern 2: String matching on errors (fragile)**

```go
// BAD: Breaks if error message changes
if strings.Contains(err.Error(), "duplicate key") {
	// Handle duplicate key error
}

// Also fragile: Works in English, breaks on localization
if err.Error() == "user not found" {
	// What if error is "user not found" but in French?
}

// GOOD: Use errors.Is for sentinel errors
if errors.Is(err, ErrNotFound) {
	// Handle not found error
}

// GOOD: Use errors.As for structured errors with fields
var pgErr *pgconn.PgError
if errors.As(err, &pgErr) && pgErr.Code == "23505" {  // UNIQUE violation
	// Handle duplicate key error
}
```

String matching breaks when error messages change, during localization, or when third-party libraries change their messages.

**Antipattern 3: Panic in goroutines without recovery**

```go
// BAD: Goroutine crashes silently
go func() {
	riskyOperation()  // If this panics, goroutine dies, no one knows
}()
// main() continues, doesn't know background work failed

// WORSE: Panic in HTTP handler (crashes request-serving goroutine)
http.HandleFunc("/bookings", func(w http.ResponseWriter, r *http.Request) {
	riskyOperation()  // Panics, crashes this request handler
	// Other requests still work, but this one is gone
})

// GOOD: Recover in goroutines
go func() {
	defer func() {
		if r := recover(); r != nil {
			logger.Error("goroutine panicked", slog.Any("panic", r), slog.String("stack", debug.Stack()))
			metrics.PanicCounter.Inc()  // Alert on panics
		}
	}()
	riskyOperation()
}()

// GOOD: Recover at HTTP handler entry
func withPanicRecovery(h http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		defer func() {
			if r := recover(); r != nil {
				logger.Error("handler panicked", slog.Any("panic", r))
				w.WriteHeader(http.StatusInternalServerError)
			}
		}()
		h.ServeHTTP(w, r)
	})
}
```

**Antipattern 4: Wrapping errors too many times**

```go
// BAD: Error message is unreadable
err := database.Query(...)
if err != nil {
	err = fmt.Errorf("user query: %w", err)
	// Now: "user query: connection refused"
}
if err != nil {
	err = fmt.Errorf("fetch user: %w", err)
	// Now: "fetch user: user query: connection refused"
}
if err != nil {
	err = fmt.Errorf("handle request: %w", err)
	// Now: "handle request: fetch user: user query: connection refused"
	// Too many layers!
}
return err

// GOOD: Wrap once at the boundary
err := database.Query(...)
if err != nil {
	return fmt.Errorf("fetch user: %w", err)
	// Just: "fetch user: connection refused"
	// Still can inspect with errors.Is to find root cause
}
```

**Antipattern 5: Type assertion without checking**

```go
// BAD: Panics if type is wrong
var valErr *ValidationError
valErr = err.(*ValidationError)  // Panics if err is not *ValidationError

// GOOD: Use type assertion with ok check
var valErr *ValidationError
if err, ok := err.(*ValidationError); ok {
	fmt.Printf("field: %s\n", err.Field)
}

// BETTER: Use errors.As which walks the chain
var valErr *ValidationError
if errors.As(err, &valErr) {  // Safe, walks chain
	fmt.Printf("field: %s\n", valErr.Field)
}
```

## Interview Corner: Common Questions and Answers

**Q1: Explain the difference between %w and %v when wrapping errors.**

A: `%w` preserves the error in a chain that `errors.Is()` and `errors.As()` can walk. With `%w`, you can later check if the underlying error matches a sentinel: `errors.Is(wrappedErr, sql.ErrNoRows)`. With `%v`, you just get a formatted string and lose the chain—you can only do string matching, which is fragile. Always use `%w` when you intend for callers to inspect the error.

**Q2: How do you extract a custom error type from a wrapped error?**

A: Use `errors.As()`. Example: `var validErr *ValidationError; if errors.As(err, &validErr) { process(validErr.Field) }`. It walks the unwrap chain looking for a type match. This is different from `errors.Is()`, which matches values.

**Q3: When should you use sentinel errors vs custom error types?**

A: Sentinel errors (`var ErrNotFound = errors.New(...)`) for binary conditions where you don't need metadata. Custom types (`type PaymentError struct { Code, Message string }`) when you need to return structured data the caller must inspect. Sentinel errors are constants; custom types can carry dynamic data.

**Q4: Your goroutine panics and crashes. Why doesn't this crash the entire program?**

A: Go runs each goroutine independently. A panic in one goroutine only kills that goroutine; the main goroutine and other goroutines continue. If you need the program to fail fast on any goroutine panic, you must either recover and propagate the error, or use errgroup to cancel on first error.

**Q5: How should you structure errors in a multi-layer system (HTTP handler → service → database)?**

A: Add context as you go up: `database returns sql.ErrNoRows → service wraps "user not found: %w" → handler responds with 404`. Each layer sees the original error but adds context. Callers should check for domain errors (payment declined) not database errors (connection timeout).

**Q6: You have a function that can error in two different ways: invalid input or external service failure. How do you let the caller know which it is?**

A: Use custom error types: `type ValidationError struct {...}`, `type ServiceError struct {...}`. Return the appropriate one. Caller uses `errors.As()` to check. Or use structured sentinel errors like `ErrInvalidInput`, `ErrServiceUnavailable`. Avoid magic error strings.

**Q7: How do you collect errors from multiple concurrent goroutines?**

A: Use `errgroup.WithContext()` which automatically cancels on first error and returns it, or use a manual error channel: `errChan := make(chan error, n)` and collect from it after `wg.Wait()`. errgroup is cleaner for most cases.

**Q8: Explain the defer + Rollback pattern for transactions.**

A: Begin a transaction, defer Rollback, do work, Commit if successful. Rollback is a no-op if Commit succeeded. If any error occurs, the deferred Rollback executes automatically. This ensures failed transactions always rollback without explicit error handling in every branch.

**Q9: You have a function that returns an error. The caller checks `if err != nil` but the error might be wrapped multiple times. How do you ensure the caller can still detect a specific error?**

A: The caller should use `errors.Is()` or `errors.As()` instead of `==` comparison. These functions walk the unwrap chain built by `fmt.Errorf(..., %w, ...)`. So if your function returns `fmt.Errorf("db: %w", sql.ErrNoRows)`, the caller can do `if errors.Is(err, sql.ErrNoRows)` and it will still match, even though the error is wrapped.

**Q10: How should you design errors in a business domain like movie booking?**

A: Create custom error types that carry structured data: `type BookingError struct { Code, Message string; StatusCode int; Retryable bool }`. This lets your service layer communicate not just what went wrong, but how to respond. The handler can check `errors.As(err, &bookErr)` and use `bookErr.StatusCode` for HTTP response, `bookErr.Retryable` to decide whether to retry, etc. This separates error handling concerns across layers cleanly.

**Q11: How do you debug a production issue where errors are being lost?**

A: First, ensure all errors are logged with full context (use structured logging with slog). Second, ensure errors are wrapped with `%w` so the chain is preserved. Use error aggregation services (Sentry, Datadog) to track error patterns. Finally, in your application, add instrumentation counters for each error code so you can see error rates in real time. This lets you catch issues before users do.

## What Breaks at Scale

1. **Swallowed errors**: `_ = operation()` without checking means silent failures and cascading issues. A movie booking silently fails to charge the credit card, database becomes inconsistent.
2. **String matching on errors**: Fragile if error messages change; breaks during localization or library updates.
3. **Panics in goroutines**: A single panicked background goroutine crashes and you don't notice until 3AM when the payment processor stopped working.
4. **Not wrapping errors**: Loss of context as errors bubble up. Was it a network error or a bad request? "error" doesn't tell you.
5. **Returning interface{}**: Callers must type-assert every error, easy to miss cases and crashes.
6. **Error strings in logs**: Unstructured "failed to create booking: connection refused" can't be aggregated by error code, filtered, or alerted on.
7. **Not retrying transient errors**: Network timeouts (5XX errors, connection resets) cause permanent failures when a retry would succeed.
8. **Wrong panic/error choice**: Panicking on invalid user input crashes the server. Returning error (and logging it) is the right choice.
9. **Nested error handling**: Too many defer blocks or error handlers create spaghetti code that's hard to reason about.

## Real-World Error Patterns

In production systems, errors must be:
1. **Structured**: Carry codes, messages, metadata for automation
2. **Loggable**: Include context for debugging
3. **Actionable**: HTTP handlers know what status to return
4. **Retryable**: Some errors should trigger automatic retries

A movie booking system needs:
- SeatUnavailableError (409 Conflict, don't retry)
- PaymentDeclinedError (402 Payment Required, maybe retry)
- DatabaseError (500 Internal, retry with backoff)
- ValidationError (400 Bad Request, don't retry)

This separation allows:
- Caller decides retry strategy based on error type
- HTTP handler picks correct status code
- Logging system routes errors to right dashboards
- Metrics track error rates by category

## Exercise

**Exercise 1: Custom Error Types**

Design error types for the movie booking domain:
- `SeatsUnavailableError` with a list of unavailable seats
- `PaymentError` with a reason code (DECLINED, TIMEOUT, etc.)
- `ValidationError` with field name and message

Write code that returns these errors and show how to check for them with `errors.As()`.

**Exercise 2: Error Wrapping and Inspection**

Write a function that:
1. Calls a database query that can fail
2. Wraps the error with context
3. Returns it to a caller
4. Caller checks if the original error is `sql.ErrNoRows` using `errors.Is()`
5. Show what breaks if you use `%v` instead of `%w`

**Exercise 3: Transaction with Proper Rollback**

Write a function that:
1. Starts a transaction
2. Defers Rollback
3. Does multiple database operations
4. Returns an error from one operation
5. Verify that Rollback is called

Use pgx and verify the transaction never committed.

**Exercise 4: Concurrent Error Collection**

Implement:
- A function that charges 100 bookings in parallel
- Collect errors from failed charges
- Return a summary error listing all failures
- Do it both with manual channels and with errgroup

**Exercise 5: HTTP Error Responses**

Write an HTTP handler that:
1. Calls a service that returns your custom error types
2. Maps each error type to an HTTP status code
3. Returns a JSON response with the error code and message
4. Write tests that verify each error type maps correctly

**Exercise 6: Recover in Goroutines**

Write a worker pool that processes jobs from a channel:
- Each worker goroutine should recover panics
- On panic, log the error and re-queue the job for retry
- Show the difference between with and without recovery in a test

**Exercise 7: Error Wrapping Chain**

Write code that creates an error chain:
1. Inner: custom PaymentError with structured fields
2. Middle: wrapped with context "service layer"
3. Outer: wrapped with context "HTTP handler"

Show how errors.Is and errors.As can inspect at each level.

