package email

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"shiptrip/pkg/redisbus"
)

const (
	testSenderNetToken = "test-only-sender-token-0123456789"
	testRecipient      = "private.person@example.com"
	testSubject        = "Your code 483921"
	testBody           = "Body with 483921"
)

// senderNetAPI is an httptest stand-in for Sender's endpoint. It records the
// last request and answers with the configured status and body.
type senderNetAPI struct {
	status int
	answer string
	delay  time.Duration
	hits   atomic.Int32

	mu           sync.Mutex
	method, path string
	header       http.Header
	body         []byte
	query        string
}

func (a *senderNetAPI) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	a.hits.Add(1)
	body, _ := io.ReadAll(r.Body)
	a.mu.Lock()
	a.method, a.path, a.header, a.query, a.body = r.Method, r.URL.Path, r.Header.Clone(), r.URL.RawQuery, body
	a.mu.Unlock()
	if a.delay > 0 {
		select {
		case <-time.After(a.delay):
		case <-r.Context().Done():
			return
		}
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(a.status)
	_, _ = io.WriteString(w, a.answer)
}

// lastBody returns the most recent request body.
func (a *senderNetAPI) lastBody() []byte {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.body
}

func newSenderNetTest(t *testing.T, api *senderNetAPI, cfg SenderNetConfig) EmailSender {
	t.Helper()
	server := httptest.NewServer(api)
	t.Cleanup(server.Close)
	cfg.Endpoint = server.URL + "/v2/message/send"
	if cfg.Token == "" {
		cfg.Token = testSenderNetToken
	}
	if cfg.FromAddr == "" {
		cfg.FromAddr = "contact@wassla.eu"
	}
	if cfg.FromName == "" {
		cfg.FromName = "Wassla"
	}
	sender, err := NewSenderNetSender(cfg, discardLog())
	if err != nil {
		t.Fatalf("NewSenderNetSender: %v", err)
	}
	return sender
}

func testPayload() EmailPayload {
	return EmailPayload{EventID: "evt-1", To: testRecipient, Subject: testSubject, Body: testBody, HTML: "<p>" + testBody + "</p>", Kind: "kyc_status"}
}

const accepted = `{"success": true, "message": "Email sent", "emailId": "abc"}`

func TestSenderNetSendsTheDocumentedRequest(t *testing.T) {
	api := &senderNetAPI{status: http.StatusOK, answer: accepted}
	sender := newSenderNetTest(t, api, SenderNetConfig{ReplyTo: "contact@wassla.eu"})
	if err := sender.Send(context.Background(), testPayload()); err != nil {
		t.Fatalf("accepted send returned %v", err)
	}
	api.mu.Lock()
	defer api.mu.Unlock()
	if api.method != http.MethodPost || api.path != "/v2/message/send" || api.query != "" {
		t.Fatalf("request line = %s %s?%s", api.method, api.path, api.query)
	}
	if got := api.header.Get("Authorization"); got != "Bearer "+testSenderNetToken {
		t.Fatalf("Authorization = %q", got)
	}
	if api.header.Get("Accept") != "application/json" || api.header.Get("Content-Type") != "application/json" {
		t.Fatalf("content negotiation headers = %v", api.header)
	}
	var body map[string]any
	if err := json.Unmarshal(api.body, &body); err != nil {
		t.Fatal(err)
	}
	want := map[string]any{
		"from":    map[string]any{"email": "contact@wassla.eu", "name": "Wassla"},
		"to":      map[string]any{"email": testRecipient},
		"subject": testSubject,
		"text":    testBody,
		"html":    "<p>" + testBody + "</p>",
	}
	gotJSON, _ := json.Marshal(body)
	wantJSON, _ := json.Marshal(want)
	if !bytes.Equal(gotJSON, wantJSON) {
		t.Fatalf("body = %s, want %s (no headers when Reply-To equals From)", gotJSON, wantJSON)
	}
	if bytes.Contains(api.body, []byte(testSenderNetToken)) {
		t.Fatal("the token travelled in the body")
	}
}

func TestSenderNetSendsReplyToOnlyWhenItDiffersFromFrom(t *testing.T) {
	for _, tc := range []struct {
		replyTo string
		want    string
	}{
		{"", ""},
		{"CONTACT@wassla.eu", ""},
		{"help@wassla.eu", "help@wassla.eu"},
	} {
		api := &senderNetAPI{status: http.StatusOK, answer: accepted}
		sender := newSenderNetTest(t, api, SenderNetConfig{ReplyTo: tc.replyTo})
		if err := sender.Send(context.Background(), testPayload()); err != nil {
			t.Fatal(err)
		}
		var body struct {
			Headers map[string]string `json:"headers"`
		}
		_ = json.Unmarshal(api.lastBody(), &body)
		if body.Headers["Reply-To"] != tc.want || (tc.want == "" && body.Headers != nil) {
			t.Fatalf("reply-to %q: headers = %v", tc.replyTo, body.Headers)
		}
	}
}

func TestSenderNetPlainTextOnlyOmitsHTML(t *testing.T) {
	api := &senderNetAPI{status: http.StatusOK, answer: accepted}
	sender := newSenderNetTest(t, api, SenderNetConfig{})
	p := testPayload()
	p.HTML = ""
	if err := sender.Send(context.Background(), p); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(api.lastBody(), []byte(`"html"`)) {
		t.Fatalf("plain-text payload sent an html part: %s", api.lastBody())
	}
}

func TestSenderNetClassifiesEveryAnswer(t *testing.T) {
	for _, tc := range []struct {
		name      string
		status    int
		answer    string
		wantErr   bool
		permanent bool
	}{
		{"200 success", 200, accepted, false, false},
		{"201 success", 201, accepted, false, false},
		{"200 without success", 200, `{"success": false}`, true, false},
		{"200 success as a string", 200, `{"success": "true"}`, true, false},
		{"200 not JSON", 200, `Email sent`, true, false},
		{"204 empty", 204, ``, true, false},
		{"302 redirect", 302, ``, true, false},
		{"400 bad request", 400, `{"message": "bad"}`, true, true},
		{"401 bad token", 401, `{"message": "Unauthenticated."}`, true, false},
		{"403 forbidden", 403, ``, true, false},
		{"404 not found", 404, ``, true, false},
		{"408 request timeout", 408, ``, true, false},
		{"422 invalid", 422, `{"errors": {"to.email": ["` + testRecipient + ` is invalid"]}}`, true, true},
		{"429 too many", 429, ``, true, false},
		{"500 server", 500, ``, true, false},
		{"503 unavailable", 503, ``, true, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			api := &senderNetAPI{status: tc.status, answer: tc.answer}
			err := newSenderNetTest(t, api, SenderNetConfig{}).Send(context.Background(), testPayload())
			if (err != nil) != tc.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tc.wantErr)
			}
			if err == nil {
				return
			}
			permanent, ok := AsPermanent(err)
			if ok != tc.permanent {
				t.Fatalf("permanent = %v, want %v (%v)", ok, tc.permanent, err)
			}
			if ok && permanent.Code != tc.status {
				t.Fatalf("PermanentError.Code = %d, want %d", permanent.Code, tc.status)
			}
			var failure *SenderNetFailure
			if !errors.As(err, &failure) || failure.Status != tc.status {
				t.Fatalf("failure = %#v, want status %d", failure, tc.status)
			}
			assertSenderNetErrorIsLogSafe(t, err)
		})
	}
}

func TestSenderNetDoesNotFollowRedirectsWithTheToken(t *testing.T) {
	target := &senderNetAPI{status: http.StatusOK, answer: accepted}
	elsewhere := httptest.NewServer(target)
	defer elsewhere.Close()
	redirect := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Redirect(w, r, elsewhere.URL, http.StatusTemporaryRedirect)
	})
	server := httptest.NewServer(redirect)
	defer server.Close()
	sender, err := NewSenderNetSender(SenderNetConfig{Endpoint: server.URL, Token: testSenderNetToken, FromAddr: "contact@wassla.eu"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	err = sender.Send(context.Background(), testPayload())
	if err == nil || target.hits.Load() != 0 {
		t.Fatalf("redirect followed: err %v, hits %d", err, target.hits.Load())
	}
	if _, permanent := AsPermanent(err); permanent {
		t.Fatal("a redirect is configuration trouble, not a permanent refusal")
	}
}

func TestSenderNetTimeoutIsBoundedAndRetryable(t *testing.T) {
	api := &senderNetAPI{status: http.StatusOK, answer: accepted, delay: 2 * time.Second}
	sender := newSenderNetTest(t, api, SenderNetConfig{Timeout: 100 * time.Millisecond})
	start := time.Now()
	err := sender.Send(context.Background(), testPayload())
	if err == nil {
		t.Fatal("stalled API did not time out")
	}
	if time.Since(start) > time.Second {
		t.Fatal("send exceeded the configured timeout")
	}
	var failure *SenderNetFailure
	if _, permanent := AsPermanent(err); permanent || !errors.As(err, &failure) || failure.Class != "timeout" {
		t.Fatalf("timeout classified as %v", err)
	}
	assertSenderNetErrorIsLogSafe(t, err)
}

func TestSenderNetConnectionFailureAndCancellationAreRetryable(t *testing.T) {
	server := httptest.NewServer(http.NotFoundHandler())
	endpoint := server.URL
	server.Close()
	sender, err := NewSenderNetSender(SenderNetConfig{Endpoint: endpoint, Token: testSenderNetToken, FromAddr: "contact@wassla.eu"}, discardLog())
	if err != nil {
		t.Fatal(err)
	}
	err = sender.Send(context.Background(), testPayload())
	var failure *SenderNetFailure
	if _, permanent := AsPermanent(err); err == nil || permanent || !errors.As(err, &failure) || failure.Class != "transport" {
		t.Fatalf("connection refused classified as %v", err)
	}
	assertSenderNetErrorIsLogSafe(t, err)

	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	api := &senderNetAPI{status: http.StatusOK, answer: accepted}
	err = newSenderNetTest(t, api, SenderNetConfig{}).Send(ctx, testPayload())
	if _, permanent := AsPermanent(err); err == nil || permanent || !errors.As(err, &failure) || failure.Class != "canceled" {
		t.Fatalf("cancellation classified as %v", err)
	}
}

func TestSenderNetRefusesAnUnbuildableMessageBeforeTheNetwork(t *testing.T) {
	for _, p := range []EmailPayload{
		{EventID: "e", To: "not an <address", Subject: "s", Body: "b"},
		{EventID: "e", To: testRecipient, Subject: "s\r\nBcc: other@example.com", Body: "b"},
	} {
		api := &senderNetAPI{status: http.StatusOK, answer: accepted}
		err := newSenderNetTest(t, api, SenderNetConfig{}).Send(context.Background(), p)
		if _, permanent := AsPermanent(err); !permanent || api.hits.Load() != 0 {
			t.Fatalf("payload %q: err %v, hits %d", p.To, err, api.hits.Load())
		}
		if strings.Contains(err.Error(), "not an <address") || strings.Contains(err.Error(), "Bcc") {
			t.Fatalf("error text quotes the payload: %v", err)
		}
	}
}

func TestNewSenderNetSenderRequiresItsConfiguration(t *testing.T) {
	for _, cfg := range []SenderNetConfig{
		{Endpoint: SenderNetEndpoint, FromAddr: "contact@wassla.eu"},
		{Endpoint: SenderNetEndpoint, Token: testSenderNetToken},
		{Endpoint: "not a url", Token: testSenderNetToken, FromAddr: "contact@wassla.eu"},
		{Endpoint: "ftp://api.sender.net/v2/message/send", Token: testSenderNetToken, FromAddr: "contact@wassla.eu"},
	} {
		if _, err := NewSenderNetSender(cfg, discardLog()); err == nil {
			t.Fatalf("incomplete configuration accepted: endpoint %q", cfg.Endpoint)
		} else if strings.Contains(err.Error(), testSenderNetToken) {
			t.Fatal("constructor error names the token")
		}
	}
	if SenderNetEndpoint != "https://api.sender.net/v2/message/send" {
		t.Fatal("production endpoint changed")
	}
}

// The consumer logs a failed send through SendFailureLogAttrs only. With an
// answer that echoes the recipient, nothing private may reach the log.
func TestSenderNetFailureLogsNeverNameTheRecipientSubjectBodyOrToken(t *testing.T) {
	for _, status := range []int{422, 503} {
		var buf bytes.Buffer
		log := slog.New(slog.NewTextHandler(&buf, &slog.HandlerOptions{Level: slog.LevelDebug}))
		api := &senderNetAPI{status: status, answer: `{"message": "` + testRecipient + ` ` + testSubject + `"}`}
		server := httptest.NewServer(api)
		sender, err := NewSenderNetSender(SenderNetConfig{Endpoint: server.URL, Token: testSenderNetToken, FromAddr: "contact@wassla.eu"}, log)
		if err != nil {
			t.Fatal(err)
		}
		c := NewConsumer(nil, ConsumerConfig{Sender: sender}, log)
		c.rdb = &fakeStream{}
		raw, _ := json.Marshal(testPayload())
		c.handle(context.Background(), redisbus.StreamMessage{
			ID: sid(1), Values: map[string]any{"event_id": "evt-1", "payload": string(raw)},
		})
		server.Close()

		out := buf.String()
		for _, private := range []string{testRecipient, "483921", testSenderNetToken} {
			if strings.Contains(out, private) {
				t.Fatalf("status %d: log output carries %q:\n%s", status, private, out)
			}
		}
		if !strings.Contains(out, "http_status=") || !strings.Contains(out, "provider=sender_net") {
			t.Fatalf("status %d: log output lacks the status and provider:\n%s", status, out)
		}
	}
}

func assertSenderNetErrorIsLogSafe(t *testing.T, err error) {
	t.Helper()
	text := err.Error()
	attrs, _ := json.Marshal(SendFailureLogAttrs(err))
	for _, private := range []string{testRecipient, testSubject, testBody, "483921", testSenderNetToken} {
		if strings.Contains(text, private) || strings.Contains(string(attrs), private) {
			t.Fatalf("failure carries %q: %s %s", private, text, attrs)
		}
	}
}
