using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewValley;
using StardewValley.Locations;
using StardewValley.Menus;

namespace ArmadaStardew;

// JunimoNoteMenu.setUpMenu changes quests, mail, area completion and rewards.
// Read the same save-owned BundleData and deposited flags without creating it.
internal sealed class CommunityPages
{
    private readonly Assets art;
    private object? snapshot;
    private long snapshotTime;
    public CommunityPages(Assets art) => this.art = art;
    public void Invalidate() => snapshot = null;

    public object Skin()
    {
        var note = Game1.content.Load<Texture2D>("LooseSprites\\JunimoNote");
        return new
        {
            overview = art.Get(note, new Rectangle(0, 0, 320, 180)),
            detail = art.Get(note, new Rectangle(320, 0, 320, 180)),
            slot = art.Get(note, new Rectangle(512, 244, 18, 18)),
            tab = art.Get(Game1.mouseCursors, new Rectangle(331, 374, 15, 14))
        };
    }

    private sealed class Ingredient
    {
        public string id { get; init; } = "";
        public string name { get; init; } = "";
        public Sprite? image { get; init; }
        public int count { get; init; }
        public int quality { get; init; }
        public bool donated { get; init; }
        public int held { get; init; }
        public bool ready => !donated && held >= count;
        public bool money { get; init; }
    }
    private sealed class BundleInfo
    {
        public int id { get; init; }
        public string name { get; init; } = "";
        public Sprite? image { get; init; }
        public int required { get; init; }
        public int donated => ingredients.Count(i => i.donated);
        public bool complete => donated >= required;
        public bool rewardAvailable { get; init; }
        public object? reward { get; init; }
        public List<Ingredient> ingredients { get; } = new();
    }
    private sealed class Room
    {
        public int id { get; init; }
        public string name { get; init; } = "";
        public bool unlocked { get; init; }
        public bool complete { get; init; }
        public string reward { get; init; } = "";
        public List<BundleInfo> bundles { get; init; } = new();
    }

    public object Snapshot()
    {
        long now = Environment.TickCount64;
        if (snapshot != null && now - snapshotTime < 1000) return snapshot;
        var p = Game1.player;
        var center = Game1.getLocationFromName("CommunityCenter") as CommunityCenter;
        bool joja = Game1.MasterPlayer.hasOrWillReceiveMail("JojaMember");
        bool readable = p.hasOrWillReceiveMail("canReadJunimoText");
        var rooms = new List<Room>();
        string status = joja ? "joja" : !readable || center == null ? "locked" : "active";
        string message = joja ? "Joja Community Development has replaced the Community Centre bundles."
            : !readable ? "The Junimo writing is still unreadable. Follow the Community Centre story to unlock the bundles."
            : center == null ? "The Community Centre is unavailable." : "Bundle progress and matching items in your backpack.";
        if (!joja && readable && center != null)
        {
            var note = Game1.content.Load<Texture2D>("LooseSprites\\JunimoNote");
            var data = Game1.netWorldState.Value.BundleData;
            for (int area = 0; area <= 6; area++)
            {
                // The Missing Bundle is visible only once discovered in-game.
                if (area == 6 && !p.hasOrWillReceiveMail("hasSeenAbandonedJunimoNote")) continue;
                string areaName = CommunityCenter.getAreaNameFromNumber(area);
                bool complete = area < center.areasComplete.Count && center.areasComplete[area];
                bool unlocked = complete || center.shouldNoteAppearInArea(area);
                var bundles = new List<BundleInfo>();
                if (unlocked)
                {
                    foreach (var pair in data)
                    {
                        string[] key = pair.Key.Split('/');
                        if (key.Length < 2 || key[0] != areaName || !int.TryParse(key[1], out int id)) continue;
                        if (!center.bundles.TryGetValue(id, out var flags)) continue;
                        var bundle = ParseBundle(id, pair.Value, flags, area == 4, note, center);
                        if (bundle != null) bundles.Add(bundle);
                    }
                }
                rooms.Add(new Room { id = area, name = CommunityCenter.getAreaDisplayNameFromNumber(area),
                    unlocked = unlocked, complete = complete || bundles.Count > 0 && bundles.All(b => b.complete),
                    reward = unlocked ? AreaReward(area) : "", bundles = bundles });
            }
            if (rooms.Count >= 6 && rooms.Where(r => r.id < 6).All(r => r.complete)) status = "complete";
        }
        snapshotTime = now;
        return snapshot = new { status, message, rooms };
    }

    private BundleInfo? ParseBundle(int id, string raw, bool[] flags, bool money, Texture2D note, CommunityCenter center)
    {
        string[] fields = raw.Split('/');
        if (fields.Length < 4) return null;
        string[] tokens = ArgUtility.SplitBySpace(fields[2]);
        int count = tokens.Length / 3;
        int slots = fields.Length > 4 && int.TryParse(fields[4], out int parsed) ? parsed : count;
        var bundle = new BundleInfo { id = id, name = fields.Length > 6 && fields[6].Length > 0 ? fields[6] : fields[0],
            required = slots, image = BundleImage(id, fields.Length > 5 ? fields[5] : "", note),
            reward = Reward(fields[1]), rewardAvailable = center.bundleRewards.TryGetValue(id, out bool available) && available };
        for (int i = 0; i < count; i++)
        {
            if (!int.TryParse(tokens[i * 3 + 1], out int stack) || !int.TryParse(tokens[i * 3 + 2], out int quality)) continue;
            string itemId = tokens[i * 3];
            bool done = i < flags.Length && flags[i];
            if (money)
            {
                bundle.ingredients.Add(new Ingredient { id = itemId, name = "Gold", count = stack, donated = done,
                    held = Game1.player.Money, money = true });
                continue;
            }
            var ingredient = new BundleIngredientDescription(itemId, stack, quality, done, null);
            string representative = JunimoNoteMenu.GetRepresentativeItemId(ingredient);
            var itemData = ItemRegistry.GetDataOrErrorItem(representative);
            string name = itemData.DisplayName;
            // Same category labels as JunimoNoteMenu.setUpBundleSpecificPage.
            int stringKey = ingredient.category switch { -2 => 569, -75 => 570, -4 => 571, -5 => 572, -6 => 573, _ => 0 };
            if (stringKey != 0) name = Game1.content.LoadString("Strings\\StringsFromCSFiles:CraftingRecipe.cs." + stringKey);
            int held = Game1.player.Items.Where(item => item != null && item.Quality >= quality &&
                (ingredient.category.HasValue ? item.Category == ingredient.category.Value
                    || ingredient.category.Value == -5 && item.QualifiedItemId == "(O)107"
                    : ItemRegistry.HasItemId(item, ingredient.id))).Sum(item => item.Stack);
            bundle.ingredients.Add(new Ingredient { id = itemId, name = name,
                image = art.Get(itemData.GetTexture(), itemData.GetSourceRect()), count = stack, quality = quality,
                donated = done, held = held });
        }
        return bundle;
    }

    private Sprite? BundleImage(int index, string spriteOverride, Texture2D note)
    {
        Texture2D texture = note;
        int y = 180;
        if (!string.IsNullOrWhiteSpace(spriteOverride))
        {
            string[] parts = spriteOverride.Split(':', 2);
            if (int.TryParse(parts[^1], out int overridden))
            {
                index = overridden;
                if (parts.Length == 2) { texture = Game1.content.Load<Texture2D>(parts[0]); y = 0; }
            }
        }
        return art.Get(texture, new Rectangle(index * 32 % texture.Width, y + index * 32 / texture.Width * 32, 32, 32));
    }

    private object? Reward(string description)
    {
        if (string.IsNullOrWhiteSpace(description)) return null;
        // This factory creates a detached item; it does not give it to the farmer.
        #pragma warning disable CS0618 // BundleData still uses this legacy reward format in Stardew 1.6.
        var item = Utility.getItemFromStandardTextDescription(description, Game1.player, ' ');
        #pragma warning restore CS0618
        if (item == null) return null;
        var data = ItemRegistry.GetDataOrErrorItem(item.QualifiedItemId);
        return new { name = item.DisplayName, count = item.Stack, image = art.Get(data.GetTexture(), data.GetSourceRect()) };
    }

    private static string AreaReward(int area)
    {
        string key = area switch { 0 => "Pantry", 1 => "Crafts", 2 => "FishTank", 3 => "Boiler", 4 => "Vault", 5 => "Bulletin", _ => "" };
        return key.Length == 0 ? "" : Game1.content.LoadString("Strings\\UI:JunimoNote_Reward" + key);
    }
}
