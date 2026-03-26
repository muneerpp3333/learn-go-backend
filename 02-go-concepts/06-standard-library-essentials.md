# Standard Library Essentials: Building Production Systems

## Problem: Mastering the Tools You'll Use Every Day

You need to:
- Build HTTP servers with middleware and proper timeouts
- Parse and generate JSON with type safety and custom marshaling
- Handle structured logging with context integration
- Manage time, timers, and timezone conversions
- Secure applications with crypto and TLS
- Optimize I/O with buffering and composition

The Go standard library is deliberately minimal but powerful. Mastering it is critical for senior backend engineers.

---

## Part 1: net/http — HTTP Servers and Clients

### HTTP Server Basics

```go
import "net/http"

func main() {
    // Simple handler
    http.HandleFunc("/hello", func(w http.ResponseWriter, r *http.Request) {
        w.Header().Set("Content-Type", "text/plain")
        w.WriteHeader(http.StatusOK)
        w.Write([]byte("Hello, World!"))
    })

    // Create server with timeouts
    server := &http.Server{
        Addr:         ":8080",
        Handler:      http.DefaultServeMux,
        ReadTimeout:  5 * time.Second,   // Time to read request
        WriteTimeout: 10 * time.Second,  // Time to write response
        IdleTimeout:  60 * time.Second,  // Keep-alive timeout
    }

    if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
        log.Fatal(err)
    }
}
```

**Timeout meanings**:
- **ReadTimeout**: Max time to read entire request (headers + body)
- **WriteTimeout**: Max time to write response
- **IdleTimeout**: Max time a keep-alive connection stays idle before closing

**Important**: Don't use `http.DefaultServeMux` in production; always create custom mux or router.

### Graceful Shutdown

```go
func main() {
    server := &http.Server{
        Addr:    ":8080",
        Handler: myRouter,
    }

    // Start server in goroutine
    go func() {
        if err := server.ListenAndServe(); err != nil && err != http.ErrServerClosed {
            log.Printf("server error: %v", err)
        }
    }()

    // Wait for shutdown signal
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
    <-sigChan

    // Graceful shutdown: stop accepting new connections, wait for existing requests
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    if err := server.Shutdown(ctx); err != nil {
        log.Printf("shutdown error: %v", err)
    }

    log.Println("server shut down gracefully")
}
```

### Middleware Pattern

```go
// Middleware type
type Middleware func(http.Handler) http.Handler

// Logging middleware
func LoggingMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        start := time.Now()
        next.ServeHTTP(w, r)
        duration := time.Since(start)
        log.Printf("%s %s took %v", r.Method, r.URL.Path, duration)
    })
}

// Recovery middleware
func RecoveryMiddleware(next http.Handler) http.Handler {
    return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
        defer func() {
            if err := recover(); err != nil {
                log.Printf("panic: %v", err)
                http.Error(w, "Internal Server Error", http.StatusInternalServerError)
            }
        }()
        next.ServeHTTP(w, r)
    })
}

// Chain middlewares
func chainMiddleware(middlewares ...Middleware) func(http.Handler) http.Handler {
    return func(next http.Handler) http.Handler {
        for i := len(middlewares) - 1; i >= 0; i-- {
            next = middlewares[i](next)
        }
        return next
    }
}

// Usage
handler := chainMiddleware(LoggingMiddleware, RecoveryMiddleware)(myHandler)
server := &http.Server{
    Addr:    ":8080",
    Handler: handler,
}
```

### HTTP Client with Connection Pooling

```go
// DON'T: Use http.DefaultClient (no timeout)
resp, err := http.Get("http://cinema-api.local/m1")  // DANGER: can hang forever

// DO: Create client with timeouts and pooling
client := &http.Client{
    Timeout: 10 * time.Second,  // Overall request timeout
    Transport: &http.Transport{
        MaxIdleConns:        100,
        MaxIdleConnsPerHost: 10,
        MaxConnsPerHost:     100,
        IdleConnTimeout:     90 * time.Second,
        DialTimeout:         5 * time.Second,
        TLSHandshakeTimeout: 5 * time.Second,
        ResponseHeaderTimeout: 5 * time.Second,
    },
}

resp, err := client.Get("http://cinema-api.local/m1")
if err != nil {
    if errors.Is(err, context.DeadlineExceeded) {
        log.Print("request timeout")
    }
    return err
}
defer resp.Body.Close()
```

**Connection pooling benefits**:
- Reuses TCP connections (avoids 3-way handshake overhead)
- Reduces latency for repeated requests
- Default pool is efficient; only tune if needed

---

## Part 2: encoding/json — Parsing and Generating JSON

### Struct Tags and JSON Marshal

```go
type Movie struct {
    ID    string `json:"id"`
    Title string `json:"title"`
    Year  int    `json:"year"`
    // Unexported fields are ignored in JSON
    internal string
}

// Marshal: Go -> JSON
movie := Movie{ID: "m1", Title: "Inception", Year: 2010}
jsonBytes, err := json.Marshal(movie)
// Output: {"id":"m1","title":"Inception","year":2010}

// Unmarshal: JSON -> Go
var parsed Movie
err := json.Unmarshal(jsonBytes, &parsed)
```

### Tag Options

```go
type User struct {
    ID       string `json:"id"`                    // Standard field
    Email    string `json:"email,omitempty"`       // Omit if empty
    Password string `json:"-"`                     // Never marshal
    Name     string `json:"name,string"`           // Convert to/from string
    Count    int    `json:"count,omitempty,string"` // Multiple options
}

// omitempty: Don't include field if zero value
// -: Skip this field entirely
// string: Convert to/from JSON string
```

**Important gotcha**:

```go
type Booking struct {
    Seats []string `json:"seats,omitempty"`
}

// Empty slice IS NOT omitted (only nil is)!
booking := Booking{Seats: []string{}}
json.Marshal(booking)
// Output: {"seats":[]}  -- NOT {""}

// To omit empty slices, use nil:
booking := Booking{Seats: nil}
```

### Custom Marshaler/Unmarshaler

```go
type Timestamp time.Time

// Implement json.Marshaler
func (t Timestamp) MarshalJSON() ([]byte, error) {
    return []byte(fmt.Sprintf("\"%s\"", time.Time(t).Format(time.RFC3339))), nil
}

// Implement json.Unmarshaler
func (t *Timestamp) UnmarshalJSON(data []byte) error {
    var s string
    if err := json.Unmarshal(data, &s); err != nil {
        return err
    }
    parsed, err := time.Parse(time.RFC3339, s)
    if err != nil {
        return err
    }
    *t = Timestamp(parsed)
    return nil
}

// Usage
type Booking struct {
    CreatedAt Timestamp `json:"created_at"`
}

booking := Booking{CreatedAt: Timestamp(time.Now())}
jsonBytes, _ := json.Marshal(booking)
// Output: {"created_at":"2024-03-26T12:34:56Z"}
```

### Streaming JSON

For large files or continuous data:

```go
// Streaming decoder (memory efficient)
func processBookings(file *os.File) error {
    decoder := json.NewDecoder(file)  // Parses incrementally

    for decoder.More() {
        var booking Booking
        if err := decoder.Decode(&booking); err != nil {
            return err
        }
        // Process one booking at a time (constant memory)
    }

    return nil
}

// Streaming encoder
func writeBookings(file *os.File, bookings []Booking) error {
    encoder := json.NewEncoder(file)

    for _, booking := range bookings {
        if err := encoder.Encode(booking); err != nil {
            return err
        }
    }

    return nil
}
```

---

## Part 3: slog — Structured Logging

Go 1.21+ structured logging standard.

### Basic Logging

```go
import "log/slog"

func main() {
    // Default JSON handler
    handler := slog.NewJSONHandler(os.Stderr, nil)
    logger := slog.New(handler)

    logger.Info("booking created",
        slog.String("booking_id", "b123"),
        slog.String("user_id", "u456"),
        slog.Int("seats", 2),
    )
    // Output: {"time":"...","level":"INFO","msg":"booking created","booking_id":"b123","user_id":"u456","seats":2}
}
```

### Log Levels

```go
logger.Debug("detailed info", slog.String("key", "value"))     // Won't appear by default
logger.Info("normal operation", slog.String("key", "value"))
logger.Warn("unexpected but recoverable", slog.String("key", "value"))
logger.Error("error occurred", slog.String("key", "value"))
```

### Context Integration

```go
// Attach values to context
type loggerKey struct{}

ctx := context.Background()
ctx = context.WithValue(ctx, loggerKey{}, logger)

// Extract and use logger
func handleRequest(ctx context.Context) {
    logger := ctx.Value(loggerKey{}).(*slog.Logger)

    logger.InfoContext(ctx, "handling request",
        slog.String("user_id", "u123"),
    )
}
```

### Structured Groups

```go
logger.Info("operation",
    slog.Group("request",
        slog.String("method", "POST"),
        slog.String("path", "/book"),
    ),
    slog.Group("response",
        slog.Int("status", 200),
        slog.Int("latency_ms", 45),
    ),
)
// Output: {"request":{"method":"POST","path":"/book"},"response":{"status":200,"latency_ms":45}}
```

---

## Part 4: time — Handling Time and Timezones

### time.Time and Duration

```go
now := time.Now()
tomorrow := now.AddDate(0, 0, 1)        // Add 1 day
inTenSeconds := now.Add(10 * time.Second)

duration := tomorrow.Sub(now)  // time.Duration

// Parse time
t, err := time.Parse(time.RFC3339, "2024-03-26T12:34:56Z")

// Format time
formatted := now.Format(time.RFC3339)  // "2024-03-26T12:34:56Z"
formatted2 := now.Format("2006-01-02 15:04:05")  // Custom format
```

### Timezone Handling

```go
// DANGER: time.Parse ignores timezone info!
t, _ := time.Parse(time.RFC3339, "2024-03-26T12:00:00+05:00")
// t is in UTC, not +05:00!

// SAFE: Specify location
loc, _ := time.LoadLocation("Asia/Karachi")  // +05:00
t := time.Date(2024, 3, 26, 12, 0, 0, 0, loc)

// Or specify layout with timezone
t, _ := time.Parse("2006-01-02 15:04:05 MST", "2024-03-26 12:00:00 PKT")

// Always use RFC3339 for APIs
formatted := t.Format(time.RFC3339)
```

### Monotonic Clock

```go
// Regular clock (can go backward if system time adjusted)
start := time.Now()
// ... some operation ...
elapsed := time.Since(start)  // Can be negative if clock adjusted!

// Monotonic clock (always increases, good for measuring)
startMono := time.Now()
// ... some operation ...
elapsedMono := time.Since(startMono)  // Always positive

// time.Since uses monotonic clock internally (safe for benchmarking)
```

### Timer and Ticker

```go
// One-shot timer
timer := time.NewTimer(5 * time.Second)
defer timer.Stop()  // IMPORTANT: Prevents goroutine leak

select {
case <-timer.C:
    log.Print("timeout")
case <-ctx.Done():
    return
}

// Repeating ticker
ticker := time.NewTicker(1 * time.Second)
defer ticker.Stop()

for {
    select {
    case <-ticker.C:
        log.Print("tick")
    case <-ctx.Done():
        return
    }
}
```

---

## Part 5: io Package — Composition and Reader/Writer

### Reader/Writer Interface

```go
type Reader interface {
    Read(p []byte) (n int, err error)
}

type Writer interface {
    Write(p []byte) (n int, err error)
}

// Composition: chain readers
func copyWithModification(src io.Reader, dst io.Writer) error {
    // Decompress -> Parse -> Process -> Encode -> Write
    gzipped, _ := gzip.NewReader(src)
    decoder := json.NewDecoder(gzipped)
    encoder := json.NewEncoder(dst)

    for decoder.More() {
        var item interface{}
        if err := decoder.Decode(&item); err != nil {
            return err
        }
        // Process item
        if err := encoder.Encode(item); err != nil {
            return err
        }
    }

    return nil
}

// io.Copy: Generic copying
written, err := io.Copy(dst, src)  // Buffer size optimized automatically
```

### bufio for Performance

```go
// Without buffering: syscall per read (slow)
for {
    var b [1]byte
    if _, err := file.Read(b[:]); err != nil {
        break
    }
    process(b[0])
}

// With buffering: fewer syscalls (fast)
scanner := bufio.NewScanner(file)
for scanner.Scan() {
    processLine(scanner.Text())
}

// Or manual buffering with Writer
writer := bufio.NewWriter(file)
for item := range items {
    writer.WriteString(item)
}
writer.Flush()  // IMPORTANT: Flush before closing
```

---

## Part 6: crypto Package — Hashing and Encryption

### Hashing

```go
import "crypto/sha256"

// SHA-256
hash := sha256.Sum256([]byte("password"))
hashStr := hex.EncodeToString(hash[:])

// For passwords: use bcrypt, not SHA-256!
import "golang.org/x/crypto/bcrypt"

hashedPassword, err := bcrypt.GenerateFromPassword([]byte("password"), bcrypt.DefaultCost)
err = bcrypt.CompareHashAndPassword(hashedPassword, []byte("password"))
```

### HMAC

```go
import "crypto/hmac"

func sign(message, secret string) string {
    h := hmac.New(sha256.New, []byte(secret))
    h.Write([]byte(message))
    return hex.EncodeToString(h.Sum(nil))
}

func verify(message, secret, signature string) bool {
    expected := sign(message, secret)
    return hmac.Equal([]byte(signature), []byte(expected))
}
```

### TLS/TLS Configuration

```go
// Client with custom TLS
client := &http.Client{
    Transport: &http.Transport{
        TLSClientConfig: &tls.Config{
            InsecureSkipVerify: false,  // Always verify in production!
            MinVersion:        tls.VersionTLS12,
        },
    },
}

// Server with TLS
server := &http.Server{
    Addr:      ":443",
    Handler:   myHandler,
    TLSConfig: &tls.Config{
        MinVersion: tls.VersionTLS12,
    },
}

if err := server.ListenAndServeTLS("cert.pem", "key.pem"); err != nil {
    log.Fatal(err)
}
```

---

## Part 7: embed Package — Static Files

### Embedding Files

```go
import "embed"

//go:embed templates/*
var templates embed.FS

//go:embed static/*
var staticFiles embed.FS

func getTemplate(name string) (*template.Template, error) {
    content, err := templates.ReadFile(name)
    if err != nil {
        return nil, err
    }
    return template.New(name).Parse(string(content))
}

func serveStatic(w http.ResponseWriter, r *http.Request) {
    content, _ := staticFiles.ReadFile(r.URL.Path[1:])
    w.Header().Set("Content-Type", "text/plain")
    w.Write(content)
}
```

---

## Part 8: Production HTTP Server Example

Complete implementation with all best practices.

```go
package main

import (
    "context"
    "encoding/json"
    "errors"
    "log/slog"
    "net"
    "net/http"
    "os"
    "os/signal"
    "sync"
    "syscall"
    "time"
)

// Movie booking API server
type BookingServer struct {
    server *http.Server
    logger *slog.Logger
    db     *sql.DB
}

func NewBookingServer(addr string, logger *slog.Logger) *BookingServer {
    bs := &BookingServer{
        logger: logger,
    }

    mux := http.NewServeMux()

    // Apply middleware
    handler := chainMiddleware(
        loggingMiddleware(bs.logger),
        recoveryMiddleware(bs.logger),
        timeoutMiddleware(30 * time.Second),
    )(mux)

    // Routes
    mux.HandleFunc("POST /book", bs.handleBook)
    mux.HandleFunc("GET /bookings/{id}", bs.handleGetBooking)
    mux.HandleFunc("GET /health", bs.handleHealth)

    bs.server = &http.Server{
        Addr:         addr,
        Handler:      handler,
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 10 * time.Second,
        IdleTimeout:  60 * time.Second,
        ErrorLog:     slog.NewLogLogger(logger.Handler(), slog.LevelError),
    }

    return bs
}

// Middleware chain
type middlewareFunc func(http.Handler) http.Handler

func chainMiddleware(middlewares ...middlewareFunc) middlewareFunc {
    return func(next http.Handler) http.Handler {
        for i := len(middlewares) - 1; i >= 0; i-- {
            next = middlewares[i](next)
        }
        return next
    }
}

func loggingMiddleware(logger *slog.Logger) middlewareFunc {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            start := time.Now()

            // Wrap response writer to capture status code
            wrapper := &responseWrapper{ResponseWriter: w, statusCode: http.StatusOK}

            next.ServeHTTP(wrapper, r)

            duration := time.Since(start)
            logger.InfoContext(r.Context(), "request completed",
                slog.String("method", r.Method),
                slog.String("path", r.URL.Path),
                slog.Int("status", wrapper.statusCode),
                slog.Float64("duration_ms", float64(duration.Milliseconds())),
            )
        })
    }
}

func recoveryMiddleware(logger *slog.Logger) middlewareFunc {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            defer func() {
                if err := recover(); err != nil {
                    logger.ErrorContext(r.Context(), "panic recovered",
                        slog.String("panic", fmt.Sprintf("%v", err)),
                    )
                    http.Error(w, "Internal Server Error", http.StatusInternalServerError)
                }
            }()
            next.ServeHTTP(w, r)
        })
    }
}

func timeoutMiddleware(timeout time.Duration) middlewareFunc {
    return func(next http.Handler) http.Handler {
        return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
            ctx, cancel := context.WithTimeout(r.Context(), timeout)
            defer cancel()
            next.ServeHTTP(w, r.WithContext(ctx))
        })
    }
}

// Handlers
type BookingRequest struct {
    UserID  string   `json:"user_id"`
    MovieID string   `json:"movie_id"`
    SeatIDs []string `json:"seat_ids"`
}

type BookingResponse struct {
    BookingID string `json:"booking_id"`
    CreatedAt string `json:"created_at"`
}

func (bs *BookingServer) handleBook(w http.ResponseWriter, r *http.Request) {
    var req BookingRequest
    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        http.Error(w, "Invalid request", http.StatusBadRequest)
        return
    }

    // Validate
    if req.UserID == "" || req.MovieID == "" {
        http.Error(w, "Missing required fields", http.StatusBadRequest)
        return
    }

    // Business logic with context
    bookingID, err := bs.createBooking(r.Context(), req)
    if err != nil {
        if errors.Is(err, context.DeadlineExceeded) {
            http.Error(w, "Request timeout", http.StatusGatewayTimeout)
        } else {
            http.Error(w, "Booking failed", http.StatusInternalServerError)
        }
        return
    }

    // Response
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusCreated)
    json.NewEncoder(w).Encode(BookingResponse{
        BookingID: bookingID,
        CreatedAt: time.Now().Format(time.RFC3339),
    })
}

func (bs *BookingServer) handleGetBooking(w http.ResponseWriter, r *http.Request) {
    bookingID := r.PathValue("id")
    // Get booking logic
    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(map[string]string{"booking_id": bookingID})
}

func (bs *BookingServer) handleHealth(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    json.NewEncoder(w).Encode(map[string]string{"status": "healthy"})
}

func (bs *BookingServer) createBooking(ctx context.Context, req BookingRequest) (string, error) {
    // Use ctx for database query with timeout
    const query = `
        INSERT INTO bookings (user_id, movie_id, seat_ids, created_at)
        VALUES ($1, $2, $3, NOW())
        RETURNING id
    `

    var bookingID string
    err := bs.db.QueryRowContext(ctx, query, req.UserID, req.MovieID, req.SeatIDs).Scan(&bookingID)
    return bookingID, err
}

func (bs *BookingServer) Start() error {
    bs.logger.InfoContext(context.Background(), "server starting", slog.String("addr", bs.server.Addr))
    return bs.server.ListenAndServe()
}

func (bs *BookingServer) Shutdown(ctx context.Context) error {
    bs.logger.InfoContext(ctx, "server shutting down")
    return bs.server.Shutdown(ctx)
}

// Main
func main() {
    // Logger
    handler := slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
        Level: slog.LevelInfo,
    })
    logger := slog.New(handler)

    // Server
    server := NewBookingServer(":8080", logger)

    // Start in goroutine
    go func() {
        if err := server.Start(); err != nil && err != http.ErrServerClosed {
            logger.Error("server error", slog.String("error", err.Error()))
        }
    }()

    // Wait for shutdown signal
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)
    <-sigChan

    // Graceful shutdown
    ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
    defer cancel()

    if err := server.Shutdown(ctx); err != nil {
        logger.Error("shutdown error", slog.String("error", err.Error()))
    }

    logger.InfoContext(context.Background(), "server shut down")
}

// Response wrapper to capture status code
type responseWrapper struct {
    http.ResponseWriter
    statusCode int
}

func (w *responseWrapper) WriteHeader(code int) {
    w.statusCode = code
    w.ResponseWriter.WriteHeader(code)
}
```

---

## Part 8: HTTP Timeouts and What Happens Without Them

Understanding timeout interactions is critical:

```go
// DANGER: No timeouts = can hang forever
client := &http.Client{}
resp, err := client.Get("http://slow-api.example.com")
// If server never responds, goroutine waits forever

// FIXED: Set explicit timeouts
client := &http.Client{
    Timeout: 10 * time.Second,  // Overall timeout for entire request

    Transport: &http.Transport{
        DialTimeout:           5 * time.Second,    // TCP connect timeout
        TLSHandshakeTimeout:   5 * time.Second,    // TLS handshake timeout
        ResponseHeaderTimeout: 3 * time.Second,    // Time to receive response headers
        IdleConnTimeout:       90 * time.Second,   // Keep-alive timeout
    },
}

// Server-side timeouts prevent slow clients from tying up resources
server := &http.Server{
    Addr:         ":8080",
    Handler:      handler,
    ReadTimeout:  5 * time.Second,     // Time to read full request
    WriteTimeout: 10 * time.Second,    // Time to write response
    IdleTimeout:  60 * time.Second,    // Keep-alive idle timeout
}

// What happens with each timeout:
// ReadTimeout: Client takes > 5s to send request? Connection closed.
// WriteTimeout: Response takes > 10s to send? Connection closed.
// IdleTimeout: Connection idle > 60s? Closed (prevents connection leaks).

// GOTCHA: ReadTimeout includes time reading request body
// A 100MB upload to a slow client might trigger ReadTimeout
// Solution: Use context with per-operation timeouts instead

func slowUploadHandler(w http.ResponseWriter, r *http.Request) {
    // Don't rely on ReadTimeout for large uploads
    // Use io.CopyN with size limits instead
    written, err := io.CopyN(w, r.Body, maxUploadSize)
    if err != nil {
        http.Error(w, "Upload failed", http.StatusBadRequest)
    }
}
```

---

## Part 9: HTTP RoundTripper for Custom Transports

`http.RoundTripper` is the interface for making HTTP requests. Customize it for logging, retries, auth injection:

```go
import "net/http"

// Custom RoundTripper: Add headers to every request
type AuthRoundTripper struct {
    token string
    next  http.RoundTripper
}

func (rt *AuthRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
    req.Header.Add("Authorization", fmt.Sprintf("Bearer %s", rt.token))
    return rt.next.RoundTrip(req)
}

// Custom RoundTripper: Retry on transient errors
type RetryRoundTripper struct {
    maxRetries int
    next       http.RoundTripper
}

func (rt *RetryRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
    for i := 0; i < rt.maxRetries; i++ {
        resp, err := rt.next.RoundTrip(req)

        // Retry on transient errors (connection reset, timeout)
        if isTransientError(err) {
            time.Sleep(time.Duration(i+1) * 100 * time.Millisecond)
            continue
        }

        return resp, err
    }
    return nil, fmt.Errorf("max retries exceeded")
}

// Use with HTTP client
client := &http.Client{
    Transport: &RetryRoundTripper{
        maxRetries: 3,
        next: &AuthRoundTripper{
            token: "secret-token",
            next:  http.DefaultTransport,
        },
    },
}

resp, err := client.Get("http://api.example.com/data")
```

---

## Part 10: JSON RawMessage for Delayed Parsing

`json.RawMessage` delays JSON parsing until needed. Useful for handling unknow structures:

```go
// Event with flexible payload
type Event struct {
    Type    string          `json:"type"`
    Payload json.RawMessage `json:"payload"`  // Unparsed JSON
}

// Parse event
var event Event
json.Unmarshal([]byte(`{
    "type": "booking.created",
    "payload": {"booking_id": "b123", "user_id": "u456"}
}`), &event)

// Later, parse payload based on type
switch event.Type {
case "booking.created":
    var payload struct {
        BookingID string `json:"booking_id"`
        UserID    string `json:"user_id"`
    }
    json.Unmarshal(event.Payload, &payload)
    fmt.Println("Booking:", payload.BookingID)

case "payment.processed":
    var payload struct {
        Amount float64 `json:"amount"`
    }
    json.Unmarshal(event.Payload, &payload)
}

// Also useful for proxying: pass JSON through without parsing
type ProxyMessage struct {
    ID      int64           `json:"id"`
    Content json.RawMessage `json:"content"`  // Forward as-is
}
```

---

## Part 11: Slog Handler Customization

Go 1.21+ `slog` is highly customizable:

```go
import "log/slog"

// JSON handler (production)
jsonHandler := slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{
    Level: slog.LevelInfo,
})

// Text handler (development)
textHandler := slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
    Level: slog.LevelDebug,
})

// Custom handler: add request ID to every log
type requestIDHandler struct {
    next  slog.Handler
    reqID string
}

func (h *requestIDHandler) Handle(ctx context.Context, r slog.Record) error {
    // Add request ID to every log record
    r.AddAttrs(slog.String("request_id", h.reqID))
    return h.next.Handle(ctx, r)
}

func (h *requestIDHandler) WithAttrs(attrs []slog.Attr) slog.Handler {
    return &requestIDHandler{
        next:  h.next.WithAttrs(attrs),
        reqID: h.reqID,
    }
}

func (h *requestIDHandler) WithGroup(name string) slog.Handler {
    return &requestIDHandler{
        next:  h.next.WithGroup(name),
        reqID: h.reqID,
    }
}

// Use custom handler
logger := slog.New(&requestIDHandler{
    next:  slog.NewJSONHandler(os.Stderr, nil),
    reqID: "req-123",
})

logger.Info("request received")  // Includes request_id automatically
```

---

## Part 12: IO Pipes and Streaming

`io.Pipe` creates an in-process pipe for streaming:

```go
import "io"

// Producer writes to pipe, consumer reads
reader, writer := io.Pipe()

// Producer (in goroutine)
go func() {
    defer writer.Close()

    for i := 1; i <= 100; i++ {
        fmt.Fprintf(writer, "Line %d\n", i)
    }
}()

// Consumer reads as data becomes available
scanner := bufio.NewScanner(reader)
for scanner.Scan() {
    fmt.Println(scanner.Text())  // Processes as producer writes
}

// Use case: Stream large files without buffering
func streamLargeFile(w http.ResponseWriter, movieID string) {
    reader, writer := io.Pipe()

    go func() {
        defer writer.Close()

        // Generate file content on-the-fly
        for chunk := range generateChunks(movieID) {
            writer.Write(chunk)
        }
    }()

    w.Header().Set("Content-Type", "application/octet-stream")
    io.Copy(w, reader)  // Stream directly to HTTP response
}
```

---

## Part 13: Subprocesses with os/exec

```go
import "os/exec"

// Simple subprocess
cmd := exec.Command("ls", "-la")
output, err := cmd.Output()  // Captures stdout

// With stderr
cmd := exec.Command("docker", "build", ".")
output, err := cmd.CombinedOutput()  // stdout + stderr

// Interactive subprocess
cmd := exec.Command("python", "script.py")
cmd.Stdin = os.Stdin
cmd.Stdout = os.Stdout
cmd.Stderr = os.Stderr
err := cmd.Run()

// Context cancellation
ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
defer cancel()

cmd := exec.CommandContext(ctx, "long-running-command")
err := cmd.Run()
if errors.Is(err, context.DeadlineExceeded) {
    // Process was killed due to timeout
}

// Capture output in real-time
cmd := exec.Command("curl", "http://api.example.com")

stdout, _ := cmd.StdoutPipe()
scanner := bufio.NewScanner(stdout)

cmd.Start()

for scanner.Scan() {
    fmt.Println("Output:", scanner.Text())
}

cmd.Wait()
```

---

## Interview Corner

### Q1: What are the timeout options in http.Client and http.Server?

**Model Answer**:
- **Client**:
  - `Timeout`: Overall request timeout (includes redirect, TLS, reading body)
  - Transport timeouts: `DialTimeout`, `TLSHandshakeTimeout`, `ResponseHeaderTimeout`
- **Server**:
  - `ReadTimeout`: Time to read request (headers + body)
  - `WriteTimeout`: Time to write response
  - `IdleTimeout`: Keep-alive timeout

Set all timeouts. Default zero values = no timeout = hanging requests.

### Q2: Explain JSON struct tags and omitempty gotcha.

**Model Answer**:
```go
type User struct {
    Email string `json:"email,omitempty"`  // Omit if empty
}
```

`omitempty` omits zero values. For slices, only nil is omitted, not empty slice `[]`.

```go
type Data struct {
    Items []string `json:"items,omitempty"`
}

Data{Items: []string{}}   // Marshals to {"items":[]}  -- NOT omitted!
Data{Items: nil}          // Marshals to {}  -- Omitted
```

Use custom marshalers for more control.

### Q3: What's the difference between io.Reader and json.Decoder?

**Model Answer**:
- **io.Reader**: Generic byte streaming interface. Low-level.
- **json.Decoder**: Parses JSON incrementally from an io.Reader. High-level.

Decoder is more efficient for large JSON: it doesn't load entire file into memory.

```go
decoder := json.NewDecoder(file)
for decoder.More() {
    var item interface{}
    decoder.Decode(&item)
    // Process one item (constant memory)
}
```

### Q4: How do you handle timezones safely?

**Model Answer**:
1. Always parse with location: `time.Parse` uses UTC unless location specified
2. Use RFC3339 format for APIs (includes timezone info)
3. Store times in UTC internally
4. Convert to user's timezone only for display

```go
t, _ := time.Parse(time.RFC3339, "2024-03-26T12:00:00+05:00")  // Correct
formatted := t.Format(time.RFC3339)  // "2024-03-26T07:00:00Z" (converted to UTC)
```

### Q5: Design a complete HTTP server with logging, timeouts, and graceful shutdown.

See production example above. Key points:
- Middleware for logging, recovery, timeouts
- Graceful shutdown with context timeout
- Structured logging with slog
- Proper HTTP timeouts (read, write, idle)
- Response wrapper to capture status code

### Q6: How do you use http.RoundTripper to add cross-cutting concerns?

**Model Answer**:
Implement `http.RoundTripper` to wrap an existing transport:

```go
type LoggingRoundTripper struct {
    next http.RoundTripper
}

func (rt *LoggingRoundTripper) RoundTrip(req *http.Request) (*http.Response, error) {
    start := time.Now()
    resp, err := rt.next.RoundTrip(req)
    duration := time.Since(start)

    log.Printf("%s %s took %v", req.Method, req.URL, duration)
    return resp, err
}

// Chain multiple concerns
client := &http.Client{
    Transport: &LoggingRoundTripper{
        next: &RetryRoundTripper{
            maxRetries: 3,
            next:       http.DefaultTransport,
        },
    },
}
```

### Q7: What's the purpose of json.RawMessage and when would you use it?

**Model Answer**:
`json.RawMessage` stores raw JSON bytes without parsing. Use when:
1. **Event sourcing**: Payload structure varies by event type
2. **Proxying**: Forward JSON without understanding structure
3. **Delayed parsing**: Parse complex structures only if needed
4. **Unions/Sum types**: Handle different message formats

```go
type Message struct {
    Type    string          `json:"type"`
    Payload json.RawMessage `json:"payload"`
}

// Payload parsed later based on type
```

### Q8: Design a production-grade HTTP API with proper error handling, logging, and timeouts.

**Model Answer**:
```go
package api

import (
    "context"
    "encoding/json"
    "log/slog"
    "net/http"
    "time"
)

type ErrorResponse struct {
    Code    string `json:"code"`
    Message string `json:"message"`
}

func respondError(w http.ResponseWriter, code int, errCode, message string) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(code)
    json.NewEncoder(w).Encode(ErrorResponse{Code: errCode, Message: message})
}

func respondSuccess(w http.ResponseWriter, data interface{}) {
    w.Header().Set("Content-Type", "application/json")
    w.WriteHeader(http.StatusOK)
    json.NewEncoder(w).Encode(data)
}

type BookingAPI struct {
    service *BookingService
    logger  *slog.Logger
}

func NewBookingAPI(service *BookingService, logger *slog.Logger) *BookingAPI {
    return &BookingAPI{
        service: service,
        logger:  logger,
    }
}

func (api *BookingAPI) CreateBooking(w http.ResponseWriter, r *http.Request) {
    var req struct {
        UserID  string   `json:"user_id"`
        MovieID string   `json:"movie_id"`
        Seats   []string `json:"seats"`
    }

    if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
        api.logger.ErrorContext(r.Context(), "invalid request", slog.String("error", err.Error()))
        respondError(w, http.StatusBadRequest, "INVALID_REQUEST", "Invalid request body")
        return
    }

    // Validate
    if req.UserID == "" || req.MovieID == "" || len(req.Seats) == 0 {
        respondError(w, http.StatusBadRequest, "MISSING_FIELDS", "Missing required fields")
        return
    }

    // Call service with timeout
    ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
    defer cancel()

    booking, err := api.service.CreateBooking(ctx, req.UserID, req.MovieID, req.Seats)

    if err != nil {
        if errors.Is(err, context.DeadlineExceeded) {
            api.logger.WarnContext(r.Context(), "booking timeout", slog.String("user_id", req.UserID))
            respondError(w, http.StatusGatewayTimeout, "TIMEOUT", "Request timeout")
        } else if errors.Is(err, ErrInsufficientSeats) {
            respondError(w, http.StatusConflict, "INSUFFICIENT_SEATS", "Not enough seats available")
        } else {
            api.logger.ErrorContext(r.Context(), "booking failed", slog.String("error", err.Error()))
            respondError(w, http.StatusInternalServerError, "INTERNAL_ERROR", "Booking failed")
        }
        return
    }

    api.logger.InfoContext(r.Context(), "booking created",
        slog.String("booking_id", booking.ID),
        slog.String("user_id", req.UserID),
    )

    respondSuccess(w, booking)
}

// Use with server
func setupServer(logger *slog.Logger) *http.Server {
    service := NewBookingService()
    api := NewBookingAPI(service, logger)

    mux := http.NewServeMux()
    mux.HandleFunc("POST /bookings", api.CreateBooking)
    mux.HandleFunc("GET /health", func(w http.ResponseWriter, r *http.Request) {
        w.WriteHeader(http.StatusOK)
    })

    return &http.Server{
        Addr:         ":8080",
        Handler:      chainMiddleware(loggingMiddleware(logger), recoveryMiddleware)(mux),
        ReadTimeout:  5 * time.Second,
        WriteTimeout: 10 * time.Second,
        IdleTimeout:  60 * time.Second,
    }
}
```

Key production patterns:
- Structured error responses with error codes
- Context timeouts for all operations
- Proper logging at different levels
- HTTP timeouts configured
- Middleware chain for cross-cutting concerns
- Graceful error handling (don't expose internals)

### Q9: How would you implement efficient streaming JSON processing for large datasets?

**Model Answer**:
```go
func streamProcessBookings(ctx context.Context, file io.Reader, processor func(*Booking) error) error {
    decoder := json.NewDecoder(file)

    // Skip opening bracket
    if _, err := decoder.Token(); err != nil {
        return err
    }

    for decoder.More() {
        select {
        case <-ctx.Done():
            return ctx.Err()
        default:
        }

        var booking Booking
        if err := decoder.Decode(&booking); err != nil {
            return err
        }

        if err := processor(&booking); err != nil {
            return err
        }
    }

    return nil
}

// Usage with database bulk insert
func bulkInsertBookings(ctx context.Context, file *os.File, db *pgx.Pool) error {
    batch := &pgx.Batch{}
    batchSize := 1000
    count := 0

    return streamProcessBookings(ctx, file, func(b *Booking) error {
        batch.Queue(
            "INSERT INTO bookings (id, user_id, movie_id) VALUES ($1, $2, $3)",
            b.ID, b.UserID, b.MovieID,
        )

        count++
        if count >= batchSize {
            results := db.SendBatch(ctx, batch)
            if err := results.Close(); err != nil {
                return err
            }
            batch = &pgx.Batch{}
            count = 0
        }

        return nil
    })
}
```

Benefits:
- Constant memory regardless of file size
- Streaming processing (no need to load all into memory)
- Efficient batch inserts
- Respects context cancellation

**Model Answer**:
`json.RawMessage` stores raw JSON bytes without parsing. Use when:
1. **Event sourcing**: Payload structure varies by event type
2. **Proxying**: Forward JSON without understanding structure
3. **Delayed parsing**: Parse complex structures only if needed
4. **Unions/Sum types**: Handle different message formats

```go
type Message struct {
    Type    string          `json:"type"`
    Payload json.RawMessage `json:"payload"`
}

// Payload parsed later based on type
```

---

## Tradeoffs and Best Practices

### HTTP Client
- Always set timeouts (at minimum, use Transport timeouts)
- Reuse http.Client for connection pooling
- Use context for cancellation

### JSON
- Use struct tags with `omitempty` for optional fields
- Custom marshalers for complex types
- Streaming for large files

### Logging
- Use slog for structured logging (Go 1.21+)
- Include trace ID in logs
- Use appropriate log levels

### Time
- Always consider timezones
- Use RFC3339 for serialization
- time.Since() uses monotonic clock (safe for benchmarking)

---

## Exercise

Build a **complete HTTP API** for movie bookings with:

1. **HTTP Server**:
   - POST /book: Create booking
   - GET /bookings/{id}: Get booking
   - GET /health: Health check
   - All with proper timeouts and error handling

2. **Middleware**:
   - Logging (method, path, status, latency)
   - Recovery (panic handling)
   - Request timeout (10 seconds)

3. **JSON Handling**:
   - Request/response marshaling
   - Custom error responses
   - Proper content types

4. **Graceful Shutdown**:
   - Signal handling (SIGINT, SIGTERM)
   - Wait for in-flight requests
   - 30-second timeout for shutdown

5. **Testing**:
   - HTTP handler tests (httptest)
   - Middleware tests
   - JSON parsing tests

Requirements:
- Must pass `go test -race`
- Must log all requests
- Must handle timeouts correctly
- Must gracefully shutdown

Bonus: Add TLS support, structured logging with slog, and database integration.

