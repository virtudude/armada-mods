using System;
using System.Collections.Generic;
using System.Reflection;
using System.Text;
using TeamCherry.Localization;
using UnityEngine;

namespace ArmadaSecondScreen
{
    // Keeps a private copy of the in-game map in its quick-map state for the current
    // area and streams it under the HTML view.
    public class Entry : Provider
    {
        static readonly Vector3 Far = new Vector3(5000f, 5000f, 0f);
        static readonly Dictionary<string, string[]> Zones = new Dictionary<string, string[]>
        {
            {"ABYSS", new[]{"QuickMapAncientBasin", "mapAbyss"}},
            {"CITY", new[]{"QuickMapCity", "mapCity"}}, {"KINGS_STATION", new[]{"QuickMapCity", "mapCity"}},
            {"SOUL_SOCIETY", new[]{"QuickMapCity", "mapCity"}}, {"LURIENS_TOWER", new[]{"QuickMapCity", "mapCity"}},
            {"CLIFFS", new[]{"QuickMapCliffs", "mapCliffs"}},
            {"CROSSROADS", new[]{"QuickMapCrossroads", "mapCrossroads"}}, {"SHAMAN_TEMPLE", new[]{"QuickMapCrossroads", "mapCrossroads"}},
            {"MINES", new[]{"QuickMapCrystalPeak", "mapMines"}},
            {"DEEPNEST", new[]{"QuickMapDeepnest", "mapDeepnest"}}, {"BEASTS_DEN", new[]{"QuickMapDeepnest", "mapDeepnest"}},
            {"FOG_CANYON", new[]{"QuickMapFogCanyon", "mapFogCanyon"}}, {"MONOMON_ARCHIVE", new[]{"QuickMapFogCanyon", "mapFogCanyon"}},
            {"WASTES", new[]{"QuickMapFungalWastes", "mapFungalWastes"}}, {"QUEENS_STATION", new[]{"QuickMapFungalWastes", "mapFungalWastes"}},
            {"GREEN_PATH", new[]{"QuickMapGreenpath", "mapGreenpath"}},
            {"OUTSKIRTS", new[]{"QuickMapKingdomsEdge", "mapOutskirts"}}, {"HIVE", new[]{"QuickMapKingdomsEdge", "mapOutskirts"}},
            {"COLOSSEUM", new[]{"QuickMapKingdomsEdge", "mapOutskirts"}},
            {"ROYAL_GARDENS", new[]{"QuickMapQueensGardens", "mapRoyalGardens"}},
            {"RESTING_GROUNDS", new[]{"QuickMapRestingGrounds", "mapRestingGrounds"}},
            {"TOWN", new[]{"QuickMapDirtmouth", "mapDirtmouth"}}, {"KINGS_PASS", new[]{"QuickMapDirtmouth", "mapDirtmouth"}},
            {"WATERWAYS", new[]{"QuickMapWaterways", "mapWaterways"}}, {"GODSEEKER_WASTE", new[]{"QuickMapWaterways", "mapWaterways"}},
        };
        // State the game pushes into its own map from scene scripts.
        static readonly string[] Mirrored = { "originOffsetX", "originOffsetY", "sceneWidth", "sceneHeight", "doorX", "doorY",
            "doorScene", "doorMapZone", "doorOriginOffsetX", "doorOriginOffsetY", "doorSceneWidth", "doorSceneHeight", "inRoom" };
        static readonly FieldInfo[] MirroredFields = Array.ConvertAll(Mirrored, n =>
            typeof(GameMap).GetField(n, BindingFlags.Instance | BindingFlags.NonPublic | BindingFlags.Public));

        GameObject holder, clone;
        GameMap src, map;
        int cloneFrame, visible, settleAt, settlePass;
        string shownKey, shownZone;
        float nextRefresh;
        bool worldView;
        RectInt lastCompass = new RectInt(-1, -1, 0, 0);
        string extra = "";
        float nextExtra;
        Transform inventory;
        readonly HashSet<string> sentIcons = new HashSet<string>();

        protected override string Hello => "{\"game\":\"Hollow Knight\",\"appid\":367520,\"provider\":\"hk-companion\",\"view\":\"html\",\"version\":2}";
        protected override bool Show => true;
        protected override string Extra => extra;
        protected override void OnAttach() { sentIcons.Clear(); }
        protected override void OnDetach() { DropClone(); extra = ""; }

        protected override void OnShutdown() { DropClone(); }
        protected override void OnConfig() { shownKey = null; nextRefresh = 0f; }
        protected override void OnTap() { worldView = !worldView; ResetView(); nextRefresh = 0f; }
        protected override void OnViewChanged() { if (content) Reframe(); }

        protected override void Step()
        {
            var gm = GameManager.UnsafeInstance;
            var hero = HeroController.UnsafeInstance;
            if (gm == null || hero == null || gm.gameMap == null || !gm.IsGameplayScene())
            {
                if (gm == null || gm.gameMap == null) DropClone();
                SetStatus("menu");
                if (content) { content = false; streamer.Invalidate(); }
                shownKey = null; extra = "";
                return;
            }
            if (Time.unscaledTime >= nextExtra)
            {
                nextExtra = Time.unscaledTime + 0.25f;
                FindInventory();
                extra = Companion.State(PlayerData.instance, gm, worldView, Companion.CharmScreenOpen(inventory));
                for (int i = 0; i < 3 && SendIcon(); i++) { }
            }
            var live = gm.gameMap.GetComponent<GameMap>();
            if (clone == null || live != src) BuildClone(live);
            if (Time.frameCount - cloneFrame < 2) return;
            Mirror();
            if (Time.unscaledTime >= nextRefresh)
            {
                nextRefresh = Time.unscaledTime + 0.5f;
                string zone = src.inRoom ? src.doorMapZone : gm.GetCurrentMapZone();
                string key = Signature(gm, zone);
                if (key != shownKey) Refresh(zone, key);
                else if (content && Visible() != visible) Reframe();
            }
            // The game's FSMs settle pin and label visibility a few frames after a refresh.
            if (content && settleAt > 0 && Time.frameCount >= settleAt)
            {
                settleAt = settlePass++ < 2 ? Time.frameCount + 20 : 0;
                Reframe();
            }
            TrackRenderer(map.compassIcon.GetComponent<Renderer>(), ref lastCompass);
        }

        void BuildClone(GameMap live)
        {
            DropClone();
            src = live;
            holder = new GameObject("ArmadaSecondScreenHolder");
            holder.SetActive(false);
            DontDestroyOnLoad(holder);
            clone = Instantiate(live.gameObject, holder.transform);
            clone.name = "ArmadaSecondScreenMap";
            // This FSM would register the copy as the game's map. The rest are the
            // game's own pin and marker visibility rules and must keep running.
            foreach (var fsm in clone.GetComponents<PlayMakerFSM>())
                if (fsm.FsmName == "Globalise") DestroyImmediate(fsm);
            map = clone.GetComponent<GameMap>();
            map.canPan = false;
            clone.transform.SetParent(null, false);
            clone.transform.position = Far;
            clone.transform.localScale = live.transform.lossyScale;
            DontDestroyOnLoad(clone);
            clone.SetActive(true);
            cloneFrame = Time.frameCount;
            shownKey = null;
            int mask = 0;
            foreach (var r in clone.GetComponentsInChildren<Renderer>(true)) mask |= 1 << r.gameObject.layer;
            streamer.Cam.cullingMask = mask;
            Log.Info("cloned map, mask " + mask);
        }

        void DropClone()
        {
            if (clone != null) Destroy(clone);
            if (holder != null) Destroy(holder);
            clone = null; holder = null; map = null; src = null; shownKey = null;
        }

        void Mirror()
        {
            foreach (var f in MirroredFields) f.SetValue(map, f.GetValue(src));
        }

        // Everything that changes what the map shows, other than the moving player marker.
        string Signature(GameManager gm, string zone)
        {
            var pd = PlayerData.instance;
            return zone + "|" + gm.sceneName + "|" + pd.scenesMapped.Count + "|" + pd.hasQuill + pd.hasMap + pd.equippedCharm_2 +
                pd.soulLimited + "|" + pd.shadeScene + "|" + pd.dreamGateScene + "|" + pd.shadeMapPos + pd.dreamgateMapPos + "|" +
                pd.scenesEncounteredCocoon.Count + "|" + pd.scenesEncounteredDreamPlant.Count + "|" + pd.scenesEncounteredDreamPlantC.Count + "|" +
                pd.hasPin + pd.hasPinBench + pd.hasPinCocoon + pd.hasPinDreamPlant + pd.hasPinGuardian + pd.hasPinBlackEgg + pd.hasPinShop +
                pd.hasPinSpa + pd.hasPinStag + pd.hasPinTram + pd.hasPinGhost + "|" + worldView;
        }

        void Refresh(string zone, string key)
        {
            if (zone != shownZone) { shownZone = zone; ResetView(); }
            shownKey = key;
            streamer.Invalidate();
            lastCompass = new RectInt(-1, -1, 0, 0);
            var pd = PlayerData.instance;
            if (!Zones.TryGetValue(zone, out var z))
            {
                map.CloseQuickMap(); content = false; SetStatus("unmapped-zone"); return;
            }
            if (!pd.hasMap || !pd.GetBool(z[1]))
            {
                map.CloseQuickMap(); content = false; SetStatus("no-map"); return;
            }
            map.CloseQuickMap();
            map.SetupMap();
            if (worldView) map.WorldMap();
            else typeof(GameMap).GetMethod(z[0]).Invoke(map, null);
            map.shadeMarker.transform.localPosition = pd.shadeMapPos;
            map.dreamGateMarker.transform.localPosition = pd.dreamgateMapPos;
            content = Frame();
            visible = Visible();
            settleAt = Time.frameCount + 3; settlePass = 0;
            SetStatus(content ? "map" : "empty");
        }

        int Visible()
        {
            int n = 0;
            foreach (var r in clone.GetComponentsInChildren<Renderer>(false)) if (r.enabled) n++;
            return n;
        }

        void Reframe()
        {
            content = Frame();
            visible = Visible();
            streamer.Invalidate();
            lastCompass = new RectInt(-1, -1, 0, 0);
        }

        bool Frame()
        {
            bool any = false; Bounds b = new Bounds();
            foreach (var area in new[] { map.areaAncientBasin, map.areaCity, map.areaCliffs, map.areaCrossroads, map.areaCrystalPeak,
                map.areaDeepnest, map.areaFogCanyon, map.areaFungalWastes, map.areaGreenpath, map.areaKingdomsEdge,
                map.areaQueensGardens, map.areaRestingGrounds, map.areaDirtmouth, map.areaWaterways })
            {
                if (!area.activeSelf) continue;
                foreach (var r in area.GetComponentsInChildren<Renderer>(false))
                {
                    if (!r.enabled) continue;
                    if (!any) { b = r.bounds; any = true; } else b.Encapsulate(r.bounds);
                }
            }
            if (any) FitCamera(b, clone.transform.position.z - 30f);
            return any;
        }

        protected override void OnInput(string json)
        {
            string action = Str(json, "action");
            if (action == "tab")
            {
                streaming = Str(json, "name") == "map";
                if (streaming) streamer.Invalidate();
            }
            else if (action == "insets")
            {
                insetTop = Mathf.Clamp(Flt(json, "top", 0f), 0f, 0.4f); insetBottom = Mathf.Clamp(Flt(json, "bottom", 0f), 0f, 0.4f);
                if (content) Reframe();
            }
            else if (action == "world") OnTap();
            else if (action == "assets") { sentIcons.Clear(); Resend(); }
            else if (action == "charm") { Companion.ToggleCharm(Num(json, "id", 0), inventory); nextExtra = 0f; }
        }

        void FindInventory()
        {
            if (inventory != null) return;
            var cams = GameObject.Find("_GameCameras");
            if (cams != null) inventory = cams.transform.Find("HudCamera/Inventory");
        }

        // Charm and inventory art is read from the game's own sprites, one a tick, and sent to the view once.
        bool SendIcon()
        {
            var pd = PlayerData.instance;
            var icons = CharmIconList.Instance;
            if (icons == null || !link.Connected) return false;
            for (int id = 1; id <= 40; id++)
            {
                if (!pd.GetBool("gotCharm_" + id)) continue;
                var sprite = icons.GetSprite(id);
                if (sprite == null) continue;
                string key = id + ":" + sprite.name;
                if (sentIcons.Contains(key)) continue;
                sentIcons.Add(key);
                SendPicture("c" + id, sprite);
                return true;
            }
            if (inventory == null) return false;
            foreach (var entry in Companion.Shown)
            {
                var sprite = Companion.ArtFor(inventory, entry);
                string key = entry + ":" + (sprite != null ? sprite.name : "");
                if (sentIcons.Contains(key)) continue;
                sentIcons.Add(key);
                if (sprite == null) continue;
                SendPicture("i:" + entry, sprite);
                return true;
            }
            return false;
        }

        // A sprite that cannot be read is left out; the view shows the entry without a picture.
        void SendPicture(string name, Sprite sprite)
        {
            try { link.SendText(Msg.State, "{\"assets\":{\"" + name + "\":\"" + Companion.Png(sprite, 128) + "\"}}"); }
            catch (Exception e) { Log.Info("picture " + name + ": " + e.Message); }
        }

        protected override string OnCommand(string cmd)
        {
            var sb = new StringBuilder();
            if (cmd == "dump" && src != null) Dump(src.transform, 0, 2, sb);
            else if (cmd == "dumpclone" && clone != null) Dump(clone.transform, 0, 3, sb);
            else if (cmd.StartsWith("sprites "))
            {
                // sprites under a named root object, with their paths, for finding the game's own art
                var root = GameObject.Find(cmd.Substring(8));
                if (root != null)
                    foreach (var r in root.GetComponentsInChildren<SpriteRenderer>(true))
                    {
                        if (r.sprite == null) continue;
                        string path = r.name; var tr = r.transform.parent;
                        for (int i = 0; i < 4 && tr != null && tr != root.transform; i++, tr = tr.parent) path = tr.name + "/" + path;
                        sb.Append(path).Append(" = ").Append(r.sprite.name).Append(r.sprite.packed ? " packed " + r.sprite.packingMode + " " + r.sprite.packingRotation : "").Append('\n');
                        if (sb.Length > 15000) break;
                    }
            }
            else if (cmd.StartsWith("set "))
            {
                // set <PlayerData field> <true|false|number>
                var w = cmd.Split(' ');
                if (w[2] == "true" || w[2] == "false") PlayerData.instance.SetBool(w[1], w[2] == "true");
                else PlayerData.instance.SetInt(w[1], int.Parse(w[2]));
                sb.Append("ok");
            }
            else if (cmd.StartsWith("kids "))
            {
                var root = GameObject.Find(cmd.Substring(5));
                if (root != null) Dump(root.transform, 0, 2, sb);
            }
            else if (cmd == "info")
            {
                var gm = GameManager.UnsafeInstance; var pd = PlayerData.instance;
                sb.Append("status=" + status + " key=" + shownKey + " scene=" + (gm ? gm.sceneName : "-") + " mapped=" + pd.scenesMapped.Count +
                    " cam=" + streamer.Cam.transform.position + " size=" + streamer.Cam.orthographicSize + " frames=" + link.FramesSent);
            }
            return sb.ToString();
        }
    }
}
