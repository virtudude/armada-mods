using System.Runtime.CompilerServices;
using System.Text.Json;
using Microsoft.Xna.Framework;
using StardewModdingAPI;
using StardewValley;
using StardewValley.WorldMaps;
using StardewValley.Quests;

namespace ArmadaStardew;

public sealed class ModEntry : Mod
{
    private readonly Link link = new();
    private Assets art = null!;
    private RenderedArt rendered = null!;
    private CollectionPages collectionPages = null!;
    private CommunityPages communityPages = null!;
    private NpcMap npcMap = null!;
    private string session = Guid.NewGuid().ToString("N");
    private long revision;
    private object? skin;
    private object? reply;
    private bool warned;
    private readonly HashSet<string> moveRequests = new();
    private readonly Queue<string> moveRequestOrder = new();

    public override void Entry(IModHelper helper)
    {
        art = new Assets(Path.Combine(helper.DirectoryPath, "assets"), Monitor);
        rendered = new RenderedArt(Path.Combine(helper.DirectoryPath, "assets"));
        collectionPages = new CollectionPages(art);
        communityPages = new CommunityPages(art);
        npcMap = new NpcMap(art, Monitor);
        helper.Events.GameLoop.UpdateTicked += (_, e) =>
        {
            while (link.Incoming.TryDequeue(out string? json)) Handle(json);
            art.Tick();
            if (e.IsMultipleOf(15)) Snapshot();
        };
        helper.Events.GameLoop.SaveLoaded += (_, _) => ResetSession();
        helper.Events.GameLoop.ReturnedToTitle += (_, _) => ResetSession();
        helper.Events.Content.AssetsInvalidated += (_, _) => { skin = null; art.Invalidate(); rendered.Invalidate(); collectionPages.Invalidate(); communityPages.Invalidate(); npcMap.Invalidate(); };
        AppDomain.CurrentDomain.ProcessExit += (_, _) => link.Dispose();
        link.Start(message => Monitor.Log(message, LogLevel.Debug));
        Monitor.Log("Field Journal connected through SMAPI events; no Harmony patches.", LogLevel.Info);
    }

    private bool CanSelect() => Context.IsWorldReady && !Context.IsMultiplayer && Game1.activeClickableMenu == null
        && !Game1.eventUp && !Game1.fadeToBlack && Game1.player.CanMove && !Game1.player.UsingTool;
    private static string Key(Item item) => $"{RuntimeHelpers.GetHashCode(item)}:{item.QualifiedItemId}:{item.Stack}:{item.Quality}";
    private void ResetSession()
    {
        session = Guid.NewGuid().ToString("N"); reply = null;
        moveRequests.Clear(); moveRequestOrder.Clear();
        collectionPages.Invalidate();
        communityPages.Invalidate();
        npcMap.Invalidate();
    }
    private bool SlotMatches(JsonElement root, string property, Item? item)
        => root.GetProperty(property).GetString() == (item == null ? null : Key(item));
    private void HandleMove(JsonElement root, string request)
    {
        if (!moveRequests.Add(request)) return;
        moveRequestOrder.Enqueue(request);
        if (moveRequestOrder.Count > 128) moveRequests.Remove(moveRequestOrder.Dequeue());
        bool ok = false;
        string message = "Open the game's backpack or return to normal play to move items.";
        if (InventoryMoves.Allowed() && root.GetProperty("session").GetString() == session)
        {
            int from = root.GetProperty("from").GetInt32(), to = root.GetProperty("to").GetInt32();
            long seen = root.GetProperty("revision").GetInt64();
            var p = Game1.player;
            message = "Your backpack changed. Try the move again.";
            if (from != to && from >= 0 && to >= 0 && from < p.MaxItems && to < p.MaxItems
                && from < p.Items.Count && to < p.Items.Count && seen <= revision && revision - seen <= 12
                && p.Items[from] != null && SlotMatches(root, "fromKey", p.Items[from]) && SlotMatches(root, "toKey", p.Items[to]))
            {
                try
                {
                    message = InventoryMoves.Move(from, to, ex => Monitor.Log("Inventory moved, but its held-item or sound effect failed: " + ex, LogLevel.Warn)); ok = true;
                    Monitor.Log($"Companion inventory move {from + 1} -> {to + 1}: {message}.", LogLevel.Trace);
                }
                catch (Exception ex)
                {
                    message = "The move failed; your items were restored.";
                    Monitor.Log("Companion inventory move was rolled back: " + ex, LogLevel.Error);
                }
            }
        }
        reply = new { request, ok, message }; Snapshot();
    }
    private void Handle(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json); var root = doc.RootElement;
            if (!root.TryGetProperty("action", out var action) || action.GetString() is not ("select" or "move")) return;
            string request = root.GetProperty("request").GetString() ?? "";
            if (request.Length is 0 or > 80) return;
            if (action.GetString() == "move") { HandleMove(root, request); return; }
            string message = "Return to the game before changing tools.";
            bool ok = false;
            if (CanSelect() && root.GetProperty("session").GetString() == session)
            {
                int slot = root.GetProperty("slot").GetInt32();
                long seen = root.GetProperty("revision").GetInt64();
                if (slot >= 0 && slot < Game1.player.Items.Count && seen <= revision && revision - seen <= 12
                    && Game1.player.Items[slot] is Item item && root.GetProperty("key").GetString() == Key(item))
                {
                    Game1.player.CurrentToolIndex = slot;
                    ok = true; message = "Selected " + item.DisplayName;
                    Monitor.Log($"Companion selected inventory slot {slot + 1}.", LogLevel.Trace);
                }
                else message = "Your backpack changed. Tap the item again.";
            }
            reply = new { request, ok, message };
            Snapshot();
        }
        catch (Exception ex) when (ex is JsonException or InvalidOperationException or KeyNotFoundException or FormatException)
        { /* Ignore malformed/stale page messages; never apply a partial action. */ }
    }

    private object? MapLayer(MapAreaTexture? layer) => layer == null ? null : new
    {
        image = art.Get(layer.Texture, layer.SourceRect), rect = Assets.Rect(layer.MapPixelArea)
    };
    private object Maps()
    {
        return WorldMapManager.GetMapRegions().Select(region => new
        {
            id = region.Id,
            layers = new[] { MapLayer(region.GetBaseTexture()) }.Concat(region.GetAreas().SelectMany(a => a.GetTextures()).Select(MapLayer)).Where(x => x != null).ToArray(),
            places = region.GetAreas().SelectMany(a => a.GetTooltips()).Select(t => new { text = t.Text, rect = Assets.Rect(t.GetPixelArea()) }).ToArray()
        }).ToArray();
    }

    private object Profile()
    {
        var p = Game1.player;
        var equipment = new (string id, Item? item, int tile)[] {
            ("Left Ring", p.leftRing.Value, 41), ("Right Ring", p.rightRing.Value, 41),
            ("Boots", p.boots.Value, 40), ("Hat", p.hat.Value, 42),
            ("Shirt", p.shirtItem.Value, 69), ("Pants", p.pantsItem.Value, 68)
        };
        return new {
            portrait = rendered.Portrait(), name = p.Name, farm = p.farmName.Value,
            money = p.Money, totalMoneyEarned = p.totalMoneyEarned, date = Utility.getDateString(),
            equipment = equipment.Select((e, i) => new {
                id = e.id, name = e.item?.DisplayName ?? e.id, description = e.item?.getDescription() ?? "Nothing equipped.",
                image = e.item == null ? null : rendered.Item("equipment-" + i, e.item),
                placeholder = art.Get(Game1.menuTexture, Game1.getSourceRectForStandardTileSheet(Game1.menuTexture, e.tile))
            }).ToArray()
        };
    }

    private static string CssColor(Color color) => $"#{color.R:x2}{color.G:x2}{color.B:x2}";

    private object Quests()
    {
        // Match QuestLog.GetAllQuests without its removal of destroyed entries.
        var p = Game1.player;
        var quests = p.team.specialOrders.Reverse().Cast<IQuest>()
            .Concat(p.questLog.Reverse().Where(q => q != null && !q.destroy.Value).Cast<IQuest>());
        return quests.Where(q => !q.IsHidden()).Select(q =>
        {
            string id = RuntimeHelpers.GetHashCode(q).ToString("x");
            string title = q.GetName();
            var objectives = q.GetObjectiveDescriptions();
            return new { id, title, titleImage = rendered.QuestTitle(id, title), description = q.GetDescription(),
                objectives, objective = string.Join("\n", objectives), completed = q.ShouldDisplayAsComplete(),
                days = q.GetDaysLeft(), timed = q.IsTimedQuest(), isNew = q.ShouldDisplayAsNew() };
        }).ToArray();
    }

    private void Snapshot()
    {
        try
        {
            if (Game1.menuTexture != null && Game1.smallFont != null)
                skin ??= new
                {
                    panel = art.Get(Game1.menuTexture, new Rectangle(0, 256, 60, 60)), font = art.Font(Game1.smallFont),
                    dialogueFont = art.Font(Game1.dialogueFont), textColor = CssColor(Game1.textColor),
                    shadowColor = CssColor(Game1.textShadowDarkerColor),
                    character = CharacterPages.Skin(art),
                    community = communityPages.Skin(),
                    social = new {
                        gift = art.Get(Game1.mouseCursors2, new Rectangle(166, 174, 14, 12)),
                        talk = art.Get(Game1.mouseCursors2, new Rectangle(180, 175, 13, 11)),
                        uncheckedBox = art.Get(Game1.mouseCursors, new Rectangle(227, 425, 9, 9)),
                        checkedBox = art.Get(Game1.mouseCursors, new Rectangle(236, 425, 9, 9))
                    },
                    journalRow = art.Get(Game1.mouseCursors, new Rectangle(384, 396, 15, 15)),
                    questNew = art.Get(Game1.mouseCursors, new Rectangle(317, 410, 23, 9)),
                    questComplete = art.Get(Game1.mouseCursors, new Rectangle(341, 410, 23, 9)),
                    menuAtlas = art.Get(Game1.menuTexture, new Rectangle(0, 0, 256, 256)),
                    landscape = art.Get(Game1.mouseCursors, new Rectangle(0, 886, 639, 148)),
                    sky = art.Get(Game1.mouseCursors, new Rectangle(703, 1912, 1, 264)),
                    scenery = SceneryArt.Skin(art),
                    slot = art.Get(Game1.menuTexture, Game1.getSourceRectForStandardTileSheet(Game1.menuTexture, 10)),
                    lockedSlot = art.Get(Game1.menuTexture, Game1.getSourceRectForStandardTileSheet(Game1.menuTexture, 57)),
                    tabs = new {
                        inventory = art.Get(Game1.mouseCursors, new Rectangle(0, 368, 16, 16)),
                        people = art.Get(Game1.mouseCursors, new Rectangle(32, 368, 16, 16)),
                        map = art.Get(Game1.mouseCursors, new Rectangle(48, 368, 16, 16)),
                        skills = art.Get(Game1.mouseCursors, new Rectangle(16, 368, 16, 16)),
                        animals = art.Get(Game1.mouseCursors_1_6, new Rectangle(257, 246, 16, 16)),
                        special = art.Get(Game1.mouseCursors_1_6, new Rectangle(216, 494, 16, 16)),
                        collections = art.Get(Game1.mouseCursors, new Rectangle(80, 368, 16, 16)),
                        community = art.Get(Game1.mouseCursors, new Rectangle(331, 374, 15, 14)),
                        journal = art.Get(Game1.mouseCursors, new Rectangle(383, 493, 11, 14))
                    },
                    heart = art.Get(Game1.mouseCursors, new Rectangle(211, 428, 7, 6)),
                    emptyHeart = art.Get(Game1.mouseCursors, new Rectangle(218, 428, 7, 6))
                };
            object? world = null;
            bool ready = Context.IsWorldReady;
            if (ready)
            {
                var p = Game1.player;
                var pos = WorldMapManager.GetPositionData(Game1.currentLocation, p.TilePoint);
                var pixel = pos?.GetMapPixelPosition();
                world = new
                {
                    farm = p.farmName.Value, player = p.Name,
                    season = Game1.currentSeason, day = Game1.dayOfMonth, year = Game1.year,
                    location = Game1.currentLocation.DisplayName,
                    region = pos?.Data.Region.Id, x = pixel?.X, y = pixel?.Y,
                    mapFace = rendered.MapFace(),
                    maps = Maps(), npcs = npcMap.Snapshot(), selectedSlot = p.CurrentToolIndex,
                    money = p.Money, inventoryCapacity = p.MaxItems,
                    profile = Profile(),
                    skills = CharacterPages.Skills(art), animals = CharacterPages.Animals(art),
                    specialItems = collectionPages.SnapshotSpecialItems(), collections = collectionPages.SnapshotCollections(),
                    community = communityPages.Snapshot(),
                    inventory = p.Items.Select((item, slot) =>
                    {
                        return new { slot, key = item == null ? null : Key(item), name = item?.DisplayName ?? "Empty slot",
                            count = item?.Stack ?? 0, quality = item?.Quality ?? 0,
                            description = item?.getDescription() ?? "", category = item?.getCategoryName() ?? "",
                            imageRendered = true, image = item == null ? null : rendered.Item("slot-" + slot, item) };
                    }).ToArray(),
                    people = p.friendshipData.Pairs.Select(pair =>
                    {
                        var npc = Game1.getCharacterFromName(pair.Key);
                        var f = pair.Value;
                        return new { id = pair.Key, name = npc?.displayName ?? pair.Key,
                            points = f.Points, hearts = Math.Clamp(f.Points / 250, 0, 14),
                            maxHearts = f.IsMarried() ? 14 : 10,
                            talked = f.TalkedToToday, gifts = f.GiftsThisWeek,
                            status = f.Status.ToString(), birthdaySeason = npc?.Birthday_Season, birthdayDay = npc?.Birthday_Day,
                            birthday = npc?.isBirthday() ?? false,
                            sprite = npc == null ? null : art.Get(npc.Sprite.Texture, npc.getMugShotSourceRect()),
                            portrait = npc == null ? null : art.Get(npc.Portrait, new Rectangle(0, 0, 64, 64)) };
                    }).OrderByDescending(n => n.birthday).ThenByDescending(n => n.points).ThenBy(n => n.name).ToArray(),
                    quests = Quests()
                };
            }
            link.Publish(JsonSerializer.Serialize(new { ready, session, revision = ++revision, skin, world, canSelect = CanSelect(), canMove = InventoryMoves.Allowed(), reply }));
            warned = false;
        }
        catch (Exception ex)
        {
            if (!warned) Monitor.Log("Companion state unavailable: " + ex, LogLevel.Warn);
            warned = true;
            link.Publish(JsonSerializer.Serialize(new { ready = false, session, revision = ++revision, skin, message = "Waiting for the valley…" }));
        }
    }
}
