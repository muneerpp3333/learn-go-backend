# Types and Data Structures: Memory, Performance, and Production Patterns

## The Problem

You're migrating from TypeScript/JavaScript to Go and think you understand types. But Go's type system isn't about DX sugar—it's about memory efficiency and explicit performance control. A careless slice operation can leak gigabytes of memory. A map's iteration order randomness breaks your distributed system's consistency checks. String concatenation in a loop can allocate a megabyte per iteration. Struct alignment wastes 40% of your memory on a high-cardinality entity.

At $200-300K backend positions, you're expected to:
- Understand the memory layout of every data structure you use
- Know when slices and maps break at scale
- Optimize allocations without premature optimization
- Debug production memory leaks caused by data structure misuse
- Write zero-copy parsers for hot paths

This lesson dives into the internals that make or break your Go backend.

## Theory: The Memory Model

### Slices: The Most Misunderstood Data Structure

A slice in Go is not an array. It's a lightweight wrapper around an array with three components:

```
Slice Header (24 bytes on 64-bit):
┌──────────────┬──────────────┬──────────────┐
│ Pointer (8b) │ Length (8b)  │ Capacity (8b)│
└──────────────┴──────────────┴──────────────┘
     ↓
     [actual data in backing array]
```

When you write `s := []int{1, 2, 3}`, Go allocates:
1. A backing array somewhere in memory
2. A 24-byte slice header pointing to it with len=3, cap=3

The key insight: the slice header is just a pointer and two integers. When you pass a slice to a function, Go copies this 24-byte header (not the underlying array). This is why slices are reference types for mutation but value types for the header.

When you append: `s = append(s, 4)`, the runtime checks if `len < cap`. If yes, it increments len and writes to the next slot. If no, it allocates a new backing array and copies everything.

The allocation strategy is critical: Go uses 2x growth for small slices (under ~256 elements), then switches to 1.25x growth for larger slices. Why? To balance memory waste (2x wastes 50% on the last reallocation) with the cost of allocations. Let's trace through concrete numbers:

- Slice size 0: append to 1 element → allocate 1
- Slice size 1: append to 2 elements → allocate 2 (2x)
- Slice size 2: append to 4 elements → allocate 4 (2x)
- Slice size 4: append to 8 elements → allocate 8 (2x)
- ... (2x growth continues until ~256 elements)
- Slice size 256: append to 512 elements → allocate 512 (2x)
- Slice size 512: append to 640 elements → allocate 640 (1.25x) ← switches here
- Slice size 640: append to 800 elements → allocate 800 (1.25x)

This transition minimizes memory waste on large slices while keeping small slice operations fast.

```go
// Demonstrate slice internals
package main

import (
	"fmt"
	"unsafe"
)

type SliceHeader struct {
	Data uintptr
	Len  int
	Cap  int
}

func main() {
	s := make([]int, 0, 10)

	// Read the slice header
	sh := (*SliceHeader)(unsafe.Pointer(&s))
	fmt.Printf("Empty slice: ptr=%v, len=%d, cap=%d\n", sh.Data, sh.Len, sh.Cap)

	// Append and watch capacity growth
	for i := 0; i < 1000; i++ {
		oldCap := cap(s)
		s = append(s, i)
		newCap := cap(s)

		if oldCap != newCap {
			fmt.Printf("Growth at i=%d: cap %d → %d (growth factor: %.2f)\n",
				i, oldCap, newCap, float64(newCap)/float64(oldCap))
		}
	}
}
```

This matters because:
1. **Memory waste**: Each append that triggers growth wastes 0-50% of memory temporarily
2. **GC pressure**: Large allocations trigger garbage collection, which pauses all goroutines
3. **Cache misses**: Copying moves data to a new address, destroying CPU cache locality
4. **Latency spikes**: A seemingly innocent append can take 10-100ms when copying a 10GB slice
5. **Allocator pressure**: Each reallocation fragments the heap and stresses the memory allocator

**Real-world impact**: In a movie booking system processing 100,000 bookings per second where each booking has a seat slice that grows, uncontrolled slice growth can cause GC pauses that drop throughput by 50%.

**What breaks at scale**: The classic "leak" is subslicing. When you do `tail := s[1000:]` on a million-element slice, you keep the entire million-element backing array in memory, just with a higher pointer. The 999,000 elements you didn't want to reference can't be garbage collected. This is especially pernicious in long-running servers.

```go
// Memory leak example
func processBatch(data []Element) {
	// Process only the last 100 elements but keep everything
	tail := data[len(data)-100:]  // len=100, cap=999,900

	// Send to async processor that holds tail for 30 minutes
	go processAsync(tail)

	// Original data (all 1M elements) stays in memory because tail references it
}

// Another common leak: slicing and storing
type Cache struct {
	items []string
}

func (c *Cache) AddLargeList(data []string) {
	// If data has capacity 1M but we only care about data[0:100]
	// This stores a reference to the entire 1M capacity
	c.items = data[0:100]
}
```

Solution: Copy the slice if you need to keep it long-term:
```go
filtered := make([]Element, len(data)-999900)
copy(filtered, data[999900:])

// Or if space is not critical
tail := append([]Element(nil), data[len(data)-100:]...)
```

**Preallocating slices matters for performance**:

```go
// BAD: Multiple allocations
var results []int
for i := 0; i < 1000000; i++ {
	results = append(results, compute(i))
}

// GOOD: Single allocation
results := make([]int, 0, 1000000)
for i := 0; i < 1000000; i++ {
	results = append(results, compute(i))
}

// The difference: BAD does ~20 reallocations and copies 1+2+4+...+1M elements
// GOOD does 1 allocation. On a modern CPU, this is 100x faster.
```

### Maps: Hash Tables Under the Hood

A Go map is a hash table with buckets. The internal structure is complex but important to understand:

```
map[K]V structure:
- Internally uses a bucket array with power-of-2 size (16, 32, 64, 128, ...)
- Each bucket is typically 128 bytes and holds up to 8 key-value pairs
- Hash collision is handled with overflow buckets (chain hashing)
- Load factor (count / num_buckets) triggers evacuation at ~6.5
```

The memory layout is: for a map with n elements, Go allocates approximately `n / 6.5` buckets, then adds 20% overhead for overflow buckets. This means:

```
map[string]int with 1 million elements:
- ~154k buckets × 128 bytes = ~20MB for bucket array
- Plus key strings themselves
- Plus value data
- Total: ~30-50MB depending on key/value sizes
```

When the load factor gets too high, Go triggers **evacuation**: it allocates a new, larger bucket array (exactly 2x the old size) and rehashes every key-value pair. This is O(n) and blocks ALL map operations.

```go
// Demonstrate map evacuation pressure
package main

import (
	"fmt"
	"time"
)

func main() {
	m := make(map[int]int)

	// Grow to 100k elements
	start := time.Now()
	for i := 0; i < 100000; i++ {
		m[i] = i
	}
	fmt.Printf("Inserted 100k elements: %v\n", time.Since(start))

	// Keep appending; evacuation will happen occasionally
	for i := 100000; i < 200000; i++ {
		m[i] = i
	}
	fmt.Printf("Inserted 200k total elements\n")

	// Deletions don't shrink the map
	start = time.Now()
	for i := 0; i < 100000; i++ {
		delete(m, i)
	}
	fmt.Printf("Deleted 100k elements: %v\n", time.Since(start))
	fmt.Printf("Map still uses memory for 200k buckets\n")
}
```

Evacuation is invisible but causes latency spikes. If you insert 1 million elements into a map in production, periodic pauses of 10-50ms can occur when evacuations happen. This breaks latency SLAs.

The iteration order is **intentionally randomized** by the Go runtime:

```go
// Demonstrate map internals and iteration order
package main

import "fmt"

func main() {
	m := map[string]int{
		"a": 1, "b": 2, "c": 3, "d": 4, "e": 5,
	}

	// Iteration order is randomized per iteration
	for i := 0; i < 3; i++ {
		fmt.Printf("Iteration %d: ", i)
		for k := range m {
			fmt.Print(k, " ")
		}
		fmt.Println()
	}
	// Output: different order each iteration
	// Iteration 0: a c b d e
	// Iteration 1: d e a b c
	// Iteration 2: b a d c e
}
```

**Why randomization?** It prevents developers from relying on iteration order (which changes between Go versions and platforms). But this breaks:
- Deterministic distributed systems (consensus algorithms that iterate maps)
- Consistent hashing algorithms that must process keys in order
- Test assertions that compare map string representations
- Protocol buffers that need deterministic serialization
- Cache invalidation logic that depends on key order

This is an intentional design decision to force better code. If you need order, don't use a map for that purpose.

**Solution**: If order matters, use a sorted slice of keys:

```go
keys := make([]string, 0, len(m))
for k := range m {
	keys = append(keys, k)
}
sort.Strings(keys)
for _, k := range keys {
	v := m[k]
	// process k, v in deterministic order
}
```

**Concurrent map access**: Maps are not thread-safe. Concurrent reads and writes, or even concurrent writes without reads, cause a panic:
```go
// PANICS with "concurrent map iteration" or "concurrent map write"
m := make(map[string]int)

go func() {
	for k, v := range m {
		// do work
	}
}()

time.Sleep(1ms)
m["new_key"] = 99  // Panic: concurrent map write

// Also panics:
go func() { m["a"] = 1 }()
go func() { m["b"] = 2 }()  // May panic if both write simultaneously
```

This is a safety feature but requires synchronization. Options:

```go
// Option 1: sync.Mutex
type SafeMap struct {
	mu sync.RWMutex
	m map[string]int
}

func (sm *SafeMap) Get(k string) (int, bool) {
	sm.mu.RLock()
	defer sm.mu.RUnlock()
	v, ok := sm.m[k]
	return v, ok
}

// Option 2: sync.Map (for mostly-read workloads)
var m sync.Map
m.Store("key", 42)
v, _ := m.Load("key")

// Option 3: Channel-based synchronization
mapChan := make(chan mapOp)
go func() {
	m := make(map[string]int)
	for op := range mapChan {
		// single goroutine accesses map, no races
	}
}()
```

At scale, maps never shrink. If you had 1 million keys and delete 999,999 of them, the map still holds the memory for the bucket array:

```go
m := make(map[int]int)

// Insert 1 million
for i := 0; i < 1000000; i++ {
	m[i] = i
}
// Memory usage: ~30MB

// Delete 999,999
for i := 0; i < 999999; i++ {
	delete(m, i)
}
// Memory usage: STILL ~30MB (all bucket memory retained)

// Only way to shrink: rebuild
newM := make(map[int]int)
for k, v := range m {
	newM[k] = v
}
m = newM
```

This is a memory leak pattern in long-running servers. If you periodically rebuild maps, do it in a goroutine to avoid blocking:

```go
func (c *Cache) Compact() {
	go func() {
		newCache := make(map[string]Value, len(c.m))
		for k, v := range c.m {
			newCache[k] = v
		}
		c.mu.Lock()
		c.m = newCache
		c.mu.Unlock()
	}()
}
```

**What breaks at scale**:
1. Evacuation latency: Inserting into a full map pauses briefly as it reallocates
2. Memory never shrinks: Cache keys accumulate forever
3. Iteration is non-deterministic: Distributed systems can't rely on order
4. Not thread-safe: Must coordinate access with mutex or channel

### Struct Alignment and Padding

Go allocates struct fields in declaration order. But the CPU accesses memory in aligned chunks (4, 8, or 16 bytes). If a field's address isn't aligned, the CPU needs extra cycles to load it.

Go automatically pads structs to satisfy alignment:

```go
type BadOrder struct {
	B  byte      // 1 byte  → address 0
	   // 7 bytes padding (to align I to 8-byte boundary)
	I  int64     // 8 bytes → address 8
	C  byte      // 1 byte  → address 16
	   // 7 bytes padding (to make total size 24, a multiple of 8)
}
// Size: 24 bytes

type GoodOrder struct {
	I  int64     // 8 bytes → address 0
	B  byte      // 1 byte  → address 8
	C  byte      // 1 byte  → address 9
	   // 6 bytes padding
}
// Size: 16 bytes
```

The key insight: each type has an **alignment requirement**. `int64` requires 8-byte alignment, `int32` requires 4-byte alignment, `byte` requires 1-byte alignment. The struct's alignment is the maximum of all its fields' alignments. Go pads to ensure:

1. Each field is at an address divisible by its alignment
2. The total struct size is divisible by the struct's alignment

This is handled automatically, but it wastes memory if fields are in the wrong order.

For high-cardinality entities (movies table with millions of rows), field ordering matters massively:

```go
type Movie struct {
	// BAD: 64 bytes (3x more memory than necessary!)
	Title     string      // 16 bytes (2×8 byte pointer + length)
	Budget    float32     // 4 bytes
	           // 4 bytes padding to align next field
	Duration  int32       // 4 bytes
	           // 4 bytes padding to align ReleaseAt
	ReleaseAt time.Time   // 24 bytes (2×int64 + 1×int64)
	Rating    float64     // 8 bytes
}

type MovieOptimized struct {
	// GOOD: 48 bytes (saves 16 bytes per movie!)
	ReleaseAt time.Time   // 24 bytes @ address 0
	Title     string      // 16 bytes @ address 24
	Rating    float64     // 8 bytes @ address 40
	           // 0 bytes padding
}
```

For a billion movies in memory:
- BadOrder: 64 billion bytes = 64GB
- MovieOptimized: 48 billion bytes = 48GB
- **Savings: 16GB just by reordering fields**

The principle: **order fields by size, largest first**. This minimizes padding.

```go
// Use unsafe.Sizeof() to verify
fmt.Printf("BadOrder: %d bytes\n", unsafe.Sizeof(Movie{}))          // 64
fmt.Printf("MovieOptimized: %d bytes\n", unsafe.Sizeof(MovieOptimized{})) // 48
```

**More complex example with mixed types**:

```go
type Request struct {
	// Bad ordering
	ID       string        // 16 bytes
	Active   bool          // 1 byte → 7 bytes padding
	Count    int32         // 4 bytes → 4 bytes padding
	Timestamp int64        // 8 bytes
	Data     []byte        // 24 bytes
	Total    float64       // 8 bytes
}
// Total: 80 bytes

type RequestOptimized struct {
	// Good ordering (by size)
	Data      []byte        // 24 bytes @ 0
	Timestamp int64         // 8 bytes @ 24
	Total     float64       // 8 bytes @ 32
	ID        string        // 16 bytes @ 40
	Count     int32         // 4 bytes @ 56
	Active    bool          // 1 byte @ 60
	           // 3 bytes padding
}
// Total: 64 bytes (20% savings)
```

You can use a tool to auto-fix this:

```bash
# Install fieldalignment checker
go install golang.org/x/tools/go/analysis/passes/fieldalignment/cmd/fieldalignment@latest

# Check your code
fieldalignment ./...
# Output: struct of size 80 bytes, could be 64 bytes if reordered
```

**Real-world impact on performance**: Bad alignment causes:
1. **More memory usage**: Wastes cache lines (CPU fetches 64-byte cache lines)
2. **Cache misses**: 16GB wasted on a 64GB memory machine means more data in main memory, not L3 cache
3. **GC pressure**: Larger structs mean more allocations and more GC work
4. **Network serialization**: Sending millions of structs over the network with padding wastes bandwidth

In a movie booking system with millions of booking objects in memory, bad struct alignment could waste gigabytes of RAM and cause GC pauses every few seconds.

### String Internals: Immutable Byte Slices

Strings in Go are immutable. Under the hood:

```
String Header (16 bytes on 64-bit):
┌──────────────┬──────────────┐
│ Pointer (8b) │ Length (8b)  │
└──────────────┴──────────────┘
```

A string points to a read-only byte array. Multiple strings can share the same underlying bytes:

```go
s1 := "hello world"
s2 := s1[0:5]  // "hello" - same data pointer, different len
// s1 and s2 share the same backing array in read-only memory

// Even concatenation can reuse memory
s3 := "hello" + " " + "world"  // String interning may reuse constant bytes
```

The immutability means:
1. You can safely pass strings between goroutines (no locks needed)
2. Multiple strings can share memory (read-only)
3. You cannot modify a string once created (no `s[0] = 'H'`)

Strings are **not** slices of bytes—they are byte sequences with length but no capacity. You **cannot** iterate over a string with an index expecting to get Unicode characters:

```go
s := "こんにちは"
fmt.Println(len(s))     // 15 (3 bytes per character in UTF-8)
fmt.Println(s[0])       // 227 (first byte, not the character '\u3053')
fmt.Println(s[1])       // 130 (second byte of first character)

// The three bytes form one character: [227, 130, 147] → "こ"

// CORRECT: range over the string to get runes
for i, r := range s {
	fmt.Printf("%d: %U (%c)\n", i, r, r)
}
// Output:
// 0: U+3053 (こ)
// 3: U+3093 (ん)
// 6: U+306B (に)
// 9: U+3061 (ち)
// 12: U+306F (は)
```

This distinction matters because:
1. Indexing a string returns a `byte`, not a `rune` (character)
2. Iterating with `range` over a string yields `runes`
3. `len(s)` returns bytes, not characters
4. UTF-8 characters can be 1-4 bytes

**String concatenation is expensive**: Each `+` allocates a new string and copies bytes:

```go
// BAD: O(n²) complexity
var s string
for i := 0; i < 1000; i++ {
	s = s + fmt.Sprintf("item_%d,", i)
}
// After first iteration: len(s)=8, allocate 8
// After second iteration: len(s)=16, allocate 16 (copy old 8 + new 8)
// After third iteration: len(s)=24, allocate 24 (copy old 16 + new 8)
// ... total allocations: 8+16+24+32+...+8000 = 4,008,000 bytes copied
```

For a logging system that concatenates 100k messages, this is a performance disaster. Benchmark:

```go
import "testing"

func BenchmarkConcatenate(b *testing.B) {
	for i := 0; i < b.N; i++ {
		var s string
		for j := 0; j < 10000; j++ {
			s = s + "x"
		}
	}
}
// Result: ~10ms for 10k concatenations

func BenchmarkBuilder(b *testing.B) {
	for i := 0; i < b.N; i++ {
		var buf strings.Builder
		for j := 0; j < 10000; j++ {
			buf.WriteRune('x')
		}
		_ = buf.String()
	}
}
// Result: ~100µs for 10k concatenations (100x faster!)
```

Use `strings.Builder` instead:

```go
var buf strings.Builder
buf.Grow(8000)  // Preallocate if you know the size
for i := 0; i < 1000; i++ {
	fmt.Fprintf(&buf, "item_%d,", i)
}
s := buf.String()  // Single allocation
```

Also consider `bytes.Buffer` and `io.WriteString` for different use cases.

### Value vs Reference Semantics

Go is a **value-semantics** language by default:

```go
type Point struct {
	X, Y int
}

p1 := Point{1, 2}
p2 := p1        // COPY the entire struct (16 bytes on 64-bit)
p2.X = 99       // Doesn't affect p1 (different memory location)

fmt.Println(p1.X)  // 1 (unchanged)
fmt.Println(p2.X)  // 99
```

Slices, maps, and channels are **reference types** (or more precisely, they contain a pointer to shared data):

```go
s1 := []int{1, 2, 3}
s2 := s1        // Copy the 24-byte header (pointer, len, cap), NOT the backing array
s2[0] = 99      // Modifies the shared backing array
fmt.Println(s1[0])  // 99 (changed! shared data)

m1 := map[string]int{"a": 1}
m2 := m1        // m1 and m2 reference the same map
m2["a"] = 99    // Modifies the shared map
fmt.Println(m1["a"]) // 99 (both see the change)
```

For maps and channels, assignment creates a second reference to the same underlying data structure. For slices, assignment copies the header (pointer, len, cap), but both slice headers point to the same backing array.

**When it matters**: Passing large structs to functions:

```go
type Config struct {
	Data [1000]int
}

func ProcessValue(c Config) {    // Copies all 8000 bytes each call
	c.Data[0] = 99               // Modifies the copy, not the original
}

func ProcessPointer(c *Config) { // Copies 8-byte pointer only
	c.Data[0] = 99               // Modifies the original
}

// Benchmark shows this clearly
func BenchmarkValuePass(b *testing.B) {
	c := &Config{}
	for i := 0; i < b.N; i++ {
		ProcessValue(*c)  // Copies 8000 bytes each iteration
	}
}
// Result: 5,000,000 ops in 1 second = 40GB/s of copying

func BenchmarkPointerPass(b *testing.B) {
	c := &Config{}
	for i := 0; i < b.N; i++ {
		ProcessPointer(c)  // Copies 8-byte pointer
	}
}
// Result: 500,000,000 ops in 1 second = essentially free
```

**The rule**: If a struct is over ~128 bytes, pass it by pointer. Under that, value semantics are often faster because:
- No pointer dereference (extra memory access)
- Better memory locality (struct is on the stack)
- No GC overhead (stack-allocated)

But there are exceptions. A 32-byte struct passed by pointer might still be faster than by value if:
- The function doesn't modify it (pointer is cheaper than copy)
- The function is in a tight loop (dereference cost matters)

```go
type Small struct {
	A, B, C, D int64  // 32 bytes
}

// Faster to pass by pointer in tight loops
func HotPath(s *Small) {
	for i := 0; i < 1000000; i++ {
		_ = s.A + s.B + s.C + s.D
	}
}

// Passing by value makes a copy; pointer avoids it
```

**Mutability semantics**: Value vs pointer also changes mutation semantics:

```go
type User struct {
	Name string
}

func (u User) Rename(name string) {     // Value receiver
	u.Name = name                        // Modifies the COPY, not the original
}

func (u *User) Rename(name string) {    // Pointer receiver
	u.Name = name                        // Modifies the original
}

// Usage
user := User{Name: "Alice"}
user.Rename("Bob")

// With value receiver: user.Name is still "Alice"
// With pointer receiver: user.Name is now "Bob"
```

This is why `String()` methods should use pointer receivers (to modify internal state if needed) but setter methods MUST use pointer receivers.

## Production Code: Movie Booking Seat Allocation

Here's a realistic system using pgx to manage seat allocations with maps and slices:

```go
package booking

import (
	"context"
	"fmt"
	"sync"

	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgconn"
)

type Seat struct {
	SeatNumber string
	Status     string // "available", "reserved", "sold"
	ReservedBy *string // user_id if reserved
}

type ShowSeating struct {
	mu    sync.RWMutex
	seats map[string]*Seat // seat_number → seat

	// Optimization: pre-sorted available seats for faster lookup
	availableSeatsByRow map[string][]string
}

// NewShowSeating loads seats from database efficiently
func NewShowSeating(ctx context.Context, conn *pgx.Conn, showID string) (*ShowSeating, error) {
	sh := &ShowSeating{
		seats:                make(map[string]*Seat, 500),
		availableSeatsByRow: make(map[string][]string),
	}

	rows, err := conn.Query(ctx, `
		SELECT seat_number, status, reserved_by
		FROM seats
		WHERE show_id = $1
		ORDER BY seat_number
	`, showID)
	if err != nil {
		return nil, fmt.Errorf("query seats: %w", err)
	}
	defer rows.Close()

	for rows.Next() {
		var s Seat
		if err := rows.Scan(&s.SeatNumber, &s.Status, &s.ReservedBy); err != nil {
			return nil, fmt.Errorf("scan seat: %w", err)
		}
		sh.seats[s.SeatNumber] = &s

		if s.Status == "available" {
			row := s.SeatNumber[0:1] // A, B, C, etc.
			sh.availableSeatsByRow[row] = append(sh.availableSeatsByRow[row], s.SeatNumber)
		}
	}

	return sh, rows.Err()
}

// ReserveSeats atomically reserves multiple seats
func (sh *ShowSeating) ReserveSeats(ctx context.Context, tx pgx.Tx, userID string, count int) ([]string, error) {
	sh.mu.Lock()
	defer sh.mu.Unlock()

	reserved := make([]string, 0, count)

	for _, seats := range sh.availableSeatsByRow {
		if len(reserved) >= count {
			break
		}

		// Take from the beginning of the row's available seats
		needed := count - len(reserved)
		take := needed
		if take > len(seats) {
			take = len(seats)
		}

		for i := 0; i < take; i++ {
			seatNum := seats[i]
			sh.seats[seatNum].Status = "reserved"
			sh.seats[seatNum].ReservedBy = &userID
			reserved = append(reserved, seatNum)
		}

		// Remove taken seats from available
		sh.availableSeatsByRow[string(seats[0][0])] = seats[take:]
	}

	if len(reserved) < count {
		return nil, fmt.Errorf("only %d seats available, wanted %d", len(reserved), count)
	}

	// Persist to database
	for _, seat := range reserved {
		if _, err := tx.Exec(ctx, `
			UPDATE seats
			SET status = 'reserved', reserved_by = $1
			WHERE seat_number = $2
		`, userID, seat); err != nil {
			return nil, fmt.Errorf("update seat %s: %w", seat, err)
		}
	}

	return reserved, nil
}

// FindAdjacentSeats finds N consecutive available seats
// Shows why slice iteration order matters
func (sh *ShowSeating) FindAdjacentSeats(count int) []string {
	sh.mu.RLock()
	defer sh.mu.RUnlock()

	// Iterate rows in deterministic order (not map iteration)
	rows := []string{"A", "B", "C", "D", "E"}

	for _, row := range rows {
		available := sh.availableSeatsByRow[row]
		if len(available) >= count {
			// Return first count seats
			result := make([]string, count)
			copy(result, available[:count])
			return result
		}
	}

	return nil
}
```

**Key observations**:
1. Maps for O(1) seat lookups by seat_number
2. Slices for ordered iteration (availableSeatsByRow)
3. `availableSeatsByRow` indexed by row letter to avoid full map iteration
4. RWMutex because reads are frequent (availability checks)
5. Struct pointers in the map because seats are mutable and long-lived

## Pointer Arithmetic Alternatives

Go intentionally doesn't support pointer arithmetic (unlike C). But sometimes you need it. The `unsafe` package provides alternatives:

```go
// Unsafe pointer arithmetic for zero-copy parsing
func ParseBinary(data []byte) error {
	if len(data) < 8 {
		return fmt.Errorf("too short")
	}

	// Get a pointer to the first element
	ptr := unsafe.Pointer(&data[0])

	// Cast to a struct and read
	type Header struct {
		Magic    [4]byte
		Version  uint16
		Reserved uint16
	}

	h := (*Header)(ptr)
	if string(h.Magic[:]) != "MVBK" {
		return fmt.Errorf("invalid magic")
	}

	return nil
}
```

**When is unsafe justified?**
- Parsing binary protocols (message formats, serialization)
- FFI with C libraries
- Extreme performance-critical parsing on hot paths
- Memory-mapped files

**When to avoid**: Everything else. The unsafe package defeats Go's memory safety guarantees.

## Type Assertions and Type Switches

The empty interface `interface{}` (now `any` in Go 1.18+) can hold any value:

```go
var x any = "hello"
var y any = 42
var z any = Movie{Title: "Inception"}

// Type assertion: is it a string?
if s, ok := x.(string); ok {
	fmt.Println("It's a string:", s)
}

// Type switch: what is it?
switch v := x.(type) {
case string:
	fmt.Println("String:", v)
case int:
	fmt.Println("Int:", v)
case Movie:
	fmt.Println("Movie:", v.Title)
default:
	fmt.Println("Unknown type")
}
```

**Performance**: Type assertions are fast (one pointer comparison for most types), but they're not free. In hot loops, avoid them:

```go
// Bad: repeated type assertion in loop
for _, item := range items {
	val, _ := item.(Movie)
	process(val)  // Assertions on every iteration
}

// Good: assert once
mov, ok := item.(Movie)
if !ok {
	return fmt.Errorf("not a movie")
}
for _, item := range items {
	process(mov)
}
```

## Interview Corner: Common Questions and Answers

**Q1: Explain what happens when you append to a slice that's at capacity.**

A: When `len == cap`, the append triggers growth. Go allocates a new backing array with capacity `2 * cap` (for small slices) or `cap + cap/4` (for larger ones). It copies all existing elements to the new array. This is O(n) and blocks until complete. This is why preallocating slices matters: `make([]int, 0, 1000)` avoids repeated allocations.

**Q2: A goroutine writes to a map while another reads it. Why does it panic?**

A: Maps are not thread-safe. Concurrent reads and writes invoke undefined behavior. The panic is a safety mechanism Go built in to catch this. For concurrent access, use `sync.Map` (for mostly-reads) or protect with `sync.RWMutex`.

**Q3: You're using a string in a loop to accumulate results. Why is it slow?**

A: Each string concatenation (`s = s + item`) creates a new string and copies the old string's bytes into it. With n iterations, you do 1 + 2 + 4 + 8 + ... = O(n²) byte copies. Use `strings.Builder` instead, which allocates once and appends efficiently.

**Q4: Your struct is 96 bytes but feels bloated. How do you optimize it?**

A: Run `unsafe.Sizeof()` to confirm, then reorder fields by size (largest first). Group similar types together to minimize padding. If it's still large, consider breaking it into smaller structs for cache efficiency.

**Q5: Why does map iteration return keys in different order each time?**

A: Go randomizes map iteration to prevent developers from depending on order. This ensures code is portable across Go versions. If you need order, build a sorted slice of keys and iterate that instead.

**Q6: A slice from the middle of a large array keeps the entire array in memory. How do you fix it?**

A: Copy the slice: `new := make([]T, len(original[100:200])); copy(new, original[100:200])`. This creates a new backing array for just the elements you need, allowing the original to be garbage-collected.

**Q7: What's the difference between `[10]int` and `[]int`?**

A: `[10]int` is an array—a fixed-size, value type (copying it copies all 10 elements). `[]int` is a slice—a pointer, len, cap header to a dynamic backing array. Slices are almost always what you want.

**Q8: You have a `[]interface{}` with `Movie` values inside. How do you extract and use one?**

A: Use a type assertion: `if mov, ok := items[0].(Movie); ok { process(mov) }`. The comma-ok check prevents panics if the type is wrong.

## What Breaks at Scale

1. **Slice memory leaks via subslicing**: Keeping a subslice of a huge array prevents GC of the parent. Solution: copy.
2. **Map memory never shrinks**: Deleting 99% of entries doesn't free space. Solution: rebuild the map.
3. **String concatenation in loops**: O(n²) complexity, megabyte allocations per iteration. Solution: use `strings.Builder`.
4. **Struct padding waste**: On a billion-entity cache, bad field ordering costs gigabytes. Solution: order by size.
5. **Map iteration order breaks distributed systems**: Hashing a map to check consistency fails. Solution: use sorted keys.
6. **Concurrent map access panics**: No graceful degradation; just panics. Solution: `sync.Map` or mutex protection.

## Exercise

**Exercise 1: Memory-Efficient Movie Store**

Build a movie database that stores 100,000 movie objects in memory. Measure the size difference between:
- A struct with fields in random order
- The same struct with optimized field order

Optimize until you've reduced the size by at least 20%. Hint: use `unsafe.Sizeof()` and `reflect.TypeOf()` to inspect struct layout.

**Exercise 2: Concurrent Seat Reservation**

Write a concurrent seat reservation system for the movie booking domain where:
- Multiple goroutines call `ReserveSeats()` simultaneously
- Without proper synchronization, reservations conflict (two users get the same seat)
- Implement with `sync.Mutex` and show that it fixes the issue
- Benchmark: measure throughput with 10, 100, 1000 concurrent goroutines

**Exercise 3: String Concatenation Comparison**

Write a benchmark comparing:
- String concatenation with `+`: `s = s + item`
- `strings.Builder`
- `bytes.Buffer`

Build a 1-million-line log message with each approach and measure allocation count, time, and memory. Show the O(n²) behavior of naive concatenation.

**Exercise 4: Slice Header Introspection**

Write a program that:
1. Creates a slice
2. Uses `unsafe.Pointer` to read its header (data pointer, len, cap)
3. Appends elements and prints how the capacity grows (2x, then 1.25x)
4. Subslices the original and shows both slices share a backing array

**Exercise 5: Map Determinism**

Write a test that:
1. Creates a map with string keys
2. Iterates it multiple times and collects the order each time
3. Asserts that iteration orders differ (can't rely on order)
4. Shows that using a sorted slice gives deterministic output

