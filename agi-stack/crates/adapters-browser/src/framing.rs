//! Length-prefixed frame codec for the broker's stdio side.
//!
//! Frames are a 4-byte **little-endian** length prefix followed by that many
//! payload bytes. This is the framing the native-messaging broker uses on its
//! stdin/stdout pipe to the sidecar (the extension-facing WebSocket side is
//! handled by `tokio-tungstenite` in [`crate::ws_client`]). Clean EOF (zero
//! bytes of a new frame read) is `Ok(None)`; a truncated frame is an error.

use tokio::io::{AsyncRead, AsyncReadExt, AsyncWrite, AsyncWriteExt};

/// Default inbound frame cap: 8 MiB.
pub const DEFAULT_MAX_INBOUND: usize = 8 * 1024 * 1024;
/// Default outbound frame cap: 64 MiB (screenshots can be large).
pub const DEFAULT_MAX_OUTBOUND: usize = 64 * 1024 * 1024;

const LEN_PREFIX_BYTES: usize = 4;

fn len_exceeded(kind: &str, len: usize, max: usize) -> std::io::Error {
    std::io::Error::new(
        std::io::ErrorKind::InvalidData,
        format!("{kind} frame length {len} exceeds limit {max}"),
    )
}

/// Read one frame. Returns `Ok(None)` on clean EOF before a new frame starts;
/// `Err(UnexpectedEof)` when the stream ends mid-prefix or mid-payload, and
/// `Err(InvalidData)` when the declared length exceeds `max_len`.
pub async fn read_frame<R: AsyncRead + Unpin>(
    reader: &mut R,
    max_len: usize,
) -> std::io::Result<Option<Vec<u8>>> {
    // Read the first prefix byte separately so a clean EOF (nothing read) is
    // distinguishable from a torn prefix, regardless of its byte values.
    let mut prefix = [0u8; LEN_PREFIX_BYTES];
    let first = reader.read(&mut prefix[..1]).await?;
    if first == 0 {
        return Ok(None);
    }
    reader.read_exact(&mut prefix[first..]).await?;
    let len = u32::from_le_bytes(prefix) as usize;
    if len > max_len {
        return Err(len_exceeded("inbound", len, max_len));
    }
    let mut payload = vec![0u8; len];
    reader.read_exact(&mut payload).await?;
    Ok(Some(payload))
}

/// Write one frame, rejecting payloads larger than `max_len`.
pub async fn write_frame<W: AsyncWrite + Unpin>(
    writer: &mut W,
    payload: &[u8],
    max_len: usize,
) -> std::io::Result<()> {
    if payload.len() > max_len {
        return Err(len_exceeded("outbound", payload.len(), max_len));
    }
    writer
        .write_all(&(payload.len() as u32).to_le_bytes())
        .await?;
    writer.write_all(payload).await?;
    writer.flush().await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Cursor;
    use std::pin::Pin;
    use std::task::{Context, Poll};
    use tokio::io::ReadBuf;

    /// A reader that yields at most `chunk` bytes per poll, exercising the
    /// partial-read path in `read_exact`.
    struct ChunkedReader {
        inner: Cursor<Vec<u8>>,
        chunk: usize,
    }

    impl AsyncRead for ChunkedReader {
        fn poll_read(
            mut self: Pin<&mut Self>,
            cx: &mut Context<'_>,
            buf: &mut ReadBuf<'_>,
        ) -> Poll<std::io::Result<()>> {
            let limit = buf.remaining().min(self.chunk);
            let mut tmp = vec![0u8; limit];
            let mut tmp_buf = ReadBuf::new(&mut tmp);
            match Pin::new(&mut self.inner).poll_read(cx, &mut tmp_buf) {
                Poll::Ready(Ok(())) => {
                    let n = tmp_buf.filled().len();
                    buf.put_slice(&tmp_buf.filled()[..n]);
                    Poll::Ready(Ok(()))
                }
                other => other,
            }
        }
    }

    #[tokio::test]
    async fn round_trip_multiple_frames() {
        let mut wire: Vec<u8> = Vec::new();
        write_frame(&mut wire, b"hello", DEFAULT_MAX_OUTBOUND)
            .await
            .unwrap();
        write_frame(&mut wire, b"", DEFAULT_MAX_OUTBOUND)
            .await
            .unwrap();
        write_frame(&mut wire, &[0xAB; 1024], DEFAULT_MAX_OUTBOUND)
            .await
            .unwrap();

        let mut reader = Cursor::new(wire);
        assert_eq!(
            read_frame(&mut reader, DEFAULT_MAX_INBOUND).await.unwrap(),
            Some(b"hello".to_vec())
        );
        assert_eq!(
            read_frame(&mut reader, DEFAULT_MAX_INBOUND).await.unwrap(),
            Some(Vec::new())
        );
        assert_eq!(
            read_frame(&mut reader, DEFAULT_MAX_INBOUND)
                .await
                .unwrap()
                .map(|f| f.len()),
            Some(1024)
        );
        assert_eq!(
            read_frame(&mut reader, DEFAULT_MAX_INBOUND).await.unwrap(),
            None
        );
    }

    #[tokio::test]
    async fn boundary_length_is_accepted() {
        let payload = vec![7u8; 64];
        let mut wire: Vec<u8> = Vec::new();
        write_frame(&mut wire, &payload, 64).await.unwrap();
        let mut reader = Cursor::new(wire);
        assert_eq!(read_frame(&mut reader, 64).await.unwrap(), Some(payload));
    }

    #[tokio::test]
    async fn oversized_inbound_is_rejected() {
        let mut wire: Vec<u8> = Vec::new();
        wire.extend_from_slice(&(65u32).to_le_bytes());
        wire.extend_from_slice(&[0u8; 65]);
        let mut reader = Cursor::new(wire);
        let err = read_frame(&mut reader, 64).await.unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::InvalidData);
    }

    #[tokio::test]
    async fn oversized_outbound_is_rejected() {
        let mut wire: Vec<u8> = Vec::new();
        let err = write_frame(&mut wire, &[0u8; 65], 64).await.unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::InvalidData);
        assert!(wire.is_empty(), "rejected frame must not emit bytes");
    }

    #[tokio::test]
    async fn partial_reads_reassemble() {
        let mut wire: Vec<u8> = Vec::new();
        write_frame(&mut wire, b"fragmented payload", DEFAULT_MAX_OUTBOUND)
            .await
            .unwrap();
        let mut reader = ChunkedReader {
            inner: Cursor::new(wire),
            chunk: 3,
        };
        assert_eq!(
            read_frame(&mut reader, DEFAULT_MAX_INBOUND).await.unwrap(),
            Some(b"fragmented payload".to_vec())
        );
    }

    #[tokio::test]
    async fn torn_prefix_is_an_error_not_eof() {
        let mut reader = Cursor::new(vec![0x05, 0x00]); // half a length prefix
        let err = read_frame(&mut reader, DEFAULT_MAX_INBOUND)
            .await
            .unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::UnexpectedEof);
    }

    #[tokio::test]
    async fn torn_payload_is_an_error() {
        let mut wire: Vec<u8> = Vec::new();
        wire.extend_from_slice(&(10u32).to_le_bytes());
        wire.extend_from_slice(b"short");
        let mut reader = Cursor::new(wire);
        let err = read_frame(&mut reader, DEFAULT_MAX_INBOUND)
            .await
            .unwrap_err();
        assert_eq!(err.kind(), std::io::ErrorKind::UnexpectedEof);
    }
}
