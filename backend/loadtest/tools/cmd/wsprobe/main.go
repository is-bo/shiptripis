// Command wsprobe opens many idle, authenticated WebSocket connections to a
// ShipTrip realtime service and holds them, so the service's per-connection
// memory can be measured from outside (see ws_memory.py).
//
// It opens connections in steps and prints one machine-readable line per
// step: "step connected=<n> failed=<n>". It then waits for a line on stdin
// before opening the next step, which lets the sampler read the service's
// RSS at a known connection count.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"log"
	"net/http"
	"os"
	"sync"
	"sync/atomic"
	"time"

	"github.com/coder/websocket"
)

func main() {
	url := flag.String("url", "ws://127.0.0.1:8081/ws/chat", "WebSocket URL")
	tokensPath := flag.String("tokens", "", "JSON file with an \"access_tokens\" list")
	step := flag.Int("step", 250, "connections opened per step")
	steps := flag.Int("steps", 8, "number of steps")
	parallel := flag.Int("parallel", 32, "concurrent dials")
	flag.Parse()

	tokens, err := loadTokens(*tokensPath)
	if err != nil {
		log.Fatalf("wsprobe: %v", err)
	}

	var (
		mu     sync.Mutex
		conns  []*websocket.Conn
		failed atomic.Int64
	)
	stdin := bufio.NewScanner(os.Stdin)
	ctx := context.Background()
	next := 0

	for s := 0; s < *steps; s++ {
		sem := make(chan struct{}, *parallel)
		var wg sync.WaitGroup
		for i := 0; i < *step; i++ {
			token := tokens[next%len(tokens)]
			next++
			wg.Add(1)
			sem <- struct{}{}
			go func() {
				defer wg.Done()
				defer func() { <-sem }()
				dialCtx, cancel := context.WithTimeout(ctx, 10*time.Second)
				defer cancel()
				header := http.Header{}
				header.Set("Authorization", "Bearer "+token)
				conn, _, err := websocket.Dial(dialCtx, *url, &websocket.DialOptions{HTTPHeader: header})
				if err != nil {
					failed.Add(1)
					return
				}
				// Keep reading so server pings are answered and the
				// connection stays healthy for the whole measurement.
				go func() {
					for {
						if _, _, err := conn.Read(context.Background()); err != nil {
							return
						}
					}
				}()
				mu.Lock()
				conns = append(conns, conn)
				mu.Unlock()
			}()
		}
		wg.Wait()
		mu.Lock()
		connected := len(conns)
		mu.Unlock()
		fmt.Printf("step connected=%d failed=%d\n", connected, failed.Load())
		if !stdin.Scan() {
			break
		}
	}

	for _, conn := range conns {
		_ = conn.Close(websocket.StatusNormalClosure, "probe done")
	}
}

func loadTokens(path string) ([]string, error) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	var payload struct {
		AccessTokens []string `json:"access_tokens"`
	}
	if err := json.Unmarshal(raw, &payload); err != nil {
		return nil, err
	}
	if len(payload.AccessTokens) == 0 {
		return nil, fmt.Errorf("%s has no access_tokens", path)
	}
	return payload.AccessTokens, nil
}
