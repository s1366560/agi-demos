//! Bind one exact native seat; a helper without an explicit seat cannot own multiple seats.
use crate::backend::{NativeError, Result};
use std::collections::BTreeMap;
use wayland_client::{
    protocol::{wl_registry, wl_seat},
    Connection, Dispatch, QueueHandle,
};

#[derive(Default)]
struct Seats(BTreeMap<u32, (wl_seat::WlSeat, Option<String>)>);
impl Dispatch<wl_registry::WlRegistry, ()> for Seats {
    fn event(
        state: &mut Self,
        registry: &wl_registry::WlRegistry,
        event: wl_registry::Event,
        _: &(),
        _: &Connection,
        queue: &QueueHandle<Self>,
    ) {
        match event {
            wl_registry::Event::Global {
                name,
                interface,
                version,
            } if interface == "wl_seat" && version >= 2 => {
                let seat = registry.bind::<wl_seat::WlSeat, _, _>(name, 2, queue, name);
                state.0.insert(name, (seat, None));
            }
            wl_registry::Event::GlobalRemove { name } => {
                state.0.remove(&name);
            }
            _ => {}
        }
    }
}
impl Dispatch<wl_seat::WlSeat, u32> for Seats {
    fn event(
        state: &mut Self,
        _: &wl_seat::WlSeat,
        event: wl_seat::Event,
        id: &u32,
        _: &Connection,
        _: &QueueHandle<Self>,
    ) {
        if let wl_seat::Event::Name { name } = event {
            if let Some((_, value)) = state.0.get_mut(id) {
                *value = Some(name);
            }
        }
    }
}
pub fn exact_seat() -> Result<String> {
    let unavailable = || {
        NativeError::new(
            "capability_unsupported",
            "Wayland clipboard requires exactly one named native seat",
        )
    };
    let connection = Connection::connect_to_env().map_err(|_| unavailable())?;
    let mut queue = connection.new_event_queue::<Seats>();
    let _registry = connection.display().get_registry(&queue.handle(), ());
    let mut seats = Seats::default();
    queue.roundtrip(&mut seats).map_err(|_| unavailable())?;
    queue.roundtrip(&mut seats).map_err(|_| unavailable())?;
    if seats.0.len() != 1 {
        return Err(unavailable());
    }
    seats
        .0
        .into_values()
        .next()
        .and_then(|(_, name)| name)
        .filter(|name| !name.is_empty())
        .ok_or_else(unavailable)
}
