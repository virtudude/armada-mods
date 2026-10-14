struct Out { @builtin(position) position:vec4f, @location(0) uv:vec2f, @location(1) color:vec4f };
@vertex fn vs_main(@location(0) position:vec2f,@location(1) uv:vec2f,@location(2) color:vec4f)->Out {
 var o:Out; o.position=vec4f(position,0,1);o.uv=uv;o.color=color;return o;
}
@group(0) @binding(0) var picture:texture_2d<f32>;
@group(0) @binding(1) var image_sampler:sampler;
@fragment fn fs_main(i:Out)->@location(0) vec4f { return textureSample(picture,image_sampler,i.uv)*i.color; }
