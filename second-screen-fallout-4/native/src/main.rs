mod bridge;
mod gpu;
mod mesh_gpu;
mod scene;
mod ui;
use anyhow::{Context, Result};
use serde_json::{Value, json};
use std::{
    collections::{HashMap, HashSet},
    path::PathBuf,
    sync::Arc,
    time::{Duration, Instant},
};
use winit::{
    application::ApplicationHandler,
    event::{ElementState, MouseButton, MouseScrollDelta, TouchPhase, WindowEvent},
    event_loop::{ActiveEventLoop, ControlFlow, EventLoop},
    keyboard::{Key, NamedKey},
    window::{Window, WindowId},
};
struct Options {
    data: PathBuf,
    preview: Option<PathBuf>,
    capture: Option<PathBuf>,
    duration: Option<f64>,
    phase: Option<f32>,
    profile_gpu: bool,
    page: usize,
    category: usize,
}
fn options() -> Result<Options> {
    let mut o = Options {
        data: std::env::var_os("ARMADA_MOD_DATA_DIR")
            .map(PathBuf::from)
            .unwrap_or_default(),
        preview: None,
        capture: None,
        duration: None,
        phase: None,
        profile_gpu: false,
        page: 0,
        category: 0,
    };
    let mut a = std::env::args().skip(1);
    while let Some(k) = a.next() {
        match k.as_str() {
            "--preview-page" => {
                o.page = a
                    .next()
                    .context("--preview-page requires an index")?
                    .parse()?
            }
            "--preview-category" => {
                o.category = a
                    .next()
                    .context("--preview-category requires an index")?
                    .parse()?
            }
            "--profile-gpu" => o.profile_gpu = true,
            "--data" => o.data = a.next().context("--data requires a path")?.into(),
            "--preview" => {
                o.preview = Some(a.next().context("--preview requires a JSON state")?.into())
            }
            "--capture" => {
                o.capture = Some(a.next().context("--capture requires a PNG path")?.into())
            }
            "--duration" => {
                o.duration = Some(a.next().context("--duration requires seconds")?.parse()?)
            }
            "--phase" => o.phase = Some(a.next().context("--phase requires a value")?.parse()?),
            _ => anyhow::bail!("Unknown option {k}"),
        }
    }
    if o.data.as_os_str().is_empty() {
        anyhow::bail!("Set ARMADA_MOD_DATA_DIR or --data to the mod runtime data");
    }
    Ok(o)
}
fn block_on<F: std::future::Future>(f: F) -> F::Output {
    struct Wake(std::thread::Thread);
    impl std::task::Wake for Wake {
        fn wake(self: Arc<Self>) {
            self.0.unpark();
        }
        fn wake_by_ref(self: &Arc<Self>) {
            self.0.unpark();
        }
    }
    let w = std::task::Waker::from(Arc::new(Wake(std::thread::current())));
    let mut cx = std::task::Context::from_waker(&w);
    let mut f = std::pin::pin!(f);
    loop {
        match f.as_mut().poll(&mut cx) {
            std::task::Poll::Ready(r) => return r,
            std::task::Poll::Pending => std::thread::park(),
        }
    }
}
struct App {
    options: Options,
    window: Option<Arc<Window>>,
    gpu: Option<gpu::Gpu>,
    view: ui::View,
    link: Option<bridge::Link>,
    state: Value,
    start: Instant,
    next: Instant,
    frames: u64,
    cpu_render: Duration,
    position: [f32; 2],
    mouse_down: bool,
    touches: HashMap<u64, [f32; 2]>,
    pinch_distance: Option<f32>,
    occluded: bool,
    sweep_start: f64,
    next_sweep: f64,
    rng: u64,
    failed: bool,
    requested_models: HashSet<u32>,
}
impl App {
    fn commands(&self, commands: Vec<Value>) {
        if let Some(link) = &self.link {
            for command in commands {
                link.send(command);
            }
        }
    }
    fn phase(&mut self, t: f64) -> f32 {
        if let Some(p) = self.options.phase {
            return p;
        }
        if t >= self.next_sweep {
            self.sweep_start = t;
            self.rng ^= self.rng << 13;
            self.rng ^= self.rng >> 7;
            self.rng ^= self.rng << 17;
            self.next_sweep = t + 4. + 3. + (self.rng as f64 / u64::MAX as f64) * 7.;
        }
        (-0.5 + (t - self.sweep_start) * 0.5).min(1.5) as f32
    }
    fn redraw(&mut self, event_loop: &ActiveEventLoop) {
        if self.occluded {
            return;
        }
        if let Some(link) = &self.link {
            if let Some(mut s) = link.take_state() {
                if s["assets"].is_null() {
                    s["assets"] = self.state["assets"].take();
                }
                if s["connected"].as_bool() != Some(true) {
                    self.requested_models.clear();
                }
                if let Some(models) = s.as_object_mut().and_then(|v| v.remove("models")) {
                    s["assets"]["models"] = models;
                }
                self.state = s;
            }
        }
        let t = self.start.elapsed().as_secs_f64();
        if self.options.duration.is_some_and(|d| t >= d) {
            eprintln!(
                "Native preview: {} frames in {:.2}s; mean render-submit {:.3}ms",
                self.frames,
                t,
                self.cpu_render.as_secs_f64() * 1000. / self.frames.max(1) as f64
            );
            event_loop.exit();
            return;
        }
        let phase = self.phase(t);
        let scene = self.view.frame(&self.state, t);
        if self.state["connected"].as_bool() == Some(true) {
            for draw in &scene.draws {
                if let scene::Kind::Model {
                    form_id,
                    path: None,
                    ..
                } = &draw.kind
                {
                    if self.link.is_some() && self.requested_models.insert(*form_id) {
                        self.commands(vec![json!({"action":"preview_model","formID":form_id})]);
                    }
                }
            }
        }
        let color = self
            .state
            .pointer("/data/Status/EffectColor")
            .and_then(Value::as_array);
        let color = std::array::from_fn(|i| {
            color
                .and_then(|c| c.get(i))
                .and_then(Value::as_f64)
                .unwrap_or([0.08, 1., 0.09][i])
                .clamp(0., 1.) as f32
        });
        let capture = if self.frames >= 45 {
            self.options.capture.take()
        } else {
            None
        };
        let now = Instant::now();
        if let Some(gpu) = &mut self.gpu {
            if let Err(e) = gpu.render(scene, phase, color, capture.as_deref()) {
                eprintln!("Native rendering failed: {e:#}");
                self.failed = true;
                event_loop.exit();
                return;
            }
        }
        self.cpu_render += now.elapsed();
        self.frames += 1;
        self.next = now + Duration::from_secs_f64(1. / 30.);
    }
}
impl ApplicationHandler for App {
    fn resumed(&mut self, event_loop: &ActiveEventLoop) {
        if self.window.is_some() {
            return;
        }
        let attrs = Window::default_attributes()
            .with_title("Fallout 4 Pip-Boy")
            .with_decorations(false)
            .with_inner_size(winit::dpi::LogicalSize::new(1240., 1080.))
            .with_fullscreen(Some(winit::window::Fullscreen::Borderless(None)));
        let result = (|| -> Result<_> {
            let window = Arc::new(event_loop.create_window(attrs)?);
            let gpu = block_on(gpu::Gpu::new(
                window.clone(),
                self.options.data.clone(),
                self.options.profile_gpu,
            ))?;
            Ok((window, gpu))
        })();
        match result {
            Ok((window, gpu)) => {
                self.view.font = Some(gpu.font.clone());
                self.window = Some(window);
                self.gpu = Some(gpu);
                self.start = Instant::now();
                self.next = Instant::now();
            }
            Err(e) => {
                eprintln!("Cannot start native Pip-Boy: {e:#}");
                self.failed = true;
                event_loop.exit();
            }
        }
    }
    fn window_event(&mut self, event_loop: &ActiveEventLoop, _: WindowId, event: WindowEvent) {
        match event {
            WindowEvent::CloseRequested => event_loop.exit(),
            WindowEvent::Resized(size) => {
                if let Some(gpu) = &mut self.gpu {
                    gpu.resize(size.width, size.height);
                }
            }
            WindowEvent::Occluded(value) => {
                self.occluded = value;
                if !value {
                    self.next = Instant::now();
                }
            }
            WindowEvent::RedrawRequested => self.redraw(event_loop),
            WindowEvent::CursorMoved { position, .. } => {
                if let Some(gpu) = &self.gpu {
                    self.position = gpu.point(position.x, position.y);
                    if self.mouse_down {
                        self.view.pointer_move(self.position[0], self.position[1]);
                    }
                }
            }
            WindowEvent::MouseInput {
                state,
                button: MouseButton::Left,
                ..
            } => {
                let [x, y] = self.position;
                if state == ElementState::Pressed {
                    self.mouse_down = true;
                    self.view.pointer_down(x, y);
                } else if self.mouse_down {
                    self.mouse_down = false;
                    let c = self
                        .view
                        .pointer_up(x, y, self.start.elapsed().as_secs_f64());
                    self.commands(c);
                }
            }
            WindowEvent::MouseWheel { delta, .. } => {
                let dy = match delta {
                    MouseScrollDelta::LineDelta(_, y) => -y,
                    MouseScrollDelta::PixelDelta(p) => -p.y as f32 / 36.,
                };
                self.view.scroll(dy);
            }
            WindowEvent::Touch(touch) => {
                if let Some(gpu) = &self.gpu {
                    let p = gpu.point(touch.location.x, touch.location.y);
                    match touch.phase {
                        TouchPhase::Started => {
                            self.touches.insert(touch.id, p);
                            if self.touches.len() == 1 {
                                self.view.pointer_down(p[0], p[1]);
                            }
                        }
                        TouchPhase::Moved => {
                            self.touches.insert(touch.id, p);
                            if self.touches.len() == 1 {
                                self.view.pointer_move(p[0], p[1]);
                            } else if self.touches.len() == 2 {
                                let v: Vec<_> = self.touches.values().copied().collect();
                                let d = (v[0][0] - v[1][0]).hypot(v[0][1] - v[1][1]);
                                if let Some(previous) = self.pinch_distance {
                                    if previous > 1. {
                                        self.view.pinch(
                                            d / previous,
                                            (v[0][0] + v[1][0]) / 2.,
                                            (v[0][1] + v[1][1]) / 2.,
                                        );
                                    }
                                }
                                self.pinch_distance = Some(d);
                            }
                        }
                        TouchPhase::Ended | TouchPhase::Cancelled => {
                            let single = self.touches.len() == 1 && self.pinch_distance.is_none();
                            self.touches.remove(&touch.id);
                            if single && touch.phase == TouchPhase::Ended {
                                let c = self.view.pointer_up(
                                    p[0],
                                    p[1],
                                    self.start.elapsed().as_secs_f64(),
                                );
                                self.commands(c);
                            }
                            if self.touches.is_empty() {
                                self.pinch_distance = None;
                            }
                        }
                    }
                }
            }
            WindowEvent::KeyboardInput { event, .. } if event.state == ElementState::Pressed => {
                match event.logical_key {
                    Key::Named(NamedKey::ArrowDown) => self.view.scroll(1.),
                    Key::Named(NamedKey::ArrowUp) => self.view.scroll(-1.),
                    _ => {}
                }
            }
            _ => {}
        }
    }
    fn about_to_wait(&mut self, event_loop: &ActiveEventLoop) {
        if self.occluded {
            event_loop.set_control_flow(ControlFlow::Wait);
            return;
        }
        let now = Instant::now();
        if now >= self.next {
            if let Some(window) = &self.window {
                window.request_redraw();
            }
            self.next = now + Duration::from_secs_f64(1. / 30.);
        }
        event_loop.set_control_flow(ControlFlow::WaitUntil(self.next));
    }
}
fn main() -> Result<()> {
    let options = options()?;
    let (state, link) = if let Some(path) = &options.preview {
        let mut s: Value = serde_json::from_slice(&std::fs::read(path)?)?;
        s["assets"] =
            serde_json::from_slice(&std::fs::read(options.data.join("assets/manifest.json"))?)?;
        s.as_object_mut()
            .context("Preview must contain a state object")?
            .remove("confirm");
        s.as_object_mut().unwrap().remove("notice");
        (s, None)
    } else {
        let port = std::env::var("ARMADA_SECOND_SCREEN_PORT")
            .unwrap_or_else(|_| "47800".into())
            .parse()?;
        (
            json!({"connected":false,"data":{},"message":"Waiting for Fallout 4…", "assets": serde_json::from_slice::<Value>(&std::fs::read(options.data.join("assets/manifest.json"))?)?}),
            Some(bridge::start(port)?),
        )
    };
    let now = Instant::now();
    let mut view = ui::View::default();
    if options.preview.is_some() {
        view.preview_page(options.page, options.category);
    }
    let mut app = App {
        options,
        window: None,
        gpu: None,
        view,
        link,
        state,
        start: now,
        next: now,
        frames: 0,
        cpu_render: Duration::ZERO,
        position: [0.; 2],
        mouse_down: false,
        touches: HashMap::new(),
        pinch_distance: None,
        occluded: false,
        sweep_start: 0.,
        next_sweep: 9.,
        rng: 0x8d724b29,
        failed: false,
        requested_models: HashSet::new(),
    };
    let events = EventLoop::new()?;
    events.run_app(&mut app)?;
    if app.failed {
        anyhow::bail!("Pip-Boy native host failed");
    }
    Ok(())
}
