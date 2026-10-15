using StardewModdingAPI;
using StardewValley;
using StardewValley.Menus;

namespace ArmadaStardew;

internal static class InventoryMoves
{
    public static bool Allowed()
    {
        if (!Context.IsWorldReady || Context.IsMultiplayer || Game1.eventUp || Game1.fadeToBlack
            || Game1.player.UsingTool || Game1.player.CursorSlotItem != null || Game1.player.TemporaryItem != null)
            return false;
        var menu = Game1.activeClickableMenu;
        if (menu == null) return Game1.player.CanMove;
        // Allow rearranging while the ordinary inventory pauses the farm, but
        // never alongside a chest, shop, dialogue, or item on the game's cursor.
        return menu.GetType() == typeof(GameMenu) && menu.GetChildMenu() == null
            && ((GameMenu)menu).GetCurrentPage() is InventoryPage page && page.GetChildMenu() == null;
    }

    public static string Move(int from, int to, Action<Exception> reportEffectError)
    {
        var p = Game1.player;
        var source = p.Items[from];
        var target = p.Items[to];
        int sourceCount = source.Stack, targetCount = target?.Stack ?? 0;
        // InventoryMenu's native stack/swap routine, on a separate slot list.
        // Passing player.Items would also call OnItemReceived for existing items.
        var slots = new List<Item> { source, target! };
        Item? oldHeld = null, newHeld = null;
        try
        {
            var held = Utility.removeItemFromInventory(0, slots);
            slots[0] = Utility.addItemToInventory(held, 1, slots);

            bool changed = !ReferenceEquals(source, slots[0]) || !ReferenceEquals(target, slots[1])
                || source.Stack != sourceCount || (target?.Stack ?? 0) != targetCount;
            if (!changed) return "That stack is already full.";

            // Preserve the selected slot, just like moving items in InventoryPage.
            bool affectsHeld = p.CurrentToolIndex == from || p.CurrentToolIndex == to;
            oldHeld = affectsHeld ? p.Items[p.CurrentToolIndex] : null;
            newHeld = p.CurrentToolIndex == from ? slots[0] : p.CurrentToolIndex == to ? slots[1] : null;
            if (!ReferenceEquals(oldHeld, newHeld)) oldHeld?.actionWhenStopBeingHeld(p);
            p.Items[from] = slots[0];
            p.Items[to] = slots[1];
        }
        catch
        {
            // Native merging changes Stack on shared item objects. Restore both
            // objects and slots if preparation or the old held-item hook fails.
            source.Stack = sourceCount;
            if (target != null) target.Stack = targetCount;
            p.Items[from] = source; p.Items[to] = target;
            throw;
        }
        // The inventory is committed. A presentation/audio failure must not
        // turn a successful move into a timeout which invites a retry.
        try { if (!ReferenceEquals(oldHeld, newHeld)) newHeld?.actionWhenBeingHeld(p); }
        catch (Exception ex) { reportEffectError(ex); }
        try { Game1.playSound("stoneStep"); }
        catch (Exception ex) { reportEffectError(ex); }
        return target == null ? "Moved " + source.DisplayName
            : ReferenceEquals(target, slots[1]) ? "Combined stacks" : "Swapped items";
    }
}
