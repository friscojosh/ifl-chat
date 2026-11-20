package ifl

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const testInternalSecret = "internal-secret-internal-secret-000"

func clientFor(url string) *SiteClient {
	return NewSiteClient(Config{SiteInternalURL: url, InternalSecret: testInternalSecret})
}

func TestSuspensionSuccess(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			t.Errorf("method %s", r.Method)
		}
		if r.URL.Path != "/internal/chat/users/42/suspension" {
			t.Errorf("path %s", r.URL.Path)
		}
		if r.Header.Get("X-IFL-Chat-Secret") != testInternalSecret {
			t.Errorf("secret header %q", r.Header.Get("X-IFL-Chat-Secret"))
		}
		raw, _ := io.ReadAll(r.Body)
		var body map[string]string
		if err := json.Unmarshal(raw, &body); err != nil || len(body) != 2 || body["action"] != "suspend" || body["actor"] != "comm" {
			t.Errorf("body %s", raw)
		}
		w.Write([]byte(`{"suspended":true,"eligible":false,"reason":"suspended"}`))
	}))
	defer srv.Close()

	r, err := clientFor(srv.URL).Suspension(context.Background(), "42", "suspend", "comm")
	if err != nil {
		t.Fatal(err)
	}
	if !r.Suspended || r.Eligible || r.Reason == nil || *r.Reason != "suspended" {
		t.Fatalf("result %+v", r)
	}
}

func TestSuspensionRefused(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusConflict)
		w.Write([]byte(`{"error":"Cannot suspend the last commissioner"}`))
	}))
	defer srv.Close()

	_, err := clientFor(srv.URL).Suspension(context.Background(), "42", "suspend", "comm")
	if err == nil || !strings.Contains(err.Error(), "Cannot suspend the last commissioner") {
		t.Fatalf("err %v", err)
	}
}

func TestSuspension503(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusServiceUnavailable)
	}))
	defer srv.Close()

	if _, err := clientFor(srv.URL).Suspension(context.Background(), "42", "suspend", "comm"); err == nil {
		t.Fatal("expected error")
	}
}

func TestSuspensionConnectionRefused(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	url := srv.URL
	srv.Close()

	if _, err := clientFor(url).Suspension(context.Background(), "42", "suspend", "comm"); err == nil {
		t.Fatal("expected error")
	}
}

func TestSuspensionTimeout(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case <-time.After(500 * time.Millisecond):
		case <-r.Context().Done():
		}
	}))
	defer srv.Close()

	c := clientFor(srv.URL)
	c.http.Timeout = 200 * time.Millisecond
	start := time.Now()
	if _, err := c.Suspension(context.Background(), "42", "suspend", "comm"); err == nil {
		t.Fatal("expected timeout error")
	}
	if time.Since(start) > time.Second {
		t.Fatal("did not time out promptly")
	}
}

func TestSuspensionRejectsNonNumericSiteID(t *testing.T) {
	called := false
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) { called = true }))
	defer srv.Close()

	for _, id := range []string{"", "abc", "42/../x", "4 2", "-1", "42?x=1"} {
		if _, err := clientFor(srv.URL).Suspension(context.Background(), id, "suspend", "comm"); err == nil {
			t.Errorf("accepted %q", id)
		}
	}
	if called {
		t.Fatal("request was sent")
	}
}

func TestSuspensionNotConfigured(t *testing.T) {
	if _, err := NewSiteClient(Config{}).Suspension(context.Background(), "42", "suspend", "comm"); err == nil {
		t.Fatal("expected error")
	}
}
