using Microsoft.Xna.Framework;
using Microsoft.Xna.Framework.Graphics;
using StardewValley;
using StardewValley.Extensions;
using StardewValley.GameData.Objects;
using StardewValley.ItemTypeDefinitions;
using StardewValley.Locations;
using StardewValley.TokenizableStrings;
using System.Text.RegularExpressions;

namespace ArmadaStardew;

// Read-only equivalents of CollectionsPage and PowersTab's data population.
// Never construct those menus: their base constructor halts the farmer, and
// CollectionsPage's note-description helper reveals gift tastes as a side effect.
internal sealed class CollectionPages
{
    private readonly Assets art;
    private object? collections;
    private object? powers;
    private long collectionTime, powerTime;
    public CollectionPages(Assets art) => this.art = art;
    public void Invalidate() { collections = powers = null; }

    private sealed class Entry
    {
        public string id { get; init; } = "";
        public string name { get; init; } = "???";
        public string description { get; init; } = "";
        public bool unlocked { get; init; }
        public bool known { get; init; }
        public bool completed => unlocked;
        public Sprite? image { get; init; }
        public Sprite? badge { get; init; }
        public Sprite? detailImage { get; init; }
        public int? count { get; init; }
    }
    private sealed class Category
    {
        public string id { get; init; } = "";
        public string name { get; init; } = "";
        public Sprite? image { get; init; }
        public List<Entry> entries { get; } = new();
        public int unlocked => entries.Count(e => e.unlocked);
        public int total => entries.Count;
    }

    private Sprite? Cursor(int x, int y, int w = 16, int h = 16) => art.Get(Game1.mouseCursors, new Rectangle(x, y, w, h));
    private Sprite? ItemImage(string id)
    {
        var data = ItemRegistry.GetDataOrErrorItem(id);
        return art.Get(data.GetTexture(), data.GetSourceRect());
    }
    public object SnapshotSpecialItems()
    {
        long now = Environment.TickCount64;
        if (powers != null && now - powerTime < 3000) return powers;
        var entries = new List<Entry>();
        foreach (var pair in DataLoader.Powers(Game1.content))
        {
            var data = pair.Value;
            bool unlocked = GameStateQuery.CheckConditions(data.UnlockedCondition);
            entries.Add(new Entry
            {
                id = pair.Key, unlocked = unlocked, known = unlocked,
                name = unlocked ? TokenParser.ParseText(data.DisplayName) ?? pair.Key : "???",
                description = unlocked ? TokenParser.ParseText(data.Description) ?? "" : "",
                image = art.Get(Game1.content.Load<Texture2D>(data.TexturePath), new Rectangle(data.TexturePosition.X, data.TexturePosition.Y, 16, 16))
            });
        }
        powerTime = now;
        return powers = new { entries, unlocked = entries.Count(e => e.unlocked), total = entries.Count };
    }

    public object SnapshotCollections()
    {
        long now = Environment.TickCount64;
        if (collections != null && now - collectionTime < 3000) return collections;
        var p = Game1.player;
        string[] ids = { "shipped", "fish", "artifacts", "minerals", "cooking", "achievements", "letters", "notes" };
        string[] labels = { "Shipped", "Fish", "Artifacts", "Minerals", "Cooking", "Achievements", "Letters", "SecretNotes" };
        Point[] icons = { new(640,80), new(640,64), new(656,64), new(672,64), new(688,64), new(656,80), new(688,80), new(672,80) };
        var categories = ids.Select((id, i) => new Category { id = id,
            name = Game1.content.LoadString("Strings\\UI:Collections_" + labels[i]), image = Cursor(icons[i].X, icons[i].Y) }).ToList();

        // Same atlas order and legacy preserve-item positions as CollectionsPage.
        var items = ItemRegistry.GetObjectTypeDefinition().GetAllData().OrderBy(d => d.TextureName).ThenBy(d => d.SpriteIndex).ToList();
        var preserves = new List<ParsedItemData>();
        for (int i = items.Count - 1; i >= 0 && preserves.Count < 4; i--)
            if (items[i].InternalName is "Wine" or "Pickles" or "Jelly" or "Juice") { preserves.Add(items[i]); items.RemoveAt(i); }
        preserves.Sort((a, b) => a.InternalName.CompareTo(b.InternalName));
        if (preserves.Count == 4)
        {
            items.Insert(Math.Min(278, items.Count), preserves[2]);
            items.Insert(Math.Min(279, items.Count), preserves[0]);
            items.Insert(Math.Min(283, items.Count), preserves[3]);
            items.Insert(Math.Min(284, items.Count), preserves[1]);
        }
        else items.AddRange(preserves);
        foreach (var d in items)
        {
            int tab, count = 0;
            bool unlocked, known;
            string countKey;
            if (d.ObjectType == "Arch")
            {
                tab = 2; unlocked = LibraryMuseum.HasDonatedArtifact(d.ItemId);
                if (p.archaeologyFound.TryGetValue(d.ItemId, out var found) && found.Length > 0) count = found[0];
                countKey = "ArtifactsFound";
            }
            else if (d.ObjectType == "Fish")
            {
                if (d.RawData is ObjectData { ExcludeFromFishingCollection: true }) continue;
                tab = 1; unlocked = p.fishCaught.TryGetValue(d.QualifiedItemId, out var found);
                if (found?.Length > 0) count = found[0];
                countKey = "FishCaught";
            }
            else if (d.ObjectType == "Minerals" || d.Category == -2)
            {
                tab = 3; unlocked = LibraryMuseum.HasDonatedArtifact(d.ItemId);
                p.mineralsFound.TryGetValue(d.ItemId, out count); countKey = "MineralsFound";
            }
            else if (d.ObjectType == "Cooking" || d.Category == -7)
            {
                if (d.ItemId is "217" or "772" or "773" or "279" or "873") continue;
                tab = 4; unlocked = p.recipesCooked.TryGetValue(d.ItemId, out count); countKey = "RecipesCooked";
            }
            else
            {
                if (!StardewValley.Object.isPotentialBasicShipped(d.ItemId, d.Category, d.ObjectType)) continue;
                tab = 0; unlocked = p.basicShipped.TryGetValue(d.ItemId, out count); countKey = "NumberShipped";
            }
            known = unlocked || (tab == 4 && p.cookingRecipes.ContainsKey(RecipeName(d.InternalName)));
            string name = "???", description = "";
            if (known)
            {
                name = Game1.content.LoadStringReturnNullIfNotFound("Strings\\Objects:" + d.ItemId + "_CollectionsTabName") ?? d.DisplayName;
                description = Game1.content.LoadStringReturnNullIfNotFound("Strings\\Objects:" + d.ItemId + "_CollectionsTabDescription") ?? d.Description;
                description += "\n\n" + Game1.content.LoadString("Strings\\UI:Collections_Description_" + countKey, count);
                if (tab == 1 && p.fishCaught.TryGetValue(d.QualifiedItemId, out var fish) && fish.Length > 1 && fish[1] > 0)
                    description += "\n" + Game1.content.LoadString("Strings\\UI:Collections_Description_BiggestCatch", Game1.content.LoadString("Strings\\StringsFromCSFiles:FishingRod.cs.14083", LocalizedContentManager.CurrentLanguageCode == LocalizedContentManager.LanguageCode.en ? fish[1] : Math.Round(fish[1] * 2.54)));
            }
            categories[tab].entries.Add(new Entry { id = d.QualifiedItemId, name = name, description = description,
                unlocked = unlocked, known = known, count = known ? count : null, image = art.Get(d.GetTexture(), d.GetSourceRect()) });
        }
        foreach (var pair in Game1.achievements)
        {
            string[] parts = pair.Value.Split('^');
            bool earned = p.achievements.Contains(pair.Key);
            bool known = earned || (parts.Length > 3 && parts[2] == "true" && (parts[3] == "-1" || parts[3].Split(' ', StringSplitOptions.RemoveEmptyEntries).All(id => int.TryParse(id, out int n) && p.achievements.Contains(n))));
            int badge = Utility.CreateRandom(pair.Key).Next(12);
            categories[5].entries.Add(new Entry { id = pair.Key.ToString(), known = known, unlocked = earned,
                name = known ? parts[0] : "???", description = known && parts.Length > 1 ? parts[1] : "",
                image = art.Get(Game1.mouseCursors, Game1.getSourceRectForStandardTileSheet(Game1.mouseCursors, 25)),
                badge = earned ? Cursor(256 + badge % 6 * 32, 128 + badge / 6 * 32, 32, 32) : null });
        }
        var mail = DataLoader.Mail(Game1.content);
        foreach (string id in p.mailReceived)
        {
            if (!mail.TryGetValue(id, out string? text)) continue;
            string[] parts = text.Split("[#]");
            categories[6].entries.Add(new Entry { id = id, unlocked = true, known = true,
                name = parts.Length > 1 ? parts[1] : "???", description = ReadText(parts[0]), image = Cursor(190, 423, 14, 11) });
        }
        if (p.secretNotesSeen.Count > 0)
        {
            bool journals = p.secretNotesSeen.Contains(GameLocation.JOURNAL_INDEX + 1);
            foreach (var pair in DataLoader.SecretNotes(Game1.content))
            {
                bool journal = pair.Key >= GameLocation.JOURNAL_INDEX;
                if (journal ? !journals : !p.hasMagnifyingGlass) continue;
                bool seen = p.secretNotesSeen.Contains(pair.Key);
                Sprite? detail = null;
                string description = "";
                if (seen)
                {
                    if (pair.Value.StartsWith("!"))
                    {
                        if (int.TryParse(pair.Value.Split(' ', StringSplitOptions.RemoveEmptyEntries).ElementAtOrDefault(1), out int index))
                        {
                            var texture = Game1.content.Load<Texture2D>("TileSheets\\SecretNotesImages");
                            detail = art.Get(texture, new Rectangle(index * 64 % texture.Width, index * 64 / texture.Width * 64, 64, 64));
                        }
                    }
                    else description = ReadText(pair.Value);
                }
                categories[7].entries.Add(new Entry { id = pair.Key.ToString(), unlocked = seen, known = seen,
                    name = seen ? Game1.content.LoadString("Strings\\Locations:" + (journal ? "Journal_Name" : "Secret_Note_Name")) + " #" + (journal ? pair.Key - GameLocation.JOURNAL_INDEX : pair.Key) : "???",
                    description = description, image = ItemImage(journal ? "(O)842" : "(O)79"), detailImage = detail });
            }
        }
        else categories.RemoveAt(7);
        collectionTime = now;
        return collections = new { categories };
    }

    private static string RecipeName(string name) => name switch
    {
        "Cheese Cauli." => "Cheese Cauliflower", "Cheese Cauliflower" => "Cheese Cauli.",
        "Vegetable Medley" => "Vegetable Stew", "Cookie" => "Cookies", "Eggplant Parmesan" => "Eggplant Parm.",
        "Cranberry Sauce" => "Cran. Sauce", "Dish O' The Sea" => "Dish o' The Sea", _ => name
    };
    private static string ReadText(string text)
    {
        // Remove metadata without running the game's mail/reward/gift actions.
        text = Regex.Replace(text, @"%revealtaste:[^\s#%${^*]+", "");
        text = Regex.Replace(text, @"%revealtaste[^\d\r\n]*\d+", "");
        text = Regex.Replace(text, @"%[^%]*%%", "");
        text = Regex.Replace(text, @"\[letterbg\s+[^\]]*\]|\[textcolor\s+[^\]]*\]", "");
        text = Dialogue.applyGenderSwitch(Game1.player.Gender, text, true);
        if (text.Contains("%secretsanta"))
            text = text.Replace("%secretsanta", Game1.season == Season.Winter && Game1.dayOfMonth >= 18 && Game1.dayOfMonth <= 25
                ? Utility.GetRandomWinterStarParticipant()?.displayName ?? "???" : "???");
        return text.Replace("@", Game1.player.Name).Replace("%farm", Game1.player.farmName.Value).Replace('^', '\n').Replace('#', '\n').Trim();
    }
}
