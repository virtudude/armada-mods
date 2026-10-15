using StardewModdingAPI;
using StardewValley;
using StardewValley.WorldMaps;

namespace ArmadaStardew;

// Use the world's live characters, never their schedules or event duplicates.
// WorldMapManager applies the same interior/exterior mapping as the farmer pin.
internal sealed class NpcMap
{
    private readonly Assets art;
    private readonly IMonitor monitor;
    private readonly HashSet<string> warned = new(StringComparer.Ordinal);
    private object? snapshot;
    private long snapshotTime;

    public NpcMap(Assets art, IMonitor monitor) { this.art = art; this.monitor = monitor; }
    public void Invalidate() { snapshot = null; warned.Clear(); }

    public object Snapshot()
    {
        long now = Environment.TickCount64;
        if (snapshot != null && now - snapshotTime < 1000) return snapshot;
        var markers = new List<object>();
        var seen = new HashSet<string>(StringComparer.Ordinal);
        try
        {
            // Native ForEachVillager excludes monsters, pets, horses and farmer
            // children through IsVillager, and excludes EventActor when false.
            Utility.ForEachVillager(npc =>
            {
                try
                {
                    string id = npc.Name;
                    if (string.IsNullOrEmpty(id) || !Game1.player.friendshipData.ContainsKey(id)
                        || seen.Contains(id) || npc.currentLocation == null) return true;
                    var position = WorldMapManager.GetPositionData(npc.currentLocation, npc.TilePoint);
                    if (position == null) return true;
                    var pixel = position.Value.GetMapPixelPosition();
                    if (!float.IsFinite(pixel.X) || !float.IsFinite(pixel.Y)) return true;
                    // Keep the data-defined head anchor (including the native
                    // child-villager offset), omitting the social mugshot torso.
                    var head = npc.getMugShotSourceRect();
                    head.Height = Math.Min(16, head.Height);
                    var image = art.Get(npc.Sprite.Texture, head);
                    if (image == null) return true;
                    markers.Add(new { id, name = npc.displayName,
                        location = npc.currentLocation.DisplayName,
                        region = position.Value.Data.Region.Id, x = pixel.X, y = pixel.Y, image });
                    seen.Add(id);
                }
                catch (Exception ex)
                {
                    // One content-mod character with missing art/mapping must
                    // never interrupt the companion's remaining state stream.
                    Warn(npc.Name ?? "unknown", ex);
                }
                return true;
            }, false);
        }
        catch (Exception ex) { Warn("map enumeration", ex); }
        snapshotTime = now;
        return snapshot = markers.ToArray();
    }

    private void Warn(string id, Exception error)
    {
        if (warned.Add(id)) monitor.Log($"Couldn't place NPC map marker for {id}: {error.Message}", LogLevel.Trace);
    }
}
