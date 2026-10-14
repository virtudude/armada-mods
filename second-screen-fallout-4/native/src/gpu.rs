use crate::scene::{HEIGHT, Kind, Rect, Scene, WIDTH};
use anyhow::{Context, Result, bail};
use bytemuck::{Pod, Zeroable};
use std::{
    collections::{HashMap, HashSet},
    path::{Path, PathBuf},
    sync::Arc,
};
use winit::window::Window;
const FORMAT: wgpu::TextureFormat = wgpu::TextureFormat::Rgba8Unorm;
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Vertex {
    position: [f32; 2],
    uv: [f32; 2],
    color: [f32; 4],
}
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Params {
    source_size: [f32; 2],
    phase: f32,
    brightness: f32,
    effect_color: [f32; 4],
    burst: f32,
    shudder: f32,
    frequency: f32,
    unused: f32,
}
struct Texture {
    _texture: wgpu::Texture,
    view: wgpu::TextureView,
    bind: wgpu::BindGroup,
    width: u32,
    height: u32,
    last: u64,
}
struct Batch {
    key: String,
    start: u32,
    end: u32,
    clip: Rect,
}
pub struct Gpu {
    device: wgpu::Device,
    queue: wgpu::Queue,
    surface: wgpu::Surface<'static>,
    config: wgpu::SurfaceConfiguration,
    ui_pipeline: wgpu::RenderPipeline,
    present_pipeline: wgpu::RenderPipeline,
    crt_pipeline: wgpu::RenderPipeline,
    texture_layout: wgpu::BindGroupLayout,
    sampler: wgpu::Sampler,
    source: Texture,
    output: Texture,
    crt_bind: wgpu::BindGroup,
    params: wgpu::Buffer,
    vertices: wgpu::Buffer,
    vertex_capacity: usize,
    textures: HashMap<String, Texture>,
    pub font: Arc<fontdue::Font>,
    profile: Option<GpuProfile>,
    bold: fontdue::Font,
    data: PathBuf,
    frame: u64,
    warnings: HashSet<String>,
    models: crate::mesh_gpu::Models,
    started: std::time::Instant,
    pub viewport: [f32; 4],
}
fn target(
    device: &wgpu::Device,
    queue: &wgpu::Queue,
    layout: &wgpu::BindGroupLayout,
    sampler: &wgpu::Sampler,
    width: u32,
    height: u32,
    rgba: Option<&[u8]>,
    label: &str,
) -> Texture {
    let texture = device.create_texture(&wgpu::TextureDescriptor {
        label: Some(label),
        size: wgpu::Extent3d {
            width,
            height,
            depth_or_array_layers: 1,
        },
        mip_level_count: 1,
        sample_count: 1,
        dimension: wgpu::TextureDimension::D2,
        format: FORMAT,
        usage: wgpu::TextureUsages::TEXTURE_BINDING
            | wgpu::TextureUsages::COPY_DST
            | wgpu::TextureUsages::COPY_SRC
            | wgpu::TextureUsages::RENDER_ATTACHMENT,
        view_formats: &[],
    });
    if let Some(bytes) = rgba {
        queue.write_texture(
            wgpu::TexelCopyTextureInfo {
                texture: &texture,
                mip_level: 0,
                origin: wgpu::Origin3d::ZERO,
                aspect: wgpu::TextureAspect::All,
            },
            bytes,
            wgpu::TexelCopyBufferLayout {
                offset: 0,
                bytes_per_row: Some(width * 4),
                rows_per_image: Some(height),
            },
            wgpu::Extent3d {
                width,
                height,
                depth_or_array_layers: 1,
            },
        );
    }
    let view = texture.create_view(&Default::default());
    let bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
        label: Some(label),
        layout,
        entries: &[
            wgpu::BindGroupEntry {
                binding: 0,
                resource: wgpu::BindingResource::TextureView(&view),
            },
            wgpu::BindGroupEntry {
                binding: 1,
                resource: wgpu::BindingResource::Sampler(sampler),
            },
        ],
    });
    Texture {
        _texture: texture,
        view,
        bind,
        width,
        height,
        last: 0,
    }
}
fn pipeline(
    device: &wgpu::Device,
    layout: &wgpu::PipelineLayout,
    shader: &wgpu::ShaderModule,
    format: wgpu::TextureFormat,
    geometry: bool,
    blend: bool,
    label: &str,
) -> wgpu::RenderPipeline {
    let attrs = wgpu::vertex_attr_array![0=>Float32x2,1=>Float32x2,2=>Float32x4];
    let buffers = [wgpu::VertexBufferLayout {
        array_stride: std::mem::size_of::<Vertex>() as u64,
        step_mode: wgpu::VertexStepMode::Vertex,
        attributes: &attrs,
    }];
    device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some(label),
        layout: Some(layout),
        vertex: wgpu::VertexState {
            module: shader,
            entry_point: Some("vs_main"),
            compilation_options: Default::default(),
            buffers: if geometry { &buffers } else { &[] },
        },
        primitive: Default::default(),
        depth_stencil: None,
        multisample: Default::default(),
        fragment: Some(wgpu::FragmentState {
            module: shader,
            entry_point: Some("fs_main"),
            compilation_options: Default::default(),
            targets: &[Some(wgpu::ColorTargetState {
                format,
                blend: if blend {
                    Some(wgpu::BlendState::ALPHA_BLENDING)
                } else {
                    None
                },
                write_mask: wgpu::ColorWrites::ALL,
            })],
        }),
        multiview: None,
        cache: None,
    })
}
impl Gpu {
    pub async fn new(window: Arc<Window>, data: PathBuf, profile_gpu: bool) -> Result<Self> {
        let instance = wgpu::Instance::new(&wgpu::InstanceDescriptor {
            backends: wgpu::Backends::VULKAN,
            ..Default::default()
        });
        let surface = instance.create_surface(window.clone())?;
        let adapter = instance
            .request_adapter(&wgpu::RequestAdapterOptions {
                power_preference: wgpu::PowerPreference::HighPerformance,
                compatible_surface: Some(&surface),
                force_fallback_adapter: false,
            })
            .await?;
        let info = adapter.get_info();
        eprintln!("Pip-Boy GPU: {} ({:?})", info.name, info.backend);
        if info.device_type == wgpu::DeviceType::Cpu {
            eprintln!(
                "Warning: software Vulkan adapter; battery/performance measurements are not hardware-GPU results"
            );
        }
        let profile_gpu =
            profile_gpu && adapter.features().contains(wgpu::Features::TIMESTAMP_QUERY);
        let (device, queue) = adapter
            .request_device(&wgpu::DeviceDescriptor {
                label: Some("Pip-Boy"),
                required_features: if profile_gpu {
                    wgpu::Features::TIMESTAMP_QUERY
                } else {
                    wgpu::Features::empty()
                },
                ..Default::default()
            })
            .await?;
        let caps = surface.get_capabilities(&adapter);
        let format = caps
            .formats
            .iter()
            .copied()
            .find(|f| !f.is_srgb())
            .unwrap_or(caps.formats[0]);
        let size = window.inner_size();
        let config = wgpu::SurfaceConfiguration {
            usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
            format,
            width: size.width.max(1),
            height: size.height.max(1),
            present_mode: wgpu::PresentMode::Fifo,
            desired_maximum_frame_latency: 2,
            alpha_mode: wgpu::CompositeAlphaMode::Opaque,
            view_formats: vec![],
        };
        surface.configure(&device, &config);
        let sampler = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("Linear clamp"),
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let texture_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("UI texture"),
            entries: &[
                wgpu::BindGroupLayoutEntry {
                    binding: 0,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Texture {
                        sample_type: wgpu::TextureSampleType::Float { filterable: true },
                        view_dimension: wgpu::TextureViewDimension::D2,
                        multisampled: false,
                    },
                    count: None,
                },
                wgpu::BindGroupLayoutEntry {
                    binding: 1,
                    visibility: wgpu::ShaderStages::FRAGMENT,
                    ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                    count: None,
                },
            ],
        });
        let ui_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("UI"),
            bind_group_layouts: &[&texture_layout],
            push_constant_ranges: &[],
        });
        let ui_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("UI quads"),
            source: wgpu::ShaderSource::Wgsl(include_str!("ui.wgsl").into()),
        });
        let ui_pipeline = pipeline(
            &device,
            &ui_layout,
            &ui_shader,
            FORMAT,
            true,
            true,
            "Neutral UI",
        );
        let present_pipeline = pipeline(
            &device, &ui_layout, &ui_shader, format, true, false, "Present",
        );
        let source = target(
            &device,
            &queue,
            &texture_layout,
            &sampler,
            WIDTH as u32,
            HEIGHT as u32,
            None,
            "Neutral UI surface",
        );
        let output = target(
            &device,
            &queue,
            &texture_layout,
            &sampler,
            WIDTH as u32,
            HEIGHT as u32,
            None,
            "Pip-Boy output",
        );
        let load = |name: &str| -> Result<image::RgbaImage> {
            Ok(image::open(data.join(format!("assets/effects/{name}.png")))?.to_rgba8())
        };
        let scan = load("scan")?;
        let vertical = load("verticalScan")?;
        let scan = target(
            &device,
            &queue,
            &texture_layout,
            &sampler,
            scan.width(),
            scan.height(),
            Some(scan.as_raw()),
            "Owned scan profile",
        );
        let vertical = target(
            &device,
            &queue,
            &texture_layout,
            &sampler,
            vertical.width(),
            vertical.height(),
            Some(vertical.as_raw()),
            "Owned sweep profile",
        );
        let repeat = device.create_sampler(&wgpu::SamplerDescriptor {
            label: Some("Native repeat scan"),
            address_mode_u: wgpu::AddressMode::Repeat,
            address_mode_v: wgpu::AddressMode::Repeat,
            mag_filter: wgpu::FilterMode::Linear,
            min_filter: wgpu::FilterMode::Linear,
            ..Default::default()
        });
        let params = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Native effect constants"),
            size: 48,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let mut entries = Vec::new();
        for binding in [0, 2, 3] {
            entries.push(wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Texture {
                    sample_type: wgpu::TextureSampleType::Float { filterable: true },
                    view_dimension: wgpu::TextureViewDimension::D2,
                    multisampled: false,
                },
                count: None,
            });
        }
        for binding in [1, 4] {
            entries.push(wgpu::BindGroupLayoutEntry {
                binding,
                visibility: wgpu::ShaderStages::FRAGMENT,
                ty: wgpu::BindingType::Sampler(wgpu::SamplerBindingType::Filtering),
                count: None,
            });
        }
        entries.push(wgpu::BindGroupLayoutEntry {
            binding: 5,
            visibility: wgpu::ShaderStages::FRAGMENT,
            ty: wgpu::BindingType::Buffer {
                ty: wgpu::BufferBindingType::Uniform,
                has_dynamic_offset: false,
                min_binding_size: wgpu::BufferSize::new(48),
            },
            count: None,
        });
        let crt_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("Recovered Pip-Boy effect"),
            entries: &entries,
        });
        let crt_bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: Some("Effect resources"),
            layout: &crt_layout,
            entries: &[
                wgpu::BindGroupEntry {
                    binding: 0,
                    resource: wgpu::BindingResource::TextureView(&source.view),
                },
                wgpu::BindGroupEntry {
                    binding: 1,
                    resource: wgpu::BindingResource::Sampler(&sampler),
                },
                wgpu::BindGroupEntry {
                    binding: 2,
                    resource: wgpu::BindingResource::TextureView(&scan.view),
                },
                wgpu::BindGroupEntry {
                    binding: 3,
                    resource: wgpu::BindingResource::TextureView(&vertical.view),
                },
                wgpu::BindGroupEntry {
                    binding: 4,
                    resource: wgpu::BindingResource::Sampler(&repeat),
                },
                wgpu::BindGroupEntry {
                    binding: 5,
                    resource: params.as_entire_binding(),
                },
            ],
        });
        let crt_pipeline_layout = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: Some("Native image-space effect"),
            bind_group_layouts: &[&crt_layout],
            push_constant_ranges: &[],
        });
        let crt_shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Recovered Pip-Boy shader"),
            source: wgpu::ShaderSource::Wgsl(include_str!("pipboy.wgsl").into()),
        });
        let crt_pipeline = pipeline(
            &device,
            &crt_pipeline_layout,
            &crt_shader,
            FORMAT,
            false,
            false,
            "Native 25-tap bloom",
        );
        let font = fontdue::Font::from_bytes(
            std::fs::read(data.join("assets/fonts/main.ttf"))?,
            Default::default(),
        )
        .map_err(|e| anyhow::anyhow!(e))?;
        let bold = fontdue::Font::from_bytes(
            std::fs::read(data.join("assets/fonts/bold.ttf"))?,
            Default::default(),
        )
        .map_err(|e| anyhow::anyhow!(e))?;
        let vertex_capacity = 65536;
        let vertices = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("UI vertices"),
            size: vertex_capacity as u64,
            usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let white = target(
            &device,
            &queue,
            &texture_layout,
            &sampler,
            1,
            1,
            Some(&[255; 4]),
            "White primitive",
        );
        let mut textures = HashMap::new();
        textures.insert("white".into(), white);
        let profile = profile_gpu.then(|| GpuProfile::new(&device));
        let models = crate::mesh_gpu::Models::new(&device, data.clone());
        let mut result = Self {
            models,
            started: std::time::Instant::now(),
            device,
            queue,
            surface,
            config,
            ui_pipeline,
            present_pipeline,
            crt_pipeline,
            texture_layout,
            sampler,
            source,
            output,
            crt_bind,
            params,
            vertices,
            vertex_capacity,
            textures,
            font: Arc::new(font),
            profile,
            bold,
            data,
            frame: 0,
            warnings: HashSet::new(),
            viewport: [0.; 4],
        };
        result.resize(size.width, size.height);
        Ok(result)
    }
    pub fn resize(&mut self, width: u32, height: u32) {
        if width == 0 || height == 0 {
            return;
        }
        self.config.width = width;
        self.config.height = height;
        self.surface.configure(&self.device, &self.config);
        let scale = (width as f32 / WIDTH).min(height as f32 / HEIGHT);
        self.viewport = [
            (width as f32 - WIDTH * scale) / 2.,
            (height as f32 - HEIGHT * scale) / 2.,
            WIDTH * scale,
            HEIGHT * scale,
        ];
    }
    pub fn point(&self, x: f64, y: f64) -> [f32; 2] {
        [
            (x as f32 - self.viewport[0]) * WIDTH / self.viewport[2],
            (y as f32 - self.viewport[1]) * HEIGHT / self.viewport[3],
        ]
    }
    fn asset_path(&self, path: &str) -> Result<PathBuf> {
        let path = path
            .split('?')
            .next()
            .unwrap_or(path)
            .strip_prefix("file://")
            .unwrap_or(path.split('?').next().unwrap_or(path));
        let p = Path::new(path);
        let joined = if p.is_absolute() {
            p.to_path_buf()
        } else {
            self.data.join(p)
        };
        let canonical = joined.canonicalize()?;
        if !canonical.starts_with(self.data.canonicalize()?) {
            bail!("Asset outside mod data");
        }
        Ok(canonical)
    }
    fn asset(&mut self, path: &str, rect: Rect) -> Result<String> {
        let svg = path.split('?').next().unwrap_or(path).ends_with(".svg");
        let max_side = rect[2].abs().max(rect[3].abs()).ceil().clamp(32., 1024.) as u32;
        let max_side = max_side.div_ceil(32) * 32;
        let key = format!("image:{path}:{}", if svg { max_side } else { 0 });
        if let Some(t) = self.textures.get_mut(&key) {
            t.last = self.frame;
            return Ok(key);
        }
        let p = self.asset_path(path)?;
        let (w, h, rgba) = if svg {
            let bytes = std::fs::read(p)?;
            let tree = resvg::usvg::Tree::from_data(&bytes, &resvg::usvg::Options::default())
                .map_err(|e| anyhow::anyhow!(e))?;
            let size = tree.size();
            let scale = max_side as f32 / size.width().max(size.height());
            let w = (size.width() * scale).ceil().max(1.) as u32;
            let h = (size.height() * scale).ceil().max(1.) as u32;
            let mut pix = resvg::tiny_skia::Pixmap::new(w, h).context("SVG image bounds")?;
            resvg::render(
                &tree,
                resvg::tiny_skia::Transform::from_scale(scale, scale),
                &mut pix.as_mut(),
            );
            let mut rgba = pix.take();
            for p in rgba.chunks_exact_mut(4) {
                if p[3] > 0 {
                    for i in 0..3 {
                        p[i] = ((p[i] as u32 * 255) / p[3] as u32).min(255) as u8;
                    }
                }
            }
            (w, h, rgba)
        } else {
            let img = image::ImageReader::open(p)?
                .with_guessed_format()?
                .decode()?
                .to_rgba8();
            if img.width() > 8192 || img.height() > 8192 {
                bail!("Image bounds too large");
            }
            (img.width(), img.height(), img.into_raw())
        };
        let mut t = target(
            &self.device,
            &self.queue,
            &self.texture_layout,
            &self.sampler,
            w,
            h,
            Some(&rgba),
            "Owned artwork",
        );
        t.last = self.frame;
        self.textures.insert(key.clone(), t);
        Ok(key)
    }
    fn text(&mut self, text: &str, size: f32, bold: bool) -> Result<(String, f32, f32)> {
        let size = size.clamp(1., 96.);
        let text: String = text.chars().take(2048).collect();
        let key = format!("text:{bold}:{size:.2}:{text}");
        if let Some(t) = self.textures.get_mut(&key) {
            t.last = self.frame;
            return Ok((key, t.width as f32, t.height as f32));
        }
        let font = if bold { &self.bold } else { &self.font };
        let line = font
            .horizontal_line_metrics(size)
            .context("Missing font metrics")?;
        let height = (line.ascent - line.descent).ceil().max(1.) as u32;
        let mut glyphs = Vec::new();
        let mut x = 0f32;
        let mut previous = None;
        let mut max_x = 0f32;
        for c in text.chars() {
            if let Some(prev) = previous {
                x += font.horizontal_kern(prev, c, size).unwrap_or(0.);
            }
            let (m, bitmap) = font.rasterize(c, size);
            max_x = max_x.max(x + m.xmin as f32 + m.width as f32);
            glyphs.push((x, m, bitmap));
            x += m.advance_width;
            previous = Some(c);
        }
        let width = max_x.max(x).ceil().clamp(1., 8192.) as u32;
        let mut rgba = vec![0; (width * height * 4) as usize];
        for (x, m, bitmap) in glyphs {
            let x = x.floor() as i32 + m.xmin;
            let y = (line.ascent - m.height as f32 - m.ymin as f32).round() as i32;
            for gy in 0..m.height {
                for gx in 0..m.width {
                    let px = x + gx as i32;
                    let py = y + gy as i32;
                    if px < 0 || py < 0 || px >= width as i32 || py >= height as i32 {
                        continue;
                    }
                    let i = ((py as u32 * width + px as u32) * 4) as usize;
                    rgba[i..i + 3].fill(255);
                    rgba[i + 3] = rgba[i + 3].max(bitmap[gy * m.width + gx]);
                }
            }
        }
        let mut t = target(
            &self.device,
            &self.queue,
            &self.texture_layout,
            &self.sampler,
            width,
            height,
            Some(&rgba),
            "Owned font glyphs",
        );
        t.last = self.frame;
        self.textures.insert(key.clone(), t);
        Ok((key, width as f32, height as f32))
    }
    pub fn render(
        &mut self,
        scene: Scene,
        phase: f32,
        color: [f32; 3],
        capture: Option<&Path>,
    ) -> Result<()> {
        self.frame += 1;
        let mut vertices = Vec::new();
        let mut models = Vec::new();
        let mut batches: Vec<Batch> = Vec::new();
        for draw in scene.draws {
            let clip = draw.clip.unwrap_or([0., 0., WIDTH, HEIGHT]);
            let (key, corners, uv, shade) = match draw.kind {
                Kind::SolidQuad { corners, shade } => {
                    ("white".into(), corners, [0., 0., 1., 1.], shade)
                }
                Kind::Model { path, rect, .. } => {
                    if let Some(path) = path {
                        self.models.prepare(&self.device, &self.queue, &path);
                        models.push((path, rect));
                    }
                    continue;
                }
                Kind::Rect { rect, shade } => {
                    ("white".to_string(), corners(rect), [0., 0., 1., 1.], shade)
                }
                Kind::Image {
                    path,
                    rect,
                    shade,
                    uv,
                } => match self.asset(&path, rect) {
                    Ok(k) => (k, corners(rect), uv.unwrap_or([0., 0., 1., 1.]), shade),
                    Err(e) => {
                        if self.warnings.insert(path.clone()) {
                            eprintln!("Artwork {path}: {e}");
                        }
                        continue;
                    }
                },
                Kind::ImageQuad {
                    path,
                    corners: q,
                    shade,
                    uv,
                } => {
                    let w = (q[1][0] - q[0][0]).hypot(q[1][1] - q[0][1]);
                    let h = (q[3][0] - q[0][0]).hypot(q[3][1] - q[0][1]);
                    match self.asset(&path, [0., 0., w, h]) {
                        Ok(k) => (k, q, uv.unwrap_or([0., 0., 1., 1.]), shade),
                        Err(e) => {
                            if self.warnings.insert(path.clone()) {
                                eprintln!("Artwork {path}: {e}");
                            }
                            continue;
                        }
                    }
                }
                Kind::Text {
                    text,
                    x,
                    y,
                    size,
                    shade,
                    bold,
                    align,
                } => {
                    let (k, w, h) = self.text(&text, size, bold)?;
                    (
                        k,
                        corners([x - w * align, y, w, h]),
                        [0., 0., 1., 1.],
                        shade,
                    )
                }
            };
            let start = vertices.len() as u32;
            quad(&mut vertices, corners, uv, shade);
            let end = vertices.len() as u32;
            if let Some(last) = batches
                .last_mut()
                .filter(|b| b.key == key && b.clip == clip)
            {
                last.end = end;
            } else {
                batches.push(Batch {
                    key,
                    start,
                    end,
                    clip,
                });
            }
        }
        let mut present = Vec::new();
        quad(
            &mut present,
            corners([0., 0., WIDTH, HEIGHT]),
            [0., 0., 1., 1.],
            1.,
        );
        let present_start = vertices.len() as u32;
        vertices.extend(present);
        let bytes = bytemuck::cast_slice(&vertices);
        if bytes.len() > self.vertex_capacity {
            self.vertex_capacity = bytes.len().next_power_of_two();
            self.vertices = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("UI vertices"),
                size: self.vertex_capacity as u64,
                usage: wgpu::BufferUsages::VERTEX | wgpu::BufferUsages::COPY_DST,
                mapped_at_creation: false,
            });
        }
        self.queue.write_buffer(&self.vertices, 0, bytes);
        let params = Params {
            source_size: [WIDTH, HEIGHT],
            phase,
            brightness: 1.,
            effect_color: [color[0], color[1], color[2], 1.],
            burst: 0.,
            shudder: 0.,
            frequency: 200.,
            unused: 0.,
        };
        self.queue
            .write_buffer(&self.params, 0, bytemuck::bytes_of(&params));
        let frame = match self.surface.get_current_texture() {
            Ok(f) => f,
            Err(wgpu::SurfaceError::Lost | wgpu::SurfaceError::Outdated) => {
                self.surface.configure(&self.device, &self.config);
                return Ok(());
            }
            Err(wgpu::SurfaceError::Timeout) => return Ok(()),
            Err(e) => return Err(e.into()),
        };
        let surface_view = frame.texture.create_view(&Default::default());
        let profile = self
            .profile
            .as_ref()
            .filter(|_| self.frame >= 60 && self.frame % 30 == 0);
        let mut encoder = self.device.create_command_encoder(&Default::default());
        if !models.is_empty() {
            {
                let _clear = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                    label: Some("Clear model backdrop"),
                    timestamp_writes: profile.map(|p| wgpu::RenderPassTimestampWrites {
                        query_set: &p.queries,
                        beginning_of_pass_write_index: Some(0),
                        end_of_pass_write_index: None,
                    }),
                    color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                        view: &self.source.view,
                        resolve_target: None,
                        depth_slice: None,
                        ops: wgpu::Operations {
                            load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                            store: wgpu::StoreOp::Store,
                        },
                    })],
                    ..Default::default()
                });
            }
            for (path, rect) in &models {
                self.models.draw(
                    &self.queue,
                    &mut encoder,
                    &self.source.view,
                    path,
                    *rect,
                    self.started.elapsed().as_secs_f32(),
                );
            }
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("Draw neutral native artwork"),
                timestamp_writes: profile.map(|p| wgpu::RenderPassTimestampWrites {
                    query_set: &p.queries,
                    beginning_of_pass_write_index: models.is_empty().then_some(0),
                    end_of_pass_write_index: Some(1),
                }),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.source.view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: if models.is_empty() {
                            wgpu::LoadOp::Clear(wgpu::Color::BLACK)
                        } else {
                            wgpu::LoadOp::Load
                        },
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            pass.set_pipeline(&self.ui_pipeline);
            pass.set_vertex_buffer(0, self.vertices.slice(..));
            for b in &batches {
                let [x, y, w, h] = b.clip;
                let x = x.max(0.).min(WIDTH) as u32;
                let y = y.max(0.).min(HEIGHT) as u32;
                let w = w.max(0.).min(WIDTH - x as f32) as u32;
                let h = h.max(0.).min(HEIGHT - y as f32) as u32;
                if w == 0 || h == 0 {
                    continue;
                }
                pass.set_scissor_rect(x, y, w, h);
                pass.set_bind_group(0, &self.textures[&b.key].bind, &[]);
                pass.draw(b.start..b.end, 0..1);
            }
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("Native Pip-Boy shader"),
                timestamp_writes: profile.map(|p| p.timestamps(1)),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &self.output.view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            pass.set_pipeline(&self.crt_pipeline);
            pass.set_bind_group(0, &self.crt_bind, &[]);
            pass.draw(0..3, 0..1);
        }
        {
            let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
                label: Some("Present bottom screen"),
                timestamp_writes: profile.map(|p| p.timestamps(2)),
                color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                    view: &surface_view,
                    resolve_target: None,
                    depth_slice: None,
                    ops: wgpu::Operations {
                        load: wgpu::LoadOp::Clear(wgpu::Color::BLACK),
                        store: wgpu::StoreOp::Store,
                    },
                })],
                ..Default::default()
            });
            pass.set_pipeline(&self.present_pipeline);
            let [x, y, w, h] = self.viewport;
            pass.set_viewport(x, y, w, h, 0., 1.);
            pass.set_vertex_buffer(0, self.vertices.slice(..));
            pass.set_bind_group(0, &self.output.bind, &[]);
            pass.draw(present_start..present_start + 6, 0..1);
        }
        let capture_buffer = if capture.is_some() {
            let row = (WIDTH as u32 * 4).div_ceil(256) * 256;
            let buffer = self.device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("Development capture"),
                size: row as u64 * HEIGHT as u64,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            });
            encoder.copy_texture_to_buffer(
                wgpu::TexelCopyTextureInfo {
                    texture: &self.output._texture,
                    mip_level: 0,
                    origin: wgpu::Origin3d::ZERO,
                    aspect: wgpu::TextureAspect::All,
                },
                wgpu::TexelCopyBufferInfo {
                    buffer: &buffer,
                    layout: wgpu::TexelCopyBufferLayout {
                        offset: 0,
                        bytes_per_row: Some(row),
                        rows_per_image: Some(HEIGHT as u32),
                    },
                },
                wgpu::Extent3d {
                    width: WIDTH as u32,
                    height: HEIGHT as u32,
                    depth_or_array_layers: 1,
                },
            );
            Some((buffer, row))
        } else {
            None
        };
        if let Some(p) = profile {
            encoder.resolve_query_set(&p.queries, 0..6, &p.resolve, 0);
            encoder.copy_buffer_to_buffer(&p.resolve, 0, &p.read, 0, 48);
        }
        self.queue.submit(Some(encoder.finish()));
        frame.present();
        if let Some(p) = profile {
            p.report(&self.device, self.queue.get_timestamp_period())?;
        }
        if let (Some(path), Some((buffer, row))) = (capture, capture_buffer) {
            let (tx, rx) = std::sync::mpsc::channel();
            buffer.slice(..).map_async(wgpu::MapMode::Read, move |r| {
                let _ = tx.send(r);
            });
            self.device
                .poll(wgpu::PollType::wait_indefinitely())
                .map_err(|e| anyhow::anyhow!("GPU poll: {e:?}"))?;
            rx.recv()??;
            let map = buffer.slice(..).get_mapped_range();
            let mut rgba = Vec::with_capacity(WIDTH as usize * HEIGHT as usize * 4);
            for bytes in map.chunks_exact(row as usize) {
                rgba.extend_from_slice(&bytes[..WIDTH as usize * 4]);
            }
            image::save_buffer(
                path,
                &rgba,
                WIDTH as u32,
                HEIGHT as u32,
                image::ColorType::Rgba8,
            )?;
            drop(map);
            buffer.unmap();
            eprintln!("Captured {}", path.display());
        }
        let used: usize = self
            .textures
            .values()
            .map(|t| (t.width * t.height * 4) as usize)
            .sum();
        if used > 96 * 1024 * 1024 || self.textures.len() > 768 {
            let frame = self.frame;
            self.textures
                .retain(|k, t| k == "white" || t.last + 90 >= frame);
        }
        Ok(())
    }
}
fn corners([x, y, w, h]: Rect) -> [[f32; 2]; 4] {
    [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
}
fn quad(vertices: &mut Vec<Vertex>, q: [[f32; 2]; 4], [u, v, w, h]: Rect, shade: f32) {
    let uv = [[u, v], [u + w, v], [u + w, v + h], [u, v + h]];
    for i in [0, 1, 2, 0, 2, 3] {
        vertices.push(Vertex {
            position: [q[i][0] / WIDTH * 2. - 1., 1. - q[i][1] / HEIGHT * 2.],
            uv: uv[i],
            color: [shade, shade, shade, 1.],
        });
    }
}

// Explicit diagnostic mode only. Normal rendering has no timestamps or readback.
struct GpuProfile {
    queries: wgpu::QuerySet,
    resolve: wgpu::Buffer,
    read: wgpu::Buffer,
}
impl GpuProfile {
    fn new(device: &wgpu::Device) -> Self {
        Self {
            queries: device.create_query_set(&wgpu::QuerySetDescriptor {
                label: Some("GPU timing"),
                ty: wgpu::QueryType::Timestamp,
                count: 6,
            }),
            resolve: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("Timing resolve"),
                size: 48,
                usage: wgpu::BufferUsages::QUERY_RESOLVE | wgpu::BufferUsages::COPY_SRC,
                mapped_at_creation: false,
            }),
            read: device.create_buffer(&wgpu::BufferDescriptor {
                label: Some("Timing readback"),
                size: 48,
                usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ,
                mapped_at_creation: false,
            }),
        }
    }
    fn timestamps(&self, pass: u32) -> wgpu::RenderPassTimestampWrites<'_> {
        wgpu::RenderPassTimestampWrites {
            query_set: &self.queries,
            beginning_of_pass_write_index: Some(pass * 2),
            end_of_pass_write_index: Some(pass * 2 + 1),
        }
    }
    fn report(&self, device: &wgpu::Device, period: f32) -> Result<()> {
        let (tx, rx) = std::sync::mpsc::channel();
        self.read
            .slice(..)
            .map_async(wgpu::MapMode::Read, move |r| {
                let _ = tx.send(r);
            });
        device
            .poll(wgpu::PollType::wait_indefinitely())
            .map_err(|e| anyhow::anyhow!("GPU timing poll: {e:?}"))?;
        rx.recv()??;
        let map = self.read.slice(..).get_mapped_range();
        let ticks: Vec<u64> = map
            .chunks_exact(8)
            .map(|v| u64::from_le_bytes(v.try_into().unwrap()))
            .collect();
        let ms = |a: usize, b: usize| {
            ticks[b].wrapping_sub(ticks[a]) as f64 * period as f64 / 1_000_000.
        };
        eprintln!(
            "GPU ms: UI={:.3} CRT={:.3} present={:.3} elapsed={:.3}",
            ms(0, 1),
            ms(2, 3),
            ms(4, 5),
            ms(0, 5)
        );
        drop(map);
        self.read.unmap();
        Ok(())
    }
}
