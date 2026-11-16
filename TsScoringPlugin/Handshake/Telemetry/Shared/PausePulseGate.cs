using System;
using System.Diagnostics;
using System.Threading;

namespace TSScoringPlugin.Pulse
{
    /// <summary>
    /// Pause read-only pulse gate (S05 fix stage, Owner decisions DQ-0 .. DQ-3). One small, BVE-free state machine shared by the four pulse senders
    /// (Current Telemetry Class1, Current Bridge, Legacy Bridge, Legacy Telemetry extension). A pulse is a System.Threading.Timer on a pool thread that POSTS
    /// a callback to the host UI thread while BVE is paused and no Tick runs. The host UI thread can stall (scenario load, modal dialogs), so unbounded
    /// Posts queue up and later run back to back, with no knowledge of the scenario generation they were requested in. This gate owns the rules:
    ///
    ///   INV-P1  at most ONE pulse request is pending (the others are coalesced; nothing is queued while one is waiting).
    ///   INV-P2  a request carries the scenario epoch it was made in; a callback that runs in another epoch is discarded (the BVE body is not entered).
    ///   INV-P3  from ScenarioOpened / ScenarioClosed (teardown) until read-ready the body is not entered, and nothing is posted.
    ///   INV-P4' ScenarioCreated alone is not a read permission: the body may run only when the epoch has been stable for SettleMs after ScenarioCreated.
    ///           Any generation event during the settle window restarts it (the deadline is moved, never accumulated).
    ///   INV-P5  after Dispose begins nothing is requested and no queued callback enters the body.
    ///   INV-P6  a formal Tick that came within GapMs suppresses the pulse (at request time and again at callback time).
    ///   Ownership: TryEnter hands out the single running slot, Complete releases it (the caller runs Complete in a finally).
    ///
    /// The gate decides ONLY whether the body may run. The read-only body, the component specific ready conditions, the period and the output contract stay
    /// with the component. All members are thread safe (timer thread: TryRequest / CancelRequest; UI thread: the rest).
    /// </summary>
    internal sealed class PausePulseGate
    {
        internal const long DefaultGapMs = 150;
        internal const long DefaultSettleMs = 500;
        /// <summary>A pending request that was never consumed for this long is treated as lost (the host dropped the Post) and may be replaced.</summary>
        internal const long PendingExpireMs = 10000;

        private const long NotReady = long.MaxValue;

        private readonly Func<long> nowMs;
        private readonly long gapMs;
        private readonly long settleMs;

        private int pending;
        private long pendingSinceMs;
        private int running;
        private int epoch;
        private long readyAtMs = NotReady;
        private long lastTickMs = long.MinValue / 2;
        private int disposed;

        private long requested;
        private long coalesced;
        private long expired;
        private long entered;
        private long discardedStale;
        private long discardedNotReady;
        private long discardedTick;
        private long discardedDisposed;
        private long discardedReentry;

        private static readonly Stopwatch Clock = Stopwatch.StartNew();

        internal PausePulseGate()
            : this(null, DefaultGapMs, DefaultSettleMs)
        {
        }

        internal PausePulseGate(Func<long> nowMs, long gapMs, long settleMs)
        {
            this.nowMs = nowMs ?? DefaultNowMs;
            this.gapMs = gapMs;
            this.settleMs = settleMs;
        }

        private static long DefaultNowMs()
        {
            return Clock.ElapsedMilliseconds;
        }

        /// <summary>Timer thread. True = the caller may Post exactly one callback carrying requestEpoch; false = post nothing.</summary>
        internal bool TryRequest(out int requestEpoch)
        {
            requestEpoch = Volatile.Read(ref epoch);      // read BEFORE the readiness check: an event in between can only make the request stale, never fresh
            if (Volatile.Read(ref disposed) != 0)
            {
                return false;
            }

            long now = nowMs();
            if (now - Interlocked.Read(ref lastTickMs) <= gapMs)
            {
                return false;
            }

            if (now < Interlocked.Read(ref readyAtMs))
            {
                return false;      // torn down, created but not settled: nothing is posted (nothing piles up behind a stalled UI)
            }

            if (Interlocked.CompareExchange(ref pending, 1, 0) != 0)
            {
                if (now - Interlocked.Read(ref pendingSinceMs) > PendingExpireMs)
                {
                    Interlocked.Increment(ref expired);
                    Interlocked.Exchange(ref pendingSinceMs, now);
                    Interlocked.Increment(ref requested);
                    return true;
                }

                Interlocked.Increment(ref coalesced);
                return false;
            }

            Interlocked.Exchange(ref pendingSinceMs, now);
            Interlocked.Increment(ref requested);
            return true;
        }

        /// <summary>Timer thread: the Post itself failed, so the request is not outstanding.</summary>
        internal void CancelRequest()
        {
            Interlocked.Exchange(ref pending, 0);
        }

        /// <summary>UI thread, the first statement of the posted callback. True = the read-only body may run; the caller MUST call Complete in a finally.</summary>
        internal bool TryEnter(int requestEpoch)
        {
            Interlocked.Exchange(ref pending, 0);      // the request is consumed whatever the verdict is

            if (Volatile.Read(ref disposed) != 0)
            {
                Interlocked.Increment(ref discardedDisposed);
                return false;
            }

            if (requestEpoch != Volatile.Read(ref epoch))
            {
                Interlocked.Increment(ref discardedStale);
                return false;
            }

            long now = nowMs();
            if (now - Interlocked.Read(ref lastTickMs) <= gapMs)
            {
                Interlocked.Increment(ref discardedTick);
                return false;
            }

            if (now < Interlocked.Read(ref readyAtMs))
            {
                Interlocked.Increment(ref discardedNotReady);
                return false;
            }

            if (Interlocked.CompareExchange(ref running, 1, 0) != 0)
            {
                Interlocked.Increment(ref discardedReentry);
                return false;
            }

            Interlocked.Increment(ref entered);
            return true;
        }

        /// <summary>UI thread: the callback ended (also after an exception). Releases the running slot.</summary>
        internal void Complete()
        {
            Volatile.Write(ref running, 0);
        }

        /// <summary>UI thread, at the start of every formal Tick.</summary>
        internal void NoteTick()
        {
            Interlocked.Exchange(ref lastTickMs, nowMs());
        }

        /// <summary>ScenarioOpened / ScenarioClosed: teardown or reload started. No read until the next ScenarioCreated has settled.</summary>
        internal void OnScenarioOpenedOrClosed()
        {
            Interlocked.Exchange(ref readyAtMs, NotReady);      // first: a request that sees the new epoch must also see "not ready"
            Interlocked.Increment(ref epoch);
        }

        /// <summary>ScenarioCreated (also the seed when the host already reports a created scenario at construction): the settle window starts / restarts now.</summary>
        internal void OnScenarioCreated()
        {
            Interlocked.Exchange(ref readyAtMs, nowMs() + settleMs);
            Interlocked.Increment(ref epoch);
        }

        /// <summary>Dispose has begun: nothing is requested and no queued callback enters the body.</summary>
        internal void Dispose()
        {
            Volatile.Write(ref disposed, 1);
        }

        internal bool IsReadReady
        {
            get { return Volatile.Read(ref disposed) == 0 && nowMs() >= Interlocked.Read(ref readyAtMs); }
        }

        internal int Epoch { get { return Volatile.Read(ref epoch); } }
        internal int Pending { get { return Volatile.Read(ref pending); } }
        internal bool IsRunning { get { return Volatile.Read(ref running) != 0; } }
        internal long Requested { get { return Interlocked.Read(ref requested); } }
        internal long Coalesced { get { return Interlocked.Read(ref coalesced); } }
        internal long Expired { get { return Interlocked.Read(ref expired); } }
        internal long Entered { get { return Interlocked.Read(ref entered); } }
        internal long DiscardedStale { get { return Interlocked.Read(ref discardedStale); } }
        internal long DiscardedNotReady { get { return Interlocked.Read(ref discardedNotReady); } }
        internal long DiscardedTick { get { return Interlocked.Read(ref discardedTick); } }
        internal long DiscardedDisposed { get { return Interlocked.Read(ref discardedDisposed); } }
        internal long DiscardedReentry { get { return Interlocked.Read(ref discardedReentry); } }

        /// <summary>One diagnostics fragment (key=value pairs, no spaces inside values).</summary>
        internal string StatsText()
        {
            return "gateReq=" + Requested + " gateCoal=" + Coalesced + " gateExp=" + Expired + " gateEnter=" + Entered
                + " gateStale=" + DiscardedStale + " gateNotReady=" + DiscardedNotReady + " gateTick=" + DiscardedTick
                + " gateDisp=" + DiscardedDisposed + " gateReent=" + DiscardedReentry;
        }
    }
}
