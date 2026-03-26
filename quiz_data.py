#!/usr/bin/env python3
"""
Quiz data for each lesson. Question types:
- mcq: Multiple choice (single correct answer)
- bug: Spot the bug in code
- fill: Fill in the blank / code completion
- tf: True/False with explanation
"""

QUIZZES = {
    # ======== MODULE 1: GO FOUNDATIONS ========
    "01-go-foundations/01-types-and-data-structures": [
        {
            "type": "bug",
            "question": "What's wrong with this code?",
            "code": "original := []int{1, 2, 3, 4, 5}\nsub := original[1:3]\nsub[0] = 99\nfmt.Println(original[1]) // expect: 2",
            "options": [
                "sub modifies the original slice because they share the same backing array",
                "You can't slice a slice in Go",
                "sub[0] is out of bounds",
                "fmt.Println can't print integers"
            ],
            "correct": 0,
            "explanation": "Slices share underlying arrays. `sub` is a window into `original`, so modifying `sub[0]` changes `original[1]` to 99. Use `copy()` to create an independent slice."
        },
        {
            "type": "mcq",
            "question": "What is the zero value of a `string` in Go?",
            "options": ["nil", "undefined", "\"\" (empty string)", "0"],
            "correct": 2,
            "explanation": "In Go, every type has a zero value. For strings, it's the empty string \"\". There is no `nil` or `undefined` for string types — only pointer types can be nil."
        },
        {
            "type": "tf",
            "question": "In Go, you should use `float64` to store prices like $15.99.",
            "correct": False,
            "explanation": "Never use floats for money. Floating point arithmetic causes rounding errors (e.g., 0.1 + 0.2 != 0.3). Store prices in cents as `int64` — $15.99 becomes 1599."
        },
        {
            "type": "mcq",
            "question": "When should you use a pointer receiver instead of a value receiver on a struct method?",
            "options": [
                "Always — pointer receivers are faster",
                "When the method needs to modify the struct, the struct is large, or for consistency",
                "Only when the struct contains slices or maps",
                "Never — Go automatically uses pointers"
            ],
            "correct": 1,
            "explanation": "Use pointer receivers when: the method modifies the struct, the struct is large (avoids copying), or for consistency (if one method needs a pointer receiver, use it for all)."
        },
        {
            "type": "fill",
            "question": "Complete the code to safely check if a key exists in a map:",
            "code": "seatStatus := map[string]string{\"A1\": \"available\"}\n\nstatus, _____ := seatStatus[\"A4\"]\nif !_____ {\n    fmt.Println(\"Seat not found\")\n}",
            "answer": "exists",
            "explanation": "The comma-ok idiom: `value, exists := map[key]`. The second return value is a boolean indicating whether the key was found. This distinguishes 'key not found' from 'key exists with zero value'."
        },
    ],

    "01-go-foundations/02-interfaces-and-polymorphism": [
        {
            "type": "mcq",
            "question": "How does a type satisfy an interface in Go?",
            "options": [
                "By using the `implements` keyword",
                "By declaring it in the struct definition",
                "Implicitly — by having all the methods the interface requires",
                "By registering with the interface at runtime"
            ],
            "correct": 2,
            "explanation": "Go uses implicit (structural) interface satisfaction. If a type has all the methods an interface requires, it satisfies that interface automatically. No `implements` keyword needed."
        },
        {
            "type": "mcq",
            "question": "Where should you define an interface in Go?",
            "options": [
                "In the package that implements it",
                "In a shared `interfaces` package",
                "In the package that uses/consumes it",
                "In the main package"
            ],
            "correct": 2,
            "explanation": "Go convention: define interfaces at the point of use, not at the point of implementation. If package `booking` needs to send notifications, the `Notifier` interface lives in package `booking`."
        },
        {
            "type": "bug",
            "question": "What's the problem with this interface design?",
            "code": "type BookingService interface {\n    CreateBooking(userID, showID string) error\n    CancelBooking(bookingID string) error\n    GetBooking(bookingID string) (*Booking, error)\n    ListBookings(userID string) ([]Booking, error)\n    ProcessPayment(bookingID string) error\n    SendConfirmation(bookingID string) error\n    GenerateReceipt(bookingID string) ([]byte, error)\n}",
            "options": [
                "Interfaces can't have more than 3 methods",
                "It violates interface segregation — too many responsibilities, making testing painful",
                "The method signatures are wrong",
                "You can't return errors from interface methods"
            ],
            "correct": 1,
            "explanation": "A 7-method interface forces any test fake to implement all 7 methods even if only 1 is needed. Split into small interfaces: BookingCreator, BookingReader, PaymentProcessor, etc. Go's standard library models this — io.Reader is just one method."
        },
        {
            "type": "tf",
            "question": "The Go proverb 'Accept interfaces, return structs' means your constructors should return interface types.",
            "correct": False,
            "explanation": "It's the opposite. Accept interfaces (as function parameters — flexible). Return concrete structs (from constructors — clear about what you get). Returning interfaces hides the concrete type unnecessarily."
        },
        {
            "type": "fill",
            "question": "Complete the fake for testing:",
            "code": "type FakeNotifier struct {\n    called bool\n}\n\nfunc (f *FakeNotifier) Send(to string, message string) error {\n    f._____ = true\n    return nil\n}\n\nfunc (f *FakeNotifier) WasCalled() bool {\n    return f._____\n}",
            "answer": "called",
            "explanation": "Test fakes record whether methods were called. This lets you verify side effects in tests — e.g., after a successful booking, assert that the notifier was called."
        },
    ],

    "01-go-foundations/03-error-handling": [
        {
            "type": "mcq",
            "question": "What does the `%w` verb do in `fmt.Errorf`?",
            "options": [
                "Formats the error as a warning",
                "Wraps the error so it can be unwrapped with errors.Is/errors.As",
                "Writes the error to a log file",
                "Converts the error to a string"
            ],
            "correct": 1,
            "explanation": "`%w` wraps the original error inside a new error with added context. `errors.Is()` and `errors.As()` can then walk the chain to find the original error. Use `%v` when you want to hide the original."
        },
        {
            "type": "bug",
            "question": "What happens when this code runs?",
            "code": "err := BookSeat(\"user_1\", \"A4\", \"show_1\")\nif err == ErrSeatLocked {\n    fmt.Println(\"Seat is locked\")\n}",
            "options": [
                "Works correctly",
                "Never matches — if BookSeat wraps the error with %w, direct == comparison fails. Use errors.Is() instead",
                "Compile error — can't compare errors",
                "Panics at runtime"
            ],
            "correct": 1,
            "explanation": "If BookSeat returns `fmt.Errorf(\"locking seat: %w\", ErrSeatLocked)`, the returned error is a wrapped error, not ErrSeatLocked itself. `==` compares the wrapper. `errors.Is(err, ErrSeatLocked)` walks the chain and finds it."
        },
        {
            "type": "tf",
            "question": "You should use `panic()` when a database query fails in a request handler.",
            "correct": False,
            "explanation": "Never panic in request handlers. Database errors are expected runtime conditions — return them as errors. Panic is only for truly unrecoverable programmer errors (like a nil map that should have been initialized). Use recovery middleware as a safety net, not as error handling."
        },
        {
            "type": "mcq",
            "question": "How should you map domain errors to HTTP status codes?",
            "options": [
                "Always return 500 for any error",
                "Use errors.Is/errors.As to match specific errors to specific status codes (404, 409, 422, etc.)",
                "Include the HTTP status code in the error message",
                "Let the framework handle it automatically"
            ],
            "correct": 1,
            "explanation": "Use errors.Is for sentinel errors (ErrSeatNotFound → 404, ErrSeatLocked → 409) and errors.As for custom error types (BookingError with a Code field). Default to 500 for unexpected errors, and never expose internal error details to clients."
        },
        {
            "type": "fill",
            "question": "Complete the sentinel error declaration:",
            "code": "var (\n    ErrSeatNotFound = errors._____( \"seat not found\")\n    ErrSeatLocked   = errors._____(\"seat is currently locked\")\n)",
            "answer": "New",
            "explanation": "`errors.New()` creates a new sentinel error value. Define these at package level so callers can check for them with `errors.Is()`. Convention: prefix with `Err`."
        },
    ],

    "01-go-foundations/04-project-structure-and-modules": [
        {
            "type": "mcq",
            "question": "What does the `internal/` directory do in a Go project?",
            "options": [
                "It's a convention with no compiler enforcement",
                "Code inside it can only be imported by packages within the same module — compiler-enforced",
                "It marks code as deprecated",
                "It's where test files go"
            ],
            "correct": 1,
            "explanation": "`internal/` is compiler-enforced privacy in Go. External packages cannot import anything from your `internal/` directory. This protects your business logic from being used as a library by outside code."
        },
        {
            "type": "mcq",
            "question": "How should you organize packages in a Go microservice?",
            "options": [
                "By layer: controllers/, services/, repositories/",
                "By domain: booking/, payment/, notification/ — each owning its full vertical slice",
                "Everything in one package",
                "By file type: models/, handlers/, middleware/"
            ],
            "correct": 1,
            "explanation": "Organize by domain (vertical slices), not by layer. Each domain package owns its models, handlers, service logic, and repository. This keeps related code together and reduces cross-package dependencies."
        },
        {
            "type": "tf",
            "question": "Go allows circular imports between packages if you use interfaces.",
            "correct": False,
            "explanation": "Go never allows circular imports — it's a compile error, period. Interfaces help resolve the dependency direction (dependency inversion), but the import cycle must be broken. Package A can define an interface, and package B can implement it, but they can't import each other."
        },
        {
            "type": "mcq",
            "question": "How does dependency injection work in a typical Go project?",
            "options": [
                "Use a DI framework like Spring or NestJS",
                "Use Go's built-in DI container",
                "Manual constructor injection in main.go — no framework needed",
                "Use reflection to inject dependencies at runtime"
            ],
            "correct": 2,
            "explanation": "Go favors explicit wiring. In main.go, you create concrete implementations and pass them to constructors: `NewService(repo, notifier)`. It's verbose but clear — you can read main.go and see every dependency in the system."
        },
    ],

    # ======== MODULE 2: GO CONCEPTS ========
    "02-go-concepts/01-goroutines-and-channels": [
        {
            "type": "mcq",
            "question": "How much memory does a goroutine start with?",
            "options": ["~1MB (same as an OS thread)", "~2KB (grows dynamically)", "~64KB fixed", "Depends on the function"],
            "correct": 1,
            "explanation": "Goroutines start at ~2KB of stack, which grows and shrinks dynamically. OS threads typically start at ~1MB. This is why Go can run millions of goroutines but a Java app would struggle with thousands of threads."
        },
        {
            "type": "bug",
            "question": "What's wrong with this goroutine?",
            "code": "for _, id := range seatIDs {\n    go func() {\n        fmt.Println(id) // prints seat ID\n    }()\n}",
            "options": [
                "You can't launch goroutines in a loop",
                "All goroutines capture the same `id` variable — they'll all print the last value",
                "The goroutines will deadlock",
                "fmt.Println is not thread-safe"
            ],
            "correct": 1,
            "explanation": "Classic closure capture bug. All goroutines share the same `id` variable, which changes each iteration. By the time they run, `id` is the last value. Fix: pass `id` as a function argument: `go func(seatID string) { ... }(id)`"
        },
        {
            "type": "mcq",
            "question": "When should you use a buffered channel over an unbuffered one?",
            "options": [
                "Always — buffered channels are faster",
                "When the producer is faster than the consumer and you want to absorb bursts",
                "Only when sending structs larger than 64 bytes",
                "Never — unbuffered channels are always preferred"
            ],
            "correct": 1,
            "explanation": "Buffered channels decouple sender and receiver speed. The sender can continue as long as the buffer isn't full. Use them for absorbing bursts — like a request queue in front of a payment processor. Unbuffered channels are for strict synchronization."
        },
        {
            "type": "fill",
            "question": "Complete the pattern to wait for all goroutines and close the channel:",
            "code": "var wg sync.WaitGroup\nresults := make(chan string, 10)\n\nfor i := 0; i < 10; i++ {\n    wg.Add(1)\n    go func() {\n        defer wg._____()\n        results <- \"done\"\n    }()\n}\n\ngo func() {\n    wg._____()\n    close(results)\n}()",
            "answer": "Done",
            "explanation": "wg.Done() decrements the counter. wg.Wait() blocks until the counter reaches zero. The anonymous goroutine waits for all workers to finish, then closes the channel so `range results` can terminate."
        },
        {
            "type": "tf",
            "question": "A goroutine that never exits will be garbage collected by Go's runtime.",
            "correct": False,
            "explanation": "Go never garbage collects running goroutines. A goroutine that never exits is a memory leak. Every goroutine must have a clear exit path — use context cancellation or a done channel."
        },
    ],

    "02-go-concepts/02-sync-and-mutexes": [
        {
            "type": "bug",
            "question": "This code panics under concurrent access. Why?",
            "code": "seatMap := make(map[string]string)\n\ngo func() { seatMap[\"A1\"] = \"booked\" }()\ngo func() { _ = seatMap[\"A1\"] }()",
            "options": [
                "Maps can't store strings",
                "Go maps are not safe for concurrent read/write — this is a data race that causes a panic",
                "You can't use maps in goroutines",
                "The map needs to be initialized with a size"
            ],
            "correct": 1,
            "explanation": "Go maps panic on concurrent read+write. The race detector (`go test -race`) catches this. Fix: protect with sync.RWMutex (RLock for reads, Lock for writes) or use sync.Map."
        },
        {
            "type": "mcq",
            "question": "When should you use `sync.RWMutex` instead of `sync.Mutex`?",
            "options": [
                "Always — it's strictly better",
                "When reads vastly outnumber writes (many readers, few writers)",
                "Only when using maps",
                "When you have more than 10 goroutines"
            ],
            "correct": 1,
            "explanation": "RWMutex allows multiple concurrent readers (RLock) but exclusive writers (Lock). When reads >> writes (like a seat availability cache), RWMutex gives much better throughput. If reads ≈ writes, plain Mutex is simpler and has less overhead."
        },
        {
            "type": "fill",
            "question": "Complete the atomic counter:",
            "code": "type Metrics struct {\n    totalRequests atomic._____()\n}\n\nfunc (m *Metrics) Record() {\n    m.totalRequests._____(1)\n}",
            "answer": "Int64",
            "explanation": "atomic.Int64 provides lock-free thread-safe integer operations. `.Add(1)` atomically increments. Faster than a mutex when all you need is a counter."
        },
        {
            "type": "mcq",
            "question": "What does `go test -race` do?",
            "options": [
                "Runs tests in parallel for speed",
                "Instruments your code to detect concurrent access to shared variables without synchronization",
                "Tests network race conditions",
                "Benchmarks goroutine scheduling"
            ],
            "correct": 1,
            "explanation": "The race detector instruments your code at compile time to detect data races — concurrent reads and writes to the same variable without proper synchronization. If it finds a race, it shows exactly which goroutines are involved."
        },
    ],

    "02-go-concepts/03-context": [
        {
            "type": "mcq",
            "question": "What happens when you forget to call `cancel()` on a context created with `context.WithTimeout`?",
            "options": [
                "Nothing — the timeout handles cleanup automatically",
                "Resource leak — the internal timer goroutine keeps running until the parent is cancelled",
                "The program panics",
                "The timeout is ignored"
            ],
            "correct": 1,
            "explanation": "Always `defer cancel()` immediately after creating a context. Even WithTimeout (which eventually cancels itself) leaks resources until then. Over thousands of requests, these accumulate."
        },
        {
            "type": "bug",
            "question": "What's wrong with this cleanup code?",
            "code": "func CreateBooking(ctx context.Context, req Request) error {\n    ctx, cancel := context.WithTimeout(ctx, 10*time.Second)\n    defer cancel()\n\n    err := lockSeat(ctx, req.SeatID)\n    if err != nil { return err }\n\n    _, err = chargePayment(ctx, req.UserID, req.Amount)\n    if err != nil {\n        unlockSeat(ctx, req.SeatID) // cleanup\n        return err\n    }\n    return nil\n}",
            "options": [
                "The timeout is too short",
                "lockSeat and chargePayment should use different contexts",
                "unlockSeat uses the same ctx which may already be cancelled — use context.Background() for cleanup",
                "cancel() should not be deferred"
            ],
            "correct": 2,
            "explanation": "If the payment timed out, `ctx` is already cancelled. Passing it to `unlockSeat` will fail immediately. Cleanup operations should use `context.Background()` to ensure they complete regardless of the original context's state."
        },
        {
            "type": "tf",
            "question": "You should use context values to pass a user's email address to a function that sends a booking confirmation.",
            "correct": False,
            "explanation": "If a function needs data to do its job, pass it as a parameter — that makes the dependency explicit. Context values are for cross-cutting concerns only: request IDs, trace spans, auth tokens. The test: if removing the context value breaks the function's core behavior, it should be a parameter."
        },
        {
            "type": "mcq",
            "question": "What happens if a child context has a 10-second timeout but the parent context has only 3 seconds left?",
            "options": [
                "The child gets 10 seconds",
                "The child gets 3 seconds — the tightest timeout always wins",
                "It causes a panic",
                "The child timeout overrides the parent"
            ],
            "correct": 1,
            "explanation": "Context deadlines cascade downward. A child can never outlive its parent. If the parent cancels, all children cancel too. The tightest timeout in the chain always wins."
        },
    ],

    "02-go-concepts/04-generics": [
        {
            "type": "mcq",
            "question": "When should you NOT use generics in Go?",
            "options": [
                "When building reusable data structures like caches",
                "When you only have 2-3 concrete types and the generic version is harder to read",
                "When writing utility functions like Map, Filter, Contains",
                "When avoiding interface{}/any"
            ],
            "correct": 1,
            "explanation": "Go's philosophy is simplicity first. If you only have 2-3 types, just write the functions. Generics are for when the algorithm is truly the same across many types — data structures, utility functions, reducing code generation."
        },
        {
            "type": "mcq",
            "question": "What's the difference between generics and interfaces in Go?",
            "options": [
                "They're the same thing with different syntax",
                "Interfaces: runtime polymorphism (swap implementations). Generics: compile-time polymorphism (same algorithm, different types).",
                "Generics are faster but interfaces are more flexible",
                "Interfaces are deprecated in favor of generics"
            ],
            "correct": 1,
            "explanation": "Use interfaces when behavior varies (a Notifier could be Email, SMS, or WhatsApp). Use generics when the algorithm is the same but the types differ (sorting, caching, filtering). Interfaces = different behavior. Generics = same behavior, different data."
        },
        {
            "type": "fill",
            "question": "Complete the generic function signature:",
            "code": "func Contains[T _____](slice []T, target T) bool {\n    for _, v := range slice {\n        if v == target {\n            return true\n        }\n    }\n    return false\n}",
            "answer": "comparable",
            "explanation": "The `comparable` constraint allows types that support `==` and `!=` operators. Without it, the compiler can't guarantee that `v == target` is valid for type T."
        },
    ],

    "02-go-concepts/05-testing-and-benchmarks": [
        {
            "type": "mcq",
            "question": "How do you prove that your seat booking logic handles concurrency correctly?",
            "options": [
                "Write a single unit test that books one seat",
                "Launch 10 goroutines competing for the same seat, verify exactly 1 wins, run with -race -count=100",
                "Use a debugger to step through concurrent paths",
                "Test manually by opening two browser tabs"
            ],
            "correct": 1,
            "explanation": "Concurrent correctness requires concurrent tests. Launch N goroutines competing for the same resource, verify exactly 1 succeeds and N-1 fail. Run with `-race` to catch data races, and `-count=100` to catch intermittent failures."
        },
        {
            "type": "mcq",
            "question": "What does `t.Helper()` do in a test helper function?",
            "options": [
                "Makes the test run faster",
                "Makes error messages point to the caller of the helper, not the helper itself",
                "Marks the function as a benchmark",
                "Skips the test if it fails"
            ],
            "correct": 1,
            "explanation": "Without t.Helper(), a failure in `assertNoError(t, err)` would show the line inside assertNoError. With t.Helper(), it shows the line in your test that called assertNoError — much more useful for debugging."
        },
        {
            "type": "tf",
            "question": "You should always optimize code before writing benchmarks.",
            "correct": False,
            "explanation": "Never optimize without a benchmark proving the problem exists. Benchmark first to establish a baseline, then optimize, then benchmark again to prove the improvement. Premature optimization is the root of all evil — measure first."
        },
        {
            "type": "fill",
            "question": "Complete the table-driven test structure:",
            "code": "func TestSeatStatus(t *testing.T) {\n    tests := []struct {\n        name   string\n        status SeatStatus\n        want   bool\n    }{\n        {\"available is valid\", SeatAvailable, true},\n        {\"empty is invalid\", SeatStatus(\"\"), false},\n    }\n\n    for _, tt := range tests {\n        t._____(tt.name, func(t *testing.T) {\n            got := tt.status.IsValid()\n            if got != tt.want {\n                t.Errorf(\"got %v, want %v\", got, tt.want)\n            }\n        })\n    }\n}",
            "answer": "Run",
            "explanation": "`t.Run(name, func)` creates a subtest with a descriptive name. Each test case runs independently with its own name, so failures are specific and easy to identify."
        },
    ],

    "02-go-concepts/06-standard-library-essentials": [
        {
            "type": "mcq",
            "question": "Since Go 1.22, which feature was added to the standard library's HTTP router?",
            "options": [
                "WebSocket support",
                "Method-specific routes and path parameters (e.g., `GET /api/shows/{id}`)",
                "Automatic JSON serialization",
                "Built-in rate limiting"
            ],
            "correct": 1,
            "explanation": "Go 1.22 added method matching and path parameters to the standard library's ServeMux. Before this, you needed a third-party router like chi or gorilla/mux for these features."
        },
        {
            "type": "bug",
            "question": "What's the security issue with this handler?",
            "code": "func createBooking(w http.ResponseWriter, r *http.Request) {\n    var req BookingRequest\n    json.NewDecoder(r.Body).Decode(&req)\n    // process booking...\n}",
            "options": [
                "Missing Content-Type header check",
                "No request body size limit — an attacker can send a multi-GB payload and exhaust memory",
                "json.NewDecoder is slower than json.Unmarshal",
                "Missing CORS headers"
            ],
            "correct": 1,
            "explanation": "Always use `http.MaxBytesReader(w, r.Body, maxSize)` to limit request body size. Without it, a malicious client can send an arbitrarily large body and crash your server. Also consider `DisallowUnknownFields()` for strict parsing."
        },
        {
            "type": "mcq",
            "question": "Why should you reuse `http.Client` instead of creating one per request?",
            "options": [
                "It's a Go convention but doesn't matter functionally",
                "Connection pooling — reusing the client reuses TCP connections, avoiding the overhead of new TLS handshakes",
                "http.Client can only be created once per program",
                "Memory management — Go can't garbage collect http.Client"
            ],
            "correct": 1,
            "explanation": "http.Client maintains a connection pool internally. Creating a new client per request means new TCP connections, new TLS handshakes (expensive!), and no connection reuse. One client with configured timeouts and transport settings serves all requests."
        },
        {
            "type": "tf",
            "question": "You should store configuration in YAML or JSON files for a Go microservice.",
            "correct": False,
            "explanation": "Environment variables are the standard for Go microservices. They work everywhere — locally, in Docker, in Kubernetes, in CI. No config files to manage, no parsing libraries. For secrets, use the platform's secret manager and inject them as env vars."
        },
    ],

    # ======== MODULE 3: MICROSERVICES ========
    "03-microservices/01-service-architecture": [
        {
            "type": "mcq",
            "question": "What's the biggest mistake teams make with microservices?",
            "options": [
                "Using too many programming languages",
                "Starting with microservices before understanding the domain, leading to wrong boundaries",
                "Not using Kubernetes",
                "Having too few services"
            ],
            "correct": 1,
            "explanation": "Wrong service boundaries are expensive to fix. Start with a modular monolith, understand your domain, then extract services when you have clear signals: independent scaling needs, different deployment cadence, team ownership boundaries."
        },
        {
            "type": "mcq",
            "question": "When should the Booking Service call the Payment Service synchronously vs asynchronously?",
            "options": [
                "Always async for better performance",
                "Always sync for consistency",
                "Sync — because the booking needs the transaction ID before confirming",
                "It doesn't matter"
            ],
            "correct": 2,
            "explanation": "The booking flow needs the payment result to proceed. You can't confirm a booking without knowing if payment succeeded. Notifications, analytics, and other downstream effects should be async via events."
        },
        {
            "type": "tf",
            "question": "In a microservices architecture, multiple services can share the same database for simplicity.",
            "correct": False,
            "explanation": "Database-per-service is a core principle. Shared databases create hidden coupling — a schema change in one service can break another. You've built a distributed monolith, not microservices. Cross-service data access should go through APIs."
        },
        {
            "type": "mcq",
            "question": "When would you choose gRPC over REST for service-to-service communication?",
            "options": [
                "When the service is public-facing",
                "For internal services where you need strong typing, streaming, and lower latency",
                "When you need to support browsers",
                "Only when using Protocol Buffers"
            ],
            "correct": 1,
            "explanation": "gRPC is ~10x faster than REST for internal calls, provides strong typing via protobuf, and supports streaming. Use REST for public-facing APIs (browser-friendly, human-readable). Use gRPC for internal service-to-service communication."
        },
    ],

    "03-microservices/02-saga-pattern": [
        {
            "type": "mcq",
            "question": "Why can't you use a regular database transaction across microservices?",
            "options": [
                "Transactions are too slow",
                "Each service has its own database — there's no single transaction coordinator that spans all of them",
                "Microservices don't support transactions",
                "Go doesn't support distributed transactions"
            ],
            "correct": 1,
            "explanation": "With database-per-service, there's no single database to wrap in a transaction. Two-phase commit (2PC) exists but is slow, fragile, and blocks resources. The Saga pattern provides eventual consistency with compensating actions instead."
        },
        {
            "type": "mcq",
            "question": "In a booking saga, payment succeeds but the DB write to confirm the booking fails. What should happen?",
            "options": [
                "Retry the DB write forever",
                "Ignore it — the payment went through",
                "Compensate: refund the payment AND unlock the seats, in reverse order",
                "Restart the entire saga from the beginning"
            ],
            "correct": 2,
            "explanation": "Sagas compensate in reverse order. If step 3 (confirm booking) fails: compensate step 2 (refund payment), then compensate step 1 (unlock seats). The user sees 'Something went wrong, your card was not charged.'"
        },
        {
            "type": "bug",
            "question": "What's the critical issue with this saga compensation?",
            "code": "// Step 2 compensation: refund payment\nCompensate: func(ctx context.Context) error {\n    if transactionID == \"\" {\n        return nil\n    }\n    return s.payment.Refund(ctx, transactionID)\n}",
            "options": [
                "transactionID should be a pointer",
                "The refund is not idempotent — if this compensation runs twice (e.g., after a crash), it could double-refund",
                "You can't call Refund in a compensation",
                "ctx might be nil"
            ],
            "correct": 1,
            "explanation": "Compensation must be idempotent. If the saga crashes after refunding but before marking the compensation as complete, it will retry and refund again. Use an idempotency key or check if a refund already exists for this transaction."
        },
        {
            "type": "tf",
            "question": "Orchestration-based sagas are always better than choreography-based sagas.",
            "correct": False,
            "explanation": "Orchestration makes the flow visible and easy to debug — better for complex linear flows like booking. Choreography is more decoupled with no single coordinator — better for simple event-driven workflows. Choice depends on flow complexity."
        },
    ],

    "03-microservices/03-outbox-pattern": [
        {
            "type": "mcq",
            "question": "What problem does the Outbox pattern solve?",
            "options": [
                "Slow database writes",
                "The dual-write problem — atomically updating a database AND publishing a message",
                "Message queue capacity limits",
                "Database connection pooling"
            ],
            "correct": 1,
            "explanation": "You can't atomically write to a database AND publish to Kafka — they're two different systems. The outbox puts both writes in the same database transaction (business data + outbox event). A separate process relays outbox events to Kafka."
        },
        {
            "type": "fill",
            "question": "Complete the SQL for the outbox processor to avoid duplicate processing across multiple instances:",
            "code": "SELECT id, event_type, payload FROM outbox\nWHERE published_at IS NULL\nORDER BY created_at ASC\nLIMIT 100\nFOR UPDATE _____ _____",
            "answer": "SKIP LOCKED",
            "explanation": "`FOR UPDATE SKIP LOCKED` ensures multiple outbox processor instances don't pick the same events. If Processor A is working on event #1, Processor B skips it and picks event #2. No duplicates, no contention."
        },
        {
            "type": "mcq",
            "question": "The outbox processor publishes an event to Kafka, then crashes before marking it as published. What happens?",
            "options": [
                "The event is lost",
                "The event is published again on next poll — consumers must be idempotent",
                "Kafka detects the duplicate",
                "The database rolls back the event"
            ],
            "correct": 1,
            "explanation": "This is at-least-once delivery. The event will be re-published on the next poll cycle. Consumers must handle duplicates — check if they've already processed the event (by booking ID or event ID) before acting."
        },
        {
            "type": "tf",
            "question": "Change Data Capture (CDC) is always better than polling for the outbox relay.",
            "correct": False,
            "explanation": "CDC (Debezium) gives near-zero latency but requires additional infrastructure (Kafka Connect, WAL configuration) and is harder to debug. Polling is simpler, works with any database, and covers 90% of use cases. Start with polling, move to CDC if you need real-time."
        },
    ],

    "03-microservices/04-resilience-patterns": [
        {
            "type": "mcq",
            "question": "What happens when a circuit breaker is in the OPEN state?",
            "options": [
                "Requests are queued until the service recovers",
                "Requests are retried with exponential backoff",
                "Requests fail immediately without calling the downstream service",
                "Requests are routed to a backup service"
            ],
            "correct": 2,
            "explanation": "That's the whole point — fail fast. When the circuit is open, no call is made to the failing service. Requests fail instantly with 'service unavailable'. After a cooldown period, one test request is allowed through (half-open) to check if the service recovered."
        },
        {
            "type": "mcq",
            "question": "Why is jitter important in retry with exponential backoff?",
            "options": [
                "It makes retries random so logs are easier to read",
                "It prevents thundering herd — without it, all retrying clients hit the server at the same time",
                "It's a Go convention but not functionally important",
                "It reduces memory usage"
            ],
            "correct": 1,
            "explanation": "Without jitter: 100 clients fail at T=0, all retry at T=100ms → worse spike than original. With jitter: retries spread across T=50-150ms → server isn't overwhelmed. Always add randomization to retry delays."
        },
        {
            "type": "fill",
            "question": "Complete the bulkhead pattern using a Go channel as a semaphore:",
            "code": "type Bulkhead struct {\n    sem chan struct{}\n}\n\nfunc NewBulkhead(maxConcurrent int) *Bulkhead {\n    return &Bulkhead{sem: make(chan struct{}, _____)}\n}\n\nfunc (b *Bulkhead) Execute(fn func() error) error {\n    b.sem <- struct{}{} // acquire\n    defer func() { <-b._____ }() // release\n    return fn()\n}",
            "answer": "maxConcurrent",
            "explanation": "A buffered channel acts as a semaphore. The buffer size limits concurrency. Sending acquires a slot (blocks if full), receiving releases it. This prevents one slow dependency from consuming all goroutines."
        },
        {
            "type": "mcq",
            "question": "In the resilience stack (Bulkhead → Retry → Circuit Breaker → HTTP Call), what's the correct ordering?",
            "options": [
                "The order doesn't matter",
                "Circuit Breaker should be outermost",
                "Bulkhead outermost (limits total concurrent calls), then Retry, then Circuit Breaker closest to the actual call",
                "Retry should be outermost"
            ],
            "correct": 2,
            "explanation": "Bulkhead first — limits resource consumption. Retry next — handles transient failures. Circuit Breaker last (closest to the call) — stops calling dead services. This way, retries happen within the bulkhead's concurrency limit, and the circuit breaker protects the actual HTTP call."
        },
    ],

    "03-microservices/05-cqrs": [
        {
            "type": "mcq",
            "question": "What is the main tradeoff of using CQRS?",
            "options": [
                "Slower writes",
                "Eventual consistency — the read model lags behind the write model",
                "Higher storage costs",
                "More complex authentication"
            ],
            "correct": 1,
            "explanation": "With CQRS, there's a delay between a write and the read model being updated. A user might book seat A4, but another user briefly sees it as available. The write model prevents actual double booking; the read model catches up within seconds."
        },
        {
            "type": "tf",
            "question": "You should use CQRS for every microservice to follow best practices.",
            "correct": False,
            "explanation": "CQRS adds significant complexity: two data models, an event pipeline, sync mechanisms, eventual consistency. Only use it when read/write patterns are fundamentally different and read volume vastly exceeds writes (100:1+). For simple CRUD, it's massive overkill."
        },
        {
            "type": "mcq",
            "question": "In a CQRS booking system, what keeps the read model (seat availability) in sync with the write model?",
            "options": [
                "Direct database replication",
                "The API handler updates both models in the same request",
                "Event handlers consume outbox events and update the read model",
                "A scheduled batch job runs every hour"
            ],
            "correct": 2,
            "explanation": "Events from the outbox flow through Kafka to event handlers that update the read model. This keeps the read model eventually consistent with the write model without coupling them together."
        },
    ],

    # ======== MODULE 4: SYSTEM DESIGN ========
    "04-system-design/01-scaling-patterns": [
        {
            "type": "mcq",
            "question": "Which caching strategy should you use for the seat availability map? (Read-heavy, brief staleness OK)",
            "options": [
                "Write-through — cache is always fresh",
                "Cache-aside (lazy loading) — check cache first, fall back to DB, populate cache on miss",
                "Write-behind — write to cache, async write to DB",
                "No cache — query the database every time"
            ],
            "correct": 1,
            "explanation": "Cache-aside is ideal for read-heavy workloads where brief staleness is acceptable. The seat map is read 100x more than it's written. Cache with a 30-second TTL, invalidate on booking. Most users see cached data; only misses hit the DB."
        },
        {
            "type": "mcq",
            "question": "What happens when your rate limiter's Redis instance goes down?",
            "options": [
                "All requests are blocked",
                "The system crashes",
                "Fail open — allow all requests through (don't block legitimate users because of infrastructure failure)",
                "Switch to in-memory rate limiting automatically"
            ],
            "correct": 2,
            "explanation": "Fail open is the standard approach for rate limiting infrastructure failures. It's better to temporarily allow extra traffic than to block all legitimate users. The rate limiter is a safety mechanism, not a gatekeeper for normal operation."
        },
        {
            "type": "mcq",
            "question": "When should you shard your database?",
            "options": [
                "As soon as you adopt microservices",
                "When you have more than 1000 users",
                "Almost never — only after exhausting vertical scaling, read replicas, caching, and connection pooling",
                "For every table that exceeds 1 million rows"
            ],
            "correct": 2,
            "explanation": "Sharding adds enormous complexity: cross-shard queries, rebalancing, schema changes across shards. Most companies don't need it until millions of active users. Exhaust simpler solutions first. When you do shard, shard by a key that isolates queries (show_id for a booking system)."
        },
        {
            "type": "tf",
            "question": "Read replicas in Postgres are always perfectly in sync with the primary.",
            "correct": False,
            "explanation": "Replicas can lag 10-100ms behind the primary (replication lag). A user books a seat on the primary, then reads from a replica — it might still show the seat as available. Handle this by reading from primary for the user's own data immediately after a write."
        },
    ],

    "04-system-design/02-distributed-systems-theory": [
        {
            "type": "mcq",
            "question": "In the CAP theorem, what's the real choice you're making?",
            "options": [
                "Pick any 2 of Consistency, Availability, Partition Tolerance",
                "Since network partitions are unavoidable, you choose between Consistency and Availability during a partition",
                "You can have all 3 with enough engineering effort",
                "CAP only applies to NoSQL databases"
            ],
            "correct": 1,
            "explanation": "Network partitions happen — you can't opt out of P. The real choice: during a partition, do you reject requests (CP — consistent but unavailable) or serve stale data (AP — available but inconsistent)? Different parts of the same system can make different choices."
        },
        {
            "type": "mcq",
            "question": "Which consistency guarantee does the Outbox + Kafka event pipeline provide?",
            "options": [
                "Strong consistency",
                "Eventual consistency — the read model converges to the write model over time",
                "No consistency guarantee",
                "Causal consistency"
            ],
            "correct": 1,
            "explanation": "The write model is immediately ACID-consistent. The event pipeline provides at-least-once delivery with eventual propagation. Given enough time without new writes, all views converge. This is BASE: Basically Available, Soft state, Eventually consistent."
        },
        {
            "type": "tf",
            "question": "Two-Phase Commit (2PC) is the recommended way to handle distributed transactions in microservices.",
            "correct": False,
            "explanation": "2PC blocks all participants while waiting for the coordinator. If the coordinator crashes, resources stay locked. It sacrifices availability for consistency. For microservices, the Saga pattern with compensating transactions is preferred — it provides eventual consistency without blocking."
        },
        {
            "type": "mcq",
            "question": "How does MVCC in Postgres handle a situation where User A reads seats while User B is booking?",
            "options": [
                "User A's read blocks until User B's write completes",
                "User B's write blocks until User A's read completes",
                "Both proceed concurrently — User A sees a snapshot from before User B's uncommitted write",
                "One of them gets an error"
            ],
            "correct": 2,
            "explanation": "MVCC keeps multiple versions of each row. Reads never block writes; writes never block reads. User A sees a consistent snapshot from when their transaction started. User B's uncommitted changes are invisible to User A."
        },
    ],

    "04-system-design/03-interview-framework": [
        {
            "type": "mcq",
            "question": "What's the most important step in a system design interview that most candidates skip?",
            "options": [
                "Drawing the architecture diagram",
                "Requirements clarification — asking what the system needs to do and at what scale",
                "Choosing the database",
                "Discussing the programming language"
            ],
            "correct": 1,
            "explanation": "Senior candidates drive requirements gathering. They don't assume — they ask: 'How many concurrent users? What's the consistency requirement? Is this multi-region?' Jumping straight to drawing boxes is a junior signal."
        },
        {
            "type": "mcq",
            "question": "In the scale estimation step, you calculate that reads outnumber writes 100:1. What does this tell you about your design?",
            "options": [
                "You need more databases",
                "Caching matters, read replicas help, and CQRS is worth considering",
                "You should optimize writes first",
                "The system is too read-heavy to work"
            ],
            "correct": 1,
            "explanation": "A high read:write ratio is the classic signal for caching (avoid redundant DB queries), read replicas (distribute read load), and CQRS (optimize read and write paths independently). The estimation step directly informs your architectural choices."
        },
        {
            "type": "mcq",
            "question": "After designing the system, the interviewer asks 'What breaks first at 10x scale?' What are they testing?",
            "options": [
                "Whether you've memorized scaling patterns",
                "Whether you can proactively identify bottlenecks and think about the system under stress",
                "Whether you can calculate exact numbers",
                "Whether you know cloud provider pricing"
            ],
            "correct": 1,
            "explanation": "This is the senior signal. They want to see that you think about failure modes and bottlenecks without being asked. 'The primary DB write throughput hits its limit first. We'd add PgBouncer for connection pooling, then shard by show_id if that's not enough.'"
        },
    ],

    "04-system-design/04-behavioral-prep": [
        {
            "type": "mcq",
            "question": "In a behavioral interview, when describing a production incident, what's the strongest signal you can give?",
            "options": [
                "Blaming the infrastructure team",
                "Showing that you owned the resolution end-to-end: detection → triage → mitigation → root cause → prevention",
                "Minimizing the impact of the incident",
                "Explaining that it wasn't your code"
            ],
            "correct": 1,
            "explanation": "Ownership is the #1 signal at the $200-300k level. You detected it, you triaged it, you mitigated the impact, you found the root cause, you wrote the postmortem, and you implemented prevention. You didn't wait to be told what to do."
        },
        {
            "type": "mcq",
            "question": "When telling a 'pushing back on a decision' story, what's the right way to frame it?",
            "options": [
                "Emphasize that you were right and they were wrong",
                "Show that you pushed back with data, not ego — and could disagree and commit either way",
                "Avoid mentioning any conflict",
                "Focus on the technical details only"
            ],
            "correct": 1,
            "explanation": "They're testing for mature leadership. Present alternatives with data and clear tradeoffs. If overruled, commit to the team's decision and make it succeed. 'I disagreed but once the team decided, I focused on making it work' is a strong signal."
        },
        {
            "type": "tf",
            "question": "In a STAR-format behavioral answer, you should use 'we' to show you're a team player.",
            "correct": False,
            "explanation": "Always use 'I', not 'we'. The interviewer is evaluating you, not your team. 'I proposed the caching strategy' not 'we improved performance'. You can acknowledge the team but be specific about your contributions."
        },
    ],

    # ======== NEW: OBSERVABILITY ========
    "03-microservices/06-observability": [
        {
            "type": "mcq",
            "question": "What are the three pillars of observability?",
            "options": [
                "Logs, metrics, and traces",
                "Monitoring, alerting, and dashboards",
                "CPU, memory, and disk",
                "Latency, throughput, and errors"
            ],
            "correct": 0,
            "explanation": "The three pillars are logs (discrete events), metrics (aggregated measurements), and traces (request flow across services). Together they give full visibility into system behavior."
        },
        {
            "type": "tf",
            "question": "A trace and a span are the same thing in OpenTelemetry.",
            "correct": False,
            "explanation": "A trace is the entire journey of a request across services. A span is a single unit of work within that trace. A trace contains multiple spans in a parent-child tree structure."
        },
        {
            "type": "mcq",
            "question": "What is a 'cardinality bomb' in metrics?",
            "options": [
                "Using a high-cardinality label (like user_id) on a metric, creating millions of time series",
                "Having too many metrics endpoints",
                "A metric that grows without bound",
                "When Prometheus runs out of memory"
            ],
            "correct": 0,
            "explanation": "Adding labels with unbounded values (user IDs, request IDs) to metrics creates a unique time series per value. With millions of users, this explodes storage and query cost. Use histograms and summaries instead."
        },
        {
            "type": "fill",
            "question": "In the RED method for monitoring services, R stands for Rate, E stands for Errors, and D stands for ___.",
            "answer": "Duration",
            "explanation": "The RED method (Rate, Errors, Duration) is the standard for monitoring request-driven services. Rate = requests/sec, Errors = failed requests/sec, Duration = latency distribution."
        },
    ],

    # ======== NEW: API DESIGN ========
    "03-microservices/07-api-design": [
        {
            "type": "mcq",
            "question": "Why is cursor-based pagination preferred over offset-based at scale?",
            "options": [
                "Cursors are faster because the DB doesn't need to skip rows — it seeks directly to the cursor position",
                "Cursors use less memory on the client",
                "Offset pagination is deprecated in PostgreSQL",
                "Cursors are simpler to implement"
            ],
            "correct": 0,
            "explanation": "OFFSET forces the database to scan and discard rows. At offset 1,000,000, it reads 1M rows then discards them. Cursor-based pagination uses WHERE id > cursor LIMIT N, which seeks directly via the index — O(log n) instead of O(n)."
        },
        {
            "type": "tf",
            "question": "POST requests are inherently non-idempotent and can never be made safe to retry.",
            "correct": False,
            "explanation": "POST is non-idempotent by default, but you can make it idempotent using idempotency keys. The client sends a unique key, the server checks if it's been seen before, and returns the cached response if so. This is critical for payment APIs."
        },
        {
            "type": "bug",
            "question": "What's the API design problem here?",
            "code": "// API versioning\nGET /api/movies       // v1 response\nGET /api/v2/movies    // v2 response",
            "options": [
                "Inconsistent versioning — v1 has no version prefix, making migration confusing and breaking existing clients",
                "You should never version APIs",
                "GET is the wrong HTTP method for listing",
                "The endpoint should be /api/movie not /api/movies"
            ],
            "correct": 0,
            "explanation": "If you use URL path versioning, be consistent from v1. Start with /api/v1/movies so when /api/v2/movies arrives, clients know the pattern. Never have an unversioned endpoint alongside versioned ones."
        },
        {
            "type": "mcq",
            "question": "Which HTTP status code should you return when a client exceeds their rate limit?",
            "options": [
                "429 Too Many Requests",
                "403 Forbidden",
                "503 Service Unavailable",
                "400 Bad Request"
            ],
            "correct": 0,
            "explanation": "429 Too Many Requests is the correct status code for rate limiting. Include Retry-After header to tell the client when they can retry, and X-RateLimit-Remaining to show how many requests are left in the window."
        },
    ],

    # ======== NEW: DATABASE INTERNALS ========
    "04-system-design/05-database-internals": [
        {
            "type": "mcq",
            "question": "What is the main advantage of a B-tree index over a hash index in PostgreSQL?",
            "options": [
                "B-trees support range queries (>, <, BETWEEN) while hash indexes only support equality (=)",
                "B-trees are always faster",
                "Hash indexes are deprecated",
                "B-trees use less disk space"
            ],
            "correct": 0,
            "explanation": "B-trees are ordered, so they support range scans, ORDER BY, and prefix matching efficiently. Hash indexes only support exact equality lookups. This is why B-tree is the default index type in PostgreSQL."
        },
        {
            "type": "tf",
            "question": "In PostgreSQL's MVCC implementation, an UPDATE creates a new version of the row and marks the old one as dead.",
            "correct": True,
            "explanation": "PostgreSQL's MVCC never modifies rows in place. UPDATE inserts a new tuple and marks the old one's xmax. Dead tuples are cleaned up by VACUUM. This is why long-running transactions and missing autovacuum cause table bloat."
        },
        {
            "type": "bug",
            "question": "What's wrong with this query pattern?",
            "code": "// Loading movies with their showtimes\nfor _, movie := range movies {\n    rows, _ := db.Query(ctx,\n        \"SELECT * FROM showtimes WHERE movie_id = $1\", movie.ID)\n    // process rows...\n}",
            "options": [
                "This is the N+1 query problem — it makes one query per movie instead of a single JOIN or IN query",
                "You can't use $1 in a loop",
                "The query syntax is wrong",
                "SELECT * is too slow"
            ],
            "correct": 0,
            "explanation": "The N+1 problem: 1 query to load movies + N queries for each movie's showtimes. Fix with a JOIN (SELECT m.*, s.* FROM movies m JOIN showtimes s ON...) or a single IN query (WHERE movie_id = ANY($1)) to load all showtimes in one round trip."
        },
        {
            "type": "fill",
            "question": "In PostgreSQL, the process that cleans up dead tuples left by MVCC is called ___.",
            "answer": "VACUUM",
            "explanation": "VACUUM reclaims storage from dead tuples. autovacuum runs automatically but may need tuning for high-write tables. Without vacuum, tables bloat and queries slow down as they scan dead rows."
        },
    ],

    # ======== NEW: SECURITY PATTERNS ========
    "04-system-design/06-security-patterns": [
        {
            "type": "mcq",
            "question": "Why should you use bcrypt or argon2 instead of SHA-256 for password hashing?",
            "options": [
                "bcrypt/argon2 are intentionally slow (cost factor) and include a salt, making brute-force attacks computationally expensive",
                "SHA-256 is broken and insecure",
                "bcrypt produces shorter hashes",
                "SHA-256 can't handle special characters"
            ],
            "correct": 0,
            "explanation": "SHA-256 is fast by design — an attacker can compute billions of hashes per second. bcrypt/argon2 have a configurable cost factor that makes each hash take ~100-500ms, making brute-force infeasible. They also include a random salt per password, preventing rainbow table attacks."
        },
        {
            "type": "bug",
            "question": "What's the security vulnerability here?",
            "code": "query := fmt.Sprintf(\n    \"SELECT * FROM users WHERE email = '%s' AND password = '%s'\",\n    email, password)\nrows, err := db.Query(ctx, query)",
            "options": [
                "SQL injection — the email/password are interpolated directly into the query string instead of using parameterized queries ($1, $2)",
                "You shouldn't SELECT * in production",
                "The error isn't checked",
                "You should use QueryRow not Query"
            ],
            "correct": 0,
            "explanation": "String interpolation into SQL is the #1 security vulnerability. An attacker can input: email = \"' OR 1=1 --\" to bypass authentication. Always use parameterized queries: db.Query(ctx, \"SELECT * FROM users WHERE email = $1\", email)"
        },
        {
            "type": "tf",
            "question": "A JWT token should contain the user's password hash so the server can validate it without a database lookup.",
            "correct": False,
            "explanation": "Never put sensitive data in JWTs — they're base64-encoded (not encrypted) and readable by anyone. JWTs should contain: user ID, roles, expiry, issuer. The server validates the signature, not the contents. Sensitive data stays in the database."
        },
        {
            "type": "mcq",
            "question": "What is mTLS and when do you use it?",
            "options": [
                "Mutual TLS — both client and server present certificates, used for service-to-service authentication in microservices",
                "Multi-threaded TLS for performance",
                "A TLS version that replaces HTTPS",
                "TLS with multiple encryption keys"
            ],
            "correct": 0,
            "explanation": "In standard TLS, only the server proves its identity. In mTLS, both sides authenticate with certificates. This is the foundation of zero-trust networking in microservices — each service has a certificate proving its identity, preventing unauthorized services from communicating."
        },
    ],

    # ======== NEW: CONTAINERS & ORCHESTRATION ========
    "04-system-design/07-containers-orchestration": [
        {
            "type": "mcq",
            "question": "Why do Go services typically use multi-stage Docker builds with a scratch or distroless base?",
            "options": [
                "Go compiles to a static binary with CGO_ENABLED=0, so you don't need an OS — this minimizes image size and attack surface",
                "It's faster to build",
                "Go requires a special Linux distribution",
                "Docker doesn't support Go otherwise"
            ],
            "correct": 0,
            "explanation": "Go can produce fully static binaries (no libc dependency). With a scratch base, your image contains ONLY your binary — ~10-20MB vs ~900MB for a full Ubuntu image. Smaller images = faster pulls, less disk, fewer CVEs to patch."
        },
        {
            "type": "tf",
            "question": "In Kubernetes, a liveness probe failure causes the pod to be rescheduled to a different node.",
            "correct": False,
            "explanation": "A liveness probe failure causes the kubelet to RESTART the container (kill and recreate), not reschedule the pod. The pod stays on the same node. Rescheduling only happens when a node itself fails or during eviction. A readiness probe failure removes the pod from the Service's endpoints but doesn't restart it."
        },
        {
            "type": "mcq",
            "question": "What's the difference between resource requests and limits in Kubernetes?",
            "options": [
                "Requests are guaranteed resources used for scheduling; limits are the maximum — exceeding memory limits causes OOMKill, exceeding CPU causes throttling",
                "Requests are for development, limits are for production",
                "They're the same thing with different names",
                "Requests are soft limits, limits are hard limits that crash the pod"
            ],
            "correct": 0,
            "explanation": "Requests tell the scheduler how much to reserve — a pod won't be placed on a node without enough capacity. Limits cap actual usage. Memory over-limit = OOMKilled (hard kill). CPU over-limit = throttled (slowed down, not killed). Set requests = limits for predictable behavior."
        },
        {
            "type": "fill",
            "question": "In Go, to handle graceful shutdown in Kubernetes you listen for the ___ signal.",
            "answer": "SIGTERM",
            "explanation": "Kubernetes sends SIGTERM when it wants to stop a pod (during rolling updates, scale-down, etc). Your service should catch SIGTERM, stop accepting new requests, drain in-flight requests, close DB connections, then exit. You have terminationGracePeriodSeconds (default 30s) before SIGKILL."
        },
    ],
}
