use super::export;

#[no_mangle]
pub extern "C" fn invoke(length: u32) -> u32 {
    if !(2..=65_536).contains(&length) {
        return 0;
    }
    let mut input = Vec::with_capacity(length as usize);
    // The structured ABI always supplies an object. Rust cannot borrow address zero.
    input.push(b'{');
    // SAFETY: build.rs reserves page zero for the host's initialized request.
    let tail = unsafe {
        std::slice::from_raw_parts(std::ptr::without_provenance::<u8>(1), length as usize - 1)
    };
    input.extend_from_slice(tail);
    let Some(output) = export(&input) else {
        return 0;
    };
    if output.len() > 65_536 {
        return 0;
    }
    // SAFETY: page one is the ABI response buffer, disjoint from the guest-owned output.
    unsafe {
        std::ptr::copy_nonoverlapping(
            output.as_ptr(),
            std::ptr::without_provenance_mut::<u8>(65_536),
            output.len(),
        )
    };
    output.len() as u32
}
