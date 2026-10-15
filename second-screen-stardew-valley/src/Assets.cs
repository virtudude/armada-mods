using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewModdingAPI;

namespace ArmadaStardew;

internal sealed class Sprite
{
    public string? path { get; set; }
    public int w { get; init; }
    public int h { get; init; }
}

internal sealed class Assets
{
    private readonly string directory;
    private readonly IMonitor monitor;
    private readonly Dictionary<(Texture2D, Rectangle), Sprite> cache = new();
    private readonly Queue<(Texture2D texture, Rectangle rect, Sprite sprite)> pending = new();
    private int serial;
    public Assets(string directory, IMonitor monitor) { this.directory = directory; this.monitor = monitor; Directory.CreateDirectory(directory); }
    public void Invalidate() { cache.Clear(); pending.Clear(); }
    public static int[] Rect(Rectangle r) => new[] { r.X, r.Y, r.Width, r.Height };
    public Sprite? Get(Texture2D? texture, Rectangle? crop = null)
    {
        if (texture == null || texture.IsDisposed) return null;
        Rectangle rect = Rectangle.Intersect(crop ?? texture.Bounds, texture.Bounds);
        if (rect.Width <= 0 || rect.Height <= 0) return null;
        var key = (texture, rect);
        if (!cache.TryGetValue(key, out var sprite))
        {
            sprite = new Sprite { w = rect.Width, h = rect.Height };
            cache[key] = sprite; pending.Enqueue((texture, rect, sprite));
        }
        return sprite;
    }
    // Read a small number of textures each tick to avoid one large loading hitch.
    public void Tick()
    {
        for (int i = 0; i < 2 && pending.TryDequeue(out var job); i++)
        {
            try
            {
                if (job.texture.IsDisposed) continue;
                var pixels = new Color[job.rect.Width * job.rect.Height];
                if (job.texture.Format == SurfaceFormat.Alpha8)
                {
                    var alpha = new byte[pixels.Length];
                    job.texture.GetData(0, job.rect, alpha, 0, alpha.Length);
                    for (int p = 0; p < pixels.Length; p++) pixels[p] = new Color(255, 255, 255, (int)alpha[p]);
                }
                else if (job.texture.Format == SurfaceFormat.Color)
                    job.texture.GetData(0, job.rect, pixels, 0, pixels.Length);
                else
                {
                    // Sprite fonts can use block-compressed textures. Let the GPU
                    // decode those into RGBA instead of interpreting blocks as pixels.
                    var device = job.texture.GraphicsDevice;
                    var targets = device.GetRenderTargets();
                    var viewport = device.Viewport;
                    var scissor = device.ScissorRectangle;
                    var blend = device.BlendState;
                    var depth = device.DepthStencilState;
                    var rasterizer = device.RasterizerState;
                    var sampler = device.SamplerStates[0];
                    var texture = device.Textures[0];
                    using var target = new RenderTarget2D(device, job.rect.Width, job.rect.Height, false, SurfaceFormat.Color, DepthFormat.None);
                    using var batch = new SpriteBatch(device);
                    try
                    {
                        device.SetRenderTarget(target);
                        device.Clear(Color.Transparent);
                        batch.Begin(SpriteSortMode.Immediate, BlendState.Opaque, SamplerState.PointClamp, DepthStencilState.None, RasterizerState.CullNone);
                        batch.Draw(job.texture, new Rectangle(0, 0, job.rect.Width, job.rect.Height), job.rect, Color.White);
                        batch.End();
                        device.SetRenderTargets(targets);
                        target.GetData(pixels);
                    }
                    finally
                    {
                        device.SetRenderTargets(targets);
                        device.Viewport = viewport; device.ScissorRectangle = scissor;
                        device.BlendState = blend; device.DepthStencilState = depth;
                        device.RasterizerState = rasterizer; device.SamplerStates[0] = sampler;
                        device.Textures[0] = texture;
                    }
                }
                using var cropped = new Texture2D(job.texture.GraphicsDevice, job.rect.Width, job.rect.Height);
                cropped.SetData(pixels);
                string name = $"{++serial}.png";
                string path = Path.Combine(directory, name);
                using (var stream = File.Create(path + ".tmp")) cropped.SaveAsPng(stream, job.rect.Width, job.rect.Height);
                File.Move(path + ".tmp", path, true);
                job.sprite.path = "overlay/Mods/ArmadaSecondScreen/assets/" + name;
            }
            catch (Exception ex) { monitor.Log($"Couldn't export companion art ({job.texture.Format}): " + ex.Message, LogLevel.Warn); }
        }
    }
    public object Font(SpriteFont font) => new
    {
        image = Get(font.Texture), height = font.LineSpacing, spacing = font.Spacing,
        glyphs = font.GetGlyphs().ToDictionary(p => p.Key.ToString(), p => new
        {
            rect = Rect(p.Value.BoundsInTexture), crop = Rect(p.Value.Cropping),
            left = p.Value.LeftSideBearing, right = p.Value.RightSideBearing, width = p.Value.Width
        })
    };
}
