//! Small renderer for game-derived static inventory meshes, before the common CRT pass.
use crate::scene::{HEIGHT, Rect, WIDTH};
use anyhow::{Context, Result, bail};
use bytemuck::{Pod, Zeroable};
use serde_json::Value;
use std::{
    collections::{HashMap, HashSet},
    path::PathBuf,
};
use wgpu::util::DeviceExt;
#[repr(C)]
#[derive(Clone, Copy, Pod, Zeroable)]
struct Vertex {
    position: [f32; 3],
    normal: [f32; 3],
    uv: [f32; 2],
}
struct Part {
    vertices: wgpu::Buffer,
    indices: wgpu::Buffer,
    count: u32,
    texture: wgpu::BindGroup,
}
struct Mesh {
    parts: Vec<Part>,
}
pub struct Models {
    pipeline: wgpu::RenderPipeline,
    texture_layout: wgpu::BindGroupLayout,
    uniform: wgpu::Buffer,
    bind: wgpu::BindGroup,
    sampler: wgpu::Sampler,
    depth: wgpu::TextureView,
    data: PathBuf,
    meshes: HashMap<String, Mesh>,
    failed: HashSet<String>,
    selected: String,
    selected_since: std::time::Instant,
}
fn vector<const N: usize>(v: &Value) -> Result<[f32; N]> {
    let a = v.as_array().context("Expected model vector")?;
    if a.len() != N {
        bail!("Invalid model vector length");
    }
    let mut out = [0.; N];
    for (i, v) in a.iter().enumerate() {
        out[i] = v
            .as_f64()
            .filter(|v| v.is_finite())
            .context("Nonfinite model vertex")? as f32;
    }
    Ok(out)
}
impl Models {
    pub fn new(device: &wgpu::Device, data: PathBuf) -> Self {
        let texture_layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("Model texture"),
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
        let layout = device.create_bind_group_layout(&wgpu::BindGroupLayoutDescriptor {
            label: Some("Model camera"),
            entries: &[wgpu::BindGroupLayoutEntry {
                binding: 0,
                visibility: wgpu::ShaderStages::VERTEX,
                ty: wgpu::BindingType::Buffer {
                    ty: wgpu::BufferBindingType::Uniform,
                    has_dynamic_offset: false,
                    min_binding_size: None,
                },
                count: None,
            }],
        });
        let uniform = device.create_buffer(&wgpu::BufferDescriptor {
            label: Some("Model camera"),
            size: 16,
            usage: wgpu::BufferUsages::UNIFORM | wgpu::BufferUsages::COPY_DST,
            mapped_at_creation: false,
        });
        let bind = device.create_bind_group(&wgpu::BindGroupDescriptor {
            label: None,
            layout: &layout,
            entries: &[wgpu::BindGroupEntry {
                binding: 0,
                resource: uniform.as_entire_binding(),
            }],
        });
        let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
            label: Some("Inventory static mesh"),
            source: wgpu::ShaderSource::Wgsl(include_str!("mesh.wgsl").into()),
        });
        let pl = device.create_pipeline_layout(&wgpu::PipelineLayoutDescriptor {
            label: None,
            bind_group_layouts: &[&layout, &texture_layout],
            push_constant_ranges: &[],
        });
        let attrs = wgpu::vertex_attr_array![0=>Float32x3,1=>Float32x3,2=>Float32x2];
        let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
            label: Some("Inventory model"),
            layout: Some(&pl),
            vertex: wgpu::VertexState {
                module: &shader,
                entry_point: Some("vs_main"),
                compilation_options: Default::default(),
                buffers: &[wgpu::VertexBufferLayout {
                    array_stride: 32,
                    step_mode: wgpu::VertexStepMode::Vertex,
                    attributes: &attrs,
                }],
            },
            fragment: Some(wgpu::FragmentState {
                module: &shader,
                entry_point: Some("fs_main"),
                compilation_options: Default::default(),
                targets: &[Some(wgpu::ColorTargetState {
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    blend: None,
                    write_mask: wgpu::ColorWrites::ALL,
                })],
            }),
            primitive: wgpu::PrimitiveState {
                cull_mode: None,
                ..Default::default()
            },
            depth_stencil: Some(wgpu::DepthStencilState {
                format: wgpu::TextureFormat::Depth32Float,
                depth_write_enabled: true,
                depth_compare: wgpu::CompareFunction::Less,
                stencil: Default::default(),
                bias: Default::default(),
            }),
            multisample: Default::default(),
            multiview: None,
            cache: None,
        });
        let depth = device
            .create_texture(&wgpu::TextureDescriptor {
                label: Some("Inventory model depth"),
                size: wgpu::Extent3d {
                    width: WIDTH as u32,
                    height: HEIGHT as u32,
                    depth_or_array_layers: 1,
                },
                mip_level_count: 1,
                sample_count: 1,
                dimension: wgpu::TextureDimension::D2,
                format: wgpu::TextureFormat::Depth32Float,
                usage: wgpu::TextureUsages::RENDER_ATTACHMENT,
                view_formats: &[],
            })
            .create_view(&Default::default());
        Self {
            pipeline,
            texture_layout,
            uniform,
            bind,
            sampler: device.create_sampler(&wgpu::SamplerDescriptor {
                mag_filter: wgpu::FilterMode::Linear,
                min_filter: wgpu::FilterMode::Linear,
                address_mode_u: wgpu::AddressMode::Repeat,
                address_mode_v: wgpu::AddressMode::Repeat,
                ..Default::default()
            }),
            depth,
            data,
            meshes: HashMap::new(),
            failed: HashSet::new(),
            selected: String::new(),
            selected_since: std::time::Instant::now(),
        }
    }
    fn owned(&self, path: &str) -> Result<PathBuf> {
        let p = self.data.join(path).canonicalize()?;
        if !p.starts_with(self.data.canonicalize()?) {
            bail!("Model path outside runtime data");
        }
        Ok(p)
    }
    fn load(&self, device: &wgpu::Device, queue: &wgpu::Queue, path: &str) -> Result<Mesh> {
        let p = self.owned(path)?;
        if p.metadata()?.len() > 32 * 1024 * 1024 {
            bail!("Model cache too large");
        }
        let v: Value = serde_json::from_slice(&std::fs::read(p)?)?;
        let min = vector::<3>(&v["bounds"]["min"])?;
        let max = vector::<3>(&v["bounds"]["max"])?;
        let center = std::array::from_fn::<_, 3, _>(|i| (min[i] + max[i]) * 0.5);
        let radius = (0..3)
            .map(|i| (max[i] - min[i]).powi(2))
            .sum::<f32>()
            .sqrt()
            * 0.5;
        if !radius.is_finite() || radius <= 0. {
            bail!("Invalid model bounds");
        }
        // Inventory cameras differ from world placement. Stand elongated static
        // objects on their long axis so thin lying meshes remain legible.
        let extents = std::array::from_fn::<_, 3, _>(|i| max[i] - min[i]);
        let longest = (0..3)
            .max_by(|a, b| extents[*a].total_cmp(&extents[*b]))
            .unwrap();
        let orient = |p: [f32; 3]| match longest {
            0 if extents[0] > extents[2] * 1.4 => [-p[2], p[1], p[0]],
            1 if extents[1] > extents[2] * 1.4 => [p[0], -p[2], p[1]],
            _ => p,
        };
        let primitives = v["primitives"]
            .as_array()
            .context("Missing model primitives")?;
        if primitives.len() > 128 {
            bail!("Too many model parts");
        }
        let mut parts = Vec::new();
        for primitive in primitives {
            let positions = primitive["positions"]
                .as_array()
                .context("Missing model positions")?;
            let normals = primitive["normals"]
                .as_array()
                .context("Missing model normals")?;
            let uvs = primitive["uvs"].as_array().context("Missing model UVs")?;
            if positions.len() > 200_000
                || positions.len() != normals.len()
                || positions.len() != uvs.len()
            {
                bail!("Invalid model vertex count");
            }
            let offset = primitive
                .get("uvOffset")
                .map(vector::<2>)
                .transpose()?
                .unwrap_or([0., 0.]);
            let scale = primitive
                .get("uvScale")
                .map(vector::<2>)
                .transpose()?
                .unwrap_or([1., 1.]);
            let mut vertices = Vec::new();
            for ((p, n), uv) in positions.iter().zip(normals).zip(uvs) {
                let p = vector::<3>(p)?;
                let uv = vector::<2>(uv)?;
                vertices.push(Vertex {
                    position: orient(std::array::from_fn(|i| (p[i] - center[i]) / radius)),
                    normal: orient(vector(n)?),
                    uv: [uv[0] * scale[0] + offset[0], uv[1] * scale[1] + offset[1]],
                });
            }
            let indices: Vec<u32> = primitive["indices"]
                .as_array()
                .context("Missing model triangles")?
                .iter()
                .map(|v| {
                    v.as_u64()
                        .filter(|i| *i < vertices.len() as u64)
                        .map(|v| v as u32)
                        .context("Invalid model index")
                })
                .collect::<Result<_>>()?;
            if indices.is_empty() || indices.len() % 3 != 0 || indices.len() > 600_000 {
                bail!("Invalid triangle count");
            }
            let image = if let Some(p) = primitive["diffuse"].as_str() {
                image::open(self.owned(p)?)?.to_rgba8()
            } else {
                image::RgbaImage::from_pixel(1, 1, image::Rgba([220, 220, 220, 255]))
            };
            if image.width() > 2048 || image.height() > 2048 {
                bail!("Model texture too large");
            }
            let texture = device.create_texture_with_data(
                queue,
                &wgpu::TextureDescriptor {
                    label: Some("Owned model diffuse"),
                    size: wgpu::Extent3d {
                        width: image.width(),
                        height: image.height(),
                        depth_or_array_layers: 1,
                    },
                    mip_level_count: 1,
                    sample_count: 1,
                    dimension: wgpu::TextureDimension::D2,
                    format: wgpu::TextureFormat::Rgba8Unorm,
                    usage: wgpu::TextureUsages::TEXTURE_BINDING,
                    view_formats: &[],
                },
                wgpu::util::TextureDataOrder::LayerMajor,
                &image,
            );
            let view = texture.create_view(&Default::default());
            let texture = device.create_bind_group(&wgpu::BindGroupDescriptor {
                label: None,
                layout: &self.texture_layout,
                entries: &[
                    wgpu::BindGroupEntry {
                        binding: 0,
                        resource: wgpu::BindingResource::TextureView(&view),
                    },
                    wgpu::BindGroupEntry {
                        binding: 1,
                        resource: wgpu::BindingResource::Sampler(&self.sampler),
                    },
                ],
            });
            parts.push(Part {
                vertices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("Owned mesh vertices"),
                    contents: bytemuck::cast_slice(&vertices),
                    usage: wgpu::BufferUsages::VERTEX,
                }),
                indices: device.create_buffer_init(&wgpu::util::BufferInitDescriptor {
                    label: Some("Owned mesh triangles"),
                    contents: bytemuck::cast_slice(&indices),
                    usage: wgpu::BufferUsages::INDEX,
                }),
                count: indices.len() as u32,
                texture,
            });
        }
        Ok(Mesh { parts })
    }
    pub fn prepare(&mut self, device: &wgpu::Device, queue: &wgpu::Queue, path: &str) {
        if self.selected != path {
            self.selected = path.to_owned();
            self.selected_since = std::time::Instant::now();
        }
        if self.meshes.contains_key(path) || self.failed.contains(path) {
            return;
        }
        match self.load(device, queue, path) {
            Ok(m) => {
                if self.meshes.len() >= 4 {
                    self.meshes.clear();
                }
                self.meshes.insert(path.into(), m);
            }
            Err(e) => {
                eprintln!("Inventory model {path}: {e:#}");
                self.failed.insert(path.into());
            }
        }
    }
    pub fn draw(
        &self,
        queue: &wgpu::Queue,
        encoder: &mut wgpu::CommandEncoder,
        target: &wgpu::TextureView,
        path: &str,
        rect: Rect,
        _seconds: f32,
    ) {
        let Some(mesh) = self.meshes.get(path) else {
            return;
        };
        let [x, y, w, h] = rect;
        if w <= 0. || h <= 0. || x < 0. || y < 0. || x + w > WIDTH || y + h > HEIGHT {
            return;
        }
        let angle = self.selected_since.elapsed().as_secs_f32() * 0.18 - 0.35;
        queue.write_buffer(
            &self.uniform,
            0,
            bytemuck::cast_slice(&[angle.cos(), angle.sin(), w / h, 0.]),
        );
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("Owned inventory model"),
            color_attachments: &[Some(wgpu::RenderPassColorAttachment {
                view: target,
                resolve_target: None,
                depth_slice: None,
                ops: wgpu::Operations {
                    load: wgpu::LoadOp::Load,
                    store: wgpu::StoreOp::Store,
                },
            })],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &self.depth,
                depth_ops: Some(wgpu::Operations {
                    load: wgpu::LoadOp::Clear(1.),
                    store: wgpu::StoreOp::Discard,
                }),
                stencil_ops: None,
            }),
            ..Default::default()
        });
        pass.set_pipeline(&self.pipeline);
        pass.set_viewport(x, y, w, h, 0., 1.);
        pass.set_scissor_rect(x as u32, y as u32, w as u32, h as u32);
        pass.set_bind_group(0, &self.bind, &[]);
        for part in &mesh.parts {
            pass.set_bind_group(1, &part.texture, &[]);
            pass.set_vertex_buffer(0, part.vertices.slice(..));
            pass.set_index_buffer(part.indices.slice(..), wgpu::IndexFormat::Uint32);
            pass.draw_indexed(0..part.count, 0, 0..1);
        }
    }
}
