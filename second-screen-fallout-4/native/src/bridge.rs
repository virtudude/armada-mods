//! Local A2SS transport. The existing Python provider remains the sole game client.
use anyhow::{Context, Result};
use serde_json::{Value, json};
use std::io::{self, Read, Write};
use std::net::{TcpListener, TcpStream};
use std::sync::{
    Arc, Mutex, MutexGuard,
    atomic::{AtomicBool, Ordering},
    mpsc::{self, Receiver, SyncSender},
};
use std::thread;
use std::time::{Duration, Instant};

const MAX_JSON: usize = 1024 * 1024;
const HELLO: u16 = 1;
const STATE: u16 = 3;
const INPUT: u16 = 16;
const CONFIG: u16 = 17;
const IO_LIMIT: Duration = Duration::from_secs(2);

#[derive(Default)]
struct Shared {
    latest: Option<Value>,
    assets: Value,
    generation: u64,
    connected: bool,
}

pub struct Link {
    shared: Arc<Mutex<Shared>>,
    commands: SyncSender<(u64, Value)>,
    stop: Arc<AtomicBool>,
}

fn lock(shared: &Mutex<Shared>) -> MutexGuard<'_, Shared> {
    // A failed UI caller must not permanently poison the transport.
    shared.lock().unwrap_or_else(|error| error.into_inner())
}

impl Link {
    /// Take only the newest complete provider snapshot.
    pub fn take_state(&self) -> Option<Value> {
        lock(&self.shared).latest.take()
    }

    /// Never block the rendering thread or retain input while the game is absent.
    pub fn send(&self, command: Value) {
        let shared = lock(&self.shared);
        if shared.connected && command.is_object() {
            let _ = self.commands.try_send((shared.generation, command));
        }
    }
}

impl Drop for Link {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::Relaxed);
    }
}

pub fn start(port: u16) -> Result<Link> {
    let listener = TcpListener::bind(("127.0.0.1", port))
        .with_context(|| format!("bind local Pip-Boy provider port {port}"))?;
    listener.set_nonblocking(true)?;
    let shared = Arc::new(Mutex::new(Shared::default()));
    detached(&shared);
    let stop = Arc::new(AtomicBool::new(false));
    let (commands, receiver) = mpsc::sync_channel(64);
    let thread_shared = Arc::clone(&shared);
    let thread_stop = Arc::clone(&stop);
    thread::Builder::new()
        .name("pipboy-provider".into())
        .spawn(move || {
            serve(listener, &thread_shared, &receiver, &thread_stop);
        })?;
    Ok(Link {
        shared,
        commands,
        stop,
    })
}

fn detached(shared: &Mutex<Shared>) {
    let mut shared = lock(shared);
    shared.connected = false;
    shared.generation = shared.generation.wrapping_add(1);
    shared.latest = Some(json!({"connected": false,
        "message": "Waiting for Fallout 4’s Pip-Boy bridge…", "data": {},
        "assets": shared.assets, "localMap": null, "notice": "", "confirm": null}));
}

fn publish(shared: &Mutex<Shared>, state: Value) {
    let mut shared = lock(shared);
    let connected = state.get("connected").and_then(Value::as_bool) == Some(true);
    // A game disconnect also invalidates input queued before that snapshot.
    if !connected {
        shared.generation = shared.generation.wrapping_add(1);
    }
    shared.connected = connected;
    if let Some(assets) = state.get("assets") {
        shared.assets = assets.clone();
    }
    shared.latest = Some(state);
}

fn serve(
    listener: TcpListener,
    shared: &Mutex<Shared>,
    receiver: &Receiver<(u64, Value)>,
    stop: &AtomicBool,
) {
    while !stop.load(Ordering::Relaxed) {
        match listener.accept() {
            Ok((stream, _)) => {
                if let Err(error) = session(stream, shared, receiver, stop) {
                    eprintln!("Pip-Boy provider: {error}");
                }
                detached(shared);
                while receiver.try_recv().is_ok() {}
            }
            Err(error) if error.kind() == io::ErrorKind::WouldBlock => {
                while receiver.try_recv().is_ok() {}
                thread::sleep(Duration::from_millis(20));
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => {
                eprintln!("Pip-Boy listener: {error}");
                thread::sleep(Duration::from_millis(100));
            }
        }
    }
}

fn invalid(message: &'static str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, message)
}

fn packet(kind: u16, value: &Value) -> io::Result<Vec<u8>> {
    let body = serde_json::to_vec(value).map_err(|_| invalid("invalid JSON"))?;
    if body.len() > MAX_JSON {
        return Err(invalid("oversized JSON"));
    }
    let mut bytes = Vec::with_capacity(16 + body.len());
    bytes.extend_from_slice(b"A2SS");
    bytes.extend_from_slice(&kind.to_le_bytes());
    bytes.extend_from_slice(&0u16.to_le_bytes());
    bytes.extend_from_slice(&(body.len() as u32).to_le_bytes());
    bytes.extend_from_slice(&0u32.to_le_bytes());
    bytes.extend_from_slice(&body);
    Ok(bytes)
}

#[derive(Default)]
struct Decoder {
    bytes: Vec<u8>,
}
impl Decoder {
    fn next(&mut self) -> io::Result<Option<(u16, Value)>> {
        if self.bytes.len() < 16 {
            return Ok(None);
        }
        if &self.bytes[..4] != b"A2SS" {
            return Err(invalid("bad A2SS magic"));
        }
        let kind = u16::from_le_bytes(self.bytes[4..6].try_into().unwrap());
        let flags = u16::from_le_bytes(self.bytes[6..8].try_into().unwrap());
        if flags != 0 {
            return Err(invalid("unsupported A2SS flags"));
        }
        let size = u32::from_le_bytes(self.bytes[8..12].try_into().unwrap()) as usize;
        if size > MAX_JSON {
            return Err(invalid("oversized A2SS packet"));
        }
        if self.bytes.len() < 16 + size {
            return Ok(None);
        }
        let value = serde_json::from_slice(&self.bytes[16..16 + size])
            .map_err(|_| invalid("invalid A2SS JSON"))?;
        self.bytes.drain(..16 + size);
        Ok(Some((kind, value)))
    }
}

fn handshake(kind: u16, value: &Value) -> io::Result<()> {
    if kind != HELLO || value.get("appid").and_then(Value::as_u64) != Some(377160) {
        return Err(invalid("expected Fallout 4 HELLO"));
    }
    Ok(())
}

fn session(
    mut stream: TcpStream,
    shared: &Mutex<Shared>,
    receiver: &Receiver<(u64, Value)>,
    stop: &AtomicBool,
) -> io::Result<()> {
    stream.set_nonblocking(true)?;
    stream.set_nodelay(true)?;
    let mut decoder = Decoder::default();
    let started = Instant::now();
    let mut partial_since = None;
    let mut accepted = false;
    let mut outgoing: Option<(Vec<u8>, usize, Instant, Option<u64>)> = None;
    let mut buffer = [0; 8192];
    while !stop.load(Ordering::Relaxed) {
        // Bound work per iteration so a chatty provider cannot starve commands.
        for _ in 0..16 {
            match stream.read(&mut buffer) {
                Ok(0) => return Ok(()),
                Ok(size) => {
                    if decoder.bytes.is_empty() {
                        partial_since = Some(Instant::now());
                    }
                    decoder.bytes.extend_from_slice(&buffer[..size]);
                    while let Some((kind, value)) = decoder.next()? {
                        if !accepted {
                            handshake(kind, &value)?;
                            accepted = true;
                            outgoing = Some((
                                packet(CONFIG, &json!({"w":876,"h":740,"fps":30}))?,
                                0,
                                Instant::now(),
                                None,
                            ));
                        } else if kind == STATE {
                            if !value.is_object() {
                                return Err(invalid("state must be an object"));
                            }
                            publish(shared, value);
                        } else {
                            return Err(invalid("unexpected provider packet"));
                        }
                        partial_since = if decoder.bytes.is_empty() {
                            None
                        } else {
                            Some(Instant::now())
                        };
                    }
                }
                Err(error) if error.kind() == io::ErrorKind::WouldBlock => break,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(error) => return Err(error),
            }
        }
        if (!accepted && started.elapsed() > IO_LIMIT)
            || partial_since.is_some_and(|time: Instant| time.elapsed() > IO_LIMIT)
        {
            return Err(io::Error::new(
                io::ErrorKind::TimedOut,
                "incomplete provider packet",
            ));
        }
        if accepted && outgoing.is_none() {
            while let Ok((generation, command)) = receiver.try_recv() {
                let shared = lock(shared);
                if shared.connected && generation == shared.generation {
                    if let Ok(bytes) = packet(INPUT, &command) {
                        outgoing = Some((bytes, 0, Instant::now(), Some(generation)));
                        break;
                    }
                }
            }
        }
        if let Some((_, position, _, Some(generation))) = outgoing.as_ref() {
            let shared = lock(shared);
            if !shared.connected || *generation != shared.generation {
                // A partially written frame cannot be retracted or spliced.
                if *position != 0 {
                    return Err(invalid("game detached during input write"));
                }
                outgoing = None;
            }
        }
        if let Some((bytes, position, since, _)) = outgoing.as_mut() {
            if since.elapsed() > IO_LIMIT {
                return Err(io::Error::new(
                    io::ErrorKind::TimedOut,
                    "provider is not reading input",
                ));
            }
            match stream.write(&bytes[*position..]) {
                Ok(0) => return Err(io::Error::new(io::ErrorKind::WriteZero, "provider closed")),
                Ok(size) => {
                    *position += size;
                    if *position == bytes.len() {
                        outgoing = None;
                    }
                }
                Err(error)
                    if matches!(
                        error.kind(),
                        io::ErrorKind::WouldBlock | io::ErrorKind::Interrupted
                    ) => {}
                Err(error) => return Err(error),
            }
        }
        thread::sleep(Duration::from_millis(10));
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fragments_and_coalesced_packets() {
        let first = packet(HELLO, &json!({"appid":377160})).unwrap();
        let second = packet(STATE, &json!({"connected":true,"data":{"HP":42}})).unwrap();
        let mut decoder = Decoder::default();
        for byte in &first[..first.len() - 1] {
            decoder.bytes.push(*byte);
            assert!(decoder.next().unwrap().is_none());
        }
        decoder.bytes.push(*first.last().unwrap());
        decoder.bytes.extend_from_slice(&second);
        let (kind, hello) = decoder.next().unwrap().unwrap();
        handshake(kind, &hello).unwrap();
        assert_eq!(decoder.next().unwrap().unwrap().1["data"]["HP"], 42);
        assert!(decoder.bytes.is_empty());
    }

    #[test]
    fn rejects_bad_header_before_allocating_payload() {
        for (offset, value) in [(0, b'X'), (6, 1)] {
            let mut decoder = Decoder {
                bytes: packet(STATE, &json!({})).unwrap(),
            };
            decoder.bytes[offset] = value;
            assert!(decoder.next().is_err());
        }
        let mut decoder = Decoder {
            bytes: packet(STATE, &json!({})).unwrap(),
        };
        decoder.bytes[8..12].copy_from_slice(&((MAX_JSON + 1) as u32).to_le_bytes());
        decoder.bytes.truncate(16);
        assert!(decoder.next().is_err());
        assert_eq!(decoder.bytes.len(), 16);
    }

    #[test]
    fn rejects_other_game_or_malformed_json() {
        assert!(handshake(STATE, &json!({"appid":377160})).is_err());
        assert!(handshake(HELLO, &json!({"appid":413150})).is_err());
        assert!(handshake(HELLO, &json!({"appid":"377160"})).is_err());
        let mut bytes = packet(STATE, &json!({})).unwrap();
        bytes[16] = b'!';
        assert!(Decoder { bytes }.next().is_err());
    }

    #[test]
    fn replacement_disconnect_and_bounded_input() {
        let shared = Arc::new(Mutex::new(Shared::default()));
        let (commands, receiver) = mpsc::sync_channel(64);
        let link = Link {
            shared: Arc::clone(&shared),
            commands,
            stop: Arc::new(AtomicBool::new(false)),
        };
        link.send(json!({"action":"equip"}));
        assert!(receiver.try_recv().is_err());
        publish(
            &shared,
            json!({"connected":true,"data":{"HP":1},"assets":{"fonts":{}}}),
        );
        publish(
            &shared,
            json!({"connected":true,"data":{"HP":2},"assets":{"fonts":{}}}),
        );
        assert_eq!(link.take_state().unwrap()["data"]["HP"], 2);
        assert!(link.take_state().is_none());
        for _ in 0..100 {
            link.send(json!({"action":"equip"}));
        }
        let queued: Vec<_> = receiver.try_iter().collect();
        assert_eq!(queued.len(), 64);
        detached(&shared);
        assert_ne!(queued[0].0, lock(&shared).generation);
        let state = link.take_state().unwrap();
        assert_eq!(state["connected"], false);
        assert_eq!(state["data"], json!({}));
        assert!(state["confirm"].is_null());
        assert_eq!(state["assets"], json!({"fonts":{}}));
    }

    #[test]
    fn loopback_handshake_state_and_input() {
        // Synthetic peer only: never connects to the game's companion port.
        let listener = TcpListener::bind(("127.0.0.1", 0)).unwrap();
        let address = listener.local_addr().unwrap();
        let shared = Arc::new(Mutex::new(Shared::default()));
        let stop = Arc::new(AtomicBool::new(false));
        let (commands, receiver) = mpsc::sync_channel(64);
        let worker_shared = Arc::clone(&shared);
        let worker_stop = Arc::clone(&stop);
        let worker = thread::spawn(move || {
            let (stream, _) = listener.accept().unwrap();
            session(stream, &worker_shared, &receiver, &worker_stop).unwrap();
            detached(&worker_shared);
        });
        let link = Link {
            shared,
            commands,
            stop,
        };
        let mut peer = TcpStream::connect(address).unwrap();
        peer.set_read_timeout(Some(IO_LIMIT)).unwrap();
        let hello = packet(HELLO, &json!({"appid":377160})).unwrap();
        peer.write_all(&hello[..7]).unwrap();
        peer.write_all(&hello[7..]).unwrap();
        peer.write_all(&packet(STATE, &json!({"connected":true,"data":{"HP":42}})).unwrap())
            .unwrap();
        let read_packet = |peer: &mut TcpStream| {
            let mut header = [0; 16];
            peer.read_exact(&mut header).unwrap();
            let size = u32::from_le_bytes(header[8..12].try_into().unwrap()) as usize;
            let mut bytes = header.to_vec();
            bytes.resize(16 + size, 0);
            peer.read_exact(&mut bytes[16..]).unwrap();
            Decoder { bytes }.next().unwrap().unwrap()
        };
        let (kind, config) = read_packet(&mut peer);
        assert_eq!(kind, CONFIG);
        assert_eq!(config["w"], 876);
        let until = Instant::now() + IO_LIMIT;
        while !lock(&link.shared).connected && Instant::now() < until {
            thread::sleep(Duration::from_millis(5));
        }
        assert_eq!(link.take_state().unwrap()["data"]["HP"], 42);
        link.send(json!({"action":"localmap"}));
        assert_eq!(
            read_packet(&mut peer),
            (INPUT, json!({"action":"localmap"}))
        );
        drop(peer);
        worker.join().unwrap();
        assert_eq!(link.take_state().unwrap()["connected"], false);
    }
}
