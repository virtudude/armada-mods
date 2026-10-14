using System;
using System.Globalization;
using System.IO;
using UnityEngine;

namespace ArmadaSecondScreen
{
    // Base for a per-game provider: owns the link and the off-screen surface,
    // handles config, touch view (tap, pan, pinch) and status reporting.
    public abstract class Provider : MonoBehaviour
    {
        protected Link link;
        protected SurfaceStreamer streamer;
        protected bool content;
        protected string status = "starting";
        protected Vector2 pan;
        protected float zoom = 1f;
        float zoomBase = 1f, nextState, fpsT0, worst, lastFailure = -1000f;
        int fpsFrames;
        bool touchMoved;
        Vector2 touchLast, touchDown;
        string lastError;
        int failures;
        bool dev, wasConnected;
        string lastState;
        // Fractions of the surface a view draws over at the top and bottom; the camera keeps clear of them.
        protected float insetTop, insetBottom;
        // False while the view covers the surface, so nothing is rendered or read back.
        protected bool streaming = true;

        protected abstract string Hello { get; }
        protected abstract void Step();
        protected virtual void OnTap() { }
        protected virtual void OnViewChanged() { }
        protected virtual void OnConfig() { }
        protected virtual string OnCommand(string cmd) { return ""; }
        protected virtual void OnShutdown() { }
        // Shown by the host in place of the surface while there is nothing to draw (pixel-only mods).
        protected virtual string Message => status == "menu" || status == "starting" ? "Start or load a game" : null;
        // False gives the screen back. A provider with an HTML view keeps it and lets the page say what is going on.
        protected virtual bool Show => content || Message != null;
        // More members for the state object, each as ,"key":value. Sent when they change.
        protected virtual string Extra => "";
        // Messages from an HTML view other than the surface touches.
        protected virtual void OnInput(string json) { }
        protected virtual void OnAttach() { }
        // The screen host has gone: let go of whatever was only kept for it.
        protected virtual void OnDetach() { }

        void Awake()
        {
            string logDir = Path.Combine(Application.dataPath, "..", "ArmadaSecondScreen");
            Directory.CreateDirectory(logDir);
            Log.Init(Path.Combine(logDir, "secondscreen.log"));
            Log.Info("provider awake, unity " + Application.unityVersion + ", " + Hello);
            dev = !string.IsNullOrEmpty(Environment.GetEnvironmentVariable("ARMADA_MOD_DEV"));
            link = new Link("127.0.0.1", 47800, Hello);
            streamer = new SurfaceStreamer(link, 1240, 1080);
        }

        void OnDestroy()
        {
            try { OnShutdown(); } catch (Exception e) { Log.Info("shutdown: " + e); }
            streamer?.Dispose();
            link?.Dispose();
            Log.Info("provider destroyed");
        }

        void Update()
        {
            try
            {
                fpsFrames++; worst = Mathf.Max(worst, Time.unscaledDeltaTime);
                if (dev && Time.unscaledTime - fpsT0 >= 10f)
                {
                    Log.Info("fps " + (fpsFrames / (Time.unscaledTime - fpsT0)).ToString("F1") + " worst " + (worst * 1000f).ToString("F1") +
                        "ms streaming=" + link.Connected + " sent=" + link.FramesSent + " status=" + status);
                    fpsFrames = 0; fpsT0 = Time.unscaledTime; worst = 0f;
                }
                if (link.Connected != wasConnected)
                {
                    wasConnected = link.Connected; lastState = null; nextState = 0f;
                    if (wasConnected) OnAttach(); else { content = false; OnDetach(); }
                }
                // nothing is done in the game while no screen is there to show it
                if (!wasConnected) return;
                while (link.Inbox.TryDequeue(out var m)) Handle(m);
                Step();
                if (Time.unscaledTime >= nextState)
                {
                    nextState = Time.unscaledTime + 0.25f;
                    string msg = content ? null : Message;
                    string state = "{\"status\":\"" + status + "\",\"visible\":" + (Show ? "true" : "false") + ",\"map\":" + (content ? "true" : "false") +
                        (string.IsNullOrEmpty(msg) ? "" : ",\"message\":\"" + msg.Replace("\\", "").Replace("\"", "'") + "\"") + Extra + "}";
                    if (state != lastState) { lastState = state; link.SendText(Msg.State, state); }
                }
                if (streaming) streamer.Tick(content);
                // work done a few times a second fails a few times a second: only a quiet spell clears the count
                if (Time.unscaledTime - lastFailure > 30f) failures = 0;
            }
            catch (Exception e)
            {
                var s = e.ToString();
                if (s != lastError) { lastError = s; Log.Info("update: " + s); }
                lastFailure = Time.unscaledTime;
                // A provider that keeps failing (for example after a game update) lets go of the screen.
                if (++failures > 120)
                {
                    Log.Info("too many failures, provider removed");
                    Destroy(this);
                }
            }
        }

        protected void SetStatus(string s)
        {
            if (s == status) return;
            nextState = 0f;
            status = s; nextState = 0f;
            Log.Info("status " + s);
        }

        protected void ResetView() { pan = Vector2.zero; zoom = zoomBase = 1f; }

        // Send the state again even if it has not changed, for a view that has just loaded.
        protected void Resend() { lastState = null; nextState = 0f; }

        // Fit the camera to bounds, then apply the user's pan and zoom.
        protected void FitCamera(Bounds b, float camZ)
        {
            var cam = streamer.Cam;
            float aspect = (float)streamer.Width / streamer.Height;
            float open = Mathf.Clamp(1f - insetTop - insetBottom, 0.2f, 1f);
            float size = Mathf.Max(Mathf.Max(b.extents.y / open, b.extents.x / aspect) * 1.08f, 0.5f);
            pan.x = Mathf.Clamp(pan.x, -b.extents.x, b.extents.x);
            pan.y = Mathf.Clamp(pan.y, -b.extents.y, b.extents.y);
            cam.orthographicSize = size / zoom;
            // centre the content in the band the view leaves open
            float shift = (insetTop - insetBottom) * cam.orthographicSize;
            cam.transform.position = new Vector3(b.center.x + pan.x, b.center.y + pan.y + shift, camZ);
            cam.nearClipPlane = 1f; cam.farClipPlane = 80f;
        }

        // Damage-track one moving renderer (a player marker): invalidates old and new pixels.
        protected void TrackRenderer(Renderer rend, ref RectInt last)
        {
            var r = new RectInt(-1, -1, 0, 0);
            if (content && rend != null && rend.enabled && rend.gameObject.activeInHierarchy)
            {
                Vector3 a = streamer.Cam.WorldToScreenPoint(rend.bounds.min), b = streamer.Cam.WorldToScreenPoint(rend.bounds.max);
                r = new RectInt(Mathf.FloorToInt(a.x) - 3, Mathf.FloorToInt(a.y) - 3, Mathf.CeilToInt(b.x - a.x) + 6, Mathf.CeilToInt(b.y - a.y) + 6);
            }
            if (r.Equals(last)) return;
            if (last.width > 0) streamer.Invalidate(last);
            if (r.width > 0) streamer.Invalidate(r);
            last = r;
        }

        void Handle(Incoming m)
        {
            if (m.Type == Msg.Config)
            {
                int w = Num(m.Text, "w", streamer.Width), h = Num(m.Text, "h", streamer.Height);
                streamer.Fps = Mathf.Clamp(Num(m.Text, "fps", (int)streamer.Fps), 1, 60);
                if (w >= 64 && h >= 64 && w <= 4096 && h <= 4096) streamer.Resize(w, h);
                Log.Info("config " + m.Text);
                OnConfig();
            }
            else if (m.Type == Msg.Input)
            {
                string t = Str(m.Text, "t");
                if (t == "") { OnInput(m.Text); return; }
                var p = new Vector2(Flt(m.Text, "x", 0f), Flt(m.Text, "y", 0f));
                if (t == "down") { touchLast = touchDown = p; touchMoved = false; }
                else if (t == "move" || t == "up")
                {
                    var d = p - touchLast; touchLast = p;
                    if (!touchMoved && (p - touchDown).magnitude > 0.02f) touchMoved = true;
                    if (touchMoved && d.sqrMagnitude > 0f)
                    {
                        float hgt = streamer.Cam.orthographicSize * 2f;
                        pan += new Vector2(-d.x * hgt * streamer.Cam.aspect, d.y * hgt);
                        OnViewChanged();
                    }
                    if (t == "up" && !touchMoved) OnTap();
                }
                else if (t == "zoom")
                {
                    touchMoved = true;
                    zoom = Mathf.Clamp(zoomBase * Flt(m.Text, "s", 1f), 1f, 6f);
                    OnViewChanged();
                }
                else if (t == "zoomend") zoomBase = zoom;
            }
            else if (m.Type == Msg.Cmd && dev)
            {
                string reply = OnCommand(m.Text) ?? "";
                link.SendText(Msg.State, "{\"reply\":\"" + reply.Replace("\\", "/").Replace("\"", "'").Replace("\n", "\\n") + "\"}");
            }
        }

        protected static string Str(string json, string key)
        {
            int i = json.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (i < 0) return "";
            i = json.IndexOf('"', json.IndexOf(':', i)) + 1;
            int j = json.IndexOf('"', i);
            return i > 0 && j > i ? json.Substring(i, j - i) : "";
        }

        protected static float Flt(string json, string key, float def)
        {
            int i = json.IndexOf("\"" + key + "\"", StringComparison.Ordinal);
            if (i < 0) return def;
            i = json.IndexOf(':', i) + 1;
            int j = i;
            while (j < json.Length && "0123456789.-eE ".IndexOf(json[j]) >= 0) j++;
            return float.TryParse(json.Substring(i, j - i).Trim(), NumberStyles.Float, CultureInfo.InvariantCulture, out var v) ? v : def;
        }

        protected static int Num(string json, string key, int def) { return (int)Flt(json, key, def); }

        protected static void Dump(Transform t, int depth, int max, System.Text.StringBuilder sb)
        {
            sb.Append(new string(' ', depth * 2)).Append(t.name).Append(t.gameObject.activeSelf ? " +" : " -")
              .Append(" L").Append(t.gameObject.layer).Append(" c").Append(t.childCount).Append('\n');
            if (depth >= max) return;
            for (int i = 0; i < t.childCount; i++) Dump(t.GetChild(i), depth + 1, max, sb);
        }
    }
}
