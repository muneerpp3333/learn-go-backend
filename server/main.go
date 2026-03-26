package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"os"
	"os/exec"
	"os/signal"
	"path/filepath"
	"strings"
	"syscall"
	"time"
)

// ============================================================
// Backend Mastery — Go Learning Server
// Serves the LMS static files + provides a local Go code
// execution API (compile, run, format).
// ============================================================

const (
	defaultPort    = "3000"
	maxCodeSize    = 64 * 1024 // 64KB max code size
	execTimeout    = 10 * time.Second
	formatTimeout  = 5 * time.Second
)

// RunRequest is the JSON body for /api/run
type RunRequest struct {
	Code string `json:"code"`
}

// RunResponse is the JSON response from /api/run
type RunResponse struct {
	Output string `json:"output"`
	Error  string `json:"error,omitempty"`
	Time   string `json:"time"`
}

// FormatRequest is the JSON body for /api/format
type FormatRequest struct {
	Code string `json:"code"`
}

// FormatResponse is the JSON response from /api/format
type FormatResponse struct {
	Code  string `json:"code,omitempty"`
	Error string `json:"error,omitempty"`
}

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = defaultPort
	}

	mux := http.NewServeMux()

	// API routes
	mux.HandleFunc("/api/run", corsMiddleware(handleRun))
	mux.HandleFunc("/api/format", corsMiddleware(handleFormat))
	mux.HandleFunc("/api/health", corsMiddleware(handleHealth))

	// Static file server — serves index.html and other assets from parent dir
	staticDir := filepath.Join("..", "static")
	if _, err := os.Stat(staticDir); os.IsNotExist(err) {
		// Fallback: serve from parent directory directly (index.html at root)
		staticDir = ".."
	}
	fs := http.FileServer(http.Dir(staticDir))
	mux.Handle("/", fs)

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  15 * time.Second,
		WriteTimeout: 30 * time.Second,
		IdleTimeout:  60 * time.Second,
	}

	// Graceful shutdown
	go func() {
		sigCh := make(chan os.Signal, 1)
		signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)
		<-sigCh
		log.Println("Shutting down server...")
		ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
		defer cancel()
		srv.Shutdown(ctx)
	}()

	fmt.Printf("\n")
	fmt.Printf("  ╔══════════════════════════════════════════╗\n")
	fmt.Printf("  ║   Backend Mastery — Learning Server      ║\n")
	fmt.Printf("  ║                                          ║\n")
	fmt.Printf("  ║   → http://localhost:%s                 ║\n", port)
	fmt.Printf("  ║                                          ║\n")
	fmt.Printf("  ║   API:                                   ║\n")
	fmt.Printf("  ║     POST /api/run     Execute Go code    ║\n")
	fmt.Printf("  ║     POST /api/format  Format Go code     ║\n")
	fmt.Printf("  ║     GET  /api/health  Health check       ║\n")
	fmt.Printf("  ║                                          ║\n")
	fmt.Printf("  ║   Press Ctrl+C to stop                   ║\n")
	fmt.Printf("  ╚══════════════════════════════════════════╝\n\n")

	if err := srv.ListenAndServe(); err != http.ErrServerClosed {
		log.Fatalf("Server error: %v", err)
	}
	log.Println("Server stopped.")
}

// handleRun compiles and executes Go code in a temp directory.
func handleRun(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, RunResponse{Error: "POST required"})
		return
	}

	var req RunRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, RunResponse{Error: "Invalid JSON: " + err.Error()})
		return
	}

	if len(req.Code) == 0 {
		writeJSON(w, http.StatusBadRequest, RunResponse{Error: "No code provided"})
		return
	}
	if len(req.Code) > maxCodeSize {
		writeJSON(w, http.StatusBadRequest, RunResponse{Error: "Code too large (max 64KB)"})
		return
	}

	// Basic safety check
	if containsDangerous(req.Code) {
		writeJSON(w, http.StatusBadRequest, RunResponse{Error: "Code contains restricted operations"})
		return
	}

	start := time.Now()

	// Create temp directory for this run
	tmpDir, err := os.MkdirTemp("", "gorun-*")
	if err != nil {
		writeJSON(w, http.StatusInternalServerError, RunResponse{Error: "Failed to create temp dir"})
		return
	}
	defer os.RemoveAll(tmpDir)

	// Write the code to a temp file
	codePath := filepath.Join(tmpDir, "main.go")
	if err := os.WriteFile(codePath, []byte(req.Code), 0644); err != nil {
		writeJSON(w, http.StatusInternalServerError, RunResponse{Error: "Failed to write code"})
		return
	}

	// Initialize a Go module in the temp dir so imports work
	modPath := filepath.Join(tmpDir, "go.mod")
	os.WriteFile(modPath, []byte("module playground\n\ngo 1.21\n"), 0644)

	// Run the code with timeout
	ctx, cancel := context.WithTimeout(context.Background(), execTimeout)
	defer cancel()

	cmd := exec.CommandContext(ctx, "go", "run", "main.go")
	cmd.Dir = tmpDir
	cmd.Env = append(os.Environ(),
		"GOCACHE="+filepath.Join(tmpDir, ".cache"),
		"GOPATH="+filepath.Join(tmpDir, ".gopath"),
	)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	err = cmd.Run()
	elapsed := time.Since(start)

	resp := RunResponse{
		Time: fmt.Sprintf("%.2fs", elapsed.Seconds()),
	}

	if ctx.Err() == context.DeadlineExceeded {
		resp.Error = fmt.Sprintf("Execution timed out after %s", execTimeout)
	} else if err != nil {
		// Compilation or runtime error
		errMsg := stderr.String()
		// Clean up temp paths from error messages
		errMsg = strings.ReplaceAll(errMsg, tmpDir+"/", "")
		errMsg = strings.ReplaceAll(errMsg, tmpDir, "")
		resp.Error = errMsg
		// Still include any output that was produced
		if stdout.Len() > 0 {
			resp.Output = stdout.String()
		}
	} else {
		resp.Output = stdout.String()
		if stderr.Len() > 0 {
			resp.Output += "\n[stderr]: " + stderr.String()
		}
	}

	writeJSON(w, http.StatusOK, resp)
}

// handleFormat formats Go code using gofmt.
func handleFormat(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeJSON(w, http.StatusMethodNotAllowed, FormatResponse{Error: "POST required"})
		return
	}

	var req FormatRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, FormatResponse{Error: "Invalid JSON"})
		return
	}

	if len(req.Code) == 0 {
		writeJSON(w, http.StatusBadRequest, FormatResponse{Error: "No code provided"})
		return
	}

	ctx, cancel := context.WithTimeout(context.Background(), formatTimeout)
	defer cancel()

	// Try goimports first (adds missing imports), fall back to gofmt
	formatter := "goimports"
	if _, err := exec.LookPath("goimports"); err != nil {
		formatter = "gofmt"
	}

	cmd := exec.CommandContext(ctx, formatter)
	cmd.Stdin = strings.NewReader(req.Code)

	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	if err := cmd.Run(); err != nil {
		errMsg := stderr.String()
		if errMsg == "" {
			errMsg = err.Error()
		}
		writeJSON(w, http.StatusOK, FormatResponse{Error: errMsg})
		return
	}

	writeJSON(w, http.StatusOK, FormatResponse{Code: stdout.String()})
}

// handleHealth returns server status.
func handleHealth(w http.ResponseWriter, r *http.Request) {
	// Check if Go is available
	goVersion := "unknown"
	if out, err := exec.Command("go", "version").Output(); err == nil {
		goVersion = strings.TrimSpace(string(out))
	}

	writeJSON(w, http.StatusOK, map[string]string{
		"status":  "ok",
		"go":      goVersion,
		"time":    time.Now().Format(time.RFC3339),
	})
}

// containsDangerous checks for dangerous operations in code.
// We block operations that can execute commands, delete files, or
// escape the sandbox — but allow unsafe (needed for slice/memory lessons)
// and read-only os operations.
func containsDangerous(code string) bool {
	dangerous := []string{
		"os/exec",         // executing arbitrary commands
		"syscall.Exec",    // direct exec syscall
		"syscall.Kill",    // sending signals
		"os.Remove(",      // deleting files
		"os.RemoveAll(",   // deleting directories
		"os.Exit(",        // exiting the process
		"plugin.Open",     // loading shared libraries
		"net/http",        // making network calls (keep sandbox isolated)
	}
	for _, d := range dangerous {
		if strings.Contains(code, d) {
			return true
		}
	}
	return false
}

// corsMiddleware adds CORS headers for local development.
func corsMiddleware(next http.HandlerFunc) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Access-Control-Allow-Origin", "*")
		w.Header().Set("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
		w.Header().Set("Access-Control-Allow-Headers", "Content-Type")
		if r.Method == http.MethodOptions {
			w.WriteHeader(http.StatusOK)
			return
		}
		next(w, r)
	}
}

func writeJSON(w http.ResponseWriter, status int, data interface{}) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}
