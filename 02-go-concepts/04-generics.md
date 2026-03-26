# Generics: Writing Reusable, Type-Safe Code

## Problem: Reducing Boilerplate Without Losing Type Safety

Pre-Go 1.18, you had three choices:
1. **Code duplication**: Implement List[int], List[string], List[User], etc.
2. **interface{}**: Type-unsafe, requires casting, poor performance
3. **Code generation**: Complex, slow compilation

Go 1.18+ introduced **generics** (type parameters), allowing you to write:
- Generic data structures (Stack[T], Result[T, E])
- Generic repositories for database access
- Generic functional helpers (Map, Filter, Reduce)
- Cache[K, V] with type safety

The challenge: Use generics where they reduce complexity, not where "a little copying is better than a little dependency."

---

## Part 1: Type Parameters and Constraints

### Basic Type Parameter

```go
// Generic function: works with any type T
func Contains[T comparable](slice []T, value T) bool {
    for _, v := range slice {
        if v == value {
            return true
        }
    }
    return false
}

// Usage
Contains([]int{1, 2, 3}, 2)           // true
Contains([]string{"a", "b"}, "c")     // false
Contains([]User{user1, user2}, user1) // true (if User is comparable)
```

The constraint `comparable` means the type must support `==` and `!=` operators.

### Constraints

```go
// No constraint: accepts any type
func PrintValue[T any](v T) {
    fmt.Printf("%v\n", v)
}

// Comparable constraint: types supporting ==, !=
func Equals[T comparable](a, b T) bool {
    return a == b
}

// Numeric constraint (Go 1.22+)
func Sum[T int | int64 | float64](values ...T) T {
    var sum T
    for _, v := range values {
        sum += v
    }
    return sum
}

// Custom interface constraint
type Stringer interface {
    String() string
}

func PrintStrings[T Stringer](values []T) {
    for _, v := range values {
        fmt.Println(v.String())
    }
}
```

### Type Sets and Union Types

```go
// Constraint as a union type
type Integer interface {
    int | int8 | int16 | int32 | int64
}

func Min[T Integer](a, b T) T {
    if a < b {
        return a
    }
    return b
}

// Using ~ to match underlying types
type MyInt int

func TestMin(m MyInt) {
    result := Min(m, MyInt(10))  // Works with underlying type
}
```

The `~T` syntax allows underlying type matching. Without it, only exact types match.

---

## Part 2: The Comparable Constraint and Its Gotchas

### Interface Values and Comparison

```go
// The "comparable" constraint allows == and !=
func AreEqual[T comparable](a, b T) bool {
    return a == b
}

// Problem: interface{} is comparable, but comparing nil interfaces is tricky
var x interface{} = nil
var y interface{} = (*int)(nil)

// Both are "nil", but not equal!
fmt.Println(x == y)  // false (different types)

// For slice and map types, comparable fails
type Data struct {
    Items []string  // Not comparable
    Metadata map[string]string  // Not comparable
}

// This won't compile
func CompareData[T comparable](a, b T) bool {
    return a == b  // ERROR: Data is not comparable
}
```

**Lesson**: `comparable` means supports `==`, but be aware of nil interface semantics.

---

## Part 3: Generic Data Structures

### Generic Stack

```go
type Stack[T any] struct {
    items []T
}

func NewStack[T any]() *Stack[T] {
    return &Stack[T]{items: make([]T, 0)}
}

func (s *Stack[T]) Push(v T) {
    s.items = append(s.items, v)
}

func (s *Stack[T]) Pop() (T, error) {
    var zero T  // Zero value of T
    if len(s.items) == 0 {
        return zero, errors.New("stack empty")
    }
    v := s.items[len(s.items)-1]
    s.items = s.items[:len(s.items)-1]
    return v, nil
}

func (s *Stack[T]) Len() int {
    return len(s.items)
}

// Usage
intStack := NewStack[int]()
intStack.Push(1)
intStack.Push(2)
v, _ := intStack.Pop()  // 2

strStack := NewStack[string]()
strStack.Push("hello")
s, _ := strStack.Pop()  // "hello"
```

### Generic Set

```go
type Set[T comparable] struct {
    items map[T]struct{}
}

func NewSet[T comparable](values ...T) *Set[T] {
    s := &Set[T]{items: make(map[T]struct{})}
    for _, v := range values {
        s.Add(v)
    }
    return s
}

func (s *Set[T]) Add(v T) {
    s.items[v] = struct{}{}
}

func (s *Set[T]) Contains(v T) bool {
    _, ok := s.items[v]
    return ok
}

func (s *Set[T]) Remove(v T) {
    delete(s.items, v)
}

func (s *Set[T]) Size() int {
    return len(s.items)
}

// Usage
seats := NewSet[string]("A1", "A2", "B1")
seats.Contains("A1")  // true
seats.Add("B2")
seats.Remove("A1")
```

### Generic Result Type (Rust-inspired)

```go
type Result[T, E any] struct {
    ok    T
    err   E
    isOk  bool
}

func Ok[T, E any](value T) Result[T, E] {
    return Result[T, E]{ok: value, isOk: true}
}

func Err[T, E any](err E) Result[T, E] {
    return Result[T, E]{err: err, isOk: false}
}

func (r Result[T, E]) Unwrap() (T, E) {
    return r.ok, r.err
}

func (r Result[T, E]) IsOk() bool {
    return r.isOk
}

// Usage
func fetchUser(id string) Result[*User, error] {
    user, err := db.GetUser(id)
    if err != nil {
        return Err[*User, error](err)
    }
    return Ok[*User, error](user)
}

result := fetchUser("123")
if result.IsOk() {
    user, _ := result.Unwrap()
    fmt.Println(user.Name)
}
```

---

## Part 4: Generic Repository Pattern

Data access layer with type safety and DRY principle.

```go
import "github.com/jackc/pgx/v5"

// Repository[T] is a generic CRUD interface
type Repository[T any] interface {
    Create(ctx context.Context, entity T) error
    Read(ctx context.Context, id string) (T, error)
    Update(ctx context.Context, id string, entity T) error
    Delete(ctx context.Context, id string) error
    List(ctx context.Context) ([]T, error)
}

// UserRepository implements Repository[User]
type UserRepository struct {
    db *pgx.Pool
}

type User struct {
    ID   string
    Name string
    Email string
}

func (r *UserRepository) Create(ctx context.Context, user User) error {
    _, err := r.db.Exec(ctx,
        "INSERT INTO users (id, name, email) VALUES ($1, $2, $3)",
        user.ID, user.Name, user.Email)
    return err
}

func (r *UserRepository) Read(ctx context.Context, id string) (User, error) {
    var user User
    err := r.db.QueryRow(ctx,
        "SELECT id, name, email FROM users WHERE id = $1", id).
        Scan(&user.ID, &user.Name, &user.Email)
    return user, err
}

func (r *UserRepository) List(ctx context.Context) ([]User, error) {
    rows, err := r.db.Query(ctx, "SELECT id, name, email FROM users")
    if err != nil {
        return nil, err
    }
    defer rows.Close()

    var users []User
    for rows.Next() {
        var user User
        if err := rows.Scan(&user.ID, &user.Name, &user.Email); err != nil {
            return nil, err
        }
        users = append(users, user)
    }
    return users, rows.Err()
}

// Similar implementations for Movie, Booking, etc.
// All inherit the Repository interface

// Service layer (generic)
type Service[T any] struct {
    repo Repository[T]
}

func (s *Service[T]) GetAll(ctx context.Context) ([]T, error) {
    return s.repo.List(ctx)
}
```

---

## Part 5: Functional Generics

### Map, Filter, Reduce

```go
// Map: Transform each element
func Map[T, U any](items []T, fn func(T) U) []U {
    result := make([]U, len(items))
    for i, item := range items {
        result[i] = fn(item)
    }
    return result
}

// Filter: Keep elements matching predicate
func Filter[T any](items []T, predicate func(T) bool) []T {
    var result []T
    for _, item := range items {
        if predicate(item) {
            result = append(result, item)
        }
    }
    return result
}

// Reduce: Fold left
func Reduce[T, U any](items []T, initial U, fn func(U, T) U) U {
    result := initial
    for _, item := range items {
        result = fn(result, item)
    }
    return result
}

// Usage
prices := []int{100, 200, 150}
doubled := Map(prices, func(p int) int { return p * 2 })  // [200, 400, 300]

expensive := Filter(prices, func(p int) bool { return p > 150 })  // [200]

total := Reduce(prices, 0, func(sum int, p int) int { return sum + p })  // 450
```

### Generic Cache

```go
type Cache[K comparable, V any] struct {
    mu    sync.RWMutex
    items map[K]V
}

func NewCache[K comparable, V any]() *Cache[K, V] {
    return &Cache[K, V]{items: make(map[K]V)}
}

func (c *Cache[K, V]) Get(key K) (V, bool) {
    c.mu.RLock()
    defer c.mu.RUnlock()
    v, ok := c.items[key]
    return v, ok
}

func (c *Cache[K, V]) Set(key K, value V) {
    c.mu.Lock()
    defer c.mu.Unlock()
    c.items[key] = value
}

func (c *Cache[K, V]) Delete(key K) {
    c.mu.Lock()
    defer c.mu.Unlock()
    delete(c.items, key)
}

// Usage
cache := NewCache[string, *User]()
cache.Set("user123", &User{ID: "user123", Name: "Alice"})
user, ok := cache.Get("user123")  // Type-safe retrieval
```

---

## Part 6: When NOT to Use Generics

The Go philosophy: "A little copying is better than a little dependency."

### Bad Use Case 1: Over-Engineering Simple Code

```go
// BAD: Generics add complexity without benefit
type Container[T any] struct {
    value T
}

func (c *Container[T]) Get() T { return c.value }
func (c *Container[T]) Set(v T) { c.value = v }

// Just use direct assignment; Container[T] adds nothing
```

### Bad Use Case 2: Complex Constraints

```go
// BAD: If constraints are complex, generics become unreadable
type Writer interface {
    Write([]byte) (int, error)
}

type Reader interface {
    Read([]byte) (int, error)
}

type ReadWriter interface {
    Read([]byte) (int, error)
    Write([]byte) (int, error)
}

// Constraint becomes hard to understand
func Copy[T ReadWriter](src T, dst T) error {
    // Hard to reason about
}

// Better: Just use io.ReadWriter interface
```

### Bad Use Case 3: Rarely Used Abstractions

```go
// BAD: If only used in one or two places, write concrete code
type Pair[T, U any] struct {
    First  T
    Second U
}

// This adds complexity for minimal reuse
// Better: Use a concrete struct for the specific use case
```

---

## Part 7: Generic Event Publisher

Production code for movie booking domain events.

```go
package events

import (
    "context"
    "errors"
    "sync"
)

// Event is the base interface
type Event interface {
    EventType() string
}

// BookingCreated event
type BookingCreated struct {
    BookingID string
    UserID    string
    MovieID   string
    SeatIDs   []string
}

func (e BookingCreated) EventType() string {
    return "booking.created"
}

// EventHandler[T] processes events of type T
type EventHandler[T Event] interface {
    Handle(ctx context.Context, event T) error
}

// EventPublisher[T] dispatches events to handlers
type EventPublisher[T Event] struct {
    mu       sync.RWMutex
    handlers []EventHandler[T]
}

func NewEventPublisher[T Event]() *EventPublisher[T] {
    return &EventPublisher[T]{handlers: make([]EventHandler[T], 0)}
}

func (ep *EventPublisher[T]) Subscribe(handler EventHandler[T]) {
    ep.mu.Lock()
    defer ep.mu.Unlock()
    ep.handlers = append(ep.handlers, handler)
}

func (ep *EventPublisher[T]) Publish(ctx context.Context, event T) error {
    ep.mu.RLock()
    handlers := make([]EventHandler[T], len(ep.handlers))
    copy(handlers, ep.handlers)
    ep.mu.RUnlock()

    var errs []error
    for _, handler := range handlers {
        if err := handler.Handle(ctx, event); err != nil {
            errs = append(errs, err)
        }
    }

    if len(errs) > 0 {
        return errors.Join(errs...)
    }
    return nil
}

// Concrete handler: Send email on booking
type EmailHandler struct {
    emailService EmailService
}

func (eh *EmailHandler) Handle(ctx context.Context, event BookingCreated) error {
    return eh.emailService.SendConfirmation(ctx, event.UserID)
}

type EmailService interface {
    SendConfirmation(ctx context.Context, userID string) error
}

// Concrete handler: Update analytics
type AnalyticsHandler struct {
    analytics Analytics
}

func (ah *AnalyticsHandler) Handle(ctx context.Context, event BookingCreated) error {
    return ah.analytics.TrackBooking(ctx, event.BookingID, event.UserID)
}

type Analytics interface {
    TrackBooking(ctx context.Context, bookingID, userID string) error
}

// Usage
bookingPublisher := NewEventPublisher[BookingCreated]()
bookingPublisher.Subscribe(&EmailHandler{emailService: emailSvc})
bookingPublisher.Subscribe(&AnalyticsHandler{analytics: analyticsSvc})

event := BookingCreated{
    BookingID: "b123",
    UserID:    "u456",
    MovieID:   "m789",
    SeatIDs:   []string{"A1", "A2"},
}

if err := bookingPublisher.Publish(ctx, event); err != nil {
    log.Printf("Event publishing failed: %v", err)
}
```

---

## Part 8: Performance Considerations

### Monomorphization vs Dictionary Approach

Go doesn't use C++ style template monomorphization (code duplication). Instead:

1. **Compile time**: Type parameters are erased
2. **Runtime**: Dictionary lookups for dynamic dispatch (rare, for methods)
3. **Result**: Single compiled binary, no code bloat, small performance overhead

Compare to C++:
```cpp
// C++ monomorphization: separate code for List<int>, List<string>
List<int> intList;     // ~500 bytes of code
List<string> strList;  // Another ~500 bytes of code

// Go: single binary
cache := NewCache[string, User]()  // Single compiled code, generic at runtime
cache := NewCache[int, string]()    // Same compiled code
```

### Benchmark: Generic vs interface{}

```go
func BenchmarkGenericCache(b *testing.B) {
    cache := NewCache[string, int]()

    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        cache.Set("key", i)
        cache.Get("key")
    }
}

func BenchmarkInterfaceCache(b *testing.B) {
    cache := make(map[string]interface{})

    b.ResetTimer()
    for i := 0; i < b.N; i++ {
        cache["key"] = i
        v := cache["key"].(int)  // Type assertion cost
    }
}

// Results:
// BenchmarkGenericCache    100000000  10.2 ns/op
// BenchmarkInterfaceCache   50000000  24.5 ns/op  (2.4x slower due to type assertion)
```

Generic is faster because no type assertion overhead.

---

## Part 8: Generic Value Types and Receivers

Generics work with value and pointer receivers:

```go
// Value receiver: works with both values and pointers
type Stack[T any] struct {
    items []T
}

func (s Stack[T]) Peek() T {
    // Value receiver: s is a copy
    return s.items[len(s.items)-1]
}

// Pointer receiver: only works with pointers
func (s *Stack[T]) Push(item T) {
    s.items = append(s.items, item)
}

// Usage
var s Stack[int]
s.Push(1)  // Works: receiver is automatically *s
val := s.Peek()  // Works: value or pointer

// Gotcha: interface{} doesn't preserve generic type
var x interface{} = Stack[int]{}
// Type assertion fails: can't convert back to Stack[int]
s2, ok := x.(Stack[int])  // Works only if x is exactly Stack[int]

// Better: Use constraints or keep type parameters in function signatures
```

---

## Part 9: Generic Constraints in Depth

### Constraint Anatomy

```go
// Union constraint (multiple types)
type Number interface {
    int | int64 | float64
}

// Interface constraint (implements methods)
type Reader interface {
    Read([]byte) (int, error)
}

// Combining constraints (intersection)
type ReadCloser interface {
    Read([]byte) (int, error)
    Close() error
}

// Approximation elements with ~
type MyInt int

func Min[T ~int](a, b T) T {
    // ~ allows MyInt (underlying type int)
    // Without ~: only exact int type matches
    if a < b {
        return a
    }
    return b
}

Min(MyInt(10), MyInt(20))  // Works with ~int

// Named constraints (Go 1.22+)
type cmp.Ordered interface {
    int | int8 | int16 | int32 | int64 |
        uint | uint8 | uint16 | uint32 | uint64 |
        float32 | float64 | string
}

// Use named constraint
func Min[T cmp.Ordered](a, b T) T {
    if a < b {
        return a
    }
    return b
}
```

### Type Inference Rules

Go's type parameter inference can save you from writing explicit types:

```go
// Explicit types
result := Map[int, string]([]int{1, 2, 3}, func(i int) string {
    return strconv.Itoa(i)
})

// Inferred types (cleaner!)
result := Map([]int{1, 2, 3}, func(i int) string {
    return strconv.Itoa(i)
})

// Go infers: input slice type determines first param (int)
// Return type of lambda determines second param (string)

// Limitation: Can't always infer
type Pair[T, U any] struct{ First T; Second U }

// This doesn't work - can't infer both T and U
p := Pair{1, "hello"}  // ERROR

// Must use explicit types
p := Pair[int, string]{1, "hello"}
```

---

## Part 10: Generic Pipeline and Chain-of-Responsibility

### Generic Pipeline Pattern

```go
// Stage defines a pipeline stage
type Stage[In, Out any] func(ctx context.Context, in In) (Out, error)

// Pipeline chains multiple stages
func Pipeline[T, U, V any](
    stage1 Stage[T, U],
    stage2 Stage[U, V],
) Stage[T, V] {
    return func(ctx context.Context, in T) (V, error) {
        u, err := stage1(ctx, in)
        if err != nil {
            var zero V
            return zero, err
        }

        return stage2(ctx, u)
    }
}

// Usage in booking
type BookingRequest struct {
    UserID  string
    MovieID string
}

type PaymentInfo struct {
    Amount float64
}

type Booking struct {
    ID        string
    Status    string
}

// Stages
validateRequest := func(ctx context.Context, req BookingRequest) (PaymentInfo, error) {
    return PaymentInfo{Amount: 99.99}, nil
}

processPayment := func(ctx context.Context, info PaymentInfo) (Booking, error) {
    return Booking{ID: "b123", Status: "confirmed"}, nil
}

// Create pipeline
pipeline := Pipeline(validateRequest, processPayment)

// Run
booking, err := pipeline(ctx, BookingRequest{UserID: "u1", MovieID: "m1"})
```

### Generic Middleware Chain

```go
// Request/Response for middleware
type Request[T any] struct {
    Data T
    ID   string
}

type Response[T any] struct {
    Data T
    Err  error
}

// Middleware chaining
type Middleware[T any] func(next func(Request[T]) Response[T]) func(Request[T]) Response[T]

func loggingMiddleware[T any](next func(Request[T]) Response[T]) func(Request[T]) Response[T] {
    return func(req Request[T]) Response[T] {
        log.Printf("Request: %v", req)
        resp := next(req)
        log.Printf("Response: %v", resp)
        return resp
    }
}

func validationMiddleware[T any](validator func(T) error) Middleware[T] {
    return func(next func(Request[T]) Response[T]) func(Request[T]) Response[T] {
        return func(req Request[T]) Response[T] {
            if err := validator(req.Data); err != nil {
                return Response[T]{Err: err}
            }
            return next(req)
        }
    }
}

func chainMiddleware[T any](middlewares ...Middleware[T]) func(func(Request[T]) Response[T]) func(Request[T]) Response[T] {
    return func(next func(Request[T]) Response[T]) func(Request[T]) Response[T] {
        for i := len(middlewares) - 1; i >= 0; i-- {
            next = middlewares[i](next)
        }
        return next
    }
}

// Usage
bookingValidator := func(br BookingRequest) error {
    if br.UserID == "" {
        return errors.New("user_id required")
    }
    return nil
}

chain := chainMiddleware(
    loggingMiddleware[BookingRequest],
    validationMiddleware[BookingRequest](bookingValidator),
)

handler := chain(func(req Request[BookingRequest]) Response[BookingRequest] {
    // Actual handler
    return Response[BookingRequest]{Data: req.Data}
})
```

---

## Part 11: Generic Limitations and Workarounds

### Limitation 1: No Method Type Parameters

```go
// INVALID: Can't have type parameters on methods
type Handler struct {}

func (h *Handler) Handle[T any](data T) error {
    // ERROR: Method can't have type parameters
}

// WORKAROUND: Use function instead
func Handle[T any](h *Handler, data T) error {
    return nil
}

// Or make receiver generic
type GenericHandler[T any] struct {}

func (h *GenericHandler[T]) Handle(data T) error {
    return nil
}
```

### Limitation 2: No Specialization

```go
// Go's generics don't specialize (compile to single code)
// Can't have specialized fast path for int

func Process[T any](items []T) {
    // Same code for all T
    // Can't do: if T == int { /* fast path */ }
}

// WORKAROUND: Use constraints + type assertion
func Process[T comparable](items []T) {
    for _, item := range items {
        // Generic code that works for all comparable types
    }
}
```

### Comparison with Java/TypeScript Generics

```
Feature                 | Go              | Java              | TypeScript
Specialization          | No (type erased)| Yes (JIT)         | No (runtime erased)
Constraint syntax       | Interfaces     | extends/super     | extends
Wildcard types          | No             | Yes (? extends T)  | No
Variance                | No             | Yes (covariance)   | Partial
Performance overhead    | None           | Possible (JIT)     | None (erased)

Go's approach: Simple, predictable performance, minimal binary size
Java's approach: More flexible, JIT specialization, larger binary
TypeScript's approach: Compile-time only, no runtime cost
```

---

## Interview Corner

### Q1: What are type parameters and constraints?

**Model Answer**:
Type parameters are placeholders for types, resolved at compile time. Constraints specify what operations a type parameter must support.

```go
func Max[T int | int64 | float64](a, b T) T { ... }
```

Here, `T` is the type parameter, `int | int64 | float64` is the constraint (union type). The function works for any of these types.

Constraints can be:
- `any`: No restrictions
- `comparable`: Type supports ==, !=
- Interface: Type implements the interface
- Union: Type is one of the listed types
- Named constraints (cmp.Ordered)

### Q2: When should you use generics vs interface{}?

**Model Answer**:
Use generics when:
- Type safety matters and you want compile-time checking
- You want to avoid runtime type assertions
- Reusable data structures or algorithms benefit from it

Use interface{} when:
- You truly need dynamic typing (rare in backend code)
- Performance isn't critical

Avoid generics when:
- Complexity exceeds benefit (single-use code)
- Constraints become complex and hard to read

### Q3: Explain the generic repository pattern.

**Model Answer**:
A generic Repository[T] interface defines CRUD operations for any type T:

```go
type Repository[T any] interface {
    Create(ctx context.Context, entity T) error
    Read(ctx context.Context, id string) (T, error)
    Update(ctx context.Context, entity T) error
    Delete(ctx context.Context, id string) error
}
```

Each concrete type (User, Movie, Booking) implements this interface. Services can be generic:

```go
type Service[T any] struct {
    repo Repository[T]
}
```

This eliminates boilerplate without sacrificing type safety.

### Q4: What's the difference between generic functions and generic methods?

**Model Answer**:
- **Generic functions**: Type parameters in the function signature
  ```go
  func Map[T, U any](items []T, fn func(T) U) []U { ... }
  ```
- **Generic methods**: Type parameters on receiver type
  ```go
  func (s *Stack[T]) Pop() (T, error) { ... }
  ```

Generic methods require the receiver type to be generic. Generic functions are more flexible and can be called independently. Note: Methods cannot have independent type parameters (use functions instead).

### Q5: Design a generic middleware for HTTP handlers.

**Model Answer**:
```go
type Middleware[T any] func(func(T) error) func(T) error

func LoggingMiddleware[T any](next func(T) error) func(T) error {
    return func(req T) error {
        log.Printf("Processing request")
        err := next(req)
        log.Printf("Request completed: %v", err)
        return err
    }
}

func ChainMiddleware[T any](middlewares ...Middleware[T]) Middleware[T] {
    return func(next func(T) error) func(T) error {
        for i := len(middlewares) - 1; i >= 0; i-- {
            next = middlewares[i](next)
        }
        return next
    }
}
```

### Q6: How do generics compare to Java/TypeScript generics?

**Model Answer**:
- **Go**: Type-erased (no specialization), simple constraints, no variance. Fast compile, no runtime overhead.
- **Java**: Specialized by JIT, complex syntax (extends/super), covariance support. Larger binaries, JIT overhead.
- **TypeScript**: Type-erased (compile-time only), full structural subtyping, no runtime cost.

Go chose simplicity and predictability over flexibility. This makes Go generics ideal for backend systems where performance is critical and compile times matter.

### Q7: Design a generic transaction manager for database operations.

**Model Answer**:
```go
// Transaction abstraction
type Tx[T any] interface {
    Commit(ctx context.Context) error
    Rollback(ctx context.Context) error
}

// Generic transaction manager
type TxManager[T Tx[any]] struct {
    db *pgx.Pool
}

func (tm *TxManager[T]) WithTx(ctx context.Context, fn func(T) error) error {
    tx, err := tm.db.Begin(ctx)
    if err != nil {
        return err
    }

    // Execute function
    if err := fn(tx); err != nil {
        tx.Rollback(ctx)
        return err
    }

    // Success: commit
    return tx.Commit(ctx)
}

// Specific usage for repositories
func (repo *BookingRepository) CreateWithTransaction(ctx context.Context, booking *Booking) error {
    return repo.txManager.WithTx(ctx, func(tx pgx.Tx) error {
        // All operations use same transaction
        return repo.createBookingInTx(ctx, tx, booking)
    })
}

// Nested transactions with savepoints
func (tm *TxManager[T]) WithSavepoint(ctx context.Context, name string, fn func(T) error) error {
    // Execute with savepoint, rollback to savepoint on error
    return fn(tx)  // Simplified; real implementation uses savepoints
}
```

### Q8: Implement a generic cache with TTL and automatic eviction.

**Model Answer**:
```go
type CacheEntry[T any] struct {
    value  T
    expiry time.Time
}

type TTLCache[K comparable, V any] struct {
    mu    sync.RWMutex
    items map[K]*CacheEntry[V]
    ttl   time.Duration
}

func NewTTLCache[K comparable, V any](ttl time.Duration) *TTLCache[K, V] {
    cache := &TTLCache[K, V]{
        items: make(map[K]*CacheEntry[V]),
        ttl:   ttl,
    }

    // Background eviction
    go func() {
        ticker := time.NewTicker(1 * time.Minute)
        defer ticker.Stop()

        for range ticker.C {
            cache.evictExpired()
        }
    }()

    return cache
}

func (c *TTLCache[K, V]) Get(key K) (V, bool) {
    c.mu.RLock()
    defer c.mu.RUnlock()

    entry, exists := c.items[key]
    if !exists || time.Now().After(entry.expiry) {
        var zero V
        return zero, false
    }

    return entry.value, true
}

func (c *TTLCache[K, V]) Set(key K, value V) {
    c.mu.Lock()
    defer c.mu.Unlock()

    c.items[key] = &CacheEntry[V]{
        value:  value,
        expiry: time.Now().Add(c.ttl),
    }
}

func (c *TTLCache[K, V]) evictExpired() {
    c.mu.Lock()
    defer c.mu.Unlock()

    now := time.Now()
    for key, entry := range c.items {
        if now.After(entry.expiry) {
            delete(c.items, key)
        }
    }
}

// Usage
movieCache := NewTTLCache[string, *Movie](5 * time.Minute)
movieCache.Set("m1", &Movie{ID: "m1", Title: "Inception"})

if movie, ok := movieCache.Get("m1"); ok {
    fmt.Println(movie.Title)
}
```

**Model Answer**:
- **Go**: Type-erased (no specialization), simple constraints, no variance. Fast compile, no runtime overhead.
- **Java**: Specialized by JIT, complex syntax (extends/super), covariance support. Larger binaries, JIT overhead.
- **TypeScript**: Type-erased (compile-time only), full structural subtyping, no runtime cost.

Go chose simplicity and predictability over flexibility. This makes Go generics ideal for backend systems where performance is critical and compile times matter.

---

## Part 12: Generic Option Pattern for Flexible APIs

```go
// Option pattern with generics
type ClientOptions[T any] struct {
    Timeout    time.Duration
    MaxRetries int
    Validator  func(T) error
    Logger     *slog.Logger
}

type ClientOption[T any] func(*ClientOptions[T])

func WithTimeout[T any](d time.Duration) ClientOption[T] {
    return func(opts *ClientOptions[T]) {
        opts.Timeout = d
    }
}

func WithMaxRetries[T any](n int) ClientOption[T] {
    return func(opts *ClientOptions[T]) {
        opts.MaxRetries = n
    }
}

func WithValidator[T any](validator func(T) error) ClientOption[T] {
    return func(opts *ClientOptions[T]) {
        opts.Validator = validator
    }
}

type Client[T any] struct {
    opts ClientOptions[T]
}

func NewClient[T any](options ...ClientOption[T]) *Client[T] {
    opts := ClientOptions[T]{
        Timeout:    10 * time.Second,
        MaxRetries: 3,
    }

    for _, opt := range options {
        opt(&opts)
    }

    return &Client[T]{opts: opts}
}

// Usage: Clean, type-safe, flexible
client := NewClient[BookingRequest](
    WithTimeout[BookingRequest](5 * time.Second),
    WithMaxRetries[BookingRequest](5),
    WithValidator[BookingRequest](func(req BookingRequest) error {
        if req.UserID == "" {
            return errors.New("user_id required")
        }
        return nil
    }),
)
```

---

## Part 13: Generic Ordered Constraints and Comparison

```go
// Go 1.22+ introduces cmp.Ordered for comparison operations
import "cmp"

// Find min/max with ordered constraint
func Min[T cmp.Ordered](a, b T) T {
    if a < b {
        return a
    }
    return b
}

// Generic sorted container
type SortedList[T cmp.Ordered] struct {
    items []T
}

func (sl *SortedList[T]) Insert(item T) {
    i := sort.SearchSlice(sl.items, func(j int) bool {
        return sl.items[j] >= item
    })

    sl.items = append(sl.items[:i], append([]T{item}, sl.items[i:]...)...)
}

func (sl *SortedList[T]) Find(target T) bool {
    idx := sort.SearchSlice(sl.items, func(i int) bool {
        return sl.items[i] >= target
    })

    return idx < len(sl.items) && sl.items[idx] == target
}

// Without generics, would need separate implementations for int, float64, string, etc.
// With generics, one implementation for all ordered types
```

---

## Tradeoffs and Best Practices

### When Generics Shine
- Data structures (Stack[T], Queue[T], Cache[K, V])
- Algorithms (Map, Filter, Reduce, Sort)
- Repositories and DAOs
- Result types for error handling

### When to Avoid
- Simple wrapper types
- Complex constraints that reduce readability
- Single-use code
- High performance critical paths (though generics have no runtime penalty)

### Constraint Design
- Keep constraints simple and understandable
- Use interface constraints over union types when possible
- Document constraint requirements clearly

---

## Exercise

Build a **generic event-driven architecture** for movie booking:

1. Create generic Event[T] type and EventHandler[T] interface
2. Implement specific events: BookingCreated, PaymentProcessed, SeatLocked
3. Create EventBus[T] that publishes events to multiple handlers
4. Implement concrete handlers: email notification, analytics tracking, database logging
5. Use generic Repository[T] for persistence
6. Chain handlers with error handling

Requirements:
- Must be type-safe (no interface{})
- Must support multiple subscribers
- Must handle errors from handlers
- Must work with different event types
- Must support async publishing with context cancellation

Bonus: Add event sourcing pattern where all events are persisted to a database for replay.

