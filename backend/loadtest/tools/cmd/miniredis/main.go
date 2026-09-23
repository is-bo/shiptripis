// Command miniredis serves an in-memory Redis stand-in for the local load
// harness on workstations that have no redis-server (Windows, no Docker).
//
// It is NOT a Redis performance proxy. It gives Django's RedisCache (DRF
// throttles), the after-commit publisher and the Go realtime services a real
// RESP endpoint so the request paths under test do the same round trips they
// do in production. Redis throughput numbers must come from real Redis.
package main

import (
	"flag"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/alicebob/miniredis/v2"
)

func main() {
	addr := flag.String("addr", "127.0.0.1:6379", "listen address")
	flag.Parse()

	server := miniredis.NewMiniRedis()
	if err := server.StartAddr(*addr); err != nil {
		log.Fatalf("miniredis: %v", err)
	}
	log.Printf("miniredis listening on %s", server.Addr())

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop
	server.Close()
}
