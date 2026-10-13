using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewValley;

namespace ArmadaStardew;

// Static title-screen scenery only. Never instantiate TitleMenu: its
// constructor changes menu state and consumes the game's random sequence.
internal static class SceneryArt
{
    public static object Skin(Assets art)
    {
        // TitleMenu's own content asset; the exported crops remain local to the
        // player's installation, like the companion's other native artwork.
        var clouds = Game1.content.Load<Texture2D>("Minigames\\Clouds");
        return new
        {
            baseColor = "#4088f8",
            sky = art.Get(Game1.mouseCursors, new Rectangle(703, 1912, 1, 264)),
            clouds = new[]
            {
                art.Get(clouds, new Rectangle(152, 447, 123, 55)),
                art.Get(clouds, new Rectangle(0, 471, 149, 66)),
                art.Get(clouds, new Rectangle(410, 467, 63, 37))
            },
            mountains = art.Get(Game1.mouseCursors, new Rectangle(0, 886, 639, 148)),
            foreground = art.Get(Game1.mouseCursors, new Rectangle(0, 737, 639, 148))
        };
    }
}
