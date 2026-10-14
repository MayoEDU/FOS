//! The panel's live eye values: its debug gaze dots and its eye preview. While `gaze_debug_dots` is on, or while the
//! panel listens on the socket (it binds it only while its eye preview is open, and removes it when that closes), every
//! processed sample goes to the panel as one datagram on a Unix socket in the status folder. Nothing leaves the device,
//! nothing is sent otherwise, and nothing here changes what goes to VRChat or VRCFT: these are copies for display.
//!
//! A datagram is PACKET_SIZE bytes, little-endian: b"FEOD", version 3, flags (bit 0: per-eye gaze is sent; bit 1: the
//! user's gaze scale is in use, not 1 on all sides), 2 reserved zero bytes, the sample time (f64), the six gaze values
//! as sent and the six before smoothing (f32 each: left x/y, right x/y, combined x/y; 1.0 = 45°), each eye's values
//! (EYE_SIZE bytes; the left eye first, anatomical; below), then at UNSCALED_AT the six gaze values as sent but before
//! the user's gaze scale (the same as the gaze as sent while bit 1 is clear). Each eye's values:
//!   0  f32  eyelid as sent (VRCFT scale: 0 closed, 0.75 relaxed open, 1 widened)
//!   4  f32  Valve's openness as read       8  f32  ...after the eye's scale (what the panel's raw bar shows)
//!   12 f32  the eye camera's eyelid (eyecam-rec's, VRCFT scale; NaN without fresh camera values for the eye)
//!   16 f32  squint as sent (NaN when none goes out)     20 f32  pupil diameter as sent (mm; NaN when none)
//!   24 f32  the eye camera's squint (NaN as at 12)       28 f32  the eye camera's pupil (mm; NaN as at 12)
//!   32 u8   where the sent eyelid came from (LidFrom: 0 the eye server's usual mix, 1.. the camera overrode it)
//!   33 u8   flags (bit 0: the eye camera reads the eye closed)    34 two reserved zero bytes
//! Version 3 is version 2 (136 bytes) with flag bit 1 and the gaze before the scale added at the end. The panel also
//! reads version 2 (taking the gaze as sent for the gaze before the scale); other versions it ignores (and frameeyeosc
//! never reads any).

use std::io::ErrorKind;
use std::os::unix::fs::FileTypeExt;
use std::os::unix::net::UnixDatagram;
use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

pub const SOCKET_NAME: &str = "gaze-dots.sock";
const MAGIC: &[u8; 4] = b"FEOD";
const VERSION: u8 = 3;
const EYES: usize = 64;
const EYE_SIZE: usize = 36;
const UNSCALED_AT: usize = EYES + 2 * EYE_SIZE;
pub const PACKET_SIZE: usize = UNSCALED_AT + 24;
// While gaze_debug_dots is off, whether the panel listens is looked at this often (one stat).
const LOOK_INTERVAL: Duration = Duration::from_secs(1);

/// One eye's values for the panel.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DotEye {
    pub lid: f32,
    pub openness: f32,
    pub openness_scaled: f32,
    pub camera_lid: f32,
    pub squint: f32,
    pub pupil_mm: f32,
    pub camera_squint: f32,
    pub camera_pupil_mm: f32,
    pub lid_from: u8,
    pub camera_closed: bool,
}

/// One sample for the panel.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct DotSample {
    pub time: f64,
    pub gaze: [f32; 6],
    pub raw_gaze: [f32; 6],
    // As sent, but before the user's gaze scale.
    pub unscaled_gaze: [f32; 6],
    pub independent: bool,
    // The user's gaze scale is in use (Settings::gaze_scaled).
    pub scaled: bool,
    pub eyes: [DotEye; 2],
}

pub fn encode(sample: &DotSample) -> [u8; PACKET_SIZE] {
    let mut packet = [0u8; PACKET_SIZE];
    packet[..4].copy_from_slice(MAGIC);
    packet[4] = VERSION;
    packet[5] = u8::from(sample.independent) | (u8::from(sample.scaled) << 1);
    packet[8..16].copy_from_slice(&sample.time.to_le_bytes());
    for (i, value) in sample.gaze.iter().chain(&sample.raw_gaze).enumerate() {
        packet[16 + i * 4..20 + i * 4].copy_from_slice(&value.to_le_bytes());
    }
    for (e, eye) in sample.eyes.iter().enumerate() {
        let at = EYES + e * EYE_SIZE;
        let values = [
            eye.lid,
            eye.openness,
            eye.openness_scaled,
            eye.camera_lid,
            eye.squint,
            eye.pupil_mm,
            eye.camera_squint,
            eye.camera_pupil_mm,
        ];
        for (i, value) in values.iter().enumerate() {
            packet[at + i * 4..at + 4 + i * 4].copy_from_slice(&value.to_le_bytes());
        }
        packet[at + 32] = eye.lid_from;
        packet[at + 33] = u8::from(eye.camera_closed);
    }
    for (i, value) in sample.unscaled_gaze.iter().enumerate() {
        packet[UNSCALED_AT + i * 4..UNSCALED_AT + 4 + i * 4].copy_from_slice(&value.to_le_bytes());
    }
    packet
}

#[cfg(test)]
pub fn decode(packet: &[u8]) -> Option<DotSample> {
    if packet.len() != PACKET_SIZE || &packet[..4] != MAGIC || packet[4] != VERSION {
        return None;
    }
    let f32_at = |at: usize| f32::from_le_bytes(packet[at..at + 4].try_into().unwrap());
    let time = f64::from_le_bytes(packet[8..16].try_into().ok()?);
    Some(DotSample {
        time,
        gaze: std::array::from_fn(|i| f32_at(16 + i * 4)),
        raw_gaze: std::array::from_fn(|i| f32_at(40 + i * 4)),
        unscaled_gaze: std::array::from_fn(|i| f32_at(UNSCALED_AT + i * 4)),
        independent: packet[5] & 1 != 0,
        scaled: packet[5] & 2 != 0,
        eyes: std::array::from_fn(|e| {
            let at = EYES + e * EYE_SIZE;
            DotEye {
                lid: f32_at(at),
                openness: f32_at(at + 4),
                openness_scaled: f32_at(at + 8),
                camera_lid: f32_at(at + 12),
                squint: f32_at(at + 16),
                pupil_mm: f32_at(at + 20),
                camera_squint: f32_at(at + 24),
                camera_pupil_mm: f32_at(at + 28),
                lid_from: packet[at + 32],
                camera_closed: packet[at + 33] & 1 != 0,
            }
        }),
    })
}

/// Sends the samples while they are wanted; holds no socket otherwise.
pub struct DotStream {
    path: PathBuf,
    socket: Option<UnixDatagram>,
    // Whether the panel listened when last looked (its socket file was there), and when that was.
    listening: bool,
    looked: Option<Instant>,
}

impl DotStream {
    /// `dir` is the status folder ($XDG_RUNTIME_DIR/frameeyeosc), where the panel binds the socket.
    pub fn new(dir: &Path) -> Self {
        Self {
            path: dir.join(SOCKET_NAME),
            socket: None,
            listening: false,
            looked: None,
        }
    }

    /// Whether to build and send this sample: always while `dots` (gaze_debug_dots) is on, as before; otherwise while
    /// the panel's socket is there (looked at once every LOOK_INTERVAL).
    pub fn wanted(&mut self, dots: bool, now: Instant) -> bool {
        if !dots && self.looked.is_none_or(|at| now.duration_since(at) >= LOOK_INTERVAL) {
            self.looked = Some(now);
            self.listening = std::fs::symlink_metadata(&self.path).is_ok_and(|meta| meta.file_type().is_socket());
        }
        let wanted = dots || self.listening;
        if !wanted {
            self.socket = None;
        }
        wanted
    }

    pub fn send(&mut self, sample: &DotSample) {
        if self.socket.is_none() {
            self.socket = UnixDatagram::unbound()
                .and_then(|socket| socket.set_nonblocking(true).map(|()| socket))
                .ok();
        }
        // No panel listening (or it is busy) is normal: the sample is simply dropped. A socket file gone or left by a
        // panel that crashed waits for the next look
        if let Some(socket) = &self.socket
            && let Err(error) = socket.send_to(&encode(sample), &self.path)
            && matches!(error.kind(), ErrorKind::NotFound | ErrorKind::ConnectionRefused)
        {
            self.listening = false;
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn eye(lid: f32) -> DotEye {
        DotEye {
            lid,
            openness: 0.98,
            openness_scaled: 1.02,
            camera_lid: f32::NAN,
            squint: 0.25,
            pupil_mm: f32::NAN,
            camera_squint: 0.3,
            camera_pupil_mm: 6.1,
            lid_from: 4,
            camera_closed: true,
        }
    }

    fn sample() -> DotSample {
        DotSample {
            time: 19892.729813125,
            gaze: [0.1, -0.2, 0.3, -0.4, 0.5, -0.6],
            raw_gaze: [-0.1, 0.2, -0.3, 0.4, -0.5, 0.6],
            unscaled_gaze: [0.05, -0.1, 0.25, -0.3, 0.15, -0.2],
            independent: true,
            scaled: true,
            eyes: [eye(0.72), DotEye { camera_closed: false, lid_from: 0, ..eye(0.0) }],
        }
    }

    /// Equal, NaN for NaN (the values without the eye camera are NaN).
    fn same(a: &DotSample, b: &DotSample) -> bool {
        let bits = |s: &DotSample| {
            let eyes: Vec<u32> = s
                .eyes
                .iter()
                .flat_map(|e| {
                    [e.lid, e.openness, e.openness_scaled, e.camera_lid, e.squint, e.pupil_mm, e.camera_squint, e.camera_pupil_mm]
                        .map(f32::to_bits)
                        .into_iter()
                        .chain([u32::from(e.lid_from), u32::from(e.camera_closed)])
                })
                .collect();
            let gazes = [s.gaze, s.raw_gaze, s.unscaled_gaze].map(|gaze| gaze.map(f32::to_bits));
            (s.time.to_bits(), gazes, s.independent, s.scaled, eyes)
        };
        bits(a) == bits(b)
    }

    #[test]
    fn packets_read_back_exactly() {
        let sample = sample();
        let packet = encode(&sample);
        assert_eq!(PACKET_SIZE, 160);
        assert_eq!(&packet[..8], b"FEOD\x03\x03\x00\x00");
        assert!(same(&decode(&packet).unwrap(), &sample));
        // The left eye's lid first, the right eye's flags last
        assert_eq!(f32::from_le_bytes(packet[64..68].try_into().unwrap()), 0.72);
        assert_eq!(packet[64 + 33], 1);
        assert_eq!(packet[100 + 32..100 + 36], [0, 0, 0, 0]);
        // The gaze before the scale last: its combined x at 152
        assert_eq!(f32::from_le_bytes(packet[152..156].try_into().unwrap()), 0.15);
        // Without the scale in use, bit 1 is clear
        let plain = encode(&DotSample { scaled: false, independent: false, ..sample });
        assert_eq!(plain[5], 0);
        assert!(!decode(&plain).unwrap().scaled);
        let mut wrong = packet;
        wrong[0] = b'X';
        assert_eq!(decode(&wrong), None);
        // Versions 1 (40 bytes) and 2 (136), and anything else of the wrong size or version, are not this
        let mut old = packet;
        old[4] = 2;
        assert_eq!(decode(&old), None);
        assert_eq!(decode(&old[..136]), None);
        assert_eq!(decode(&packet[..40]), None);
        assert_eq!(decode(&packet[..136]), None);
        assert_eq!(decode(&packet[..159]), None);
    }

    #[test]
    fn the_panel_gets_each_sample_only_while_wanted() {
        let dir = std::env::temp_dir().join(format!("frameeyeosc-dots-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let now = Instant::now();
        let mut stream = DotStream::new(&dir);
        let sample = sample();
        // Nobody listening and the dots off: not wanted, no socket held
        assert!(!stream.wanted(false, now));
        assert!(stream.socket.is_none());
        let panel = UnixDatagram::bind(dir.join(SOCKET_NAME)).unwrap();
        panel.set_nonblocking(true).unwrap();
        // The panel's socket is noticed at the next look, a second later
        assert!(!stream.wanted(false, now + Duration::from_millis(500)));
        assert!(stream.wanted(false, now + LOOK_INTERVAL));
        stream.send(&sample);
        let mut buffer = [0u8; 256];
        let size = panel.recv(&mut buffer).unwrap();
        assert!(same(&decode(&buffer[..size]).unwrap(), &sample));
        // The panel closes its socket (the preview closed): the next send notices, and nothing more is sent
        drop(panel);
        std::fs::remove_file(dir.join(SOCKET_NAME)).unwrap();
        stream.send(&sample);
        assert!(!stream.wanted(false, now + LOOK_INTERVAL + Duration::from_millis(10)));
        assert!(stream.socket.is_none());
        // gaze_debug_dots on: wanted with nobody listening, as before (the sample is dropped)
        assert!(stream.wanted(true, now + LOOK_INTERVAL + Duration::from_millis(20)));
        stream.send(&sample);
        std::fs::remove_dir_all(&dir).unwrap();
    }
}
