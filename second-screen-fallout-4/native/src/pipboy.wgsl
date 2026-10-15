// Translation of the installed game's Pip-Boy ps_5_0, not an imitation filter.
// Source: shaders011.fxp, DXBC offset 0xbe901c, length 1840 bytes.
// Pack SHA-256: 13569a497f9ba091a2be293859bcf5585ad8faa8fc1d3ad74991b8512eea125b
// DXBC SHA-256: 758036c4e0dd7129f6bc3bb896be5280486a63078cf3993cad21125d7f3074e5
// Native constants: cb2[0].xy inverse source dimensions;
// cb2[1] burst / sweep phase / vertical shudder / brightness;
// cb2[2].y scanline frequency; cb2[3].rgb Pip-Boy colour.
// The host supplies grayscale artwork and extracted Scan/VScan textures.
// Host adaptation: the final alpha is 1 for the opaque second-screen surface.

struct Params {
    source_size: vec2<f32>,
    phase: f32,
    brightness: f32,
    effect_color: vec4<f32>,
    burst: f32,
    shudder: f32,
    frequency: f32,
    unused: f32,
};

@group(0) @binding(0) var source: texture_2d<f32>;
@group(0) @binding(1) var clamp_sampler: sampler;
@group(0) @binding(2) var scan: texture_2d<f32>;
@group(0) @binding(3) var vertical_scan: texture_2d<f32>;
@group(0) @binding(4) var repeat_sampler: sampler;
@group(0) @binding(5) var<uniform> params: Params;

struct VertexOutput {
    @builtin(position) position: vec4<f32>,
    @location(0) uv: vec2<f32>,
};

@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> VertexOutput {
    // Oversized triangle: (-1, 1), (3, 1), (-1, -3).
    // The framebuffer and artwork share top-left UV (0, 0).
    let uv = vec2<f32>(f32((index << 1u) & 2u), f32(index & 2u));
    var output: VertexOutput;
    output.position = vec4<f32>(uv.x * 2.0 - 1.0, 1.0 - uv.y * 2.0, 0.0, 1.0);
    output.uv = uv;
    return output;
}

@fragment
fn fs_main(input: VertexOutput) -> @location(0) vec4<f32> {
    // Native instructions 13-21: wrap the shuddered coordinate once.
    // Keep y==1 at 1; fract() would incorrectly move that edge to y==0.
    var y = input.uv.y + params.shudder;
    if y > 1.0 {
        y -= 1.0;
    }
    if y < 0.0 {
        y += 1.0;
    }
    let uv = vec2<f32>(input.uv.x, y);
    var foreground = textureSample(source, clamp_sampler, uv);

    // Instructions 22-32: both textures modulate existing foreground.
    // VScan is a single clamped travelling band, not a background overlay.
    if params.frequency != 0.0 {
        let scan_uv = vec2<f32>(uv.x, uv.y * params.frequency);
        foreground *= textureSample(scan, repeat_sampler, scan_uv);
    }
    let sweep_uv = vec2<f32>(uv.x, (uv.y - params.phase) * 3.0);
    let sweep = textureSample(vertical_scan, clamp_sampler, sweep_uv).r;
    foreground = foreground * sweep + foreground;

    // Instructions 33-63: the original 25 source samples and weights.
    // The first tap is -2.5 steps, not -2.  Preserve this half-step offset,
    // the x-outer/y-inner accumulation order, and burst-scaled amplitude.
    let burst_scale = params.burst + 1.0;
    let texel_step = (vec2<f32>(1.0) / params.source_size) * 3.0;
    let start = uv - (texel_step * burst_scale) * 2.5;
    var sum = vec4<f32>(0.0);
    var sample_x = start.x;
    for (var x = 0u; x < 5u; x += 1u) {
        var sample_y = start.y;
        for (var j = 0u; j < 5u; j += 1u) {
            sum += textureSample(source, clamp_sampler, vec2<f32>(sample_x, sample_y));
            sample_y = texel_step.y * burst_scale + sample_y;
        }
        sample_x = texel_step.x * burst_scale + sample_x;
    }

    // Instructions 64-67: 60% direct signal + 40% box-average at burst 0.
    // Luminance conversion comes before the player's selected Pip-Boy tint.
    let glow = (sum * burst_scale) * 0.016;
    let mixed = foreground * 0.6 + glow;
    let luminance = dot(mixed.rgb, vec3<f32>(0.3, 0.59, 0.11));
    return vec4<f32>((luminance * params.effect_color.rgb) * params.brightness, 1.0);
}
