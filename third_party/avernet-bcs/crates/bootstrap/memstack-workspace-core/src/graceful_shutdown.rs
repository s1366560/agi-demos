//! Ordered, bounded shutdown for the autonomous Workspace producer/consumer chain.

use std::future::Future;
use std::time::Duration;

use anyhow::{Context, Result, bail};
use tokio::task::JoinHandle;
use tokio_util::sync::CancellationToken;

/// Counters from the final bounded consumer drain.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq)]
pub struct WorkspaceAutonomyDrainOutcome {
    pub passes: usize,
    pub claimed: usize,
}

/// Stop the scheduler first, stop background consumers second, then drain the
/// durable bootstrap -> progression -> task-dispatch chain to a fixed point.
///
/// All phases share one wall-clock timeout. Remaining tasks are aborted only
/// after that deadline or a task failure.
pub async fn stop_producer_then_drain_consumers<F, Fut>(
    producer_stop: CancellationToken,
    mut producer_task: JoinHandle<()>,
    consumer_stop: CancellationToken,
    mut consumer_tasks: Vec<JoinHandle<()>>,
    shutdown_timeout: Duration,
    max_drain_passes: usize,
    mut drain_once: F,
) -> Result<WorkspaceAutonomyDrainOutcome>
where
    F: FnMut() -> Fut,
    Fut: Future<Output = Result<usize>>,
{
    if shutdown_timeout.is_zero() || max_drain_passes == 0 {
        bail!("Workspace Autonomy shutdown controls are invalid");
    }
    let shutdown = async {
        producer_stop.cancel();
        (&mut producer_task)
            .await
            .context("Workspace Autonomy scheduler task failed during shutdown")?;

        consumer_stop.cancel();
        for task in &mut consumer_tasks {
            task.await
                .context("Workspace Autonomy consumer task failed during shutdown")?;
        }

        let mut outcome = WorkspaceAutonomyDrainOutcome::default();
        for _ in 0..max_drain_passes {
            let claimed = drain_once().await?;
            outcome.passes += 1;
            outcome.claimed = outcome.claimed.saturating_add(claimed);
            if claimed == 0 {
                return Ok(outcome);
            }
        }
        bail!("Workspace Autonomy consumer drain did not reach a fixed point");
    };

    match tokio::time::timeout(shutdown_timeout, shutdown).await {
        Ok(Ok(outcome)) => Ok(outcome),
        Ok(Err(error)) => {
            producer_task.abort();
            for task in consumer_tasks {
                task.abort();
            }
            Err(error)
        }
        Err(_) => {
            producer_task.abort();
            for task in consumer_tasks {
                task.abort();
            }
            bail!("Workspace Autonomy graceful shutdown exceeded its bounded timeout")
        }
    }
}

#[cfg(test)]
mod tests {
    use std::sync::Arc;

    use tokio::sync::Mutex;

    use super::*;

    #[tokio::test]
    async fn scheduler_stops_before_consumers_and_drain() -> Result<()> {
        let events = Arc::new(Mutex::new(Vec::new()));
        let producer_stop = CancellationToken::new();
        let producer_task = tokio::spawn({
            let events = Arc::clone(&events);
            let stop = producer_stop.clone();
            async move {
                stop.cancelled().await;
                tokio::time::sleep(Duration::from_millis(10)).await;
                events.lock().await.push("producer");
            }
        });
        let consumer_stop = CancellationToken::new();
        let consumer_task = tokio::spawn({
            let events = Arc::clone(&events);
            let stop = consumer_stop.clone();
            async move {
                stop.cancelled().await;
                events.lock().await.push("consumer");
            }
        });

        let outcome = stop_producer_then_drain_consumers(
            producer_stop,
            producer_task,
            consumer_stop,
            vec![consumer_task],
            Duration::from_secs(1),
            2,
            {
                let events = Arc::clone(&events);
                move || {
                    let events = Arc::clone(&events);
                    async move {
                        events.lock().await.push("drain");
                        Ok(0)
                    }
                }
            },
        )
        .await?;

        assert_eq!(outcome.passes, 1);
        assert_eq!(*events.lock().await, vec!["producer", "consumer", "drain"]);
        Ok(())
    }

    #[tokio::test]
    async fn shutdown_timeout_is_bounded_before_consumer_cancellation() -> Result<()> {
        let producer_stop = CancellationToken::new();
        let producer_task = tokio::spawn({
            let stop = producer_stop.clone();
            async move {
                stop.cancelled().await;
                std::future::pending::<()>().await;
            }
        });
        let consumer_stop = CancellationToken::new();
        let observed_consumer_stop = consumer_stop.clone();
        let consumer_task = tokio::spawn({
            let stop = consumer_stop.clone();
            async move { stop.cancelled().await }
        });

        let error = match stop_producer_then_drain_consumers(
            producer_stop,
            producer_task,
            consumer_stop,
            vec![consumer_task],
            Duration::from_millis(20),
            1,
            || async { Ok(0) },
        )
        .await
        {
            Ok(_) => bail!("hung producer must time out"),
            Err(error) => error,
        };

        assert!(error.to_string().contains("bounded timeout"));
        assert!(
            !observed_consumer_stop.is_cancelled(),
            "consumer cancellation must not precede producer termination"
        );
        Ok(())
    }
}
