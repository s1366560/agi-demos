//! P5 channel configuration read/status foundation.
//!
//! This module intentionally owns only the database-backed channel config and
//! observability surfaces plus narrow runtime foundations that can be strangled
//! without taking over Python's full live channel runtime. Feishu webhook
//! delivery is present as a default-off server-only adapter foundation, Feishu
//! webhook ingress fans newly persisted normalized events into the shared
//! EventStream, and connection lifecycle endpoints currently update shared local
//! status markers only. Plugin runtime management, provider credential rotation,
//! live provider sessions, and full session/workspace message routing stay
//! Python-owned until their runtime semantics move as a full vertical slice.

mod delivery_runtime;
mod error;
mod queries;
mod routes;
mod service;
mod views;
mod webhook_verifier;

#[cfg(test)]
mod tests;

pub(crate) use delivery_runtime::{
    ChannelOutboxDeliveryWorker, ChannelOutboxDeliveryWorkerConfig, FeishuWebhookDeliverer,
    SharedChannelOutboxDeliveryWorker,
};
pub(crate) use routes::{router, router_public};
pub(crate) use service::{DevChannelService, PgChannelService, SharedChannels};

#[cfg(test)]
pub(crate) use queries::{ChannelConfigQuery, ChannelOutboxQuery, ChannelPageQueryParams};
#[cfg(test)]
pub(crate) use service::ChannelService;
#[cfg(test)]
pub(crate) use views::{
    ChannelConfigListView, ChannelConfigView, ChannelObservabilitySummaryView,
    ChannelOutboxListView, ChannelSessionBindingListView, ChannelStatusView,
    ChannelWebhookChallengeView, ChannelWebhookIngressView,
};
