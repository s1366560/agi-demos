//! Bounded RIFF/WAVE writer preserving the device's native sample-format header.
use crate::backend::{NativeError, Result};
use std::{
    fs::File,
    io::{Seek, SeekFrom, Write},
    path::Path,
};
pub struct Wave {
    file: File,
    data_size_offset: u64,
    bytes: u32,
}
impl Wave {
    pub fn create(path: &Path, format: &[u8]) -> Result<Self> {
        if !(16..=80).contains(&format.len()) {
            return Err(NativeError::new(
                "audio_format_unsupported",
                "invalid native WAV format",
            ));
        }
        let mut file = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(|_| {
                NativeError::new("artifact_unavailable", "cannot create recording file")
            })?;
        file.write_all(b"RIFF\0\0\0\0WAVEfmt ")
            .and_then(|_| file.write_all(&(format.len() as u32).to_le_bytes()))
            .and_then(|_| file.write_all(format))
            .and_then(|_| file.write_all(b"data\0\0\0\0"))
            .map_err(|_| NativeError::new("audio_failed", "cannot write recording header"))?;
        Ok(Self {
            file,
            data_size_offset: 24 + format.len() as u64,
            bytes: 0,
        })
    }
    pub fn append(&mut self, bytes: &[u8]) -> Result<()> {
        let length = u32::try_from(bytes.len())
            .map_err(|_| NativeError::new("audio_limit", "audio buffer exceeds WAV budget"))?;
        let next = self
            .bytes
            .checked_add(length)
            .filter(|bytes| u64::from(*bytes) + self.data_size_offset + 5 <= 64 * 1024 * 1024)
            .ok_or_else(|| NativeError::new("audio_limit", "recording exceeds RIFF budget"))?;
        self.file
            .write_all(bytes)
            .map_err(|_| NativeError::new("audio_failed", "cannot append recording samples"))?;
        self.bytes = next;
        Ok(())
    }
    pub fn finish(mut self) -> Result<u32> {
        let padding = self.bytes % 2;
        if padding != 0 {
            self.file
                .write_all(&[0])
                .map_err(|_| NativeError::new("audio_failed", "cannot align WAV samples"))?;
        }
        let riff_size = self.data_size_offset as u32 + self.bytes + padding - 4;
        self.file
            .seek(SeekFrom::Start(4))
            .and_then(|_| self.file.write_all(&riff_size.to_le_bytes()))
            .and_then(|_| self.file.seek(SeekFrom::Start(self.data_size_offset)))
            .and_then(|_| self.file.write_all(&self.bytes.to_le_bytes()))
            .and_then(|_| self.file.flush())
            .map_err(|_| NativeError::new("audio_failed", "cannot finalize WAV header"))?;
        Ok(self.bytes)
    }
}
#[cfg(test)]
mod tests {
    #[test]
    fn wav_codec_has_correct_riff_and_data_lengths() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("native.wav");
        let format = [1, 0, 1, 0, 0x80, 0xbb, 0, 0, 0, 0x77, 1, 0, 2, 0, 16, 0];
        let mut file = super::Wave::create(&path, &format).unwrap();
        file.append(&[1, 2, 3, 4]).unwrap();
        assert_eq!(file.finish().unwrap(), 4);
        let bytes = std::fs::read(path).unwrap();
        assert_eq!(&bytes[0..4], b"RIFF");
        assert_eq!(
            u32::from_le_bytes(bytes[4..8].try_into().unwrap()) as usize,
            bytes.len() - 8
        );
        assert_eq!(&bytes[36..40], b"data");
        assert_eq!(u32::from_le_bytes(bytes[40..44].try_into().unwrap()), 4);
    }
    #[test]
    fn odd_pcm_data_has_riff_padding_without_changing_sample_length() {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("odd.wav");
        let format = [1, 0, 1, 0, 0x80, 0xbb, 0, 0, 0x80, 0xbb, 0, 0, 1, 0, 8, 0];
        let mut file = super::Wave::create(&path, &format).unwrap();
        file.append(&[128, 127, 126]).unwrap();
        assert_eq!(file.finish().unwrap(), 3);
        let bytes = std::fs::read(path).unwrap();
        assert_eq!(bytes.len(), 48);
        assert_eq!(u32::from_le_bytes(bytes[4..8].try_into().unwrap()), 40);
        assert_eq!(u32::from_le_bytes(bytes[40..44].try_into().unwrap()), 3);
        assert_eq!(&bytes[44..], &[128, 127, 126, 0]);
    }
}
