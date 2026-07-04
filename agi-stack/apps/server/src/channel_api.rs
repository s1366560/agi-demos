//! P5 channel configuration read/status foundation.
//!
//! This module intentionally owns only the database-backed channel config and
//! observability surfaces that can be strangled without taking over Python's
//! live channel runtime. Plugin runtime management, connection lifecycle,
//! webhook ingress, outbox delivery and channel message routing stay
//! Python-owned until their runtime semantics move as a full vertical slice.

mod error;
mod queries;
mod routes;
mod service;
mod views;

#[cfg(test)]
mod tests;

pub(crate) use routes::router;
pub(crate) use service::{DevChannelService, PgChannelService, SharedChannels};

#[cfg(test)]
pub(crate) use queries::{ChannelConfigQuery, ChannelOutboxQuery, ChannelPageQueryParams};
#[cfg(test)]
pub(crate) use service::ChannelService;
#[cfg(test)]
pub(crate) use views::{
    ChannelConfigListView, ChannelConfigView, ChannelObservabilitySummaryView,
    ChannelOutboxListView, ChannelSessionBindingListView, ChannelStatusView,
};
