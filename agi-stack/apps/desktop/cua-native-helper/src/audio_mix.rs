//! Bounded native WAV decoding, timeline alignment, linear resampling and clipped PCM mixing.
use crate::{
    backend::{NativeError, Result},
    wave::Wave,
};
use std::{
    fs::File,
    io::{Read, Seek, SeekFrom},
    path::Path,
};
fn invalid() -> NativeError {
    NativeError::new(
        "audio_format_unsupported",
        "native recording format cannot be mixed",
    )
}
struct Reader {
    file: File,
    format: u16,
    channels: usize,
    rate: u32,
    bits: u16,
    block: usize,
    start: u64,
    frames: u64,
    cache_start: u64,
    cache: Vec<u8>,
}
impl Reader {
    fn open(path: &Path) -> Result<Self> {
        let mut file = File::open(path).map_err(|_| invalid())?;
        let mut header = [0; 12];
        file.read_exact(&mut header).map_err(|_| invalid())?;
        if &header[..4] != b"RIFF" || &header[8..] != b"WAVE" {
            return Err(invalid());
        }
        let mut format = None;
        let mut data = None;
        while let Ok(()) = file.read_exact(&mut header[..8]) {
            let count = u32::from_le_bytes(header[4..8].try_into().unwrap()) as usize;
            let offset = file.stream_position().map_err(|_| invalid())?;
            match &header[..4] {
                b"fmt " => {
                    if !(16..=80).contains(&count) {
                        return Err(invalid());
                    }
                    let mut bytes = vec![0; count];
                    file.read_exact(&mut bytes).map_err(|_| invalid())?;
                    format = Some(bytes);
                }
                b"data" => {
                    data = Some((offset, count));
                    break;
                }
                _ => {}
            }
            file.seek(SeekFrom::Start(offset + count as u64 + (count % 2) as u64))
                .map_err(|_| invalid())?;
        }
        let bytes = format.ok_or_else(invalid)?;
        let (start, length) = data.ok_or_else(invalid)?;
        let word = |offset| u16::from_le_bytes([bytes[offset], bytes[offset + 1]]);
        let mut format = word(0);
        let channels = word(2) as usize;
        let rate = u32::from_le_bytes(bytes[4..8].try_into().unwrap());
        let block = word(12) as usize;
        let bits = word(14);
        if format == 0xfffe {
            if bytes.len() < 40 {
                return Err(invalid());
            }
            format = u16::from_le_bytes(bytes[24..26].try_into().unwrap());
        }
        if !(1..=32).contains(&channels)
            || !(8000..=192000).contains(&rate)
            || block != channels * (bits as usize / 8)
            || length % block.max(1) != 0
            || !matches!((format, bits), (1, 8 | 16 | 24 | 32) | (3, 32 | 64))
        {
            return Err(invalid());
        }
        if file.metadata().map_err(|_| invalid())?.len() < start + length as u64 {
            return Err(invalid());
        }
        Ok(Self {
            file,
            format,
            channels,
            rate,
            bits,
            block,
            start,
            frames: (length / block) as u64,
            cache_start: u64::MAX,
            cache: Vec::new(),
        })
    }
    fn frame(&mut self, index: u64) -> Result<[f64; 2]> {
        if index >= self.frames {
            return Ok([0.0; 2]);
        }
        if index < self.cache_start
            || index
                >= self
                    .cache_start
                    .saturating_add((self.cache.len() / self.block) as u64)
        {
            self.cache_start = index;
            let count = (self.frames - index).min(4096) as usize * self.block;
            self.cache.resize(count, 0);
            self.file
                .seek(SeekFrom::Start(self.start + index * self.block as u64))
                .and_then(|_| self.file.read_exact(&mut self.cache))
                .map_err(|_| invalid())?;
        }
        let offset = (index - self.cache_start) as usize * self.block;
        let width = self.bits as usize / 8;
        let mut result = [0.0; 2];
        for channel in 0..self.channels {
            let value = decode(
                self.format,
                self.bits,
                &self.cache[offset + channel * width..offset + (channel + 1) * width],
            )?;
            if self.channels == 1 {
                result = [value; 2];
            } else if self.channels == 2 {
                result[channel] = value;
            } else {
                result[0] += value / self.channels as f64;
                result[1] += value / self.channels as f64;
            }
        }
        Ok(result)
    }
    fn sample(&mut self, time: f64, offset: f64) -> Result<[f64; 2]> {
        if time < offset {
            return Ok([0.0; 2]);
        }
        let index = (time - offset) * self.rate as f64;
        let first = self.frame(index.floor() as u64)?;
        let second = self.frame(index.floor() as u64 + 1)?;
        let t = index.fract();
        Ok([
            first[0] + (second[0] - first[0]) * t,
            first[1] + (second[1] - first[1]) * t,
        ])
    }
}
fn decode(format: u16, bits: u16, bytes: &[u8]) -> Result<f64> {
    let value = match (format, bits) {
        (1, 8) => (bytes[0] as f64 - 128.0) / 128.0,
        (1, 16) => i16::from_le_bytes(bytes.try_into().map_err(|_| invalid())?) as f64 / 32768.0,
        (1, 24) => {
            let value = i32::from_le_bytes([
                bytes[0],
                bytes[1],
                bytes[2],
                if bytes[2] & 0x80 != 0 { 0xff } else { 0 },
            ]);
            value as f64 / 8388608.0
        }
        (1, 32) => {
            i32::from_le_bytes(bytes.try_into().map_err(|_| invalid())?) as f64 / 2147483648.0
        }
        (3, 32) => f32::from_le_bytes(bytes.try_into().map_err(|_| invalid())?) as f64,
        (3, 64) => f64::from_le_bytes(bytes.try_into().map_err(|_| invalid())?),
        _ => return Err(invalid()),
    };
    if !value.is_finite() {
        return Err(NativeError::new(
            "audio_invalid_samples",
            "native recording contains non-finite samples",
        ));
    }
    Ok(value)
}
pub fn mix(
    first: &Path,
    first_offset: f64,
    second: &Path,
    second_offset: f64,
    output: &Path,
) -> Result<u32> {
    if ![first_offset, second_offset]
        .into_iter()
        .all(|value| value.is_finite() && (0.0..=10.0).contains(&value))
    {
        return Err(NativeError::new(
            "audio_alignment_invalid",
            "native capture timing is outside the recording budget",
        ));
    }
    let mut first = Reader::open(first)?;
    let mut second = Reader::open(second)?;
    let seconds = (first_offset + first.frames as f64 / first.rate as f64)
        .max(second_offset + second.frames as f64 / second.rate as f64);
    if seconds > 610.0 {
        return Err(NativeError::new(
            "audio_limit",
            "mixed recording exceeds the duration budget",
        ));
    }
    let rate = 48000u32;
    let frames = (seconds * rate as f64).ceil() as u64;
    let mut format = Vec::new();
    format.extend(1u16.to_le_bytes());
    format.extend(2u16.to_le_bytes());
    format.extend(rate.to_le_bytes());
    format.extend((rate * 4).to_le_bytes());
    format.extend(4u16.to_le_bytes());
    format.extend(16u16.to_le_bytes());
    let mut wave = Wave::create(output, &format)?;
    let mut buffer = Vec::with_capacity(4096);
    for frame in 0..frames {
        let time = frame as f64 / rate as f64;
        let a = first.sample(time, first_offset)?;
        let b = second.sample(time, second_offset)?;
        for channel in 0..2 {
            let value = (a[channel] + b[channel]).clamp(-1.0, 1.0);
            let sample = if value >= 0.0 {
                (value * 32767.0).round() as i16
            } else {
                (value * 32768.0).round() as i16
            };
            buffer.extend(sample.to_le_bytes());
        }
        if buffer.len() >= 4096 {
            wave.append(&buffer)?;
            buffer.clear();
        }
    }
    if !buffer.is_empty() {
        wave.append(&buffer)?;
    }
    wave.finish()
}
#[cfg(test)]
mod tests {
    fn fixture(path: &std::path::Path, rate: u32, value: f32, frames: usize) {
        let mut format = Vec::new();
        format.extend(3u16.to_le_bytes());
        format.extend(1u16.to_le_bytes());
        format.extend(rate.to_le_bytes());
        format.extend((rate * 4).to_le_bytes());
        format.extend(4u16.to_le_bytes());
        format.extend(32u16.to_le_bytes());
        let mut wave = crate::wave::Wave::create(path, &format).unwrap();
        wave.append(&value.to_le_bytes().repeat(frames)).unwrap();
        wave.finish().unwrap();
    }
    #[test]
    fn mixed_pcm_aligns_resamples_and_saturates() {
        let root = tempfile::tempdir().unwrap();
        let a = root.path().join("a.wav");
        let b = root.path().join("b.wav");
        let out = root.path().join("mixed.wav");
        fixture(&a, 16000, 0.8, 160);
        fixture(&b, 48000, 0.8, 480);
        super::mix(&a, 0.0, &b, 0.001, &out).unwrap();
        let mut reader = super::Reader::open(&out).unwrap();
        assert_eq!((reader.rate, reader.channels, reader.bits), (48000, 2, 16));
        assert!((reader.frame(0).unwrap()[0] - 0.8).abs() < 0.0001);
        assert!(reader.frame(100).unwrap()[0] > 0.999);
        assert_eq!(reader.frames, 528);
    }
    #[test]
    fn malformed_or_nonfinite_native_samples_are_rejected() {
        let root = tempfile::tempdir().unwrap();
        let bad = root.path().join("bad.wav");
        fixture(&bad, 48000, f32::NAN, 1);
        assert!(super::Reader::open(&bad).unwrap().frame(0).is_err());
        assert!(super::decode(1, 24, &[0, 0, 0x80]).unwrap() <= -1.0);
    }
}
