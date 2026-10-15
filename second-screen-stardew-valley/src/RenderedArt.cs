using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewValley;
using StardewValley.BellsAndWhistles;

namespace ArmadaStardew;

// Reuse the small native UI renderers, without constructing a menu (which halts
// the farmer), changing the active menu, or reading either screen's framebuffer.
internal sealed class RenderedArt
{
    private readonly string directory;
    private readonly Dictionary<string, (string fingerprint, Sprite sprite)> cache = new();
    private long revision;
    public RenderedArt(string directory) => this.directory = directory;
    public void Invalidate() => cache.Clear();

    private Sprite Draw(string id, string fingerprint, int width, int height, Action<SpriteBatch> draw)
    {
        if (cache.TryGetValue(id, out var existing) && existing.fingerprint == fingerprint) return existing.sprite;
        var device = Game1.graphics.GraphicsDevice;
        var targets = device.GetRenderTargets();
        var viewport = device.Viewport;
        var scissor = device.ScissorRectangle;
        var blend = device.BlendState;
        var depth = device.DepthStencilState;
        var rasterizer = device.RasterizerState;
        var sampler = device.SamplerStates[0];
        var texture = device.Textures[0];
        bool drawingUi = FarmerRenderer.isDrawingForUI;
        using var target = new RenderTarget2D(device, width, height, false, SurfaceFormat.Color, DepthFormat.None);
        using var batch = new SpriteBatch(device);
        try
        {
            device.SetRenderTarget(target);
            device.Clear(Color.Transparent);
            FarmerRenderer.isDrawingForUI = true;
            batch.Begin(SpriteSortMode.Deferred, BlendState.AlphaBlend, SamplerState.PointClamp, DepthStencilState.None, RasterizerState.CullNone);
            draw(batch);
            batch.End();
            device.SetRenderTargets(targets);
            long version = ++revision;
            string name = $"rendered-{id}-{version % 2}.png";
            string path = Path.Combine(directory, name);
            using (var stream = File.Create(path + ".tmp")) target.SaveAsPng(stream, width, height);
            File.Move(path + ".tmp", path, true);
            var sprite = new Sprite { path = $"overlay/Mods/ArmadaSecondScreen/assets/{name}?v={version}", w = width, h = height };
            cache[id] = (fingerprint, sprite);
            return sprite;
        }
        finally
        {
            FarmerRenderer.isDrawingForUI = drawingUi;
            device.SetRenderTargets(targets);
            device.Viewport = viewport; device.ScissorRectangle = scissor;
            device.BlendState = blend; device.DepthStencilState = depth;
            device.RasterizerState = rasterizer; device.SamplerStates[0] = sampler;
            device.Textures[0] = texture;
        }
    }

    public Sprite Item(string id, Item item) => Draw(id, $"{item.QualifiedItemId}:{item.Stack}:{item.Quality}:{item.GetType()}:{System.Runtime.CompilerServices.RuntimeHelpers.GetHashCode(item)}:{(item as StardewValley.Objects.Clothing)?.clothesColor.Value}", 64, 64,
        batch => item.drawInMenu(batch, Vector2.Zero, 1f));

    public Sprite MapFace()
    {
        var p = Game1.player;
        string fingerprint = $"{p.UniqueMultiplayerID}:{p.Gender}:{p.hair.Value}:{p.skin.Value}:{p.hairstyleColor.Value}:{p.newEyeColor.Value}";
        return Draw("map-face", fingerprint, 72, 72, batch =>
            p.FarmerRenderer.drawMiniPortrat(batch, new Vector2(4, 8), .8f, 4f, 2, p, 1f));
    }

    public Sprite QuestTitle(string id, string title)
    {
        // SpriteText wraps at >= width, including its next-word lookahead.
        // Leave a glyph of padding beyond the measured text, as QuestLog does.
        int width = Math.Clamp(SpriteText.getWidthOfString(title) + 48, 1, 960);
        int height = Math.Max(1, SpriteText.getHeightOfString(title, width));
        return Draw("quest-" + id, title, width, height,
            batch => SpriteText.drawString(batch, title, 0, 0, width: width));
    }

    public Sprite Portrait()
    {
        var p = Game1.player;
        bool night = Game1.timeOfDay >= 1900;
        var background = night ? Game1.nightbg : Game1.daybg;
        string fingerprint = $"{p.UniqueMultiplayerID}:{night}:{p.Gender}:{p.hair.Value}:{p.skin.Value}:{p.hairstyleColor.Value}:{p.newEyeColor.Value}:{p.bathingClothes.Value}:{p.hat.Value?.QualifiedItemId}:{p.shirt.Value}:{p.pants.Value}:{p.pantsColor.Value}:{p.shirtItem.Value?.QualifiedItemId}:{p.shirtItem.Value?.clothesColor.Value}:{p.pantsItem.Value?.QualifiedItemId}:{p.pantsItem.Value?.clothesColor.Value}:{p.boots.Value?.QualifiedItemId}";
        return Draw("farmer", fingerprint, background.Width, background.Height, batch =>
        {
            batch.Draw(background, Vector2.Zero, Color.White);
            int frame = p.bathingClothes.Value ? 108 : 0;
            var animation = new FarmerSprite.AnimationFrame(0, frame, false, false, null, false);
            var source = new Rectangle(0, p.bathingClothes.Value ? 576 : 0, 16, 32);
            p.FarmerRenderer.draw(batch, animation, frame, source, new Vector2(32, 32), Vector2.Zero, .8f, 2, Color.White, 0f, 1f, p);
            if (night) p.FarmerRenderer.draw(batch, animation, frame, source, new Vector2(32, 32), Vector2.Zero, .8f, 2, Color.DarkBlue * .3f, 0f, 1f, p);
        });
    }
}
