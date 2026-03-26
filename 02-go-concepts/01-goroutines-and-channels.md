# Goroutines and Channels: Mastering Concurrent Patterns in Go

## Problem: Building Concurrent Systems

You're building a movie booking system that must:
- Check seat availability across 100+ cinema locations simultaneously
- Handle real-time ticket purchases without blocking
- Gracefully handle timeouts when cinema APIs are slow
- Prevent goroutine leaks from accumulating over time

The core challenge: Go makes concurrency *easy* (one keyword: `go`), but doesn't force you to get it *right*. Understanding goroutine internals, channel mechanics, and proper synchronization patterns is what separates senior engineers from novices.

---

## Part 1: Goroutine Internals and Execution Model

### The G-M-P Model

Go's runtime scheduler uses a three-tier model:

- **G (Goroutine)**: A lightweight execution context. ~2KB initial stack (grows dynamically), ~1μs creation overhead
- **M (Machine/OS Thread)**: An actual OS thread. ~1-2MB stack committed from OS
- **P (Processor)**: A logical processor (GOMAXPROCS, defaults to runtime.NumCPU()). Holds a queue of G's

When you `go f()`, the runtime:
1. Creates a new G with 2KB stack
2. Queues it to the current P's local run queue (or global queue if local is full)
3. If all M's are busy, spawns a new M (up to 10,000 M's hard limit)
4. An M picks up the G, executes it, and parks when blocked on I/O or a channel

**Key insight**: Goroutines are NOT threads. The runtime multiplexes many G's onto fewer M's. This enables millions of goroutines.

### Goroutine Stack Growth

Initial stack: 2KB (much smaller in recent Go versions). When a function call would overflow:
1. The stack grows to the next power of 2 (up to ~1GB limit)
2. All local variables are copied to the new stack
3. Stack pointers in frames are updated

This happens transparently but has CPU cost. Heavy recursion creates overhead.

### Goroutine States and Scheduling

A goroutine can be:
- **Runnable (G)**: Waiting on a P's queue, ready to run
- **Running**: Currently executing on an M
- **Waiting**: Blocked (I/O, channel op, mutex, cond var)
- **Dead**: Finished

The scheduler is **cooperative**. Goroutines yield on:
- I/O operations (net.Dial, file reads, etc.)
- Channel send/receive
- time.Sleep(), time.After()
- Synchronization primitives (mutex, cond var, wait group)

Long CPU-bound work without these yields blocks other goroutines. Use `runtime.Gosched()` to force yield in tight loops.

---

## Part 2: Channel Internals

### The hchan Structure

Internally, channels are represented as:

```go
type hchan struct {
    qcount   uint           // Current queue size
    dataqsiz uint           // Circular queue capacity
    buf      unsafe.Pointer // Actual data array
    elemsize uint16         // Size of each element
    closed   uint32         // Is closed? (atomic)
    elemtype *_type         // Type of elements
    sendx    uint           // Send index in buf
    recvx    uint           // Receive index in buf
    recvq    waitq          // Recv goroutines waiting on empty channel
    sendq    waitq          // Send goroutines waiting on full channel
    lock     mutex          // Protects all fields
}
```

### Send/Receive Mechanics

**Sending on a channel**:
1. Acquire hchan.lock
2. If there's a blocked receiver, wake it up and copy data
3. If buffer has space, write to buf[sendx], increment sendx and qcount
4. If buffer is full, add sender to sendq and park the goroutine
5. Release lock

**Receiving from a channel**:
1. Acquire hchan.lock
2. If there's buffered data, read from buf[recvx], increment recvx
3. If there's a blocked sender, wake it up
4. If channel is empty and closed, return zero value + false
5. If buffer is empty, add receiver to recvq and park
6. Release lock

**Sending on closed channel**: Panic
**Receiving from closed channel**: Returns zero values + false

### Buffered vs Unbuffered

- **Unbuffered (chan T)**: dataqsiz=0, buf=nil. Send blocks until receiver ready.
- **Buffered (chan T, n)**: dataqsiz=n, buf=malloced array of size n*elemsize. Send blocks only when buffer full.

**Performance implication**: Buffered channels reduce blocking on high-throughput scenarios, but buffer memory is wasted if unused.

---

## Part 3: Classic Concurrency Patterns

### Pattern 1: Fan-Out/Fan-In

Distribute work across multiple workers, then merge results.

```go
// Fan-out: spawn N workers
func fanOut(workers int, jobs <-chan Job) []<-chan Result {
    results := make([]<-chan Result, workers)
    for i := 0; i < workers; i++ {
        ch := make(chan Result)
        results[i] = ch
        go func(c chan<- Result) {
            for job := range jobs {
                c <- processJob(job)
            }
            close(c)
        }(ch)
    }
    return results
}

// Fan-in: merge all results back
func fanIn(channels ...<-chan Result) <-chan Result {
    var wg sync.WaitGroup
    out := make(chan Result)

    for _, ch := range channels {
        wg.Add(1)
        go func(c <-chan Result) {
            defer wg.Done()
            for result := range c {
                out <- result
            }
        }(ch)
    }

    go func() {
        wg.Wait()
        close(out)
    }()

    return out
}

// Usage
jobs := make(chan Job, 100)
results := fanIn(fanOut(4, jobs)...)

for i := 0; i < 10; i++ {
    jobs <- Job{id: i}
}
close(jobs)

for result := range results {
    fmt.Println(result)
}
```

### Pattern 2: Worker Pool for Bounded Concurrency

Limit concurrent API calls to avoid exhausting resources.

```go
type WorkerPool struct {
    workers int
    jobs    chan Job
    results chan Result
    wg      sync.WaitGroup
}

func NewWorkerPool(workers int) *WorkerPool {
    return &WorkerPool{
        workers: workers,
        jobs:    make(chan Job, workers*2),
        results: make(chan Result, workers*2),
    }
}

func (wp *WorkerPool) Start(ctx context.Context) {
    for i := 0; i < wp.workers; i++ {
        wp.wg.Add(1)
        go wp.worker(ctx)
    }
}

func (wp *WorkerPool) worker(ctx context.Context) {
    defer wp.wg.Done()

    for {
        select {
        case job, ok := <-wp.jobs:
            if !ok {
                return // jobs channel closed, exit
            }
            result := executeJob(ctx, job)
            // Non-blocking send; drop result if buffer full
            select {
            case wp.results <- result:
            case <-ctx.Done():
                return
            }
        case <-ctx.Done():
            return
        }
    }
}

func (wp *WorkerPool) Submit(job Job) error {
    select {
    case wp.jobs <- job:
        return nil
    default:
        return ErrPoolFull
    }
}

func (wp *WorkerPool) Wait() {
    close(wp.jobs)
    wp.wg.Wait()
    close(wp.results)
}

func (wp *WorkerPool) Results() <-chan Result {
    return wp.results
}
```

### Pattern 3: Pipeline

Chain operations where each stage is a goroutine.

```go
// Stage 1: Generate numbers
func generate(ctx context.Context, nums ...int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for _, n := range nums {
            select {
            case out <- n:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Stage 2: Square numbers
func square(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {
            select {
            case out <- n * n:
            case <-ctx.Done():
                return
            }
        }
    }()
    return out
}

// Stage 3: Filter evens
func filterEven(ctx context.Context, in <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        defer close(out)
        for n := range in {
            if n%2 == 0 {
                select {
                case out <- n:
                case <-ctx.Done():
                    return
                }
            }
        }
    }()
    return out
}

// Usage: generate(ctx, 1,2,3,4,5) -> square -> filterEven -> consume
func pipeLine(ctx context.Context) {
    nums := generate(ctx, 1, 2, 3, 4, 5)
    squared := square(ctx, nums)
    evens := filterEven(ctx, squared)

    for n := range evens {
        fmt.Println(n) // 4, 16
    }
}
```

---

## Part 4: Goroutine Leaks and Detection

### What Is a Goroutine Leak?

A goroutine that never exits, consuming memory and resources indefinitely. Common causes:

1. **Blocked on channel receive**: No sender ever sends, no close signal
2. **Blocked on channel send**: Buffer full, no receiver, channel never closed
3. **Blocked on mutex.Lock()**: Lock never released
4. **time.After() leak**: Goroutine waits forever if you forget to drain the channel

### Detection

```go
func TestGoroutineLeakDetector(t *testing.T) {
    initialCount := runtime.NumGoroutine()

    // Your test code here
    leakyOperation()

    // Force GC to clean up closed goroutines
    time.Sleep(100 * time.Millisecond)
    runtime.GC()

    finalCount := runtime.NumGoroutine()
    if finalCount > initialCount {
        t.Fatalf("goroutine leak detected: %d -> %d", initialCount, finalCount)
    }
}
```

### Prevention Patterns

```go
// LEAK: Sender never closes, receiver waits forever
func leakyFanOut(jobs <-chan int) <-chan int {
    out := make(chan int)
    go func() {
        for j := range jobs {
            out <- j * 2  // If jobs never closes, goroutine never exits
        }
        // Missing: close(out)
    }()
    return out
}

// FIXED: Use WaitGroup to signal completion
func properFanOut(jobs <-chan int) <-chan int {
    out := make(chan int)
    var wg sync.WaitGroup

    wg.Add(1)
    go func() {
        defer wg.Done()
        for j := range jobs {
            out <- j * 2
        }
    }()

    go func() {
        wg.Wait()
        close(out)
    }()

    return out
}

// LEAK: Sender blocks on full buffer, never checks context
func leakyPolling(ctx context.Context, ch chan<- int) {
    go func() {
        for i := 0; i < 1000000; i++ {
            ch <- i  // Blocks if no receiver, ignores ctx cancellation
        }
    }()
}

// FIXED: Check context in send
func properPolling(ctx context.Context, ch chan<- int) {
    go func() {
        for i := 0; i < 1000000; i++ {
            select {
            case ch <- i:
            case <-ctx.Done():
                return
            }
        }
    }()
}
```

---

## Part 5: Select Statement Deep Dive

### Basic Select

```go
select {
case x := <-ch1:
    fmt.Println("received from ch1:", x)
case y := <-ch2:
    fmt.Println("received from ch2:", y)
case ch3 <- value:
    fmt.Println("sent to ch3")
default:
    fmt.Println("no channels ready")
}
```

Waits for one of the channels to be ready. If multiple are ready, picks one at random. If none are ready and no default, blocks.

### The Priority Select Hack

When one channel should be checked before others:

```go
// PROBLEM: if ch1 and ch2 both have data, we want ch1 first
func prioritySelect() {
    var ch1, ch2 <-chan int

    for {
        select {
        case x := <-ch1:
            fmt.Println("ch1:", x)
        case y := <-ch2:
            fmt.Println("ch2:", y)
        }
    }
}

// SOLUTION: nested select
func prioritySelectFixed() {
    var ch1, ch2 <-chan int

    for {
        select {
        case x := <-ch1:
            fmt.Println("ch1:", x)
        default:
            select {
            case y := <-ch2:
                fmt.Println("ch2:", y)
            default:
                // Both empty
            }
        }
    }
}
```

### Timeout Patterns

```go
// Pattern 1: time.After (beware: goroutine leak)
func timeoutAfter(ch <-chan int, duration time.Duration) (int, error) {
    select {
    case x := <-ch:
        return x, nil
    case <-time.After(duration):
        return 0, ErrTimeout
    }
    // time.After goroutine is cleaned up only after duration elapses!
}

// Pattern 2: time.Timer (reusable)
func timeoutTimer(ch <-chan int, duration time.Duration) (int, error) {
    timer := time.NewTimer(duration)
    defer timer.Stop()  // Critical: stop timer to prevent goroutine leak

    select {
    case x := <-ch:
        return x, nil
    case <-timer.C:
        return 0, ErrTimeout
    }
}

// Pattern 3: context.WithTimeout (preferred)
func timeoutContext(ctx context.Context, ch <-chan int) (int, error) {
    ctx, cancel := context.WithTimeout(ctx, 5*time.Second)
    defer cancel()

    select {
    case x := <-ch:
        return x, nil
    case <-ctx.Done():
        return 0, ctx.Err()
    }
}
```

### Done Channel Pattern

Signal completion or cancellation across goroutines:

```go
func workerWithDone(id int, jobs <-chan int, done <-chan struct{}) {
    for {
        select {
        case job := <-jobs:
            fmt.Printf("Worker %d processing job %d\n", id, job)
        case <-done:
            fmt.Printf("Worker %d shutting down\n", id)
            return
        }
    }
}

func main() {
    jobs := make(chan int, 10)
    done := make(chan struct{})

    for i := 1; i <= 3; i++ {
        go workerWithDone(i, jobs, done)
    }

    for i := 1; i <= 20; i++ {
        jobs <- i
    }

    close(done) // Signal all workers to exit
    time.Sleep(1 * time.Second)
}
```

---

## Part 6: Production Code — Concurrent Seat Availability Checker

Real-world scenario: Check seat availability across 50 cinema locations, with timeout and error handling.

```go
package cinema

import (
    "context"
    "errors"
    "fmt"
    "net/http"
    "sync"
    "time"
)

// Movie and Seat availability types
type Cinema struct {
    ID   string
    Name string
    URL  string
}

type SeatAvailability struct {
    CinemaID   string
    Available  int
    Total      int
    LastChecked time.Time
}

type CheckResult struct {
    Cinema    Cinema
    Availability *SeatAvailability
    Error     error
}

// CinemaChecker uses a worker pool to check multiple cinemas
type CinemaChecker struct {
    workers int
    timeout time.Duration
    client  *http.Client
}

func NewCinemaChecker(workers int, timeout time.Duration) *CinemaChecker {
    return &CinemaChecker{
        workers: workers,
        timeout: timeout,
        client: &http.Client{
            Timeout: timeout,
        },
    }
}

// CheckAvailability fetches availability from a single cinema
func (cc *CinemaChecker) checkAvailability(ctx context.Context, cinema Cinema) (*SeatAvailability, error) {
    ctx, cancel := context.WithTimeout(ctx, cc.timeout)
    defer cancel()

    req, err := http.NewRequestWithContext(ctx, http.MethodGet, cinema.URL, nil)
    if err != nil {
        return nil, err
    }

    resp, err := cc.client.Do(req)
    if err != nil {
        return nil, fmt.Errorf("failed to fetch from %s: %w", cinema.ID, err)
    }
    defer resp.Body.Close()

    if resp.StatusCode != http.StatusOK {
        return nil, fmt.Errorf("cinema %s returned status %d", cinema.ID, resp.StatusCode)
    }

    // Parse response (simplified)
    return &SeatAvailability{
        CinemaID:    cinema.ID,
        Available:   rand.Intn(100),
        Total:       100,
        LastChecked: time.Now(),
    }, nil
}

// CheckMultiple checks all cinemas concurrently with worker pool
func (cc *CinemaChecker) CheckMultiple(ctx context.Context, cinemas []Cinema) []CheckResult {
    jobs := make(chan Cinema, len(cinemas))
    results := make([]CheckResult, 0, len(cinemas))
    var resultsMu sync.Mutex

    // Start workers
    var wg sync.WaitGroup
    for i := 0; i < cc.workers; i++ {
        wg.Add(1)
        go func() {
            defer wg.Done()
            for cinema := range jobs {
                availability, err := cc.checkAvailability(ctx, cinema)

                resultsMu.Lock()
                results = append(results, CheckResult{
                    Cinema:        cinema,
                    Availability: availability,
                    Error:         err,
                })
                resultsMu.Unlock()
            }
        }()
    }

    // Send jobs
    for _, cinema := range cinemas {
        jobs <- cinema
    }
    close(jobs)

    // Wait for completion
    wg.Wait()
    return results
}

// Example usage with timeout cascade
func checkBookingAvailability(ctx context.Context, movieID string) error {
    // Create cancellable context for the entire operation
    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)
    defer cancel()

    // Phase 1: Check availability (max 5 seconds)
    availCtx, _ := context.WithTimeout(ctx, 5*time.Second)
    checker := NewCinemaChecker(10, 1*time.Second)

    cinemas := []Cinema{
        {ID: "c1", Name: "Downtown", URL: "http://cinema-api.local/c1"},
        {ID: "c2", Name: "Mall", URL: "http://cinema-api.local/c2"},
        // ... 48 more
    }

    results := checker.CheckMultiple(availCtx, cinemas)

    // Phase 2: Lock seats (max 3 seconds remaining)
    lockCtx, _ := context.WithTimeout(ctx, 3*time.Second)
    _ = lockCtx // Use for locking operation

    // Phase 3: Process payment (remaining time)
    for _, result := range results {
        if result.Error != nil {
            fmt.Printf("Failed to check %s: %v\n", result.Cinema.ID, result.Error)
            continue
        }
        fmt.Printf("%s has %d/%d seats\n", result.Cinema.Name,
            result.Availability.Available, result.Availability.Total)
    }

    return nil
}
```

---

## Part 7: What Breaks at Scale

### Issue 1: Unbounded Goroutine Creation

```go
// DANGER: Each request spawns a goroutine that never exits if client disconnects
http.HandleFunc("/movie-check", func(w http.ResponseWriter, r *http.Request) {
    go func() {
        // If client disconnects, this goroutine still runs to completion
        results := expensiveCheck(r.Context())
        // What if it takes 1 hour? Goroutine leak!
    }()
})
```

Fix: Use request context, respect cancellation:

```go
http.HandleFunc("/movie-check", func(w http.ResponseWriter, r *http.Request) {
    select {
    case results := <-performCheck(r.Context()):
        json.NewEncoder(w).Encode(results)
    case <-r.Context().Done():
        // Client disconnected, cleanly exit
        http.Error(w, "Request cancelled", http.StatusRequestTimeout)
    }
})
```

### Issue 2: Channel Deadlocks Under Load

```go
// DANGER: If buffer fills, senders block. If all workers are blocked, new work starves
func process(jobs <-chan Job) {
    results := make(chan Result, 1000) // Fixed buffer

    for job := range jobs {
        results <- processJob(job)  // Blocks if buffer full!
    }
}
```

Fix: Non-blocking send or drop policy:

```go
func process(jobs <-chan Job) <-chan Result {
    results := make(chan Result)
    go func() {
        defer close(results)
        for job := range jobs {
            result := processJob(job)
            select {
            case results <- result:
                // Sent
            default:
                // Drop result if buffer full (or retry, or fail fast)
                fmt.Println("dropped result, consumer too slow")
            }
        }
    }()
    return results
}
```

### Issue 3: Context Cancellation Ignored

```go
// DANGER: Ignores context cancellation, runs to completion regardless
func leakyWorker(ctx context.Context, jobs <-chan Job) {
    for job := range jobs {
        processJob(job)  // No context check!
    }
}
```

Fix: Always check context in loops:

```go
func properWorker(ctx context.Context, jobs <-chan Job) {
    for {
        select {
        case job, ok := <-jobs:
            if !ok { return }
            processJob(job)
        case <-ctx.Done():
            return
        }
    }
}
```

---

## Part 8: Channel Direction Types

Go allows specifying send-only or receive-only channels in function signatures for safety:

```go
// Send-only channel (can only send, not receive)
func sendToChannel(ch chan<- int) {
    ch <- 42  // OK
    // x := <-ch  // ERROR: receive on send-only channel
}

// Receive-only channel (can only receive, not send)
func receiveFromChannel(ch <-chan int) int {
    return <-ch  // OK
    // ch <- 42  // ERROR: send on receive-only channel
}

// Bidirectional channel (default)
func fullChannel(ch chan int) {
    ch <- 1
    x := <-ch
}

// Implicit conversion: bidirectional -> unidirectional
func worker(jobs <-chan Job, results chan<- Result) {
    for job := range jobs {
        results <- process(job)
    }
}

var jobs chan Job = make(chan Job)
var results chan Result = make(chan Result)

go worker(jobs, results)  // Auto-converted to send/receive only
```

This is more than syntactic sugar: it enforces ownership. Only the owner can send; only consumers receive.

---

## Part 9: Advanced Channel Patterns

### Or-Channel Pattern

Merge multiple channels into a single output:

```go
// Wait for first signal from any channel
func orChannel(channels ...<-chan struct{}) <-chan struct{} {
    switch len(channels) {
    case 0:
        return nil
    case 1:
        return channels[0]
    }

    orDone := make(chan struct{})
    go func() {
        defer close(orDone)
        switch len(channels) {
        case 2:
            select {
            case <-channels[0]:
            case <-channels[1]:
            }
        default:
            select {
            case <-channels[0]:
            case <-channels[1]:
            case <-channels[2]:
            // ... or use recursion
            case <-orChannel(append(channels[3:])...):
            }
        }
    }()
    return orDone
}

// Usage: cancel if any of multiple contexts cancelled
done := orChannel(ctx1.Done(), ctx2.Done(), ctx3.Done())
<-done  // Returns when any context is cancelled
```

### Tee-Channel Pattern

Duplicate a channel to multiple consumers:

```go
func tee[T any](ch <-chan T) (<-chan T, <-chan T) {
    ch1 := make(chan T, 1)
    ch2 := make(chan T, 1)

    go func() {
        defer close(ch1)
        defer close(ch2)

        for val := range ch {
            select {
            case ch1 <- val:
            case <-ch1:
                ch1 <- val
            }
            select {
            case ch2 <- val:
            case <-ch2:
                ch2 <- val
            }
        }
    }()

    return ch1, ch2
}

// Usage: broadcast to multiple readers
results := tee(resultsChannel)
go processWithLogging(results)  // Consumer 1
go processWithAnalytics(results) // Consumer 2
```

### Bridge-Channel Pattern

Connect generator to pipeline:

```go
func bridge[T any](ch <-chan <-chan T) <-chan T {
    out := make(chan T)

    go func() {
        defer close(out)

        for {
            var inner <-chan T
            select {
            case nextCh, ok := <-ch:
                if !ok {
                    return
                }
                inner = nextCh
            default:
            }

            if inner != nil {
                select {
                case val, ok := <-inner:
                    if !ok {
                        inner = nil
                    } else {
                        out <- val
                    }
                }
            }
        }
    }()

    return out
}

// Usage: handle sequence of channels
gen := generateChannelSequence()
merged := bridge(gen)
```

### Nil Channel Behavior in Select

```go
// DANGER: Receiving on nil channel blocks forever
var ch chan int
<-ch  // DEADLOCK

// But in select, it's ignored
var ch chan int
select {
case <-ch:  // Ignored because ch is nil
    fmt.Println("never executes")
case <-time.After(1 * time.Second):
    fmt.Println("timeout")
}

// Clever: disable channel by setting to nil
func worker(cancel <-chan struct{}, ch <-chan Job) {
    for {
        select {
        case <-cancel:
            return
        case job, ok := <-ch:
            if !ok {
                ch = nil  // Disable this case by setting to nil
            } else {
                process(job)
            }
        case val := <-otherCh:
            handleOther(val)
        }
    }
}
```

### GOMAXPROCS and Goroutine Scheduling

```go
import "runtime"

// GOMAXPROCS controls number of processors
fmt.Println(runtime.NumCPU())        // Physical CPUs
fmt.Println(runtime.GOMAXPROCS(-1))  // Current setting

// Override (usually bad idea)
runtime.GOMAXPROCS(4)  // Force 4 logical processors

// When to tune GOMAXPROCS:
// 1. High I/O-bound workloads: may benefit from > NumCPU
// 2. Low CPU-bound workloads: may use < NumCPU to reduce context switching
// 3. Containers with CPU limits: must match container limits
//    runtime.GOMAXPROCS(runtime.NumCPU()) // Might be wrong!
//    Better: Use cgroup-aware detection (requires syscall)
```

### Goroutine Preemption (Go 1.14+)

Go 1.14 introduced **non-cooperative** preemption. Goroutines can be paused even without yielding.

```go
// Before Go 1.14: This would starve other goroutines
func busyLoop() {
    for {
        // No I/O, no channel, no sync primitive
        // Goroutine never yields, blocks other G's on same thread
    }
}

// Go 1.14+: Runtime injects preemption points
// Goroutines are paused on signal (every ~10ms)
// This solves the starvation problem

// LIMITATION: Can't preempt during syscall
// If goroutine blocks on syscall (file I/O, network), it ties up M thread
// Solution: Use non-blocking I/O (net, os) which yields properly
```

---

## Interview Corner

### Q1: What is the difference between buffered and unbuffered channels?

**Model Answer**:
- **Unbuffered (chan T)**: Send blocks until a receiver is ready. Enforces synchronization.
- **Buffered (chan T, n)**: Send only blocks when buffer is full. Decouples sender/receiver.

Use unbuffered for tight synchronization (e.g., done signals). Use buffered for work distribution (e.g., job queues) or to prevent sender blocking when receiver is slower.

Memory cost: Buffered channels allocate memory upfront (n * sizeof(T)). If unused, it's wasted.

### Q2: How do you prevent goroutine leaks in a worker pool?

**Model Answer**:
1. Always close channels to signal completion to workers
2. Use WaitGroup to track worker lifecycle
3. Check context.Done() in worker loops
4. Ensure all goroutines have an exit condition

```go
var wg sync.WaitGroup
for i := 0; i < workers; i++ {
    wg.Add(1)
    go func() {
        defer wg.Done()
        for job := range jobs {
            processJob(job)
        }
    }()
}
close(jobs)
wg.Wait()
```

### Q3: Why is `time.After()` a goroutine leak in a loop?

**Model Answer**:
Each call to `time.After(d)` starts a timer goroutine. If the timer fires (because you exited the select), the goroutine is cleaned up. But if your code already returned or moved to another iteration *before* the timer fires, that goroutine waits around until the timer expires (up to `d` seconds).

In a tight loop, this accumulates. Fix: Use `time.Timer` and call `Stop()`:

```go
timer := time.NewTimer(timeout)
defer timer.Stop()
select {
case x := <-ch:
    return x
case <-timer.C:
    return ErrTimeout
}
```

### Q4: Explain the G-M-P scheduler model.

**Model Answer**:
- **G**: Goroutine. Lightweight execution context, 2KB initial stack, scheduled by runtime.
- **M**: OS thread. ~1-2MB stack, handles actual CPU execution.
- **P**: Logical processor. GOMAXPROCS of them, each has a run queue of G's.

When a goroutine blocks on I/O, the M is parked and another M picks up the next G. This allows 1M threads to multiplex 1M goroutines.

Scheduler is **cooperative**: goroutines yield on I/O, channels, time.Sleep(), or synchronization. Long CPU-bound work without yields blocks other goroutines. Go 1.14+ added non-cooperative preemption, but syscalls still tie up threads.

### Q5: Design a rate limiter using channels.

**Model Answer**:
```go
type RateLimiter struct {
    tokens chan struct{}
    tick   *time.Ticker
}

func NewRateLimiter(rps int) *RateLimiter {
    rl := &RateLimiter{
        tokens: make(chan struct{}, rps),
        tick:   time.NewTicker(time.Second / time.Duration(rps)),
    }

    // Replenish tokens periodically
    go func() {
        for range rl.tick.C {
            select {
            case rl.tokens <- struct{}{}:
            default: // Token bucket full
            }
        }
    }()

    return rl
}

func (rl *RateLimiter) Allow(ctx context.Context) bool {
    select {
    case <-rl.tokens:
        return true
    case <-ctx.Done():
        return false
    }
}

func (rl *RateLimiter) Close() {
    rl.tick.Stop()
}
```

### Q6: Design a broadcast channel pattern where one sender sends to multiple receivers.

**Model Answer**:
```go
type Broadcaster[T any] struct {
    mu   sync.RWMutex
    subs map[string]<-chan T
}

// Instead of a broadcaster, use tee or fan-out:
func broadcastToMultiple[T any](in <-chan T, receivers ...chan<- T) {
    for val := range in {
        for _, ch := range receivers {
            select {
            case ch <- val:
            default:
                // Receiver too slow, drop or block
            }
        }
    }
    for _, ch := range receivers {
        close(ch)
    }
}

// Better: Use sync.Cond or sync/atomic for broadcasting state
type State struct {
    mu    sync.Mutex
    cond  *sync.Cond
    data  interface{}
}

func (s *State) Notify(data interface{}) {
    s.mu.Lock()
    defer s.mu.Unlock()
    s.data = data
    s.cond.Broadcast()  // Wake all waiting readers
}
```

### Q7: What happens if you close a channel while goroutines are sending on it?

**Model Answer**:
Sending on a closed channel causes a panic. This is a **synchronization problem**: the sender doesn't know if the channel is closed.

```go
// DANGER: Panic if close(ch) is called concurrently
go func() {
    ch <- value
}()

close(ch)  // If sender is mid-send, panic!
```

**Solution**: Establish ownership. Only the last sender/goroutine should close.

```go
// Pattern: Sync.Once to ensure single closer
var once sync.Once
done := false

// Only one goroutine calls this
func closeOnce() {
    once.Do(func() {
        close(ch)
        done = true
    })
}

// All senders check this
go func() {
    if !done {
        ch <- value
    }
}()
```

Better: Use context cancellation instead of closing channels directly.

### Q8: Design a concurrent merge-sort using goroutines and channels.

**Model Answer**:
```go
func mergeSort[T cmp.Ordered](items []T) []T {
    if len(items) <= 1 {
        return items
    }

    mid := len(items) / 2

    // Sort halves concurrently
    leftCh := make(chan []T)
    rightCh := make(chan []T)

    go func() {
        leftCh <- mergeSort(items[:mid])
    }()

    go func() {
        rightCh <- mergeSort(items[mid:])
    }()

    left := <-leftCh
    right := <-rightCh

    return merge(left, right)
}

func merge[T cmp.Ordered](left, right []T) []T {
    result := make([]T, 0, len(left)+len(right))
    i, j := 0, 0

    for i < len(left) && j < len(right) {
        if left[i] <= right[j] {
            result = append(result, left[i])
            i++
        } else {
            result = append(result, right[j])
            j++
        }
    }

    result = append(result, left[i:]...)
    result = append(result, right[j:]...)
    return result
}
```

Key design decisions:
- Each level of recursion spawns 2 goroutines (exponential growth)
- Must cap goroutines with semaphore or use sync.Pool for thread reuse
- Better approach: Use worker pool instead of unbounded goroutines

### Q9: How would you design a circuit breaker pattern using channels and goroutines?

**Model Answer**:
```go
type CircuitBreaker struct {
    maxFailures int
    timeout     time.Duration
    failures    atomic.Int32
    lastFailure time.Time
    mu          sync.Mutex
    state       string  // "closed", "open", "half-open"
}

func (cb *CircuitBreaker) Call(fn func() error) error {
    cb.mu.Lock()

    // If open and timeout passed, try half-open
    if cb.state == "open" {
        if time.Since(cb.lastFailure) > cb.timeout {
            cb.state = "half-open"
            cb.failures.Store(0)
        } else {
            cb.mu.Unlock()
            return errors.New("circuit open")
        }
    }

    cb.mu.Unlock()

    // Execute function
    err := fn()

    cb.mu.Lock()
    defer cb.mu.Unlock()

    if err != nil {
        cb.failures.Add(1)
        cb.lastFailure = time.Now()

        if cb.failures.Load() >= int32(cb.maxFailures) {
            cb.state = "open"
        }
        return err
    }

    // Success: reset state
    cb.state = "closed"
    cb.failures.Store(0)
    return nil
}
```

This prevents cascading failures by failing fast when a dependency is unavailable.

**Model Answer**:
Sending on a closed channel causes a panic. This is a **synchronization problem**: the sender doesn't know if the channel is closed.

```go
// DANGER: Panic if close(ch) is called concurrently
go func() {
    ch <- value
}()

close(ch)  // If sender is mid-send, panic!
```

**Solution**: Establish ownership. Only the last sender/goroutine should close.

```go
// Pattern: Sync.Once to ensure single closer
var once sync.Once
done := false

// Only one goroutine calls this
func closeOnce() {
    once.Do(func() {
        close(ch)
        done = true
    })
}

// All senders check this
go func() {
    if !done {
        ch <- value
    }
}()
```

Better: Use context cancellation instead of closing channels directly.

---

## Tradeoffs and Real-World Considerations

### Goroutines vs Threads
- **Goroutines**: Cheap (millions), fast creation (1μs), garbage-collected
- **Threads**: Expensive (thousands max), slow creation (1ms), OS-managed
- Use goroutines freely; threads only for long-lived system tasks

### Buffered vs Unbuffered
- **Unbuffered**: Simpler coordination, but sender/receiver must be ready simultaneously
- **Buffered**: Allows async work, but requires careful capacity planning
- Many experts: prefer unbuffered + explicit synchronization for clarity

### Select with Default
- **Without default**: Blocks until a channel is ready
- **With default**: Non-blocking; useful for quick checks
- Beware: default can cause busy-waiting loops; combine with time.Sleep()

### Context in Goroutines
- **Always pass context**: Respects cancellation, allows graceful shutdown
- **Don't ignore ctx.Done()**: Leaks resources and ignores timeouts
- **Avoid context.Background() in goroutines**: Should be passed from caller

---

## Exercise

Build a **concurrent movie seat scanner** that:
1. Scans 20 cinema APIs in parallel (worker pool)
2. Times out individual requests after 500ms
3. Returns results as they complete (not waiting for all)
4. Detects and reports any goroutine leaks
5. Gracefully shuts down on context cancellation

Requirements:
- Must not leak goroutines (test with `runtime.NumGoroutine()`)
- Must handle slow/failing APIs without blocking others
- Must use `context.Context` properly
- Must close channels appropriately

Bonus: Implement a "best availability" aggregator that returns the cinema with the most available seats.

