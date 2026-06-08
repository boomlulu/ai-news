// Package sse implements a tiny in-process, GLOBAL broadcast pub/sub bus used
// to push task-state changes to every connected SSE client. Unlike a keyed
// topic, every Publish reaches every live subscriber.
//
// Design notes:
//   - Each subscriber gets a buffered channel (~16). If a consumer can't keep
//     up, Publish drops the message rather than block — producers (the task
//     store) must NEVER stall on a slow browser.
//   - Subscribe returns an unsubscribe closure that removes the channel and
//     closes it. The closure is idempotent. Always defer-call it.
package sse

import "sync"

const subBuffer = 16

// Broker is a global broadcast bus. The zero value is NOT ready; call
// NewBroker. Safe for concurrent Subscribe/Publish/unsubscribe.
type Broker struct {
	mu   sync.RWMutex
	subs map[*subscriber]struct{}
}

type subscriber struct {
	ch chan []byte
}

// NewBroker returns a ready-to-use Broker.
func NewBroker() *Broker {
	return &Broker{subs: make(map[*subscriber]struct{})}
}

// Subscribe registers a buffered channel and returns (recv-channel,
// unsubscribe-fn). The unsubscribe closure is idempotent and closes the
// channel.
func (b *Broker) Subscribe() (<-chan []byte, func()) {
	sub := &subscriber{ch: make(chan []byte, subBuffer)}

	b.mu.Lock()
	b.subs[sub] = struct{}{}
	b.mu.Unlock()

	var once sync.Once
	unsub := func() {
		once.Do(func() {
			b.mu.Lock()
			delete(b.subs, sub)
			b.mu.Unlock()
			close(sub.ch)
		})
	}
	return sub.ch, unsub
}

// Publish broadcasts b to every subscriber. Slow consumers (full channel) are
// dropped silently. Never blocks; safe to call from the task store hot path.
func (b *Broker) Publish(msg []byte) {
	b.mu.RLock()
	if len(b.subs) == 0 {
		b.mu.RUnlock()
		return
	}
	// Snapshot subscribers under RLock; send outside to keep the lock short.
	subs := make([]*subscriber, 0, len(b.subs))
	for s := range b.subs {
		subs = append(subs, s)
	}
	b.mu.RUnlock()

	for _, s := range subs {
		select {
		case s.ch <- msg:
		default:
			// Slow client: drop rather than block producers.
		}
	}
}
