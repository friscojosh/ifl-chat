// IFL: league chat fork (app cards).
package ifl

import (
	"context"
	"errors"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestCardIDs(t *testing.T) {
	for id, ok := range map[string]bool{"1": true, "123456789012": true, "": false, "1234567890123": false, "12a": false, "-1": false} {
		if ValidMatchupID(id) != ok {
			t.Errorf("ValidMatchupID(%q) = %v", id, !ok)
		}
	}
	for id, ok := range map[string]bool{"rw-123": true, "a:b.c": true, "": false, "a b": false, "a/b": false, "a?b": false, "a#b": false} {
		if ValidStoryID(id) != ok {
			t.Errorf("ValidStoryID(%q) = %v", id, !ok)
		}
	}
}

func TestCards(t *testing.T) {
	var got []string
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("X-IFL-Chat-Secret") != testInternalSecret {
			w.WriteHeader(http.StatusUnauthorized)
			return
		}
		got = append(got, r.URL.RequestURI())
		switch r.URL.Path {
		case "/internal/chat/cards/score/7":
			w.Write([]byte(" {\"week\":{},\"matchup\":{}}\n"))
		case "/internal/chat/cards/score/8":
			w.Write([]byte(`[1,2]`))
		case "/internal/chat/cards/score/9":
			w.WriteHeader(http.StatusInternalServerError)
		case "/internal/chat/cards/news/a:b":
			w.Write([]byte(`{"item":{}}`))
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	}))
	defer srv.Close()
	c := clientFor(srv.URL)
	ctx := context.Background()

	body, err := c.ScoreCard(ctx, "7")
	if err != nil || string(body) != `{"week":{},"matchup":{}}` {
		t.Fatalf("score: %q %v", body, err)
	}
	if _, err := c.ScoreCard(ctx, "6"); !errors.Is(err, ErrNoCard) {
		t.Fatalf("404: %v", err)
	}
	for _, id := range []string{"8", "9"} {
		if _, err := c.ScoreCard(ctx, id); err == nil || errors.Is(err, ErrNoCard) {
			t.Fatalf("score %s: %v", id, err)
		}
	}
	if _, err := c.NewsCard(ctx, "a:b", "7201"); err != nil {
		t.Fatal(err)
	}
	if _, err := c.NewsCard(ctx, "a:b", "not-a-site-id"); err != nil {
		t.Fatal(err)
	}
	// A malformed id never reaches the site.
	if _, err := c.NewsCard(ctx, "../x", ""); !errors.Is(err, ErrNoCard) {
		t.Fatalf("bad id: %v", err)
	}
	want := []string{
		"/internal/chat/cards/score/7", "/internal/chat/cards/score/6", "/internal/chat/cards/score/8", "/internal/chat/cards/score/9",
		"/internal/chat/cards/news/a:b?viewer=7201", "/internal/chat/cards/news/a:b",
	}
	if len(got) != len(want) {
		t.Fatalf("calls %v", got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Errorf("call %d: %s, want %s", i, got[i], want[i])
		}
	}
}
