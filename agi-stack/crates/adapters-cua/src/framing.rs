//! 4-byte little-endian length framing over the helper socket, mirroring the
//! observed reference transport (8 MiB cap included).

use agistack_core::{CoreError, CoreResult};
use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

/// Hard per-frame cap, matching the reference client's 8 MiB guard.
pub const MAX_FRAME_BYTES: u32 = 8_388_608;

pub fn encode_frame(payload: &[u8]) -> CoreResult<Vec<u8>> {
    let len =
        u32::try_from(payload.len()).map_err(|_| CoreError::Tool("cua_frame_too_large".into()))?;
    if len > MAX_FRAME_BYTES {
        return Err(CoreError::Tool(format!(
            "cua_frame_too_large: {len} > {MAX_FRAME_BYTES}"
        )));
    }
    let mut frame = Vec::with_capacity(4 + payload.len());
    frame.extend_from_slice(&len.to_le_bytes());
    frame.extend_from_slice(payload);
    Ok(frame)
}

pub async fn write_frame<W: AsyncWrite + Unpin>(sink: &mut W, payload: &[u8]) -> CoreResult<()> {
    let frame = encode_frame(payload)?;
    sink.write_all(&frame)
        .await
        .map_err(|e| CoreError::Tool(format!("cua_socket_write_failed: {e}")))?;
    sink.flush()
        .await
        .map_err(|e| CoreError::Tool(format!("cua_socket_write_failed: {e}")))?;
    Ok(())
}

pub async fn read_frame<R: AsyncRead + Unpin>(source: &mut R) -> CoreResult<Vec<u8>> {
    let mut header = [0u8; 4];
    source
        .read_exact(&mut header)
        .await
        .map_err(|e| CoreError::Tool(format!("cua_socket_closed: {e}")))?;
    let len = u32::from_le_bytes(header);
    if len > MAX_FRAME_BYTES {
        return Err(CoreError::Tool(format!(
            "cua_frame_too_large: {len} > {MAX_FRAME_BYTES}"
        )));
    }
    let mut body = vec![0u8; len as usize];
    source
        .read_exact(&mut body)
        .await
        .map_err(|e| CoreError::Tool(format!("cua_socket_closed: {e}")))?;
    Ok(body)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trips_payload() {
        let payload = br#"{"jsonrpc":"2.0","id":1}"#;
        let frame = encode_frame(payload).expect("encode");
        assert_eq!(&frame[..4], &(payload.len() as u32).to_le_bytes());
        assert_eq!(&frame[4..], payload);
    }

    #[test]
    fn rejects_oversized_frame() {
        assert!(encode_frame(&vec![0u8; (MAX_FRAME_BYTES + 1) as usize]).is_err());
    }

    #[tokio::test]
    async fn frames_survive_a_duplex_pipe() {
        let (mut client, mut server) = tokio::io::duplex(64);
        write_frame(&mut client, br#"{"a":1}"#)
            .await
            .expect("write");
        let received = read_frame(&mut server).await.expect("read");
        assert_eq!(received, br#"{"a":1}"#);

        write_frame(&mut server, br#"{"b":2}"#)
            .await
            .expect("write");
        let replied = read_frame(&mut client).await.expect("read");
        assert_eq!(replied, br#"{"b":2}"#);
    }
}
