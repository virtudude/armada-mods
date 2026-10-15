// Owned-game static geometry. Lighting is a reconstruction, not Bethesda's material shader.
struct Params { rotation: vec2<f32>, aspect: f32, unused: f32 };
@group(0) @binding(0) var<uniform> params: Params;
@group(1) @binding(0) var diffuse: texture_2d<f32>;
@group(1) @binding(1) var tex_sampler: sampler;
struct Out { @builtin(position) position: vec4<f32>, @location(0) normal: vec3<f32>, @location(1) uv: vec2<f32> };
fn rotate(p: vec3<f32>) -> vec3<f32> {
    return vec3<f32>(p.x*params.rotation.x-p.y*params.rotation.y, p.x*params.rotation.y+p.y*params.rotation.x,p.z);
}
@vertex fn vs_main(@location(0) position: vec3<f32>, @location(1) normal: vec3<f32>, @location(2) uv: vec2<f32>) -> Out {
    let p=rotate(position);
    let h=p.z*0.94-p.y*0.342;
    let d=3.0-(p.y*0.94+p.z*0.342);
    var o: Out;
    o.position=vec4<f32>(p.x*2.3/params.aspect,h*2.3,d*1.010101-0.1010101,d);
    o.normal=rotate(normal);
    o.uv=uv;
    return o;
}
@fragment fn fs_main(i: Out) -> @location(0) vec4<f32> {
    let tex=textureSample(diffuse,tex_sampler,i.uv);
    if tex.a<0.1 { discard; }
    let n=normalize(i.normal);
    let light=0.5+0.7*max(dot(n,normalize(vec3<f32>(-0.3,-0.6,1.0))),0.0);
    let spec=0.2*pow(max(dot(n,normalize(vec3<f32>(-0.1,-1.0,0.6))),0.0),24.0);
    return vec4<f32>((vec3<f32>(0.45)+0.55*sqrt(max(tex.rgb,vec3<f32>(0.0))))*light+vec3<f32>(spec),1.0);
}
