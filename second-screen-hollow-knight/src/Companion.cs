using System;
using System.Collections.Generic;
using System.Text;
using TeamCherry.Localization;
using UnityEngine;

namespace ArmadaSecondScreen
{
    // Charms and inventory for the view, with art from the game's sprites, and equipping at a bench.
    static class Companion
    {
        static string Esc(string s)
        {
            if (s == null) return "";
            var sb = new StringBuilder(s.Length + 8);
            foreach (char c in s.Replace("<br>", " "))
            {
                if (c == '"') sb.Append("\\\""); else if (c == '\\') sb.Append("\\\\");
                else if (c < 32) sb.Append(' '); else sb.Append(c);
            }
            return sb.ToString();
        }

        // The game's own text in the player's language, or the English fallback when a key is unknown.
        static string Text(string key, string fallback)
        {
            string s = null;
            try { s = Language.Get(key, "UI"); } catch (Exception) { }
            return string.IsNullOrEmpty(s) || s.Contains("#!#") || s == key ? fallback : s;
        }

        static string CharmKey(PlayerData pd, int id)
        {
            if (id == 23 && pd.GetBool("fragileHealth_unbreakable") || id == 24 && pd.GetBool("fragileGreed_unbreakable") ||
                id == 25 && pd.GetBool("fragileStrength_unbreakable")) return id + "_G";
            if (id == 36) return pd.GetInt("royalCharmState") == 4 ? "36_C" : pd.GetInt("royalCharmState") == 3 ? "36_B" : "36_A";
            if (id == 40 && pd.GetInt("grimmChildLevel") == 5) return "40_N";
            return id.ToString();
        }

        static bool Broken(PlayerData pd, int id) { return id >= 23 && id <= 25 && pd.GetBool("brokenCharm_" + id); }

        // Inventory entries in the last state, by text key, and the object in the game's
        // inventory screen that carries each one's picture.
        public static readonly List<string> Shown = new List<string>();
        static readonly Dictionary<string, string> Art = new Dictionary<string, string>
        {
            {"SPELL_FOCUS", "Spell Focus"}, {"SPELL_FIREBALL", "Spell Fireball"}, {"SPELL_QUAKE", "Spell Quake"}, {"SPELL_SCREAM", "Spell Scream"},
            {"ART_CYCLONE", "Art Cyclone"}, {"ART_DASH", "Art Dash"}, {"ART_UPPER", "Art Uppercut"}, {"NAIL", "Nail"},
            {"DASH", "Dash Cloak"}, {"SHADOWDASH", "Dash Cloak"}, {"WALLJUMP", "Mantis Claw"}, {"SUPERDASH", "Super Dash"},
            {"DOUBLEJUMP", "Double Jump"}, {"ACIDARMOUR", "Acid Armour"}, {"DREAMNAIL_A", "Dream Nail"}, {"DREAMNAIL_B", "Dream Nail"},
            {"DREAMGATE", "Dream Gate"}, {"KINGSBRAND", "Kings Brand"}, {"LANTERN", "Lantern"}, {"TRAM_PASS", "Tram Pass"},
            {"CITYKEY", "City Key"}, {"STOREKEY", "Store Key"}, {"WHITEKEY", "White Key"}, {"LOVEKEY", "Love Key"}, {"FLOWER", "Xun Flower"},
            {"SIMPLEKEY", "Simple Key"}, {"ORE", "Ore"}, {"RANCIDEGG", "Rancid Egg"}, {"TRINKET1", "Trinket1"}, {"TRINKET2", "Trinket2"},
            {"TRINKET3", "Trinket3"}, {"TRINKET4", "Trinket4"},
            {"MAPQUILL", "Map and Quill"}, {"MAP", "Map and Quill"}, {"QUILL", "Map and Quill"},
        };

        public static Sprite ArtFor(Transform inventory, string key)
        {
            if (!Art.TryGetValue(key, out var name) && !Art.TryGetValue(key.TrimEnd('1', '2', '3', '4', '5'), out name)) return null;
            foreach (var r in inventory.GetComponentsInChildren<SpriteRenderer>(true))
            {
                if (r.name != name) continue;
                // until the game's inventory has been opened once, this slot still holds another item's picture
                if (name == "Map and Quill" && r.sprite != null && r.sprite.name.StartsWith("White_Flower")) return null;
                return r.sprite;
            }
            return null;
        }

        static void Entry(StringBuilder sb, ref int n, string key, string fallback, int count = -1)
        {
            Shown.Add(key);
            if (n++ > 0) sb.Append(',');
            sb.Append("{\"name\":\"").Append(Esc(Text("INV_NAME_" + key, fallback))).Append("\",\"desc\":\"").Append(Esc(Text("INV_DESC_" + key, "")))
              .Append("\",\"icon\":\"").Append(key).Append('"');
            if (count >= 0) sb.Append(",\"count\":").Append(count);
            sb.Append('}');
        }

        // The game's own charm screen does not follow changes made here while it is open.
        public static bool CharmScreenOpen(Transform inventory)
        {
            var pane = inventory != null ? inventory.Find("Charms") : null;
            return pane != null && pane.gameObject.activeInHierarchy;
        }

        public static string State(PlayerData pd, GameManager gm, bool worldView, bool charmScreen)
        {
            var sb = new StringBuilder(8192);
            Shown.Clear(); Shown.Add("NAIL");
            string zone = "";
            try { zone = Language.Get(gm.GetCurrentMapZone(), "Map Zones"); } catch (Exception) { }
            sb.Append(",\"zone\":\"").Append(Esc(zone)).Append("\",\"world\":").Append(worldView ? "true" : "false")
              .Append(",\"bench\":").Append(pd.GetBool("atBench") ? "true" : "false").Append(",\"charmScreen\":").Append(charmScreen ? "true" : "false")
              .Append(",\"notches\":").Append(pd.GetInt("charmSlots")).Append(",\"used\":").Append(pd.GetInt("charmSlotsFilled"))
              .Append(",\"over\":").Append(pd.GetBool("overcharmed") ? "true" : "false").Append(",\"charms\":[");
            int n = 0;
            for (int id = 1; id <= 40; id++)
            {
                if (!pd.GetBool("gotCharm_" + id)) continue;
                string key = CharmKey(pd, id);
                if (n++ > 0) sb.Append(',');
                sb.Append("{\"id\":").Append(id).Append(",\"name\":\"").Append(Esc(Text("CHARM_NAME_" + key, "Charm " + id)))
                  .Append("\",\"desc\":\"").Append(Esc(Text("CHARM_DESC_" + key, ""))).Append("\",\"cost\":").Append(pd.GetInt("charmCost_" + id))
                  .Append(",\"on\":").Append(pd.GetBool("equippedCharm_" + id) ? "true" : "false")
                  .Append(",\"broken\":").Append(Broken(pd, id) ? "true" : "false").Append('}');
            }
            int nail = Mathf.Clamp(pd.GetInt("nailSmithUpgrades"), 0, 4);
            sb.Append("],\"nail\":{\"name\":\"").Append(Esc(Text("INV_NAME_NAIL" + (nail + 1), new[] { "Old Nail", "Sharpened Nail", "Channelled Nail", "Coiled Nail", "Pure Nail" }[nail])))
              .Append("\",\"desc\":\"").Append(Esc(Text("INV_DESC_NAIL" + (nail + 1), ""))).Append("\",\"level\":").Append(nail).Append(",\"damage\":").Append(pd.GetInt("nailDamage")).Append('}');

            sb.Append(",\"spells\":["); n = 0;
            Entry(sb, ref n, "SPELL_FOCUS", "Focus");
            int f = pd.GetInt("fireballLevel"), q = pd.GetInt("quakeLevel"), s = pd.GetInt("screamLevel");
            if (f > 0) Entry(sb, ref n, "SPELL_FIREBALL" + f, f == 1 ? "Vengeful Spirit" : "Shade Soul");
            if (q > 0) Entry(sb, ref n, "SPELL_QUAKE" + q, q == 1 ? "Desolate Dive" : "Descending Dark");
            if (s > 0) Entry(sb, ref n, "SPELL_SCREAM" + s, s == 1 ? "Howling Wraiths" : "Abyss Shriek");
            if (pd.GetBool("hasCyclone")) Entry(sb, ref n, "ART_CYCLONE", "Cyclone Slash");
            if (pd.GetBool("hasDashSlash")) Entry(sb, ref n, "ART_DASH", "Dash Slash");
            if (pd.GetBool("hasUpwardSlash")) Entry(sb, ref n, "ART_UPPER", "Great Slash");

            sb.Append("],\"abilities\":["); n = 0;
            if (pd.GetBool("hasShadowDash")) Entry(sb, ref n, "SHADOWDASH", "Shade Cloak");
            else if (pd.GetBool("hasDash")) Entry(sb, ref n, "DASH", "Mothwing Cloak");
            if (pd.GetBool("hasWalljump")) Entry(sb, ref n, "WALLJUMP", "Mantis Claw");
            if (pd.GetBool("hasSuperDash")) Entry(sb, ref n, "SUPERDASH", "Crystal Heart");
            if (pd.GetBool("hasDoubleJump")) Entry(sb, ref n, "DOUBLEJUMP", "Monarch Wings");
            if (pd.GetBool("hasAcidArmour")) Entry(sb, ref n, "ACIDARMOUR", "Isma's Tear");
            if (pd.GetBool("hasDreamNail")) Entry(sb, ref n, pd.GetBool("dreamNailUpgraded") ? "DREAMNAIL_B" : "DREAMNAIL_A", pd.GetBool("dreamNailUpgraded") ? "Awoken Dream Nail" : "Dream Nail");
            if (pd.GetBool("hasDreamGate")) Entry(sb, ref n, "DREAMGATE", "Dreamgate");
            if (pd.GetBool("hasKingsBrand")) Entry(sb, ref n, "KINGSBRAND", "King's Brand");
            if (pd.GetBool("hasLantern")) Entry(sb, ref n, "LANTERN", "Lumafly Lantern");

            sb.Append("],\"items\":["); n = 0;
            if (pd.GetBool("hasMap") && pd.GetBool("hasQuill")) Entry(sb, ref n, "MAPQUILL", "Map and Quill");
            else if (pd.GetBool("hasMap")) Entry(sb, ref n, "MAP", "Map");
            else if (pd.GetBool("hasQuill")) Entry(sb, ref n, "QUILL", "Quill");
            if (pd.GetBool("hasTramPass")) Entry(sb, ref n, "TRAM_PASS", "Tram Pass");
            if (pd.GetBool("hasCityKey")) Entry(sb, ref n, "CITYKEY", "City Crest");
            if (pd.GetBool("hasSlykey")) Entry(sb, ref n, "STOREKEY", "Shopkeeper's Key");
            if (pd.GetBool("hasWhiteKey")) Entry(sb, ref n, "WHITEKEY", "Elegant Key");
            if (pd.GetBool("hasLoveKey")) Entry(sb, ref n, "LOVEKEY", "Love Key");
            if (pd.GetBool("hasXunFlower")) Entry(sb, ref n, "FLOWER", "Delicate Flower");
            if (pd.GetInt("simpleKeys") > 0) Entry(sb, ref n, "SIMPLEKEY", "Simple Key", pd.GetInt("simpleKeys"));
            if (pd.GetInt("ore") > 0) Entry(sb, ref n, "ORE", "Pale Ore", pd.GetInt("ore"));
            if (pd.GetInt("rancidEggs") > 0) Entry(sb, ref n, "RANCIDEGG", "Rancid Egg", pd.GetInt("rancidEggs"));
            string[] relics = { "Wanderer's Journal", "Hallownest Seal", "King's Idol", "Arcane Egg" };
            for (int i = 1; i <= 4; i++)
                if (pd.GetInt("trinket" + i) > 0) Entry(sb, ref n, "TRINKET" + i, relics[i - 1], pd.GetInt("trinket" + i));

            sb.Append("],\"progress\":{\"essence\":").Append(pd.GetBool("hasDreamNail") ? pd.GetInt("dreamOrbs") : -1)
              .Append(",\"grubs\":").Append(pd.GetInt("grubsCollected")).Append(",\"shards\":").Append(pd.GetInt("heartPieces"))
              .Append(",\"fragments\":").Append(pd.GetInt("vesselFragments")).Append(",\"completion\":").Append(pd.GetBool("unlockedCompletionRate") ? Mathf.RoundToInt(pd.GetFloat("completionPercentage")) : -1)
              .Append(",\"time\":").Append((int)pd.GetFloat("playTime")).Append('}');
            return sb.ToString();
        }

        // One sprite out of its atlas as a PNG data URL, scaled to fit a square of the given size.
        public static string Png(Sprite sprite, int size)
        {
            var tex = sprite.texture;
            // the area the sprite's mesh covers; valid however the atlas was packed
            Vector2 lo = Vector2.one, hi = Vector2.zero;
            foreach (var uv in sprite.uv) { lo = Vector2.Min(lo, uv); hi = Vector2.Max(hi, uv); }
            var r = new Rect(lo.x * tex.width, lo.y * tex.height, (hi.x - lo.x) * tex.width, (hi.y - lo.y) * tex.height);
            float k = size / Mathf.Max(r.width, r.height);
            int w = Mathf.Max(1, Mathf.RoundToInt(r.width * k)), h = Mathf.Max(1, Mathf.RoundToInt(r.height * k));
            var rt = RenderTexture.GetTemporary(w, h, 0, RenderTextureFormat.ARGB32);
            var prev = RenderTexture.active;
            var copy = new Texture2D(w, h, TextureFormat.RGBA32, false);
            // the game's rendering is left as it was found, whatever happens here
            try
            {
                Graphics.Blit(tex, rt, new Vector2(r.width / tex.width, r.height / tex.height), new Vector2(r.x / tex.width, r.y / tex.height));
                RenderTexture.active = rt;
                copy.ReadPixels(new Rect(0, 0, w, h), 0, 0);
                copy.Apply();
                return "data:image/png;base64," + Convert.ToBase64String(ImageConversion.EncodeToPNG(copy));
            }
            finally
            {
                RenderTexture.active = prev;
                RenderTexture.ReleaseTemporary(rt);
                UnityEngine.Object.Destroy(copy);
            }
        }

        // Follows the game's own charm rules. Refused while the game's charm screen is open,
        // which would keep showing the old set.
        public static void ToggleCharm(int id, Transform inventory)
        {
            var pd = PlayerData.instance;
            var hero = HeroController.UnsafeInstance;
            if (pd == null || hero == null || CharmScreenOpen(inventory) || id < 1 || id > 40 || !pd.GetBool("atBench") || !pd.GetBool("gotCharm_" + id)) return;
            bool on = pd.GetBool("equippedCharm_" + id);
            if (on)
            {
                if (id == 36 && pd.GetInt("royalCharmState") == 4) return;
                pd.UnequipCharm(id);
            }
            else
            {
                int free = pd.GetInt("charmSlots") - pd.GetInt("charmSlotsFilled");
                if (Broken(pd, id) || free <= 0 || (free < pd.GetInt("charmCost_" + id) && !pd.GetBool("canOvercharm"))) return;
                pd.EquipCharm(id);
            }
            pd.SetBool("equippedCharm_" + id, !on);
            pd.CalculateNotchesUsed();
            GameManager.instance.RefreshOvercharm();
            hero.CharmUpdate();
            PlayMakerFSM.BroadcastEvent("CHARM INDICATOR CHECK");
            PlayMakerFSM.BroadcastEvent("CHARM EQUIP CHECK");
        }
    }
}
