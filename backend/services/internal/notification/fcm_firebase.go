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
	client           multicaster
	log              *slog.Logger
	isPermanentToken func(error) bool
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
	// Pin the credential type to a service account rather than using the
	// deprecated WithCredentialsFile, which accepts any credential-config
	// shape. FCM credentials are always a service-account JSON, so anything
	// else in FCM_CREDENTIALS_PATH is a misconfiguration (or a swapped-in
	// external-account config pointing at a URL we don't control) and should
	// fail here instead of being loaded.
	app, err := firebase.NewApp(ctx, cfg,
		option.WithAuthCredentialsFile(option.ServiceAccount, credentialsPath))
	if err != nil {
		return nil, fmt.Errorf("fcm: init firebase app: %w", err)
	}
	client, err := app.Messaging(ctx)
	if err != nil {
		return nil, fmt.Errorf("fcm: init messaging client: %w", err)
	}

	log.Info("fcm firebase sender ready", "project_id", projectID)
	return &firebaseSender{
		client: client,
		log:    log,
		isPermanentToken: func(err error) bool {
			return messaging.IsUnregistered(err) || messaging.IsInvalidArgument(err)
		},
	}, nil
}

// Send delivers p to every token in p.Tokens via a single multicast call.
//
// Semantics, in order of intent:
//   - Empty token list: nothing to do (decodePayload already rejects this,
//     but the guard keeps Send total).
//   - Partial transient failure: returns token indexes for the consumer to
//     enqueue as a smaller retry batch. Successful tokens are never included
//     in that retry, avoiding a deterministic duplicate.
//   - Unregistered / invalid tokens: returned as Django-owned PushDevice row
//     IDs so the consumer can publish cleanup feedback without exposing a
//     registration token.
//   - Total transient failure (or the API call itself errored): returns an
//     error so the consumer leaves the entry in the PEL for the sweeper.
//   - Total permanent failure: returns cleanup IDs without an error, so an
//     invalid token cannot poison the queue forever.
func (s *firebaseSender) Send(ctx context.Context, p FCMPayload) (SendResult, error) {
	if len(p.Tokens) == 0 {
		return SendResult{}, nil
	}

	msg := &messaging.MulticastMessage{
		Tokens: p.Tokens,
		Data:   p.Data,
		Notification: &messaging.Notification{
			Title: p.Title,
			Body:  p.Body,
		},
		Android: &messaging.AndroidConfig{
			Priority:    "normal",
			CollapseKey: p.CollapseKey,
			Notification: &messaging.AndroidNotification{
				ChannelID: p.AndroidChannelID,
			},
		},
	}

	resp, err := s.client.SendEachForMulticast(ctx, msg)
	if err != nil {
		// Transport / auth / quota error — nothing was sent. Surface it so
		// the entry stays in the PEL for the sweeper.
		return SendResult{}, fmt.Errorf("fcm: multicast send (event %s): %w", p.EventID, err)
	}

	result, transientFailures := s.classifyResults(p, resp)

	// Every token failed — treat as a send failure so the sweeper retries.
	// A transient FCM hiccup that fails all tokens should not be acked away.
	if resp.SuccessCount == 0 && transientFailures > 0 {
		return result, fmt.Errorf("fcm: all %d tokens failed transiently (event %s)", transientFailures, p.EventID)
	}

	s.log.Debug("fcm sent",
		"event_id", p.EventID,
		"user_id", p.UserID,
		"success", resp.SuccessCount,
		"failure", resp.FailureCount,
	)
	return result, nil
}

// classifyResults converts FCM's token-indexed response back into Django-owned
// device row IDs. Registration tokens never enter logs or the cleanup stream.
func (s *firebaseSender) classifyResults(p FCMPayload, resp *messaging.BatchResponse) (SendResult, int) {
	result := SendResult{}
	transientFailures := 0
	classifier := s.isPermanentToken
	if classifier == nil {
		classifier = func(err error) bool {
			return messaging.IsUnregistered(err) || messaging.IsInvalidArgument(err)
		}
	}
	for i, r := range resp.Responses {
		if i >= len(p.DeviceIDs) {
			break
		}
		if r.Success {
			result.SuccessfulDeviceIDs = append(result.SuccessfulDeviceIDs, p.DeviceIDs[i])
			result.SuccessfulTokenFingerprints = append(result.SuccessfulTokenFingerprints, p.TokenFingerprints[i])
			continue
		}
		permanent := r.Error != nil && classifier(r.Error)
		if permanent {
			result.InvalidDeviceIDs = append(result.InvalidDeviceIDs, p.DeviceIDs[i])
			result.InvalidTokenFingerprints = append(result.InvalidTokenFingerprints, p.TokenFingerprints[i])
		} else {
			transientFailures++
			result.RetryTokenIndexes = append(result.RetryTokenIndexes, i)
		}
		s.log.Warn("fcm token failed",
			"event_id", p.EventID,
			"user_id", p.UserID,
			"device_id", p.DeviceIDs[i],
			"permanent", permanent,
		)
	}
	return result, transientFailures
}
