package notification

import (
	"context"
	"errors"
	"fmt"
	"log/slog"

	firebase "firebase.google.com/go/v4"
	"firebase.google.com/go/v4/messaging"
	"google.golang.org/api/option"
)

// multicaster is the one method firebaseSender needs from the Firebase
// messaging client. *messaging.Client satisfies it via its promoted
// SendEachForMulticast; a test fake satisfies it to exercise the
// batch-response branches without a live FCM project.
type multicaster interface {
	SendEachForMulticast(ctx context.Context, message *messaging.MulticastMessage) (*messaging.BatchResponse, error)
}

// firebaseSender is the production FCMSender backed by the Firebase Admin
// SDK. It is the concrete swap for LogOnlySender (fcm.go) and is wired in
// cmd/notification/main.go when FCM_ENABLED=true.
//
// One firebaseSender is built per process at boot and shared across all
// consumer handlers — messaging.Client is safe for concurrent use and
// holds a pooled HTTP/2 connection to FCM, so a single instance serves the
// whole handleConcurrency fan-out.
type firebaseSender struct {
	client multicaster
	log    *slog.Logger
}

// NewFirebaseSender builds a real FCMSender from a service-account JSON
// credentials file. projectID may be empty — the Admin SDK reads it from
// the credentials file — but passing it explicitly (FCM_PROJECT_ID) makes
// a mismatched key fail loud here at boot rather than on the first send.
//
// Returns an error on unreadable/invalid credentials so a half-configured
// push deploy fails at startup (CLAUDE.md §9: evidence > assertions), not
// silently on the first notification. credentialsPath is required.
func NewFirebaseSender(ctx context.Context, projectID, credentialsPath string, log *slog.Logger) (FCMSender, error) {
	if log == nil {
		log = slog.Default()
	}
	if credentialsPath == "" {
		return nil, errors.New("fcm: credentials path is required")
	}

	cfg := &firebase.Config{ProjectID: projectID}
	app, err := firebase.NewApp(ctx, cfg, option.WithCredentialsFile(credentialsPath))
	if err != nil {
		return nil, fmt.Errorf("fcm: init firebase app: %w", err)
	}
	client, err := app.Messaging(ctx)
	if err != nil {
		return nil, fmt.Errorf("fcm: init messaging client: %w", err)
	}

	log.Info("fcm firebase sender ready", "project_id", projectID)
	return &firebaseSender{client: client, log: log}, nil
}

// Send delivers p to every token in p.Tokens via a single multicast call.
//
// Semantics, in order of intent:
//   - Empty token list: nothing to do (decodePayload already rejects this,
//     but the guard keeps Send total).
//   - Partial failure: if some tokens succeed and others fail, Send returns
//     nil. Re-sending the whole batch on a partial failure would duplicate
//     the push to the tokens that already received it — worse than dropping
//     the few that failed (the periodic FCM flow tolerates an occasional
//     miss; a duplicate is user-visible). Failed tokens are logged.
//   - Unregistered / invalid tokens: logged at WARN with the token index so
//     a future Django token-pruning job has a signal. We can't prune here —
//     token storage is Django's (accounts_user.fcm_token, §Part B); the Go
//     side never writes that table.
//   - Total failure (every token failed, or the API call itself errored):
//     returns an error so the consumer leaves the entry in the PEL and the
//     sweeper retries (fcm.go handle()).
func (s *firebaseSender) Send(ctx context.Context, p FCMPayload) error {
	if len(p.Tokens) == 0 {
		return nil
	}

	msg := &messaging.MulticastMessage{
		Tokens: p.Tokens,
		Data:   p.Data,
		Notification: &messaging.Notification{
			Title: p.Title,
			Body:  p.Body,
		},
	}

	resp, err := s.client.SendEachForMulticast(ctx, msg)
	if err != nil {
		// Transport / auth / quota error — nothing was sent. Surface it so
		// the entry stays in the PEL for the sweeper.
		return fmt.Errorf("fcm: multicast send (event %s): %w", p.EventID, err)
	}

	if resp.FailureCount > 0 {
		s.reportFailures(p, resp)
	}

	// Every token failed — treat as a send failure so the sweeper retries.
	// A transient FCM hiccup that fails all tokens should not be acked away.
	if resp.SuccessCount == 0 {
		return fmt.Errorf("fcm: all %d tokens failed (event %s)", resp.FailureCount, p.EventID)
	}

	s.log.Debug("fcm sent",
		"event_id", p.EventID,
		"user_id", p.UserID,
		"success", resp.SuccessCount,
		"failure", resp.FailureCount,
	)
	return nil
}

// reportFailures logs each per-token failure. Unregistered/invalid tokens
// are flagged distinctly so a Django pruning job can act on them; other
// failures (transient, rate-limited) are informational.
func (s *firebaseSender) reportFailures(p FCMPayload, resp *messaging.BatchResponse) {
	for i, r := range resp.Responses {
		if r.Success || r.Error == nil {
			continue
		}
		stale := messaging.IsUnregistered(r.Error) || messaging.IsInvalidArgument(r.Error)
		s.log.Warn("fcm token failed",
			"event_id", p.EventID,
			"user_id", p.UserID,
			"token_index", i,
			"stale", stale,
			"err", r.Error,
		)
	}
}
