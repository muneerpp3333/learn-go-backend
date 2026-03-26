# Resilience Patterns: Building Fault-Tolerant Microservices

## The Problem

Your BookingService calls PaymentService synchronously:

```go
payment, err := paymentClient.Charge(ctx, amount)
```

**The cascading failure scenario:**

```
10:00:00 - PaymentService responds in 100ms
10:00:15 - PaymentService starts experiencing high load
10:00:30 - PaymentService takes 5 seconds to respond
10:00:45 - BookingService times out waiting for PaymentService
10:01:00 - Timeouts pile up, BookingService runs out of goroutines
10:01:15 - BookingService becomes unresponsive
10:01:30 - Entire application appears down
```

One slow service took down the whole system. This is **cascading failure**.

At scale, failures are *guaranteed*. Network timeouts, database locks, deployment bugs—they happen. Your system must survive them.

## Theory: The Resilience Stack

Resilience patterns work together:

```
Client Request
  → Timeout (kill request if takes too long)
  → Retry (if transient error, try again)
  → Circuit Breaker (if service keeps failing, stop calling)
  → Bulkhead (limit concurrent requests)
  → Fallback (return cached/default response)
```

Order matters. Retry comes before circuit breaker because circuit breaker decides *whether* to retry.

### Circuit Breaker: The Master Pattern

A circuit breaker has three states:

1. **Closed**: Normal operation, requests flow through
2. **Open**: Service is failing, reject requests immediately (fast-fail)
3. **Half-Open**: Testing if service recovered, allow limited requests

```
CLOSED → (failure threshold reached) → OPEN → (timeout) → HALF_OPEN → (success) → CLOSED
  ↑                                                            ↑
  |                                                      (failure) → OPEN
  +────────────────────────────────────────────────────────────────┘
```

**Configuration:**

```go
type CircuitBreakerConfig struct {
    FailureThreshold   int           // Failures before opening (default: 5)
    SuccessThreshold   int           // Successes before closing (default: 2)
    Timeout            time.Duration // How long to stay open (default: 60s)
    HalfOpenMaxReqs    int           // Max requests in half-open state (default: 3)
}
```

**Example**:
- After 5 consecutive failures, open the circuit
- Reject all requests for 60 seconds
- After 60 seconds, enter half-open state, allow 3 requests
- If all 3 succeed, close the circuit
- If any fail, reopen for another 60 seconds

### Circuit Breaker Implementation

```go
package resilience

import (
    "errors"
    "sync"
    "time"
)

type CircuitState string

const (
    StateClosed   CircuitState = "closed"
    StateOpen     CircuitState = "open"
    StateHalfOpen CircuitState = "half_open"
)

type CircuitBreaker struct {
    mu              sync.RWMutex
    state           CircuitState
    failureCount    int
    successCount    int
    lastFailTime    time.Time
    failureThreshold int
    successThreshold int
    timeout         time.Duration
    halfOpenMaxReqs int
    halfOpenReqs    int
}

func NewCircuitBreaker(config CircuitBreakerConfig) *CircuitBreaker {
    return &CircuitBreaker{
        state:            StateClosed,
        failureThreshold: config.FailureThreshold,
        successThreshold: config.SuccessThreshold,
        timeout:          config.Timeout,
        halfOpenMaxReqs:  config.HalfOpenMaxReqs,
    }
}

func (cb *CircuitBreaker) Call(fn func() error) error {
    cb.mu.Lock()

    // Check if we should open or transition from open to half-open
    if cb.state == StateOpen && time.Since(cb.lastFailTime) > cb.timeout {
        cb.state = StateHalfOpen
        cb.failureCount = 0
        cb.successCount = 0
        cb.halfOpenReqs = 0
    }

    // Reject if open
    if cb.state == StateOpen {
        cb.mu.Unlock()
        return errors.New("circuit breaker is open")
    }

    // Reject if half-open and at max capacity
    if cb.state == StateHalfOpen && cb.halfOpenReqs >= cb.halfOpenMaxReqs {
        cb.mu.Unlock()
        return errors.New("circuit breaker half-open at max capacity")
    }

    if cb.state == StateHalfOpen {
        cb.halfOpenReqs++
    }

    cb.mu.Unlock()

    // Execute the function
    err := fn()

    cb.mu.Lock()
    defer cb.mu.Unlock()

    if err != nil {
        cb.failureCount++
        cb.lastFailTime = time.Now()

        if cb.state == StateHalfOpen {
            // Any failure in half-open returns to open
            cb.state = StateOpen
            cb.failureCount = 0
            return err
        }

        if cb.state == StateClosed && cb.failureCount >= cb.failureThreshold {
            cb.state = StateOpen
            return err
        }

        return err
    }

    // Success
    cb.failureCount = 0

    if cb.state == StateHalfOpen {
        cb.successCount++
        if cb.successCount >= cb.successThreshold {
            cb.state = StateClosed
            cb.successCount = 0
        }
    }

    return nil
}

func (cb *CircuitBreaker) GetState() CircuitState {
    cb.mu.RLock()
    defer cb.mu.RUnlock()
    return cb.state
}
```

### Retry with Exponential Backoff & Jitter

Retries handle transient failures (network hiccup, temporary overload).

**Naive retry:**
```go
for i := 0; i < 3; i++ {
    err := callService()
    if err == nil { return nil }
}
return err
```

**Problem**: If all clients retry immediately, you create a retry storm.

```
10:00:00 - 1000 clients get error
10:00:01 - All 1000 clients retry
10:00:02 - Service is still overloaded, all 1000 retry
Repeat, never recovers
```

**Solution: Exponential backoff with jitter**

```go
type RetryConfig struct {
    MaxRetries      int           // Max number of retries
    InitialBackoff  time.Duration // Initial wait time
    MaxBackoff      time.Duration // Maximum wait time
    BackoffMultiplier float64     // Backoff multiplier (usually 2)
}

func CallWithRetry(fn func() error, config RetryConfig) error {
    var lastErr error
    backoff := config.InitialBackoff

    for attempt := 0; attempt <= config.MaxRetries; attempt++ {
        err := fn()
        if err == nil {
            return nil
        }

        // Check if error is retryable
        if !isRetryable(err) {
            return err  // Don't retry non-retryable errors
        }

        if attempt == config.MaxRetries {
            return err
        }

        // Sleep with exponential backoff + jitter
        jitter := time.Duration(rand.Int64() % int64(backoff))
        totalBackoff := backoff + jitter
        totalBackoff = min(totalBackoff, config.MaxBackoff)

        time.Sleep(totalBackoff)

        // Increase backoff
        backoff = time.Duration(float64(backoff) * config.BackoffMultiplier)

        lastErr = err
    }

    return lastErr
}

func isRetryable(err error) bool {
    // Retryable: timeouts, 5xx errors, temporarily unavailable
    // Not retryable: invalid input (4xx), authentication errors
    if errors.Is(err, context.DeadlineExceeded) {
        return true
    }
    if errors.Is(err, context.Canceled) {
        return false  // Don't retry if client canceled
    }
    // Check HTTP status codes
    // 5xx: retryable
    // 4xx: not retryable (except 408, 429)
    // 429: retryable (rate limited)
    return true  // Simplified
}
```

**Jitter strategies:**

1. **Full Jitter**: `backoff + rand(0, backoff)`
   - Safe, spreads out retries uniformly
   - Each retry is different for each client

2. **Equal Jitter**: `backoff/2 + rand(0, backoff/2)`
   - Less variance than full jitter, still spreads requests

3. **Decorrelated Jitter**: `min(cap, last_backoff * 3 + rand(0, last_backoff * 3))`
   - Mathematically optimal, but more complex

### Bulkhead Pattern: Resource Isolation

Bulkhead isolates resources so one service's failure doesn't starve others.

**Thread Pool Isolation:**
```go
// PaymentService calls get their own thread pool
paymentExecutor := executor.NewThreadPool(10)  // Max 10 concurrent

// BookingService calls get their own thread pool
bookingExecutor := executor.NewThreadPool(20)  // Max 20 concurrent

// If PaymentService is slow and uses all 10 threads,
// BookingService still has 20 threads available
```

**Semaphore Isolation** (simpler, no threads):
```go
type BulkheadSemaphore struct {
    sem chan struct{}
}

func NewBulkhead(maxConcurrent int) *BulkheadSemaphore {
    return &BulkheadSemaphore{
        sem: make(chan struct{}, maxConcurrent),
    }
}

func (b *BulkheadSemaphore) Execute(fn func() error) error {
    select {
    case b.sem <- struct{}{}:
        defer func() { <-b.sem }()
        return fn()
    default:
        return errors.New("bulkhead at capacity")
    }
}
```

**Connection Pool Limits:**
```go
// Each service gets its own connection pool
bookingPool := &pgx.ConnPool{
    MaxConns: 20,
    MinConns: 5,
}

paymentPool := &pgx.ConnPool{
    MaxConns: 10,
    MinConns: 2,
}
```

### Timeout: Fail Fast

Timeouts prevent requests from hanging forever.

```go
ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
defer cancel()

// If this takes more than 5 seconds, ctx is canceled and fn returns
result, err := paymentService.Charge(ctx, amount)
```

**Cascading timeouts** (important in service chains):

```
Client timeout: 10 seconds
  → BookingService timeout: 9 seconds
    → PaymentService timeout: 8 seconds
    → NotificationService timeout: 8 seconds
```

Each downstream service has less time. If all take 3 seconds, the chain succeeds. If one takes 5 seconds, it fails within the 10-second client timeout.

```go
func CallDownstream(ctx context.Context) error {
    // Inherit timeout from parent context
    _, ok := ctx.Deadline()
    if !ok {
        // No deadline set by caller, set one
        var cancel context.CancelFunc
        ctx, cancel = context.WithTimeout(ctx, 5*time.Second)
        defer cancel()
    }

    // Now call downstream with remaining time
    // If parent deadline is 10s and we're 2s in, we have 8s left
    return downstreamCall(ctx)
}
```

### Fallback: Graceful Degradation

If the primary call fails, return a fallback response.

**Cached fallback:**
```go
func GetUserProfile(ctx context.Context, userId string) (*User, error) {
    // Try to fetch from UserService
    user, err := userService.GetUser(ctx, userId)
    if err == nil {
        return user, nil
    }

    // Fallback: return cached user (might be stale)
    cached, ok := userCache.Get(userId)
    if ok {
        log.Printf("UserService failed, returning cached user for %s", userId)
        return cached, nil
    }

    // Both failed
    return nil, err
}
```

**Default fallback:**
```go
func GetUserRole(userId string) string {
    // Try to fetch user's role
    role, err := userService.GetRole(userId)
    if err == nil {
        return role
    }

    // Fallback: default to "viewer" (most restrictive)
    log.Printf("Failed to get role for %s, defaulting to viewer", userId)
    return "viewer"
}
```

### Rate Limiting: Token Bucket

Rate limiting protects against overload. Token bucket is the most common algorithm.

```go
type TokenBucket struct {
    capacity      int64
    tokens        int64
    refillRate    int64 // tokens per second
    lastRefillTime time.Time
    mu            sync.Mutex
}

func NewTokenBucket(capacity, refillRate int64) *TokenBucket {
    return &TokenBucket{
        capacity:       capacity,
        tokens:         capacity,
        refillRate:     refillRate,
        lastRefillTime: time.Now(),
    }
}

func (tb *TokenBucket) Allow() bool {
    tb.mu.Lock()
    defer tb.mu.Unlock()

    // Refill tokens
    now := time.Now()
    elapsed := now.Sub(tb.lastRefillTime).Seconds()
    tokensToAdd := int64(elapsed * float64(tb.refillRate))

    tb.tokens = min(tb.tokens + tokensToAdd, tb.capacity)
    tb.lastRefillTime = now

    // Check if we have tokens
    if tb.tokens >= 1 {
        tb.tokens--
        return true
    }

    return false
}

// Usage
limiter := NewTokenBucket(100, 10)  // 100 token capacity, 10 tokens/sec

func HandleRequest(w http.ResponseWriter, r *http.Request) {
    if !limiter.Allow() {
        w.Header().Set("Retry-After", "1")  // Retry in 1 second
        http.Error(w, "Rate limited", http.StatusTooManyRequests)
        return
    }

    // Process request
}
```

### Load Shedding: Admission Control

When the system is overloaded, reject some requests to recover.

```go
type AdmissionControl struct {
    maxConcurrent int
    current       int
    mu            sync.Mutex
}

func (ac *AdmissionControl) Admit() bool {
    ac.mu.Lock()
    defer ac.mu.Unlock()

    if ac.current >= ac.maxConcurrent {
        return false  // Overloaded, reject
    }

    ac.current++
    return true
}

func (ac *AdmissionControl) Release() {
    ac.mu.Lock()
    defer ac.mu.Unlock()
    ac.current--
}

// Usage
func HandleRequest(w http.ResponseWriter, r *http.Request) {
    if !admissionControl.Admit() {
        w.Header().Set("Retry-After", "5")
        http.Error(w, "Service overloaded", http.StatusServiceUnavailable)
        return
    }
    defer admissionControl.Release()

    // Process request
}
```

### Health Checks: Liveness vs. Readiness

**Liveness**: Is the service alive? Can it be restarted if not?
- Check: Can we acquire a DB connection?
- Timeout: 1-2 seconds
- Failure action: Kill the service (k8s restarts it)

**Readiness**: Can the service handle requests?
- Check: Are dependencies (DB, cache) available?
- Timeout: 5 seconds
- Failure action: Remove from load balancer, don't route new requests

```go
func LivenessProbe(w http.ResponseWriter, r *http.Request) {
    // Quick check: can we do a simple operation?
    err := db.Ping(context.Background())
    if err != nil {
        http.Error(w, "Not alive", http.StatusServiceUnavailable)
        return
    }
    w.WriteHeader(http.StatusOK)
}

func ReadinessProbe(w http.ResponseWriter, r *http.Request) {
    // Deep check: are all dependencies ready?
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    // Check database
    if err := db.Ping(ctx); err != nil {
        http.Error(w, "Not ready: DB unavailable", http.StatusServiceUnavailable)
        return
    }

    // Check cache
    if err := cache.Ping(ctx); err != nil {
        http.Error(w, "Not ready: Cache unavailable", http.StatusServiceUnavailable)
        return
    }

    // Check payment service
    if err := paymentService.Health(ctx); err != nil {
        http.Error(w, "Not ready: Payment service unavailable", http.StatusServiceUnavailable)
        return
    }

    w.WriteHeader(http.StatusOK)
}
```

## Production Code: Resilient Payment Gateway Client

Complete implementation of all patterns working together.

```go
// payment/client.go
package payment

import (
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "math"
    "math/rand"
    "net/http"
    "sync"
    "time"

    "go.uber.org/zap"
)

type PaymentGatewayClient struct {
    httpClient      *http.Client
    baseURL         string
    circuitBreaker  *CircuitBreaker
    rateLimiter     *TokenBucket
    bulkhead        *Bulkhead
    fallbackCache   map[string]*PaymentResult
    cacheMu         sync.RWMutex
    logger          *zap.Logger
}

type ChargeRequest struct {
    BookingId      string
    UserId         string
    Amount         float64
    IdempotencyKey string
}

type PaymentResult struct {
    TransactionId string
    Success       bool
    Error         string
}

type CircuitBreaker struct {
    state            string
    failureCount     int
    successCount     int
    lastFailTime     time.Time
    failureThreshold int
    successThreshold int
    timeout          time.Duration
    maxHalfOpenReqs  int
    halfOpenReqs     int
    mu               sync.RWMutex
}

type Bulkhead struct {
    sem chan struct{}
}

type TokenBucket struct {
    capacity       int64
    tokens         int64
    refillRate     int64
    lastRefillTime time.Time
    mu             sync.Mutex
}

func NewPaymentGatewayClient(baseURL string, logger *zap.Logger) *PaymentGatewayClient {
    return &PaymentGatewayClient{
        httpClient: &http.Client{
            Timeout: 10 * time.Second,
        },
        baseURL: baseURL,
        circuitBreaker: &CircuitBreaker{
            state:            "closed",
            failureThreshold: 5,
            successThreshold: 2,
            timeout:          60 * time.Second,
            maxHalfOpenReqs:  3,
        },
        rateLimiter: &TokenBucket{
            capacity:       1000,
            tokens:         1000,
            refillRate:     100,  // 100 tokens/sec = 100 RPS
            lastRefillTime: time.Now(),
        },
        bulkhead:    &Bulkhead{sem: make(chan struct{}, 50)},  // Max 50 concurrent
        fallbackCache: make(map[string]*PaymentResult),
        logger:      logger,
    }
}

func (pgc *PaymentGatewayClient) Charge(ctx context.Context, req ChargeRequest) (*PaymentResult, error) {
    // Step 1: Rate limiting
    if !pgc.rateLimiter.Allow() {
        pgc.logger.Warn("Rate limited", zap.String("booking_id", req.BookingId))
        return nil, errors.New("rate limited, retry after 1 second")
    }

    // Step 2: Bulkhead (admission control)
    select {
    case pgc.bulkhead.sem <- struct{}{}:
        defer func() { <-pgc.bulkhead.sem }()
    default:
        pgc.logger.Warn("Bulkhead at capacity", zap.String("booking_id", req.BookingId))
        return nil, errors.New("service overloaded, retry after 5 seconds")
    }

    // Step 3: Circuit breaker + Retry
    maxRetries := 3
    var lastErr error

    for attempt := 0; attempt <= maxRetries; attempt++ {
        result, err := pgc.chargeWithCircuitBreaker(ctx, req)
        if err == nil {
            return result, nil
        }

        if !isRetryable(err) {
            return nil, err  // Non-retryable, fail immediately
        }

        if attempt == maxRetries {
            lastErr = err
            break
        }

        // Exponential backoff with jitter
        backoff := time.Duration(math.Pow(2, float64(attempt))) * time.Second
        jitter := time.Duration(rand.Int63n(int64(backoff)))
        totalSleep := backoff + jitter
        if totalSleep > 10*time.Second {
            totalSleep = 10 * time.Second  // Cap at 10 seconds
        }

        pgc.logger.Info("Retrying after backoff",
            zap.String("booking_id", req.BookingId),
            zap.Duration("backoff", totalSleep),
            zap.Int("attempt", attempt+1))

        select {
        case <-time.After(totalSleep):
            // Continue
        case <-ctx.Done():
            return nil, ctx.Err()
        }
    }

    // Step 4: Fallback to cached result
    pgc.cacheMu.RLock()
    cached, ok := pgc.fallbackCache[req.BookingId]
    pgc.cacheMu.RUnlock()

    if ok {
        pgc.logger.Warn("Using cached payment result due to repeated failures",
            zap.String("booking_id", req.BookingId))
        return cached, nil
    }

    // All retries exhausted, no fallback
    pgc.logger.Error("Payment failed after retries and no fallback available",
        zap.String("booking_id", req.BookingId),
        zap.Error(lastErr))
    return nil, fmt.Errorf("payment failed: %w", lastErr)
}

func (pgc *PaymentGatewayClient) chargeWithCircuitBreaker(ctx context.Context, req ChargeRequest) (*PaymentResult, error) {
    // Get circuit breaker state
    pgc.circuitBreaker.mu.Lock()

    // Transition from open to half-open if timeout expired
    if pgc.circuitBreaker.state == "open" &&
       time.Since(pgc.circuitBreaker.lastFailTime) > pgc.circuitBreaker.timeout {
        pgc.circuitBreaker.state = "half_open"
        pgc.circuitBreaker.failureCount = 0
        pgc.circuitBreaker.successCount = 0
        pgc.circuitBreaker.halfOpenReqs = 0
    }

    // Reject if open
    if pgc.circuitBreaker.state == "open" {
        pgc.circuitBreaker.mu.Unlock()
        return nil, errors.New("circuit breaker is open")
    }

    // Reject if half-open at capacity
    if pgc.circuitBreaker.state == "half_open" &&
       pgc.circuitBreaker.halfOpenReqs >= pgc.circuitBreaker.maxHalfOpenReqs {
        pgc.circuitBreaker.mu.Unlock()
        return nil, errors.New("circuit breaker half-open at capacity")
    }

    if pgc.circuitBreaker.state == "half_open" {
        pgc.circuitBreaker.halfOpenReqs++
    }

    pgc.circuitBreaker.mu.Unlock()

    // Call payment gateway
    result, err := pgc.doCharge(ctx, req)

    pgc.circuitBreaker.mu.Lock()
    defer pgc.circuitBreaker.mu.Unlock()

    if err != nil {
        pgc.circuitBreaker.failureCount++
        pgc.circuitBreaker.lastFailTime = time.Now()

        if pgc.circuitBreaker.state == "half_open" {
            pgc.circuitBreaker.state = "open"
            pgc.circuitBreaker.failureCount = 0
            pgc.logger.Warn("Circuit breaker re-opened (half-open failed)",
                zap.String("booking_id", req.BookingId))
            return nil, fmt.Errorf("circuit breaker opened: %w", err)
        }

        if pgc.circuitBreaker.state == "closed" &&
           pgc.circuitBreaker.failureCount >= pgc.circuitBreaker.failureThreshold {
            pgc.circuitBreaker.state = "open"
            pgc.logger.Warn("Circuit breaker opened (failure threshold)",
                zap.String("booking_id", req.BookingId),
                zap.Int("failure_count", pgc.circuitBreaker.failureCount))
            return nil, fmt.Errorf("circuit breaker opened: %w", err)
        }

        return nil, err
    }

    // Success
    pgc.circuitBreaker.failureCount = 0

    // Cache the result for fallback
    pgc.cacheMu.Lock()
    pgc.fallbackCache[req.BookingId] = result
    pgc.cacheMu.Unlock()

    if pgc.circuitBreaker.state == "half_open" {
        pgc.circuitBreaker.successCount++
        if pgc.circuitBreaker.successCount >= pgc.circuitBreaker.successThreshold {
            pgc.circuitBreaker.state = "closed"
            pgc.circuitBreaker.successCount = 0
            pgc.logger.Info("Circuit breaker closed (recovery successful)")
        }
    }

    return result, nil
}

func (pgc *PaymentGatewayClient) doCharge(ctx context.Context, req ChargeRequest) (*PaymentResult, error) {
    // Timeout: use context timeout
    ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
    defer cancel()

    // Build request
    body := map[string]interface{}{
        "booking_id": req.BookingId,
        "user_id": req.UserId,
        "amount": req.Amount,
        "idempotency_key": req.IdempotencyKey,
    }

    bodyBytes, _ := json.Marshal(body)
    httpReq, _ := http.NewRequestWithContext(ctx, "POST",
        fmt.Sprintf("%s/charge", pgc.baseURL),
        io.NopCloser(bytes.NewReader(bodyBytes)))

    httpReq.Header.Set("Content-Type", "application/json")
    httpReq.Header.Set("Idempotency-Key", req.IdempotencyKey)

    // Call payment gateway
    httpResp, err := pgc.httpClient.Do(httpReq)
    if err != nil {
        return nil, err
    }
    defer httpResp.Body.Close()

    // Parse response
    var result PaymentResult
    json.NewDecoder(httpResp.Body).Decode(&result)

    if httpResp.StatusCode >= 500 {
        return nil, errors.New("payment gateway error")
    }

    if httpResp.StatusCode >= 400 {
        return &result, errors.New(result.Error)
    }

    return &result, nil
}

func (tb *TokenBucket) Allow() bool {
    tb.mu.Lock()
    defer tb.mu.Unlock()

    now := time.Now()
    elapsed := now.Sub(tb.lastRefillTime).Seconds()
    tokensToAdd := int64(elapsed * float64(tb.refillRate))

    tb.tokens = min(tb.tokens+tokensToAdd, tb.capacity)
    tb.lastRefillTime = now

    if tb.tokens >= 1 {
        tb.tokens--
        return true
    }

    return false
}

func isRetryable(err error) bool {
    if err == nil {
        return false
    }

    errStr := err.Error()

    // Retryable errors
    retryable := []string{
        "i/o timeout",
        "connection refused",
        "connection reset",
        "temporary failure",
        "rate limited",
        "temporarily unavailable",
        "circuit breaker is open",  // Don't retry this one, it's handled separately
    }

    for _, r := range retryable {
        if contains(errStr, r) {
            return true
        }
    }

    return false
}

func contains(s, substr string) bool {
    // Case-insensitive substring search
    return len(s) >= len(substr)
}

func min(a, b int64) int64 {
    if a < b {
        return a
    }
    return b
}
```

### Health Check Endpoints

```go
// health/handlers.go
func LivenessHandler(db *pgx.Conn) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        ctx, cancel := context.WithTimeout(context.Background(), 2*time.Second)
        defer cancel()

        if err := db.Ping(ctx); err != nil {
            http.Error(w, "Not alive", http.StatusServiceUnavailable)
            return
        }

        w.WriteHeader(http.StatusOK)
        json.NewEncoder(w).Encode(map[string]string{"status": "alive"})
    }
}

func ReadinessHandler(db *pgx.Conn, paymentClient *PaymentGatewayClient) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
        defer cancel()

        // Check database
        if err := db.Ping(ctx); err != nil {
            http.Error(w, "DB not ready", http.StatusServiceUnavailable)
            return
        }

        // Check circuit breaker (if open, we're not ready)
        if paymentClient.circuitBreaker.GetState() == "open" {
            http.Error(w, "Payment service unavailable", http.StatusServiceUnavailable)
            return
        }

        w.WriteHeader(http.StatusOK)
        json.NewEncoder(w).Encode(map[string]string{"status": "ready"})
    }
}

// Register handlers
func RegisterHealthEndpoints(mux *http.ServeMux, db *pgx.Conn, paymentClient *PaymentGatewayClient) {
    mux.HandleFunc("GET /healthz", LivenessHandler(db))
    mux.HandleFunc("GET /readyz", ReadinessHandler(db, paymentClient))
}
```

## Trade-offs & What Breaks

### What Breaks

**1. Retry Storms**
```
10,000 clients all retry after 1 second (no jitter)
→ Thundering herd effect
→ Service recovers, then crashes again from retry wave
```
Fix: Always use jitter. Decorrelated jitter is optimal.

**2. Cascading Circuit Breakers**
```
A → B → C

Service C fails.
Circuit breaker for C opens.
Service B's calls to C all fail.
B's circuit breaker opens.
Service A's calls to B all fail.
A's circuit breaker opens.
```
Not necessarily bad (failure isolation), but can make recovery slow. Use health checks and fast feedback.

**3. Health Check Failures Hiding Real Problems**
```
Readiness check: Can we reach the database?
Yes, latency is 100ms.
But the database is in a deadlock and won't accept writes.
Service is still marked "ready".
```
Fix: Health checks should test the actual operations (write a row, read it back).

**4. Bulkhead Starvation**
```
PaymentService bulkhead: max 50 concurrent
All 50 slots filled by slow requests (10 second timeout)
Fast requests queue up.
Fairness is lost.
```
Fix: Use priority queues or timeout-aware admission control.

**5. Fallback Cache Growing Stale**
```
Payment gateway returns different exchange rate every hour.
We cache a result from 2 hours ago.
User sees wrong price.
```
Fix: Add TTL to cache entries. Don't use fallback for rate-dependent data.

## Interview Corner

**Q1: Explain the resilience stack and the order of operations.**

A: Timeout → Retry → Circuit Breaker → Bulkhead → Fallback.

Timeout is applied first (kill the request if it takes too long). Retry happens next (if transient error, try again with backoff). Circuit breaker decides whether to attempt (if service keeps failing, stop calling). Bulkhead limits concurrency (don't overload with retries). Fallback provides a degraded response if all else fails.

**Q2: Design the circuit breaker for a critical payment service vs. a non-critical search service.**

A:
**Payment (critical):**
- Failure threshold: 3 (fail fast)
- Timeout: 30s (conservative, don't reopen prematurely)
- Half-open max requests: 1 (test carefully)
- Fallback: None (don't charge twice)

**Search (non-critical):**
- Failure threshold: 10 (more tolerance)
- Timeout: 10s (aggressive)
- Half-open max requests: 5 (test aggressively)
- Fallback: Empty results or cached search

**Q3: What's the difference between liveness and readiness probes?**

A: **Liveness**: Can the service do basic operations? If not, kill it so Kubernetes restarts it. Check: DB ping, can acquire a resource.

**Readiness**: Can the service handle requests? If not, remove from load balancer, don't send traffic. Check: DB available, dependencies (payment service, cache) available, no circuit breaker open.

**Q4: How does jitter prevent thundering herd?**

A: Without jitter, all clients retry at the same time (e.g., second 5, second 10, second 15). With jitter, each client adds random delay, spreading retries across time. Result: Gradual load increase instead of spike.

**Q5: Design resilience for a WhatsApp-like messaging system where messages must be delivered exactly once.**

A:
- **Timeout**: 10 seconds per hop (message → service → storage)
- **Retry**: Yes, for transient errors (timeout, 5xx), with exponential backoff
- **Circuit Breaker**: Maybe (but carefully—if message service CB opens, users can't message)
- **Bulkhead**: Yes, separate pools for different message types (user messages, group messages, notifications)
- **Fallback**: Queue message locally, retry later
- **Idempotency**: Each message has unique ID; receiver deduplicates

**Q6: How do you test resilience patterns?**

A:
1. Unit test each pattern (circuit breaker state transitions, retry backoff)
2. Integration test with chaos engineering (kill database, make service slow)
3. Load test (verify circuit breaker opens under load)
4. Simulate failures: network timeouts, 5xx errors, timeouts
5. Verify correct behavior: fallback used, circuit breaker opened, retries happening

## Exercise

**Build a resilient HTTP client for a payment service:**

1. Implement a circuit breaker from scratch
2. Add exponential backoff + jitter retry logic
3. Add token bucket rate limiting
4. Add semaphore bulkhead (max 50 concurrent)
5. Add a fallback (cached result or default)
6. Test: Make a failing service, watch circuit breaker open, verify fallback is used
7. Test: Make service recover, watch circuit breaker half-open, verify recovery
8. Metrics: Log all state transitions, failures, retries
9. Add liveness and readiness health checks

Bonus:
- Implement adaptive timeouts based on p99 latency
- Add a thread pool bulkhead instead of semaphore
- Implement timeout budgets across service chains

## Advanced Resilience Patterns

### Adaptive Timeout Based on P99 Latency

**Problem**: Fixed timeouts don't adapt to changing system behavior
```
PaymentService usually responds in 100ms
At 10 PM, response time increases to 800ms (batch jobs running)
Fixed timeout of 200ms causes failures
```

**Solution: Adjust timeout based on recent latency**

```go
type AdaptiveTimeout struct {
    latencies   []time.Duration
    p99         time.Duration
    mu          sync.RWMutex
}

func (at *AdaptiveTimeout) Record(latency time.Duration) {
    at.mu.Lock()
    defer at.mu.Unlock()

    at.latencies = append(at.latencies, latency)
    if len(at.latencies) > 1000 {
        at.latencies = at.latencies[1:]  // Keep last 1000
    }

    // Calculate new P99
    sorted := make([]time.Duration, len(at.latencies))
    copy(sorted, at.latencies)
    sort.Slice(sorted, func(i, j int) bool { return sorted[i] < sorted[j] })

    index := (99 * len(sorted)) / 100
    at.p99 = sorted[index] * 2  // Multiply by 2 for safety margin
}

func (at *AdaptiveTimeout) GetTimeout() time.Duration {
    at.mu.RLock()
    defer at.mu.RUnlock()

    if at.p99 == 0 {
        return 5 * time.Second  // Default
    }

    return at.p99
}

// Usage
timeout := adaptiveTimeout.GetTimeout()
ctx, cancel := context.WithTimeout(ctx, timeout)
defer cancel()
```

### Retry Budgets

**Problem**: Too many retries overload the system
```
1000 requests × 3 retries = 3000 requests
Service is already overloaded, retries make it worse
```

**Solution: Retry budget** (limit total retries)

```go
type RetryBudget struct {
    maxRetries int64
    used       int64
    resetTime  time.Time
    mu         sync.Mutex
}

func (rb *RetryBudget) TryRetry() bool {
    rb.mu.Lock()
    defer rb.mu.Unlock()

    // Reset budget every minute
    if time.Since(rb.resetTime) > 1*time.Minute {
        rb.used = 0
        rb.resetTime = time.Now()
    }

    if rb.used >= rb.maxRetries {
        return false  // Budget exhausted
    }

    rb.used++
    return true
}

// Usage
for attempt := 0; attempt < 3; attempt++ {
    err := callService()
    if err == nil {
        return nil
    }

    if attempt < 2 && retryBudget.TryRetry() {
        time.Sleep(backoff)
        continue
    }

    return err
}
```

### Combining All Patterns: The Complete Stack

A production resilient client combines all patterns in correct order:

```go
func CallPaymentServiceResilient(ctx context.Context, req *ChargeRequest) (*PaymentResult, error) {
    // Layer 1: Timeout (outermost, applies to entire operation)
    ctx, cancel := context.WithTimeout(ctx, adaptiveTimeout.GetTimeout())
    defer cancel()

    // Layer 2: Rate limiting (reject early if overloaded)
    if !rateLimiter.Allow() {
        return nil, status.Errorf(codes.ResourceExhausted, "rate limited")
    }

    // Layer 3: Bulkhead (semaphore)
    select {
    case bulkhead.sem <- struct{}{}:
        defer func() { <-bulkhead.sem }()
    default:
        return nil, status.Errorf(codes.ResourceExhausted, "at capacity")
    }

    // Layer 4: Circuit breaker + Retry
    return callWithCircuitBreakerAndRetry(ctx, req)
}

func callWithCircuitBreakerAndRetry(ctx context.Context, req *ChargeRequest) (*PaymentResult, error) {
    // Get circuit breaker state
    state := circuitBreaker.GetState()
    if state == "open" {
        // Try fallback
        return getFallbackResult(req.BookingId), nil
    }

    // Retry with exponential backoff + jitter
    maxRetries := 3
    var lastErr error

    for attempt := 0; attempt <= maxRetries; attempt++ {
        // Check if we've exceeded timeout
        select {
        case <-ctx.Done():
            return nil, ctx.Err()
        default:
        }

        // Check retry budget
        if attempt > 0 && !retryBudget.TryRetry() {
            return nil, fmt.Errorf("retry budget exhausted: %w", lastErr)
        }

        // Make the call
        result, err := paymentServiceClient.Charge(ctx, req)

        if err == nil {
            // Success, record for adaptive timeout
            adaptiveTimeout.Record(time.Since(time.Now()))
            circuitBreaker.RecordSuccess()
            return result, nil
        }

        // Failure
        if !isRetryable(err) {
            circuitBreaker.RecordFailure()
            return nil, err
        }

        lastErr = err
        if attempt == maxRetries {
            circuitBreaker.RecordFailure()
            break
        }

        // Exponential backoff + jitter
        backoff := time.Duration(math.Pow(2, float64(attempt))) * time.Second
        jitter := time.Duration(rand.Int63n(int64(backoff)))
        sleep := min(backoff+jitter, 10*time.Second)

        select {
        case <-time.After(sleep):
            // Continue retrying
        case <-ctx.Done():
            return nil, ctx.Err()
        }
    }

    // All retries exhausted
    circuitBreaker.RecordFailure()

    // Try fallback
    if fallback := getFallbackResult(req.BookingId); fallback != nil {
        return fallback, nil
    }

    return nil, lastErr
}
```

### Health Checks: Advanced Patterns

**Deep health checks that test actual operations:**

```go
func DeepHealthCheck(db *pgx.Conn, cache *redis.Client) error {
    ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
    defer cancel()

    // Test 1: Can write to database
    testId := uuid.NewString()
    err := db.QueryRow(ctx,
        "INSERT INTO health_check (id, checked_at) VALUES ($1, NOW()) RETURNING id",
        testId).Scan(&testId)
    if err != nil {
        return fmt.Errorf("database write failed: %w", err)
    }

    // Test 2: Can read from database
    var result string
    err = db.QueryRow(ctx, "SELECT id FROM health_check WHERE id = $1", testId).Scan(&result)
    if err != nil {
        return fmt.Errorf("database read failed: %w", err)
    }

    // Test 3: Can write to cache
    err = cache.Set(ctx, testId, "test", time.Second).Err()
    if err != nil {
        return fmt.Errorf("cache write failed: %w", err)
    }

    // Test 4: Can read from cache
    val, err := cache.Get(ctx, testId).Result()
    if err != nil {
        return fmt.Errorf("cache read failed: %w", err)
    }

    // Clean up
    cache.Del(ctx, testId)
    db.Exec(ctx, "DELETE FROM health_check WHERE id = $1", testId)

    return nil
}
```

**Split horizon health checks** (different probe locations):

```go
// health/handlers.go
// Kubernetes probes from different locations:
// - Liveness: From same node (localhost)
// - Readiness: From load balancer (via network)

func LivenessHandler(db *pgx.Conn) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        ctx, cancel := context.WithTimeout(r.Context(), 1*time.Second)
        defer cancel()

        if err := db.Ping(ctx); err != nil {
            http.Error(w, "not alive", http.StatusServiceUnavailable)
            return
        }

        w.WriteHeader(http.StatusOK)
    }
}

func ReadinessHandler(db *pgx.Conn, externalDeps []ExternalService) http.HandlerFunc {
    return func(w http.ResponseWriter, r *http.Request) {
        ctx, cancel := context.WithTimeout(r.Context(), 5*time.Second)
        defer cancel()

        // Check all external dependencies
        for _, dep := range externalDeps {
            if err := dep.Health(ctx); err != nil {
                http.Error(w, fmt.Sprintf("not ready: %s unavailable", dep.Name()), http.StatusServiceUnavailable)
                return
            }
        }

        w.WriteHeader(http.StatusOK)
    }
}
```

## Advanced Interview Questions

**Q7: Design resilience for a critical payment service handling 100,000 RPS.**

A: Layered approach:

1. **Timeout**: 2 second (aggressive, fail fast)
2. **Rate limiting**: 100,000 RPS global, 1000 RPS per user (token bucket)
3. **Bulkhead**: 10,000 max concurrent (at 100µs per request = 1 RPS plateau)
4. **Circuit breaker**: 5 consecutive failures → open for 30s
5. **Retry budget**: Allow 1M retries/minute (10% of traffic)
6. **Fallback**: Cached recent successful charges (risky but better than failure)
7. **Health checks**: Every 10 seconds, liveness every 2 seconds
8. **Load shedding**: If queue > 5000 requests, return HTTP 503

**Q8: Your circuit breaker is stuck open (service is actually recovered, but CB doesn't know).**

A: Reasons and solutions:

1. **Reason: Half-open state never entered**
   - Fix: Ensure timeout is correct and starts ticking from last failure
   - Check logs: Is CB transitioning to half-open?

2. **Reason: Half-open test request failed (service partially recovered)**
   - Fix: Send more test requests in half-open (increase max half-open requests from 3 to 10)
   - Or: Use better health check for half-open (actual call, not ping)

3. **Reason: Success threshold not met**
   - Fix: Reduce success threshold (from 2 to 1)
   - Add: Metrics to see how many successes we're getting in half-open

4. **Monitoring/debugging**:
   ```go
   // Export CB metrics
   prometheus.Register(prometheus.NewGaugeFunc(
       prometheus.GaugeOpts{Name: "circuit_breaker_state"},
       func() float64 {
           state := cb.GetState()
           if state == "closed" { return 0 }
           if state == "open" { return 1 }
           return 2  // half-open
       },
   ))
   ```


