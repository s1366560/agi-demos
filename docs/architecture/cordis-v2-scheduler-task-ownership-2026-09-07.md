# Scheduler task ownership during plugin disposal

The final real FastAPI shutdown exposed an AnyIO task-ownership violation. The
scheduler service manually entered `AsyncScheduler` in the startup task and exited
it from a generation-owned disposer task. APScheduler owns AnyIO task groups and
cancel scopes, which must exit in the task that entered them. The real log ended
with `CancelledError` and `Application shutdown failed`, even though the process
and the private supervisor exited. That run is not clean lifecycle acceptance.

`SchedulerOwner` now holds the complete scheduler `async with` lifetime in one
owned task. Startup waits for readiness; disposal signals stop and observes the
same task's cleanup result. The service serializes singleton transitions and
revokes access before draining. A cancelled caller cannot cancel the resource
owner, and completed failed owners are detached so a subsequent explicit start
can succeed. Errors continue to propagate. No broad cancellation suppression or
change to generation reference counting was introduced.

Five new tests use the real APScheduler with its in-memory data store and local
event broker. They cover disposal from an `OwnedLifecycleTaskV2`, startup failure,
cancelled startup, cancelled shutdown and cleanup failure followed by another
successful start. The original implementation produced the actual AnyIO
different-task cancel-scope error. These tests and the existing scheduler/Cron
regressions passed: 17 passed, 21 warnings, 17.93 seconds. Ruff and Pyright passed
with zero errors; Pyright reported zero warnings. No original database was used.

Direct source review confirms that the production Cron plugin passes
`start_scheduler` and `stop_scheduler` as generation acquisition/disposal callbacks. Only scheduler lifecycle ownership changes; job registration and
generation overlap semantics retain their existing regression coverage.

Logs are stored under `/tmp/cordis-scheduler-owner-{red,green,ruff,pyright}.log`
and copied to the private final gate archive. The failed real shutdown is preserved
under `/var/tmp/cordis-final-retirement-ufhyv7hu/first-shutdown-failed-*`.
The final acceptance document records the subsequent real startup/shutdown rerun.
