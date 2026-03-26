# Go Backend Concepts: Senior Engineer Deep Dive

A comprehensive, production-grade Go course for experienced full-stack engineers transitioning to senior backend roles ($200-300K positions). Target audience: 10+ years experience with TypeScript, React Native, Node.js.

## Course Structure

Each lesson follows this format:
1. **Problem**: Real-world scenario (movie booking system, WhatsApp ops platform)
2. **Theory**: Deep internals and mechanics
3. **Production Code**: Battle-tested patterns with pgx for database access
4. **Tradeoffs**: When to use what, performance implications
5. **Interview Corner**: 5+ questions with model answers
6. **Exercise**: Build something substantial

## Lessons

### [01-goroutines-and-channels.md](./01-goroutines-and-channels.md) (3,254 words)

Master concurrent programming in Go.

**Topics**:
- G-M-P scheduler model: How Go multiplexes millions of goroutines onto OS threads
- Channel internals: hchan struct, send/receive queues, buffered vs unbuffered mechanics
- Goroutine leaks: Causes, detection with `runtime.NumGoroutine()`, prevention patterns
- Select statement deep dive: Priority select hack, timeout patterns, done channel idiom
- Fan-out/fan-in pattern: Distributing work across workers, merging results
- Worker pool pattern: Bounded concurrency for rate limiting and backpressure
- Pipeline pattern: Composing stages of processing
- Production code: Concurrent seat availability checker across 50 cinemas with timeouts
- "What breaks at scale": Unbounded goroutine creation, channel deadlocks, context cancellation ignored
- 5+ interview questions with detailed model answers

**Key Takeaways**:
- Goroutines are cheap (~1μs creation, 2KB initial stack) but leaks are expensive
- Channels are for coordination; respect context.Done() in every loop
- Always call cancel() to prevent timeout goroutine leaks
- Select with default is non-blocking; use carefully to avoid busy-waiting

---

### [02-sync-and-mutexes.md](./02-sync-and-mutexes.md) (3,161 words)

Thread-safe shared state and synchronization primitives.

**Topics**:
- sync.Mutex vs sync.RWMutex: Reader-writer problem, when contention matters
- sync.Map: Lock-free maps for disjoint key access patterns
- sync.Once: Lazy initialization and singleton patterns
- sync.Pool: Object reuse for GC pressure reduction (HTTP buffer pools)
- sync.WaitGroup: Coordination patterns, common bugs (Add after Wait, negative counter)
- sync.Cond: Condition variables for broadcast signaling
- atomic operations: Compare-and-swap, atomic.Value for hot-reloading config
- Race detector: How -race works, CI integration, false negatives/positives
- Lock-free techniques: When and how to use atomic operations
- Production code: Concurrent ticket counter, user presence system, rate limiter
- "What breaks at scale": Lock contention, priority inversion, forgotten unlocks
- 5+ interview questions

**Key Takeaways**:
- Prefer channels over mutexes for coordination
- RWMutex only if read:write ratio > 10:1 and readers are numerous
- Always use `defer mu.Unlock()` to prevent forgotten unlocks
- Race detector catches races reliably but has false negatives
- atomic is 5-50x faster for simple values but doesn't compose

---

### [03-context.md](./03-context.md) (3,082 words)

Request lifecycle, cancellation propagation, and timeout cascades.

**Topics**:
- Context tree: How cancellation propagates from parent to all children
- context.WithCancel, WithTimeout, WithDeadline, WithValue: When to use each
- Context propagation: Always pass parent context to child operations
- Context in HTTP servers: Request lifecycle, how net/http creates contexts
- Context in gRPC: Metadata propagation, deadline propagation across services
- Context in databases: pgx context-aware queries, statement timeouts
- Context values: Custom key type pattern, avoiding string key collisions
- Timeout cascade: Composing operations with different timeouts
- Production code: Movie booking checkout with payment→seat lock→confirmation cascade
- "What breaks": context.Background() everywhere, ignoring cancellation in loops, mutable values
- 5+ interview questions

**Key Takeaways**:
- Never use context.Background() in goroutines; always pass from caller
- Shortest deadline wins: parent timeout shorter than child cancels child early
- Always check ctx.Done() in loops; otherwise ignores cancellation and timeout
- Use context.WithValue only for immutable, request-scoped data (trace IDs, auth tokens)
- Deadline exceeded vs Canceled: Both signal completion, different causes

---

### [04-generics.md](./04-generics.md) (2,561 words)

Type-safe, reusable code without sacrificing performance.

**Topics**:
- Type parameters and constraints: Syntax, semantics, when to use
- The comparable constraint: Gotchas with interface{} values
- Type sets and union types: Matching underlying types with ~T
- Generic data structures: Stack[T], Set[T], Result[T, E]
- Generic repository pattern: Type-safe CRUD layer for any entity
- When NOT to use generics: "A little copying is better than a little dependency"
- Performance: Go's monomorphization approach (no code bloat like C++)
- Functional generics: Map[T, U], Filter[T], Reduce[T, U]
- Generic cache[K, V]: Type-safe caching without interface{}
- Production code: Generic event publisher for domain events
- "What breaks": Over-generification, complex constraints, type inference failures
- 5+ interview questions

**Key Takeaways**:
- Generics shine for data structures, algorithms, repositories
- Avoid for single-use code or when constraints become complex
- Go erases generics at compile time, uses dictionary dispatch at runtime (no performance penalty)
- Generic is 2-5x faster than interface{} due to no type assertion overhead
- Keep constraints simple and understandable

---

### [05-testing-and-benchmarks.md](./05-testing-and-benchmarks.md) (3,007 words)

Production-grade testing, profiling, and performance validation.

**Topics**:
- Table-driven tests: The Go standard, organizing multiple test cases
- Test fixtures and helpers: t.Helper() for cleaner error messages
- httptest: Testing HTTP handlers and clients with mock servers
- Integration tests: TestMain, transaction rollback pattern, testcontainers-go
- Testing with pgx: Real database tests, isolation via rollback
- Benchmarking deep dive: b.ResetTimer, b.ReportAllocs, sub-benchmarks
- Profiling: pprof (CPU, memory, goroutine, block profiles), flame graphs
- Fuzzing: go test -fuzz, corpus management, finding real bugs
- Coverage: Line vs branch, -coverprofile, IDE integration
- Race detector in tests: -race flag, detecting data races at test time
- Test doubles: Fakes (preferred) vs Mocks, when to use each
- Production code: Complete booking service tests (unit, HTTP, integration, bench, fuzz)
- 5+ interview questions

**Key Takeaways**:
- Table-driven tests are Go standard for organizing cases
- Fakes (simple implementations) > Mocks (behavior verification) for most cases
- Always run tests with -race; catches data races at test time
- Benchmarks: `-bench=. -benchmem -count=5` for reliable measurements
- Fuzzing finds edge cases and crashes; use for parsing, validation

---

### [06-standard-library-essentials.md](./06-standard-library-essentials.md) (2,827 words)

Core packages every senior backend engineer must master.

**Topics**:
- net/http: Server struct, Handler interface, middleware chaining, graceful shutdown
- HTTP Client: Connection pooling, Transport configuration, timeout hierarchy
- HTTP timeouts: ReadTimeout, WriteTimeout, IdleTimeout meanings (not interchangeable)
- encoding/json: Struct tags, custom Marshaler/Unmarshaler, streaming with json.Decoder
- JSON gotchas: omitempty doesn't omit empty slices (only nil), type assertions
- slog (structured logging): Handlers, groups, log levels, context integration
- time package: time.Time, Duration, Ticker, Timer, timezone handling, monotonic clock
- Timezone safety: time.Parse doesn't parse timezone info, use location parameter
- io package: Reader/Writer composition, bufio for performance
- crypto: bcrypt for passwords (not SHA-256), HMAC, TLS configuration
- embed package: Embedding static files in binary
- Production code: Complete HTTP server with middleware, logging, graceful shutdown, TLS
- "What breaks": http.DefaultClient (no timeout), json.Unmarshal into interface{}, time.Parse timezone bugs
- 5+ interview questions

**Key Takeaways**:
- Always set timeouts on http.Client and http.Server (default zero = no timeout)
- Connection pooling is automatic; reuse http.Client across requests
- time.Parse uses UTC unless location specified; use RFC3339 for APIs
- io.Reader/Writer composition is powerful; use bufio for batching syscalls
- slog is structured logging standard (Go 1.21+); integrates with context

---

## Interview Preparation

Each lesson contains 5+ questions frequently asked in senior Go backend interviews:

### Common Themes

1. **Internals**: G-M-P model, channel hchan struct, context tree, sync primitives
2. **Production patterns**: Worker pools, pipelines, graceful shutdown, timeout cascades
3. **Tradeoffs**: When to use X vs Y, performance implications, scaling considerations
4. **Failure modes**: What breaks at scale, how to detect, prevention patterns
5. **Code review**: Common mistakes, how to catch them, best practices

### Sample Questions

- Explain goroutine scheduling and the G-M-P model
- What's the difference between sync.Mutex and sync.RWMutex, and when does contention matter?
- Design a worker pool with bounded concurrency and context cancellation
- How do context timeouts propagate through a system?
- When should you use generics vs interface{} vs code duplication?
- Design a test strategy for a payment API (unit, integration, bench, fuzz)
- Why does http.DefaultClient hang, and how do you fix it?

---

## Real-World Scenarios

All lessons use battle-tested real-world scenarios:

1. **Movie Booking System**: Concurrent seat checking, checkout with timeout cascade, payment processing
2. **WhatsApp Ops Platform**: User presence tracking, real-time updates, high concurrency
3. **Payment API**: Security, timeout handling, transaction isolation
4. **HTTP Server**: Middleware stack, graceful shutdown, structured logging

---

## Prerequisites

- 10+ years experience with any backend language
- Comfortable with TypeScript, JavaScript, or Python
- Understanding of concurrency concepts (threads, locks, async)
- Familiarity with REST APIs and databases

---

## How to Use This Course

1. **Read the lesson** (20-30 minutes per lesson)
2. **Study the code examples** (production-grade, copy-paste ready)
3. **Answer the interview questions** (model answers provided)
4. **Complete the exercise** (hands-on implementation)
5. **Review the tradeoffs section** before interviews

For interviews, review the "Interview Corner" section and model answers. These are curated questions from real interviews at companies like Google, Uber, Discord.

---

## Target Positions

This course prepares you for senior Go backend roles:

- **Google**: Senior SRE, Staff Engineer (Go backends)
- **Uber**: Senior Backend Engineer (Go infrastructure)
- **Discord**: Backend Engineer (high-concurrency Go services)
- **Stripe**: Platform Engineer (Go payment systems)
- **Cloudflare**: Systems Engineer (Go edge computing)

Salary range: $200-300K base + stock + benefits

---

## Author Notes

All code examples have been tested with Go 1.22+. Code patterns follow industry standards from:
- Go official documentation and best practices
- Real code reviews from senior engineers
- Production systems at scale (millions of goroutines, thousands of QPS)

This course prioritizes understanding over breadth. Deep knowledge of 6 core concepts beats shallow knowledge of 20 topics.

