//! Native Pip-Boy view. This only emits scenes and requests; the provider owns
//! validation, game IDs, inventory versions, and confirmation challenges.
use crate::scene::{Rect, Scene};
use serde_json::{Value, json};
use std::time::{SystemTime, UNIX_EPOCH};

const CONTENT: Rect = [38.1, 110.0, 799.8, 510.0];
const LIST: Rect = [38.1, 116.0, 360.0, 484.0];
const DETAIL: Rect = [424.0, 116.0, 414.0, 484.0];
const MAP: Rect = [38.1, 112.0, 799.8, 494.0];
const PAGES: [&str; 5] = ["STAT", "INV", "DATA", "MAP", "RADIO"];
const SPECIAL: [&str; 7] = [
    "strength",
    "perception",
    "endurance",
    "charisma",
    "intelligence",
    "agility",
    "luck",
];
const MARKERS: &str = "Cave City DiamondCity Encampment Factory Monument Metro MilitaryBase Landmark Office TownRuins UrbanRuins SancHills Settlement Sewer Vault Airfield BunkerHill Camper Car Church CountryClub CustomHouse DriveIn ElevatedHighway FaneuilHall Farm FillingStation Forested Goodneighbor Graveyard Hospital IndustrialDome IndustrialStacks Institute IrishPride Junkyard Observatory Pier PondLake Quarry RadioactiveArea RadioTower Salem School Shipwreck Submarine SwanPond SynthHead Town BoS Brownstone Bunker Castle Skyscraper Libertalia LowRise Minutemen PoliceStation Prydwen RailroadFaction Railroad Satellite Sentinel USSConstitution Door Quest QuestMarkerDoor Quest PlayerSet PlayerLoc PowerArmorLoc";

#[derive(Clone)]
enum Action {
    Page(usize),
    Category(usize),
    Select(String),
    Command(Value),
    Confirm(String),
    Cancel,
    Scroll(f32, bool),
    Zoom(f32),
    Center,
    Reset,
    MapSelect(MapSelection),
    ClearMap,
    Summary,
}
#[derive(Clone)]
struct Hit {
    rect: Rect,
    action: Action,
    enabled: bool,
}
#[derive(Clone)]
struct MapSelection {
    kind: String,
    id: String,
    label: String,
    command: Option<Value>,
}
#[derive(Clone)]
struct Challenge {
    token: String,
    label: String,
    seen: f64,
    until: f64,
}
#[derive(Clone, Copy)]
struct Drag {
    start: [f32; 2],
    last: [f32; 2],
    moved: bool,
    map: bool,
    detail: bool,
}

// RadioWave.as is a procedural display, not audio sampled from the game.
// Preserve its 226-point buffer, 41ms timer and ten samples advanced per tick.
struct RadioWave {
    identity: String,
    points: Vec<f32>,
    index: u64,
    offset: f32,
    jitter: f32,
    amp: f32,
    old_sin: f32,
    freq: f32,
    next_tick: f64,
    random: u64,
}
impl Default for RadioWave {
    fn default() -> Self {
        Self {
            identity: String::new(),
            points: Vec::new(),
            index: 0,
            offset: 0.0,
            jitter: 0.0,
            amp: 5.0,
            old_sin: 0.0,
            freq: 5.0,
            next_tick: 0.0,
            random: 0x706970626f79,
        }
    }
}
impl RadioWave {
    fn rand(&mut self) -> f32 {
        self.random ^= self.random << 13;
        self.random ^= self.random >> 7;
        self.random ^= self.random << 17;
        (self.random >> 40) as f32 / 16777216.0
    }
    fn sample(&mut self) -> f32 {
        let angle = std::f32::consts::TAU * (self.freq + self.jitter) * self.index as f32 / 226.0
            + self.offset;
        let sine = angle.sin();
        let point = 100.0 - self.amp * sine;
        self.offset += 0.025;
        if self.old_sin < 0.0 && sine > 0.0 && self.rand() < 0.75 {
            self.amp = (self.rand() * 60.0 + 40.0).floor();
        }
        self.old_sin = sine;
        self.index += 1;
        point
    }
    fn update(&mut self, item: &Value, elapsed: f64) {
        let identity = format!(
            "{}:{}:{}",
            id(item, 0),
            yes(&item["active"]),
            n(&item["frequency"])
        );
        if self.identity != identity {
            self.identity = identity;
            self.freq = if yes(&item["active"]) {
                (5.0 + (n(&item["frequency"]) - 70.0) / 40.0 * 5.0)
                    .clamp(5.0, 10.0)
                    .floor()
            } else {
                5.0
            };
            self.offset = self.rand() * std::f32::consts::TAU;
            self.jitter = 2.0 - self.rand() * 4.0;
            self.amp = 5.0;
            self.index = 0;
            self.points.clear();
            for _ in 0..226 {
                let point = self.sample();
                self.points.push(point);
            }
            self.next_tick = elapsed + 0.041;
        }
        // Bound work after a suspended window: no need to simulate hours of
        // hidden procedural points to resume a live display.
        let ticks = (((elapsed - self.next_tick) / 0.041).floor() + 1.0).clamp(0.0, 25.0) as usize;
        for _ in 0..ticks {
            self.points.drain(..10);
            for _ in 0..10 {
                let point = self.sample();
                self.points.push(point);
            }
        }
        if ticks > 0 {
            self.next_tick = elapsed + 0.041;
        }
    }
}

pub struct View {
    pub font: Option<std::sync::Arc<fontdue::Font>>,
    waiting_since: Option<f64>,
    quest_summary: bool,
    quest_started: Option<f64>,
    radio: RadioWave,
    page: usize,
    category: usize,
    selection: Option<String>,
    list_scroll: f32,
    detail_scroll: f32,
    list_max: f32,
    detail_max: f32,
    hits: Vec<Hit>,
    locked: bool,
    pending_until: f64,
    challenge: Option<Challenge>,
    dismissed_token: Option<String>,
    map_identity: String,
    map_zoom: f32,
    map_pan: [f32; 2],
    map_geometry: Rect,
    map_extents: Option<[f32; 6]>,
    map_player: Option<[f32; 2]>,
    map_selection: Option<MapSelection>,
    pointer: [f32; 2],
    drag: Option<Drag>,
}
impl Default for View {
    fn default() -> Self {
        Self {
            font: None,
            waiting_since: None,
            quest_summary: false,
            quest_started: None,
            radio: RadioWave::default(),
            page: 0,
            category: 0,
            selection: None,
            list_scroll: 0.0,
            detail_scroll: 0.0,
            list_max: 0.0,
            detail_max: 0.0,
            hits: Vec::new(),
            locked: true,
            pending_until: 0.0,
            challenge: None,
            dismissed_token: None,
            map_identity: String::new(),
            map_zoom: 1.0,
            map_pan: [0.0; 2],
            map_geometry: MAP,
            map_extents: None,
            map_player: None,
            map_selection: None,
            pointer: [0.0; 2],
            drag: None,
        }
    }
}
fn arr(value: &Value) -> &[Value] {
    value.as_array().map(Vec::as_slice).unwrap_or(&[])
}
fn n(value: &Value) -> f32 {
    value.as_f64().filter(|x| x.is_finite()).unwrap_or(0.0) as f32
}
fn yes(value: &Value) -> bool {
    value.as_bool().unwrap_or(false)
}
fn txt(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        Value::Null => String::new(),
        _ => value.to_string(),
    }
}
fn label(value: &Value) -> String {
    for field in ["text", "Name", "name"] {
        if let Some(v) = value[field].as_str() {
            return v.to_owned();
        }
    }
    String::new()
}
fn id(value: &Value, fallback: usize) -> String {
    for field in ["_id", "formID", "Clip", "Name", "text"] {
        if !value[field].is_null() {
            return txt(&value[field]);
        }
    }
    fallback.to_string()
}
fn integer(value: &Value) -> String {
    value
        .as_f64()
        .filter(|v| v.is_finite())
        .map(|v| format!("{:.0}", v.floor()))
        .unwrap_or_else(|| "—".into())
}
fn number(value: &Value, precision: usize) -> String {
    value
        .as_f64()
        .filter(|v| v.is_finite())
        .map(|v| format!("{:.*}", precision.min(3), v))
        .unwrap_or_else(|| txt(value))
}
fn path(value: &Value) -> Option<&str> {
    value.as_str().or_else(|| value["path"].as_str())
}
fn bounds(value: &Value) -> Option<Rect> {
    let v = value.as_array()?;
    if v.len() < 4 {
        return None;
    }
    Some([n(&v[0]), n(&v[1]), n(&v[2]), n(&v[3])])
}
fn contains(rect: Rect, x: f32, y: f32) -> bool {
    x >= rect[0] && y >= rect[1] && x <= rect[0] + rect[2] && y <= rect[1] + rect[3]
}
fn title(s: &str) -> String {
    match s {
        "$ROF" | "$rate" => "Fire rate",
        "$rng" | "$range" => "Range",
        "$acc" | "$accuracy" => "Accuracy",
        "$wt" => "Weight",
        "$val" => "Value",
        "$dmg" => "Damage",
        "$dr" => "Resistance",
        "$ammo" => "Ammo",
        "$speed" => "Speed",
        "$APCost" => "AP cost",
        "WorkshopRatingPopulation" => "People",
        "PowerGenerated" => "Power",
        "Bed" => "Beds",
        _ => return s.trim_start_matches('$').to_owned(),
    }
    .to_owned()
}
fn categories(page: usize) -> &'static [&'static str] {
    match page {
        0 => &["Status", "SPECIAL", "Perks"],
        1 => &["Weapons", "Apparel", "Aid", "Misc", "Junk", "Mods", "Ammo"],
        2 => &["Quests", "Workshops", "Log"],
        3 => &["World", "Local"],
        _ => &[],
    }
}
fn save_ready(state: &Value) -> bool {
    let p = &state["data"]["PlayerInfo"];
    let status = &state["data"]["Status"];
    yes(&state["connected"])
        && status.is_object()
        && !yes(&status["IsLoading"])
        && !yes(&status["IsDataUnavailable"])
        && p["PlayerName"]
            .as_str()
            .is_some_and(|s| !s.trim().is_empty())
        && n(&p["MaxHP"]) > 0.0
}
fn lock_reason(state: &Value) -> Option<String> {
    if !yes(&state["connected"]) {
        return Some(
            state["message"]
                .as_str()
                .filter(|s| !s.is_empty())
                .unwrap_or("Connecting to Fallout 4…")
                .into(),
        );
    }
    let d = &state["data"];
    let s = &d["Status"];
    if d["PlayerInfo"].is_null() || yes(&s["IsDataUnavailable"]) {
        return Some("Load a save to use the Pip-Boy".into());
    }
    if s.is_null() {
        return Some("Pip-Boy controls unavailable".into());
    }
    for (field, text) in [
        ("IsLoading", "Loading…"),
        ("IsPlayerDead", "Player is dead"),
        ("IsPipboyNotEquipped", "Pip-Boy is not equipped"),
        ("IsPlayerInDialogue", "In dialogue"),
        ("IsInVats", "V.A.T.S. active"),
        ("IsInVatsPlayback", "V.A.T.S. active"),
        ("IsPlayerPipboyLocked", "Pip-Boy controls unavailable"),
        ("IsPlayerMovementLocked", "Pip-Boy controls unavailable"),
        ("IsInAnimation", "Pip-Boy controls unavailable"),
    ] {
        if yes(&s[field]) {
            return Some(text.into());
        }
    }
    None
}
fn text_width(font: Option<&fontdue::Font>, text: &str, size: f32) -> f32 {
    let Some(font) = font else {
        return text.chars().count() as f32 * size * 0.46;
    };
    let mut width = 0.;
    let mut previous = None;
    for c in text.chars() {
        if let Some(p) = previous {
            width += font.horizontal_kern(p, c, size).unwrap_or(0.);
        }
        width += font.metrics(c, size).advance_width;
        previous = Some(c);
    }
    width
}
fn centered(scene: &mut Scene, text: &str, cx: f32, y: f32, size: f32, shade: f32, bold: bool) {
    scene.text_center(text, cx, y, size, shade, bold);
}
fn wrapped(
    font: Option<&fontdue::Font>,
    scene: &mut Scene,
    text: &str,
    x: f32,
    mut y: f32,
    width: f32,
    size: f32,
    shade: f32,
) -> f32 {
    for paragraph in text.split('\n') {
        let mut line = String::new();
        for word in paragraph.split_whitespace() {
            if !line.is_empty() && text_width(font, &format!("{line} {word}"), size) > width {
                scene.text(&line, x, y, size, shade, false);
                y += size * 1.22;
                line.clear();
            }
            if !line.is_empty() {
                line.push(' ');
            }
            for ch in word.chars() {
                if !line.is_empty() && text_width(font, &format!("{line}{ch}"), size) > width {
                    scene.text(&line, x, y, size, shade, false);
                    y += size * 1.22;
                    line.clear();
                }
                line.push(ch);
            }
        }
        if !line.is_empty() {
            scene.text(line, x, y, size, shade, false);
        }
        y += size * 1.22;
    }
    y
}
fn meter(scene: &mut Scene, rect: Rect, fraction: f32, shade: f32) {
    scene.outline(rect, 1.0, shade);
    scene.rect(
        [
            rect[0] + 1.0,
            rect[1] + 1.0,
            (rect[2] - 2.0) * fraction.clamp(0.0, 1.0),
            rect[3] - 2.0,
        ],
        shade,
    );
}
fn icon(scene: &mut Scene, value: &Value, rect: Rect, shade: f32) {
    if let Some(p) = path(value) {
        scene.image(p, rect, shade);
    }
}

impl View {
    pub fn preview_page(&mut self, page: usize, category: usize) {
        self.page = page.min(4);
        self.category = category.min(categories(self.page).len().saturating_sub(1));
    }

    fn hit(&mut self, rect: Rect, action: Action, enabled: bool) {
        self.hits.push(Hit {
            rect,
            action,
            enabled,
        });
    }
    fn button(&mut self, scene: &mut Scene, rect: Rect, text: &str, action: Action, enabled: bool) {
        let shade = if enabled { 1.0 } else { 0.32 };
        scene.outline(rect, 1.0, shade);
        if matches!(text, "↑" | "↓" | "‹" | "›" | "←" | "→") {
            let x = rect[0] + rect[2] / 2.;
            let y = rect[1] + rect[3] / 2.;
            let points = match text {
                "↑" => [[x - 7., y + 4.], [x, y - 4.], [x + 7., y + 4.]],
                "↓" => [[x - 7., y - 4.], [x, y + 4.], [x + 7., y - 4.]],
                "‹" | "←" => [[x + 4., y - 7.], [x - 4., y], [x + 4., y + 7.]],
                _ => [[x - 4., y - 7.], [x + 4., y], [x - 4., y + 7.]],
            };
            scene.line(points[0], points[1], 2., shade);
            scene.line(points[1], points[2], 2., shade);
        } else if matches!(text, "+" | "−" | "◎" | "↺") {
            let x = rect[0] + rect[2] / 2.;
            let y = rect[1] + rect[3] / 2.;
            if matches!(text, "+" | "−") {
                scene.line([x - 7., y], [x + 7., y], 2., shade);
                if text == "+" {
                    scene.line([x, y - 7.], [x, y + 7.], 2., shade);
                }
            } else {
                let steps = if text == "◎" { 24 } else { 20 };
                for i in 0..steps {
                    let a = i as f32 * std::f32::consts::TAU / 24.;
                    let b = (i + 1) as f32 * std::f32::consts::TAU / 24.;
                    scene.line(
                        [x + 7. * a.cos(), y + 7. * a.sin()],
                        [x + 7. * b.cos(), y + 7. * b.sin()],
                        1.5,
                        shade,
                    );
                }
                if text == "◎" {
                    scene.line([x - 3., y], [x + 3., y], 1.5, shade);
                    scene.line([x, y - 3.], [x, y + 3.], 1.5, shade);
                } else {
                    scene.line([x + 7., y], [x + 3., y - 3.], 1.5, shade);
                    scene.line([x + 7., y], [x + 10., y - 4.], 1.5, shade);
                }
            }
        } else {
            centered(
                scene,
                text,
                rect[0] + rect[2] / 2.,
                rect[1] + 8.,
                23.,
                shade,
                false,
            );
        }
        self.hit(rect, action, enabled);
    }
    fn command(
        &mut self,
        scene: &mut Scene,
        rect: Rect,
        text: &str,
        command: Value,
        available: bool,
    ) {
        self.button(
            scene,
            rect,
            text,
            Action::Command(command),
            available && !self.locked,
        );
    }
    pub fn frame(&mut self, state: &Value, elapsed: f64) -> Scene {
        let mut scene = Scene::default();
        self.hits.clear();
        let reason = lock_reason(state);
        self.locked = reason.is_some();
        if !save_ready(state) {
            self.locked = true;
            self.challenge = None;
            self.drag = None;
            self.pending_until = 0.0;
            let since = *self.waiting_since.get_or_insert(elapsed);
            let animation = &state["assets"]["animations"]["waiting"];
            let frames = arr(&animation["frames"]);
            if let Some([_, _, width, height]) = bounds(&animation["viewBox"]) {
                if width > 0.0 && height > 0.0 && !frames.is_empty() {
                    // The game's default perk animation raises a thumb, holds,
                    // then lowers it. Stop in its central hold for a quiet idle.
                    let fps = animation["fps"].as_f64().unwrap_or(30.0);
                    let frame = (((elapsed - since).max(0.0) * fps) as usize).min(frames.len() / 2);
                    if let Some(path) = frames[frame].as_str() {
                        let scale = (330.0 / width).min(400.0 / height);
                        let (w, h) = (width * scale, height * scale);
                        scene.image(path, [(876.0 - w) / 2.0, (740.0 - h) / 2.0, w, h], 0.7);
                    }
                }
            }
            return scene;
        }
        self.waiting_since = None;
        self.nav(&mut scene);
        match self.page {
            0 if self.category == 0 => self.status(&mut scene, state, elapsed),
            3 => self.map(&mut scene, state),
            _ => self.list_page(&mut scene, state, elapsed),
        }
        self.vitals(&mut scene, state);
        if let Some(reason) = reason {
            scene.rect([150.0, 592.0, 576.0, 34.0], 0.0);
            centered(&mut scene, &reason, 438.0, 597.0, 21.0, 0.75, false);
        }
        let notice = state["notice"]
            .as_str()
            .or_else(|| state["notice"]["message"].as_str())
            .unwrap_or("");
        if !notice.is_empty() {
            scene.rect([170.0, 666.0, 536.0, 27.0], 0.0);
            centered(&mut scene, notice, 438.0, 669.0, 19.0, 0.8, false);
        } else if elapsed < self.pending_until {
            centered(&mut scene, "Sent to game…", 438.0, 667.0, 19.0, 0.7, false);
        }
        self.confirmation(&mut scene, state, elapsed);
        scene
    }
    fn nav(&mut self, scene: &mut Scene) {
        // Pipboy_Header/shape42: two short inward-facing hooks, joined to
        // the baseline at y63.15. The hooks rise into the label's line, not
        // above it; there is no top edge across the selected word.
        let centers = [192.6, 305.1, 419.0, 540.35, 666.65];
        let widths = [84.0, 58.0, 87.0, 74.0, 102.0];
        let left = centers[self.page] - widths[self.page] / 2.0 - 12.5;
        let right = centers[self.page] + widths[self.page] / 2.0 + 12.5;
        scene.rect([38.15, 61.65, left - 38.15, 3.0], 1.0);
        scene.rect([right, 61.65, 832.8 - right, 3.0], 1.0);
        for (x, direction) in [(left, 1.0), (right, -1.0)] {
            scene.rect(
                [
                    x - if direction < 0.0 { 2.0 } else { 0.0 },
                    35.1,
                    2.0,
                    30.05,
                ],
                1.0,
            );
            scene.rect(
                [x - if direction < 0.0 { 9.0 } else { 0.0 }, 35.1, 9.0, 2.0],
                1.0,
            );
        }
        for (i, name) in PAGES.iter().enumerate() {
            centered(scene, name, centers[i], 15.0, 36.0, 1.0, true);
            self.hit(
                [
                    centers[i] - widths[i] / 2.0 - 10.0,
                    8.0,
                    widths[i] + 20.0,
                    53.0,
                ],
                Action::Page(i),
                true,
            );
        }
        // The original tab strip places the selected category below its
        // parent page and shows at most two neighbours on either side.
        let names = categories(self.page);
        if names.is_empty() {
            return;
        }
        let size = 28.0;
        let widths: Vec<f32> = names
            .iter()
            .map(|v| text_width(self.font.as_deref(), &v.to_uppercase(), size))
            .collect();
        let mut positions = vec![0.0; names.len()];
        positions[self.category] = centers[self.page] - widths[self.category] / 2.0;
        for i in (0..self.category).rev() {
            positions[i] = positions[i + 1] - 12.5 - widths[i];
        }
        for i in self.category + 1..names.len() {
            positions[i] = positions[i - 1] + widths[i - 1] + 12.5;
        }
        scene.clip(Some([38.1, 67.0, 799.8, 40.0]));
        for (i, name) in names.iter().enumerate() {
            let distance = i.abs_diff(self.category);
            if distance > 2 {
                continue;
            }
            scene.text(
                name.to_uppercase(),
                positions[i],
                72.0,
                size,
                [1.0, 0.45, 0.2][distance],
                false,
            );
            let x = positions[i].max(38.1);
            let end = (positions[i] + widths[i] + 8.0).min(837.9);
            if end > x {
                self.hit([x, 67.0, end - x, 39.0], Action::Category(i), true);
            }
        }
        scene.clip(None);
    }
    fn list_rect(&self) -> Rect {
        match (self.page, self.category) {
            (1, _) => [42.5, 163.75, 485.0, 405.0],
            (2, 1) => [38.05, 166.0, 465.0, 405.0],
            (2, _) | (4, _) => [37.5, 163.75, 395.0, 405.0],
            _ => LIST,
        }
    }
    fn status(&mut self, scene: &mut Scene, state: &Value, elapsed: f64) {
        let d = &state["data"];
        let p = &d["PlayerInfo"];
        let stats = &d["Stats"];
        let assets = &state["assets"];
        scene.clip(Some(CONTENT));
        let anim = &assets["animations"]["status"];
        let body = &anim["bodies"][integer(&stats["BodyFlags"])];
        let frames = arr(&body["frames"]);
        if !frames.is_empty() {
            let frame = ((elapsed.max(0.0) * body["fps"].as_f64().unwrap_or(30.0)).floor()
                as usize)
                % frames.len();
            if let (Some(box_), Some(p)) = (bounds(&body["viewBox"]), frames[frame].as_str()) {
                scene.image(
                    p,
                    [
                        424.95 + box_[0] * 0.06,
                        303.7 + box_[1] * 0.06,
                        box_[2] * 0.06,
                        box_[3] * 0.06,
                    ],
                    0.5,
                );
            }
            let heads = &anim["heads"];
            let head_frames = arr(&heads["frames"]);
            let head_index =
                (n(&stats["HeadFlags"]).max(0.0) as usize).min(head_frames.len().saturating_sub(1));
            if let (Some(box_), Some(p), Some(m)) = (
                bounds(&heads["viewBox"]),
                head_frames.get(head_index).and_then(Value::as_str),
                arr(&body["headTransforms"])
                    .get(frame)
                    .and_then(Value::as_array),
            ) {
                if m.len() >= 6 {
                    let [x, y, w, h] = box_;
                    let corners = [[x, y], [x + w, y], [x + w, y + h], [x, y + h]].map(|[x, y]| {
                        [
                            424.95 + 0.06 * (n(&m[0]) * x + n(&m[2]) * y + n(&m[4])),
                            303.7 + 0.06 * (n(&m[1]) * x + n(&m[3]) * y + n(&m[5])),
                        ]
                    });
                    scene.image_quad(p, corners, 0.5, None);
                }
            }
        } else {
            icon(
                scene,
                &assets["icons"]["status"]["healthy"],
                [321.1, 165.0, 205.0, 280.0],
                0.5,
            );
        }
        for (x, y, field) in [
            (417.2, 146.2, "HeadCondition"),
            (275.2, 259.2, "RArmCondition"),
            (551.2, 259.2, "LArmCondition"),
            (275.05, 404.75, "RLegCondition"),
            (551.2, 405.0, "LLegCondition"),
        ] {
            meter(
                scene,
                [x - 21.0, y - 4.0, 42.0, 8.0],
                n(&stats[field]) / 100.0,
                1.0,
            );
        }
        meter(
            scene,
            [396.2, 452.2, 42.0, 8.0],
            n(&p["CurrHP"]) / n(&p["MaxHP"]).max(1.0),
            1.0,
        );
        let damage: Vec<_> = arr(&p["TotalDamages"])
            .iter()
            .filter(|v| n(&v["Value"]) > 0.0)
            .collect();
        let resist: Vec<_> = arr(&p["TotalResists"])
            .iter()
            .filter(|v| n(&v["Value"]) > 0.0)
            .collect();
        let width = 76.0 * 2.0 + 46.0 * (damage.len() + resist.len()) as f32 + 20.0;
        let mut x = (876.0 - width) / 2.0;
        for (kind, values, offset) in [("weapon", damage, 5), ("armor", resist, -1)] {
            scene.rect([x, 492.85, 76.0, 70.0], 0.07);
            icon(
                scene,
                &assets["icons"][kind],
                [x + 7.0, 503.85, 62.0, 48.0],
                1.0,
            );
            x += 78.0;
            for v in values {
                scene.rect([x, 492.85, 44.0, 70.0], 0.07);
                let i = (n(&v["type"]) as i32 + offset).max(0) as usize;
                icon(
                    scene,
                    &assets["icons"]["damage"][i],
                    [x + 11.0, 500.0, 22.0, 22.0],
                    1.0,
                );
                centered(
                    scene,
                    &integer(&v["Value"]),
                    x + 22.0,
                    529.0,
                    28.0,
                    1.0,
                    false,
                );
                x += 46.0;
            }
            x += 18.0;
        }
        centered(
            scene,
            p["PlayerName"].as_str().unwrap_or(""),
            437.1,
            580.05,
            28.0,
            1.0,
            false,
        );
        let mut y = 135.0;
        for effect in arr(&stats["ActiveEffects"]) {
            y = wrapped(
                self.font.as_deref(),
                scene,
                &label(effect),
                680.0,
                y,
                155.0,
                18.0,
                0.75,
            );
        }
        scene.clip(None);
        let version = d["Inventory"]["Version"].clone();
        self.command(
            scene,
            [235.0, 690.0, 185.0, 42.0],
            &format!("STIMPAK ({})", integer(&stats["StimpakCount"])),
            json!({"action":"stimpak","version":version}),
            n(&stats["StimpakCount"]) > 0.0,
        );
        self.command(
            scene,
            [431.0, 690.0, 192.0, 42.0],
            &format!("RADAWAY ({})", integer(&stats["RadawayCount"])),
            json!({"action":"radaway","version":version}),
            n(&stats["RadawayCount"]) > 0.0,
        );
        self.button(
            scene,
            [636.0, 690.0, 118.0, 42.0],
            "PERKS",
            Action::Category(2),
            true,
        );
    }
    fn list_page(&mut self, scene: &mut Scene, state: &Value, elapsed: f64) {
        let d = &state["data"];
        let list = self.list_rect();
        let mut items: Vec<&Value> = match (self.page, self.category) {
            (0, 1) => arr(&d["Special"]).iter().collect(),
            (0, _) => arr(&d["Perks"])
                .iter()
                .filter(|p| yes(&p["ListVisible"]) && n(&p["Rank"]) > 0.0)
                .collect(),
            (1, cat) => {
                let filter = [2, 4, 8, 512 | 128, 1024, 2048, 4096][cat.min(6)];
                d["Inventory"]
                    .as_object()
                    .into_iter()
                    .flat_map(|o| o.iter())
                    .filter(|(k, v)| k.chars().all(|c| c.is_ascii_digit()) && v.is_array())
                    .flat_map(|(_, v)| arr(v))
                    .filter(|i| i["filterFlag"].as_u64().unwrap_or(0) & filter != 0)
                    .collect()
            }
            (2, 0) => arr(&d["Quests"]).iter().collect(),
            (2, 1) => arr(&d["Workshop"])
                .iter()
                .filter(|p| yes(&p["owned"]))
                .collect(),
            (2, _) => arr(&d["Log"]).iter().collect(),
            _ => arr(&d["Radio"]).iter().collect(),
        };
        if self.page == 1 {
            items.sort_by_key(|i| label(i).to_lowercase());
        }
        if items.is_empty() {
            centered(
                scene,
                "No entries available",
                438.0,
                285.0,
                28.0,
                0.65,
                false,
            );
            self.list_max = 0.0;
            self.detail_max = 0.0;
            if self.page == 4 {
                self.draw_radio(scene, state, None, elapsed);
            }
            return;
        }
        let selected = items
            .iter()
            .enumerate()
            .position(|(i, v)| self.selection.as_deref() == Some(&id(v, i)))
            .unwrap_or(0);
        let selected_id = id(items[selected], selected);
        if self.selection.as_deref() != Some(&selected_id) {
            self.quest_started = Some(elapsed);
            self.quest_summary = false;
        }
        self.selection = Some(selected_id);
        let font_size = if self.page == 4 {
            32.0
        } else if self.page == 0 {
            26.0
        } else {
            28.0
        };
        let row_height = if self.page == 0 { 49.0 } else { 40.0 };
        self.list_max = (items.len() as f32 * row_height - list[3]).max(0.0);
        self.list_scroll = self.list_scroll.clamp(0.0, self.list_max);
        scene.clip(Some(list));
        for (i, item) in items.iter().enumerate() {
            let y = list[1] + i as f32 * row_height - self.list_scroll;
            if y + row_height < list[1] || y > list[1] + list[3] {
                continue;
            }
            let chosen = i == selected;
            if chosen {
                scene.rect([list[0], y, list[2], row_height - 2.0], 1.0);
            }
            let shade = if chosen { 0.0 } else { 1.0 };
            let badge = match (self.page, self.category) {
                (0, 1) => integer(&item["Value"]),
                (0, _) => format!("{}/{}", integer(&item["Rank"]), integer(&item["MaxRank"])),
                (1, _) | (2, 0) => String::new(),
                (2, 1) => {
                    if n(&item["rating"]) < 0.0 {
                        "!".into()
                    } else {
                        String::new()
                    }
                }
                (4, _) => String::new(),
                _ => String::new(),
            };
            let available = list[2] - 45.0 - text_width(self.font.as_deref(), &badge, 21.0);
            let name = if self.page == 1 && n(&item["count"]) > 1.0 {
                format!("{} ({})", label(item), integer(&item["count"]))
            } else if self.page == 2 && self.category == 2 {
                title(&label(item))
            } else {
                label(item)
            };
            let mut name = name;
            if text_width(self.font.as_deref(), &name, font_size) > available {
                while !name.is_empty()
                    && text_width(self.font.as_deref(), &(name.clone() + "…"), font_size)
                        > available
                {
                    name.pop();
                }
                name.push('…');
            }
            let equipped = (self.page == 1 && n(&item["equipState"]) != 0.0)
                || (matches!(self.page, 2 | 4) && yes(&item["active"]));
            if equipped {
                scene.rect([list[0] + 9.0, y + 13.0, 9.0, 9.0], shade);
            }
            scene.text(name, list[0] + 26.25, y + 3.0, font_size, shade, false);
            scene.text(
                &badge,
                list[0] + list[2] - text_width(self.font.as_deref(), &badge, 21.0) - 8.0,
                y + 12.0,
                21.0,
                shade,
                false,
            );
            let clipped = [
                list[0],
                y.max(list[1]),
                list[2],
                (y + row_height - 2.0).min(list[1] + list[3]) - y.max(list[1]),
            ];
            if clipped[3] > 0.0 {
                self.hit(clipped, Action::Select(id(item, i)), true);
            }
        }
        scene.clip(None);

        self.detail(scene, state, items[selected], selected, elapsed);
        self.button(
            scene,
            [40.0, 690.0, 63.0, 42.0],
            "↑",
            Action::Scroll(-245.0, false),
            self.list_scroll > 0.0,
        );
        self.button(
            scene,
            [112.0, 690.0, 63.0, 42.0],
            "↓",
            Action::Scroll(245.0, false),
            self.list_scroll < self.list_max,
        );
        if self.detail_max > 0.0 {
            self.button(
                scene,
                [765.0, 690.0, 34.0, 42.0],
                "↑",
                Action::Scroll(-180.0, true),
                self.detail_scroll > 0.0,
            );
            self.button(
                scene,
                [804.0, 690.0, 34.0, 42.0],
                "↓",
                Action::Scroll(180.0, true),
                self.detail_scroll < self.detail_max,
            );
        }
    }
    fn detail(
        &mut self,
        scene: &mut Scene,
        state: &Value,
        item: &Value,
        index: usize,
        elapsed: f64,
    ) {
        let assets = &state["assets"];
        let detail = if self.page == 1 {
            [550.0, 116.0, 288.0, 484.0]
        } else {
            DETAIL
        };
        scene.clip(Some(detail));
        let top = DETAIL[1] - self.detail_scroll;
        let mut y = top + 12.0;
        if self.page == 0 && self.category != 1 {
            y = wrapped(
                self.font.as_deref(),
                scene,
                &label(item),
                439.0,
                y,
                384.0,
                29.0,
                1.0,
            ) + 12.0;
        }
        let mut facts: Vec<(String, String)> = Vec::new();
        match (self.page, self.category) {
            (0, 1) => {
                let name = SPECIAL[index.min(6)];
                let anim = &assets["animations"]["special"][name];
                let frames = arr(&anim["frames"]);
                if let (Some(box_), false) = (bounds(&anim["viewBox"]), frames.is_empty()) {
                    let frame = ((elapsed.max(0.0) * anim["fps"].as_f64().unwrap_or(30.0)).floor()
                        as usize)
                        % frames.len();
                    let scale = (320.0 / box_[2]).min(250.0 / box_[3]);
                    icon(
                        scene,
                        &frames[frame],
                        [
                            439.0 + (384.0 - box_[2] * scale) / 2.0,
                            y,
                            box_[2] * scale,
                            box_[3] * scale,
                        ],
                        1.0,
                    );
                } else {
                    icon(
                        scene,
                        &assets["icons"]["special"][name],
                        [481.0, y, 290.0, 250.0],
                        1.0,
                    );
                }
                y += 265.0;
                y = wrapped(
                    self.font.as_deref(),
                    scene,
                    item["Description"].as_str().unwrap_or(""),
                    439.0,
                    y,
                    384.0,
                    24.0,
                    1.0,
                ) + 14.0;
                facts.push(("Value".into(), integer(&item["Value"])));
                facts.push(("Modifier".into(), integer(&item["Modifier"])));
            }
            (0, _) => {
                if let Some(clip) = item["Clip"].as_str() {
                    if path(&assets["icons"][clip]).is_some() {
                        icon(scene, &assets["icons"][clip], [521.0, y, 200.0, 170.0], 1.0);
                        y += 182.0;
                    }
                }
                let rank = (n(&item["Rank"]) as usize).saturating_sub(1);
                let desc = item["Perks"][rank]["Description"]
                    .as_str()
                    .unwrap_or("No description available.");
                y = wrapped(
                    self.font.as_deref(),
                    scene,
                    desc,
                    439.0,
                    y,
                    384.0,
                    24.0,
                    1.0,
                ) + 12.0;
                facts.push((
                    "Rank".into(),
                    format!("{} / {}", integer(&item["Rank"]), integer(&item["MaxRank"])),
                ));
            }
            (1, _) => {
                scene.clip(None);
                self.inventory_card(scene, state, item);
                scene.clip(Some(detail));
                y = top;
            }
            (2, 0) => {
                y = 400.95 - self.detail_scroll;
                let quests = &assets["animations"]["quests"];
                let key = item["SWFFile"]
                    .as_str()
                    .or_else(|| item["swfFile"].as_str())
                    .unwrap_or("")
                    .replace('\\', "/")
                    .to_lowercase();
                let key = key.strip_prefix("interface/").unwrap_or(&key);
                let specific = &quests["byPath"][key];
                let (animation, scale) = if specific.is_object() {
                    (specific, 0.7 / 20.0)
                } else {
                    (&quests["default"], 1.0 / 20.0)
                };
                let frames = arr(&animation["frames"]);
                let played =
                    ((elapsed - self.quest_started.get_or_insert(elapsed).to_owned()).max(0.0)
                        * animation["fps"].as_f64().unwrap_or(30.0)) as usize;
                if yes(&animation["playOnce"])
                    && !frames.is_empty()
                    && played >= frames.len()
                    && item["description"].as_str().is_some_and(|v| !v.is_empty())
                {
                    self.quest_summary = true;
                }
                if self.quest_summary {
                    y = wrapped(
                        self.font.as_deref(),
                        scene,
                        item["description"].as_str().unwrap_or(""),
                        437.45,
                        166.35 - self.detail_scroll,
                        395.0,
                        24.0,
                        1.0,
                    )
                    .max(y - 20.0)
                        + 20.0;
                } else {
                    if let (Some(b), false) = (bounds(&animation["viewBox"]), frames.is_empty()) {
                        let frame = if yes(&animation["playOnce"]) {
                            played.min(frames.len() - 1)
                        } else {
                            played % frames.len()
                        };
                        icon(
                            scene,
                            &frames[frame],
                            [
                                475.0 + b[0] * scale,
                                106.0 + b[1] * scale - self.detail_scroll,
                                b[2] * scale,
                                b[3] * scale,
                            ],
                            1.0,
                        );
                    } else {
                        y = wrapped(
                            self.font.as_deref(),
                            scene,
                            item["description"].as_str().unwrap_or(""),
                            437.45,
                            166.35 - self.detail_scroll,
                            395.0,
                            24.0,
                            1.0,
                        )
                        .max(y - 20.0)
                            + 20.0;
                    }
                }
                let objectives = if item["objectives"].is_array() {
                    &item["objectives"]
                } else {
                    &item["Objectives"]
                };
                for objective in arr(objectives) {
                    let shade = if yes(&objective["completed"]) {
                        0.45
                    } else {
                        1.0
                    };
                    scene.outline([443.0, y + 9.0, 8.0, 8.0], 1.0, shade);
                    if yes(&objective["completed"]) {
                        scene.rect([445.0, y + 11.0, 4.0, 4.0], shade);
                    }
                    y = wrapped(
                        self.font.as_deref(),
                        scene,
                        &label(objective),
                        462.0,
                        y,
                        366.0,
                        24.0,
                        shade,
                    ) + 10.0;
                }
            }
            (2, 1) => {
                y = 165.55 - self.detail_scroll;
                for v in arr(&item["workshopData"]) {
                    scene.rect([579.0, y, 244.0, 36.5], 0.07);
                    scene.text(title(&label(v)), 620.15, y + 2.0, 24.0, 1.0, false);
                    scene.text(number(&v["Value"], 0), 749.0, y + 2.0, 24.0, 1.0, false);
                    y += 40.0;
                }
            }
            (2, _) => {
                y = 165.95 - self.detail_scroll;
                for v in arr(&item["statArray"]) {
                    if yes(&v["showIfZero"]) || n(&v["Value"]) != 0.0 {
                        scene.text(title(&label(v)), 450.05, y + 2.5, 24.0, 1.0, false);
                        scene.text(number(&v["Value"], 0), 729.3, y + 2.15, 24.0, 1.0, false);
                        y += 37.25;
                    }
                }
            }
            (4, _) => {
                scene.clip(None);
                self.draw_radio(scene, state, Some(item), elapsed);
                scene.clip(Some(detail));
                y = top;
            }
            _ => {}
        }
        for (key, value) in facts {
            scene.rect([439.0, y + 34.0, 384.0, 1.0], 0.2);
            y = wrapped(
                self.font.as_deref(),
                scene,
                &key,
                439.0,
                y,
                256.0,
                23.0,
                1.0,
            )
            .max(y + 35.0);
            scene.text(
                &value,
                825.0 - text_width(self.font.as_deref(), &value, 23.0),
                y - 35.0,
                23.0,
                1.0,
                false,
            );
        }
        if self.page != 1 {
            self.detail_max = (y - top - DETAIL[3] + 16.0).max(0.0);
        }
        self.detail_scroll = self.detail_scroll.clamp(0.0, self.detail_max);
        scene.clip(None);
        if self.page == 2
            && self.category == 0
            && item["description"].as_str().is_some_and(|v| !v.is_empty())
        {
            self.button(
                scene,
                [590.0, 690.0, 153.0, 42.0],
                if self.quest_summary {
                    "ANIMATION"
                } else {
                    "SUMMARY"
                },
                Action::Summary,
                true,
            );
        }
        let valid = item["_id"].is_u64() || item["_id"].is_i64();
        match self.page {
            1 => {
                let flag = item["filterFlag"].as_u64().unwrap_or(0);
                let equip = flag & 6 != 0;
                if equip || flag & (8 | 128 | 8192) != 0 {
                    let name = if equip {
                        if n(&item["equipState"]) != 0.0 {
                            "UNEQUIP"
                        } else {
                            "EQUIP"
                        }
                    } else if flag & 8192 != 0 {
                        "PLAY"
                    } else {
                        "USE"
                    };
                    self.command(scene,[332.0,690.0,212.0,42.0],name,json!({"action":"use","id":item["_id"],"version":state["data"]["Inventory"]["Version"]}),valid);
                }
            }
            2 if self.category == 0 => self.command(
                scene,
                [314.0, 690.0, 250.0, 42.0],
                if yes(&item["active"]) {
                    "STOP TRACKING"
                } else {
                    "TRACK QUEST"
                },
                json!({"action":"quest","id":item["_id"]}),
                valid,
            ),
            4 => self.command(
                scene,
                [332.0, 690.0, 212.0, 42.0],
                if yes(&item["active"]) {
                    "TURN OFF"
                } else {
                    "TUNE IN"
                },
                json!({"action":"radio","id":item["_id"]}),
                valid && item["inRange"] != false,
            ),
            _ => {}
        }
    }
    fn inventory_card(&mut self, scene: &mut Scene, state: &Value, item: &Value) {
        // Pipboy_InvPage ItemCard(794.05,596) builds entries bottom-up.
        // Its model is an engine render beside/behind this lower-right card.
        if let Some(form) = item["formID"].as_u64().and_then(|v| u32::try_from(v).ok()) {
            let descriptor = &state["assets"]["models"][form.to_string()];
            if descriptor["status"] != "unsupported" && descriptor["error"].is_null() {
                scene.model(
                    form,
                    descriptor["path"].as_str(),
                    [520.0, 128.0, 290.0, 260.0],
                );
            }
        }
        scene.clip(Some([550.0, 116.0, 288.0, 484.0]));
        let entries = arr(&item["itemCardInfoList"]);
        let mut rows: Vec<(String, String, Option<usize>)> = Vec::new();
        // MultiEntry moves damage/resistance groups above standard entries.
        for group in ["$dr", "$dmg"] {
            let mut first = true;
            for v in entries
                .iter()
                .filter(|v| v["text"] == group && n(&v["Value"]) > 0.0)
            {
                let index = n(&v["damageType"]) as i32 + if group == "$dmg" { 5 } else { -1 };
                rows.push((
                    if first { title(group) } else { String::new() },
                    number(&v["Value"], n(&v["precision"]) as usize),
                    Some(index.max(0) as usize),
                ));
                first = false;
            }
        }
        for v in entries {
            if matches!(v["text"].as_str(), Some("$dmg" | "$dr")) || yes(&v["showAsDescription"]) {
                continue;
            }
            if v["components"].is_array() {
                for component in arr(&v["components"]) {
                    rows.push((label(component), integer(&component["count"]), None));
                }
            } else {
                rows.push((
                    title(v["text"].as_str().unwrap_or("")),
                    number(&v["Value"], n(&v["precision"]) as usize),
                    None,
                ));
            }
        }
        self.detail_max = (rows.len() as f32 * 33.0 - 480.0).max(0.0);
        let top = 596.0 - rows.len() as f32 * 33.0 + self.detail_scroll;
        for (i, (key, value, damage)) in rows.iter().enumerate() {
            let y = top + i as f32 * 33.0;
            scene.rect([554.35, y, 259.0, 31.0], 0.07);
            scene.text(key, 560.6, y + 2.0, 28.0, 1.0, false);
            if let Some(index) = damage {
                icon(
                    scene,
                    &state["assets"]["icons"]["damage"][*index],
                    [711.0, y + 6.0, 18.0, 18.0],
                    1.0,
                );
            }
            let x = 801.0 - text_width(self.font.as_deref(), value, 28.0);
            scene.text(value, x, y + 2.0, 28.0, 1.0, true);
        }
        let description = entries
            .iter()
            .find(|v| yes(&v["showAsDescription"]))
            .and_then(|v| v["text"].as_str())
            .or_else(|| item["description"].as_str());
        if let Some(description) = description {
            // Description cards precede the property stack, matching the
            // native ItemCard's final (highest) inserted entry.
            let lines = (text_width(self.font.as_deref(), description, 22.0) / 253.0)
                .ceil()
                .max(1.0);
            wrapped(
                self.font.as_deref(),
                scene,
                description,
                560.6,
                top - lines * 28.0 - 8.0,
                253.0,
                22.0,
                1.0,
            );
        }
        scene.clip(None);
    }
    fn draw_radio(&mut self, scene: &mut Scene, state: &Value, item: Option<&Value>, elapsed: f64) {
        // Exported instrument scale preserves the irregular native tick marks.
        let scale = &state["assets"]["pages"]["radio"]["scale"];
        if let Some(p) = path(scale) {
            let b = bounds(&scale["viewBox"]).unwrap_or([11314.0, 2920.0, 4931.0, 5023.0]);
            scene.image(p, [b[0] / 20.0, b[1] / 20.0, b[2] / 20.0, b[3] / 20.0], 1.0);
        } else {
            scene.outline([565.7, 146.0, 246.55, 251.15], 1.0, 1.0);
        }
        if let Some(item) = item {
            self.radio.update(item, elapsed);
            let mut previous = [570.95, 258.0];
            for (i, value) in self.radio.points.iter().enumerate() {
                let point = [570.95 + i as f32, 158.0 + value];
                scene.line(previous, point, 2.0, 1.0);
                previous = point;
            }
        } else {
            scene.rect([565.8, 269.35, 245.0, 2.0], 1.0);
        }
    }
    fn vitals(&self, scene: &mut Scene, state: &Value) {
        let p = &state["data"]["PlayerInfo"];
        match self.page {
            0 => {
                scene.rect([38.1, 629.75, 190.0, 39.0], 0.07);
                scene.text(
                    format!("HP {}/{}", integer(&p["CurrHP"]), integer(&p["MaxHP"])),
                    44.8,
                    634.65,
                    30.0,
                    1.0,
                    true,
                );
                scene.rect([232.0, 629.75, 405.0, 39.0], 0.07);
                scene.text(
                    format!("LEVEL {}", integer(&p["XPLevel"])),
                    242.0,
                    635.0,
                    28.0,
                    1.0,
                    true,
                );
                meter(
                    scene,
                    [340.0, 642.0, 284.0, 15.0],
                    n(&p["XPProgressPct"]),
                    1.0,
                );
                scene.rect([642.0, 629.75, 195.9, 39.0], 0.07);
                scene.text(
                    format!("AP {}/{}", integer(&p["CurrAP"]), integer(&p["MaxAP"])),
                    649.0,
                    634.65,
                    30.0,
                    1.0,
                    true,
                );
            }
            1 => {
                scene.text(
                    format!(
                        "WT {}/{}",
                        integer(&p["CurrWeight"]),
                        integer(&p["MaxWeight"])
                    ),
                    44.8,
                    635.0,
                    28.0,
                    1.0,
                    true,
                );
                scene.text(
                    format!("CAPS {}", integer(&p["Caps"])),
                    287.0,
                    635.0,
                    28.0,
                    1.0,
                    true,
                );
                if self.category == 2 {
                    scene.text("HP", 578.0, 635.0, 26.0, 1.0, true);
                    meter(
                        scene,
                        [629.0, 640.0, 200.0, 18.0],
                        n(&p["CurrHP"]) / n(&p["MaxHP"]).max(1.0),
                        1.0,
                    );
                }
                if self.category <= 1 {
                    let values = if self.category == 0 {
                        &p["TotalDamages"]
                    } else {
                        &p["TotalResists"]
                    };
                    let mut x = 565.0;
                    for v in arr(values).iter().filter(|v| n(&v["Value"]) > 0.0) {
                        let i = (n(&v["type"]) as i32 + if self.category == 0 { 5 } else { -1 })
                            .max(0) as usize;
                        icon(
                            scene,
                            &state["assets"]["icons"]["damage"][i],
                            [x, 637.0, 22.0, 22.0],
                            1.0,
                        );
                        scene.text(integer(&v["Value"]), x + 27.0, 635.0, 26.0, 1.0, false);
                        x += 82.0;
                    }
                }
            }
            2 | 3 => {
                let hour = n(&p["TimeHour"]).floor() as i32;
                let minute = ((n(&p["TimeHour"]) - hour as f32) * 60.0).floor() as i32;
                scene.text(
                    format!(
                        "{}.{}.2{}",
                        integer(&p["DateMonth"]),
                        integer(&p["DateDay"]),
                        integer(&p["DateYear"])
                    ),
                    44.8,
                    635.0,
                    26.0,
                    1.0,
                    false,
                );
                scene.text(
                    format!(
                        "{}:{:02} {}",
                        if hour % 12 == 0 { 12 } else { hour % 12 },
                        minute,
                        if hour < 12 { "AM" } else { "PM" }
                    ),
                    309.0,
                    635.0,
                    26.0,
                    1.0,
                    false,
                );
                if self.page == 3 {
                    let map = &state["data"]["Map"];
                    let name = map["CurrCell"]
                        .as_str()
                        .filter(|s| !s.is_empty())
                        .or_else(|| map["CurrWorldspace"].as_str())
                        .unwrap_or("");
                    scene.clip(Some([541.0, 630.0, 297.0, 40.0]));
                    scene.text(name, 541.0, 635.0, 24.0, 1.0, false);
                    scene.clip(None);
                }
            }
            _ => {}
        }
    }
    fn map(&mut self, scene: &mut Scene, state: &Value) {
        let local = self.category == 1;
        let map = &state["data"]["Map"];
        let data = &map[if local { "Local" } else { "World" }];
        let identity = format!(
            "{}:{}",
            self.category,
            txt(&map[if local { "CurrCell" } else { "CurrWorldspace" }])
        );
        let reset = identity != self.map_identity;
        if reset {
            self.map_identity = identity;
            self.map_pan = [0.0; 2];
            // WorldMapHolder uses .75 + .117647 * (5-.75) = 1.25
            // times the loaded map texture, not a fit-to-window thumbnail.
            self.map_zoom = if local { 1.0 } else { 2048.0 * 1.25 / MAP[3] };
            self.map_selection = None;
        }
        let raw = if local && !state["localMap"]["extents"].is_null() {
            &state["localMap"]["extents"]
        } else {
            &data["Extents"]
        };
        self.map_extents = extents(raw);
        self.map_player = world_to_uv(
            self.map_extents,
            n(&data["Player"]["X"]),
            n(&data["Player"]["Y"]),
        );
        let size = MAP[2].min(MAP[3]) * self.map_zoom;
        if reset {
            if let Some([u, v]) = self.map_player {
                self.map_pan = [(0.5 - u) * size, (0.5 - v) * size];
            }
        }
        self.map_geometry = [
            MAP[0] + (MAP[2] - size) / 2.0 + self.map_pan[0],
            MAP[1] + (MAP[3] - size) / 2.0 + self.map_pan[1],
            size,
            size,
        ];
        let maps = &state["assets"]["maps"];
        let world = txt(&map["CurrWorldspace"]).to_lowercase();
        let image = if local {
            path(&state["localMap"]["url"]).or_else(|| path(&state["localMap"]["path"]))
        } else if world.contains("far harbor")
            || world.contains("farharbor")
            || world.contains("dlc03")
        {
            path(&maps["farHarbor"]).or_else(|| path(&maps["far-harbor"]))
        } else if world.contains("nuka") || world.contains("dlc04") {
            path(&maps["nukaWorld"]).or_else(|| path(&maps["nuka-world"]))
        } else if world.contains("commonwealth") {
            path(&maps["commonwealth"])
        } else {
            None
        };
        scene.clip(Some(MAP));
        scene.rect(self.map_geometry, 0.025);
        if let Some(p) = image {
            scene.image(p, self.map_geometry, 1.8);
        } else {
            let [x, y, w, h] = self.map_geometry;
            for i in 0..=10 {
                let t = i as f32 / 10.0;
                scene.rect([x + w * t, y, 1.0, h], 0.12);
                scene.rect([x, y + h * t, w, 1.0], 0.12);
            }
        }
        let mut markers: Vec<(&str, &Value, String)> = Vec::new();
        for loc in arr(&data[if local { "Doors" } else { "Locations" }]) {
            if yes(&loc["Visible"]) {
                markers.push(("location", loc, label(loc)));
            }
        }
        for q in arr(&data["Quests"]) {
            if q["Visible"] != false {
                markers.push(("quest", q, label(q)));
            }
        }
        for (field, kind, name) in [
            ("Custom", "custom", "Custom marker"),
            ("PowerArmor", "armor", "Power armor"),
        ] {
            if yes(&data[field]["Visible"]) {
                markers.push((kind, &data[field], name.into()));
            }
        }
        if data["Player"].is_object() {
            markers.push(("player", &data["Player"], "You".into()));
        }
        let names: Vec<_> = MARKERS.split_whitespace().collect();
        let mut selected_exists = self
            .map_selection
            .as_ref()
            .is_some_and(|m| m.kind == "point");
        for (index, (kind, obj, name)) in markers.iter().enumerate() {
            let Some([u, v]) = world_to_uv(self.map_extents, n(&obj["X"]), n(&obj["Y"])) else {
                continue;
            };
            let x = self.map_geometry[0] + u * size;
            let y = self.map_geometry[1] + v * size;
            let key = id(obj, index);
            let command = if *kind == "custom" {
                Some(json!({"action":"clear-marker"}))
            } else if *kind == "location"
                && !local
                && yes(&obj["Discovered"])
                && (obj["_id"].is_i64() || obj["_id"].is_u64())
            {
                Some(json!({"action":"travel","id":obj["_id"]}))
            } else {
                None
            };
            let selected = MapSelection {
                kind: (*kind).into(),
                id: key.clone(),
                label: if name.is_empty() {
                    "Location".into()
                } else {
                    name.clone()
                },
                command,
            };
            let chosen = self
                .map_selection
                .as_ref()
                .is_some_and(|m| m.kind == *kind && m.id == key);
            if chosen {
                self.map_selection = Some(selected.clone());
                selected_exists = true;
            }
            if !contains(
                [MAP[0] - 18.0, MAP[1] - 18.0, MAP[2] + 36.0, MAP[3] + 36.0],
                x,
                y,
            ) {
                continue;
            }
            let marker = match *kind {
                "location" if local => "DoorMarker".into(),
                "location" => names
                    .get(n(&obj["type"]) as usize)
                    .map(|s| {
                        if s.ends_with("MarkerDoor") {
                            (*s).to_owned()
                        } else {
                            format!("{s}Marker")
                        }
                    })
                    .unwrap_or_else(|| "TownMarker".into()),
                "quest" => "QuestMarker".into(),
                "custom" => "PlayerSetMarker".into(),
                "player" => "PlayerLocMarker".into(),
                _ => "PowerArmorLocMarker".into(),
            };
            let shade = if obj["Discovered"] == false { 0.5 } else { 1.0 };
            if chosen {
                scene.outline([x - 19.0, y - 19.0, 38.0, 38.0], 1.5, 1.0);
            }
            if let Some(p) = path(&state["assets"]["markers"][&marker]) {
                if *kind == "player" {
                    let a = n(&obj["Rotation"]).to_radians();
                    let (sin, cos) = a.sin_cos();
                    let corners = [[-12.0, -12.0], [12.0, -12.0], [12.0, 12.0], [-12.0, 12.0]]
                        .map(|[px, py]| [x + px * cos - py * sin, y + px * sin + py * cos]);
                    scene.image_quad(p, corners, shade, None);
                } else {
                    scene.image(p, [x - 12.0, y - 12.0, 24.0, 24.0], shade);
                }
            } else {
                scene.outline([x - 7.0, y - 7.0, 14.0, 14.0], 2.0, shade);
            }
            if contains(MAP, x, y) {
                self.hit(
                    [x - 19.0, y - 19.0, 38.0, 38.0],
                    Action::MapSelect(selected),
                    true,
                );
            }
        }
        if !selected_exists {
            self.map_selection = None;
        }
        scene.clip(None);
        let caption = if image.is_none() {
            if local {
                "Request a local map snapshot".to_owned()
            } else {
                "Map image unavailable · Live markers".to_owned()
            }
        } else if local {
            "LOCAL MAP".to_owned()
        } else {
            txt(&map["CurrWorldspace"])
        };
        scene.rect([49.0, 119.0, 465.0, 31.0], 0.0);
        scene.text(caption, 56.0, 124.0, 20.0, 0.8, false);
        for (i, (text, action)) in [
            ("+", Action::Zoom(1.5)),
            ("−", Action::Zoom(1.0 / 1.5)),
            ("◎", Action::Center),
            ("↺", Action::Reset),
        ]
        .into_iter()
        .enumerate()
        {
            let r = [780.0, 124.0 + i as f32 * 48.0, 46.0, 43.0];
            scene.rect(r, 0.0);
            self.button(scene, r, text, action, true);
        }
        if local {
            self.command(
                scene,
                [700.0, 324.0, 126.0, 42.0],
                "REFRESH",
                json!({"action":"localmap"}),
                true,
            );
        }
        if let Some(selected) = self.map_selection.clone() {
            scene.rect([46.0, 549.0, 783.0, 50.0], 0.0);
            scene.clip(Some([54.0, 550.0, 594.0, 43.0]));
            scene.text(&selected.label, 54.0, 560.0, 25.0, 1.0, false);
            scene.clip(None);
            if let Some(command) = selected.command {
                let text = match command["action"].as_str() {
                    Some("travel") => "TRAVEL",
                    Some("marker") => "PLACE",
                    _ => "REMOVE",
                };
                self.command(scene, [590.0, 690.0, 165.0, 42.0], text, command, true);
            }
            self.button(
                scene,
                [784.0, 552.0, 40.0, 42.0],
                "×",
                Action::ClearMap,
                true,
            );
        } else {
            scene.text(
                "Drag to pan · + / − to zoom · Tap to place a marker",
                49.0,
                581.0,
                19.0,
                0.65,
                false,
            );
        }
    }
    fn confirmation(&mut self, scene: &mut Scene, state: &Value, elapsed: f64) {
        let raw = &state["confirm"];
        if self.locked || raw.is_null() {
            if let Some(c) = self.challenge.take() {
                self.dismissed_token = Some(c.token);
            }
            return;
        }
        let Some(token) = raw["token"].as_str() else {
            return;
        };
        if self.dismissed_token.as_deref() == Some(token) {
            return;
        }
        if self.challenge.as_ref().is_none_or(|c| c.token != token) {
            let epoch = SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap_or_default()
                .as_secs_f64();
            let duration = (raw["expires"].as_f64().unwrap_or(epoch) - epoch).clamp(0.0, 5.0);
            if duration <= 0.0 {
                self.dismissed_token = Some(token.into());
                return;
            }
            self.challenge = Some(Challenge {
                token: token.into(),
                label: raw["label"].as_str().unwrap_or("Confirm action").into(),
                seen: elapsed,
                until: elapsed + duration,
            });
        }
        let Some(c) = self.challenge.clone() else {
            return;
        };
        if elapsed >= c.until {
            self.dismissed_token = Some(c.token);
            self.challenge = None;
            return;
        }
        // Modal hits replace the underlying page's hit map, preventing a tap
        // from confirming and also activating a game action underneath it.
        self.hits.clear();
        scene.rect([133.0, 230.0, 610.0, 268.0], 0.0);
        scene.outline([133.0, 230.0, 610.0, 268.0], 2.0, 1.0);
        wrapped(
            self.font.as_deref(),
            scene,
            &c.label,
            162.0,
            259.0,
            548.0,
            30.0,
            1.0,
        );
        wrapped(
            self.font.as_deref(),
            scene,
            "This changes the game. Tap Confirm to continue.",
            162.0,
            328.0,
            548.0,
            23.0,
            0.7,
        );
        self.button(
            scene,
            [189.0, 400.0, 215.0, 52.0],
            "CANCEL",
            Action::Cancel,
            true,
        );
        self.button(
            scene,
            [472.0, 400.0, 215.0, 52.0],
            "CONFIRM",
            Action::Confirm(c.token),
            elapsed >= c.seen + 0.35,
        );
        meter(
            scene,
            [161.0, 475.0, 554.0, 5.0],
            ((c.until - elapsed) / (c.until - c.seen)) as f32,
            1.0,
        );
    }
    fn emit(&mut self, command: Value, elapsed: f64) -> Vec<Value> {
        if self.locked || elapsed < self.pending_until {
            return Vec::new();
        }
        self.pending_until = elapsed + 0.45;
        vec![command]
    }
    fn reset_list(&mut self) {
        self.selection = None;
        self.quest_summary = false;
        self.quest_started = None;
        self.list_scroll = 0.0;
        self.detail_scroll = 0.0;
        self.list_max = 0.0;
        self.detail_max = 0.0;
    }
    pub fn click(&mut self, x: f32, y: f32, elapsed: f64) -> Vec<Value> {
        self.pointer = [x, y];
        let hit = self
            .hits
            .iter()
            .rev()
            .find(|h| contains(h.rect, x, y))
            .cloned();
        if let Some(hit) = hit {
            if !hit.enabled {
                return Vec::new();
            }
            match hit.action {
                Action::Page(page) => {
                    self.page = page;
                    self.category = 0;
                    self.reset_list();
                    self.map_selection = None;
                }
                Action::Category(category) => {
                    self.category = category;
                    self.reset_list();
                    if self.page == 3 && category == 1 {
                        return self.emit(json!({"action":"localmap"}), elapsed);
                    }
                }
                Action::Summary => {
                    self.quest_summary = !self.quest_summary;
                    self.quest_started = Some(elapsed);
                }
                Action::Select(id) => {
                    self.quest_summary = false;
                    self.quest_started = Some(elapsed);
                    self.selection = Some(id);
                    self.detail_scroll = 0.0;
                }
                Action::Command(command) => return self.emit(command, elapsed),
                Action::Confirm(token) => {
                    let valid = self.challenge.as_ref().is_some_and(|c| {
                        c.token == token && elapsed >= c.seen + 0.35 && elapsed < c.until
                    });
                    if valid && !self.locked {
                        self.challenge = None;
                        self.dismissed_token = Some(token.clone());
                        self.pending_until = elapsed + 0.45;
                        return vec![json!({"action":"confirm","token":token})];
                    }
                }
                Action::Cancel => {
                    if let Some(c) = self.challenge.take() {
                        self.dismissed_token = Some(c.token);
                        return vec![json!({"action":"cancel"})];
                    }
                }
                Action::Scroll(dy, detail) => {
                    if detail {
                        self.detail_scroll = (self.detail_scroll + dy).clamp(0.0, self.detail_max);
                    } else {
                        self.list_scroll = (self.list_scroll + dy).clamp(0.0, self.list_max);
                    }
                }
                Action::Zoom(factor) => {
                    self.pinch(factor, MAP[0] + MAP[2] / 2.0, MAP[1] + MAP[3] / 2.0)
                }
                Action::Center => {
                    if let Some([u, v]) = self.map_player {
                        let size = MAP[2].min(MAP[3]) * self.map_zoom;
                        self.map_pan = [(0.5 - u) * size, (0.5 - v) * size];
                    }
                }
                Action::Reset => {
                    self.map_zoom = 1.0;
                    self.map_pan = [0.0; 2];
                }
                Action::MapSelect(selected) => self.map_selection = Some(selected),
                Action::ClearMap => self.map_selection = None,
            }
            return Vec::new();
        }
        if self.challenge.is_some() {
            return Vec::new();
        }
        if self.page == 3 && contains(MAP, x, y) {
            if let Some([wx, wy]) = screen_to_world(self.map_extents, self.map_geometry, x, y) {
                self.map_selection = Some(MapSelection {
                    kind: "point".into(),
                    id: String::new(),
                    label: "Place custom marker here?".into(),
                    command: Some(
                        json!({"action":"marker","x":wx,"y":wy,"local":self.category==1}),
                    ),
                });
            }
        }
        Vec::new()
    }
    pub fn scroll(&mut self, dy: f32) {
        if self.challenge.is_some() {
            return;
        }
        if self.page == 3 {
            self.pinch(
                if dy < 0.0 { 1.15 } else { 1.0 / 1.15 },
                self.pointer[0].clamp(MAP[0], MAP[0] + MAP[2]),
                self.pointer[1].clamp(MAP[1], MAP[1] + MAP[3]),
            );
        } else if self.pointer[0] >= self.list_rect()[0] + self.list_rect()[2] {
            self.detail_scroll = (self.detail_scroll + dy).clamp(0.0, self.detail_max);
        } else {
            self.list_scroll = (self.list_scroll + dy).clamp(0.0, self.list_max);
        }
    }
    pub fn pointer_down(&mut self, x: f32, y: f32) {
        self.pointer = [x, y];
        if self.challenge.is_some() {
            return;
        }
        self.drag = Some(Drag {
            start: [x, y],
            last: [x, y],
            moved: false,
            map: self.page == 3 && contains(MAP, x, y),
            detail: x >= self.list_rect()[0] + self.list_rect()[2],
        });
    }
    pub fn pointer_move(&mut self, x: f32, y: f32) {
        self.pointer = [x, y];
        let Some(mut drag) = self.drag else { return };
        if (x - drag.start[0]).hypot(y - drag.start[1]) > 7.0 {
            drag.moved = true;
        }
        if drag.moved {
            let dx = x - drag.last[0];
            let dy = y - drag.last[1];
            if drag.map {
                self.map_pan[0] += dx;
                self.map_pan[1] += dy;
            } else if contains(CONTENT, drag.start[0], drag.start[1]) {
                if drag.detail {
                    self.detail_scroll = (self.detail_scroll - dy).clamp(0.0, self.detail_max);
                } else {
                    self.list_scroll = (self.list_scroll - dy).clamp(0.0, self.list_max);
                }
            }
        }
        drag.last = [x, y];
        self.drag = Some(drag);
    }
    pub fn pointer_up(&mut self, x: f32, y: f32, elapsed: f64) -> Vec<Value> {
        let moved = self.drag.take().is_some_and(|d| d.moved);
        if moved {
            Vec::new()
        } else {
            self.click(x, y, elapsed)
        }
    }
    pub fn pinch(&mut self, factor: f32, cx: f32, cy: f32) {
        if self.page != 3 || self.challenge.is_some() || !factor.is_finite() || factor <= 0.0 {
            return;
        }
        let next = (self.map_zoom * factor).clamp(1.0, 12.0);
        let ratio = next / self.map_zoom;
        let center = [MAP[0] + MAP[2] / 2.0, MAP[1] + MAP[3] / 2.0];
        self.map_pan[0] = (self.map_pan[0] + center[0] - cx) * ratio + cx - center[0];
        self.map_pan[1] = (self.map_pan[1] + center[1] - cy) * ratio + cy - center[1];
        self.map_zoom = next;
    }
}
fn extents(raw: &Value) -> Option<[f32; 6]> {
    let values = if let Some(a) = raw.as_array() {
        if a.len() < 6 {
            return None;
        }
        [&a[0], &a[1], &a[2], &a[3], &a[4], &a[5]]
    } else {
        [
            &raw["NWX"],
            &raw["NWY"],
            &raw["NEX"],
            &raw["NEY"],
            &raw["SWX"],
            &raw["SWY"],
        ]
    };
    if values
        .iter()
        .any(|v| !v.as_f64().is_some_and(f64::is_finite))
    {
        return None;
    }
    Some(values.map(n))
}
fn world_to_uv(e: Option<[f32; 6]>, x: f32, y: f32) -> Option<[f32; 2]> {
    let [nx, ny, ex, ey, sx, sy] = e?;
    let ax = ex - nx;
    let ay = ey - ny;
    let bx = sx - nx;
    let by = sy - ny;
    let det = ax * by - ay * bx;
    if det.abs() < 0.001 || !det.is_finite() {
        return None;
    }
    Some([
        ((x - nx) * by - (y - ny) * bx) / det,
        (ax * (y - ny) - ay * (x - nx)) / det,
    ])
}
fn screen_to_world(e: Option<[f32; 6]>, g: Rect, x: f32, y: f32) -> Option<[f32; 2]> {
    let e = e?;
    let u = (x - g[0]) / g[2];
    let v = (y - g[1]) / g[3];
    if !(0.0..=1.0).contains(&u) || !(0.0..=1.0).contains(&v) {
        return None;
    }
    Some([
        e[0] + u * (e[2] - e[0]) + v * (e[4] - e[0]),
        e[1] + u * (e[3] - e[1]) + v * (e[5] - e[1]),
    ])
}

#[cfg(test)]
mod tests {
    use super::*;
    fn state() -> Value {
        json!({"connected":true,"data":{"PlayerInfo":{"PlayerName":"Native test","CurrHP":60,"MaxHP":100},"Status":{},"Stats":{"StimpakCount":2,"RadawayCount":1},"Inventory":{"Version":4,"43":[{"_id":90,"text":"Test rifle","filterFlag":2,"count":1},{"_id":91,"text":"Test aid","filterFlag":8,"count":3}]},"Radio":[{"_id":10,"text":"Test station","inRange":false}]}})
    }
    #[test]
    fn waiting_states_hide_chrome_preserve_aspect_and_clear_pending_input() {
        let mut view = View::default();
        let mut s = state();
        s["assets"] = json!({"animations":{"waiting":{"viewBox":[12,20,200,400],"fps":30,"frames":["assets/wait/0.svg","assets/wait/1.svg","assets/wait/2.svg"]}}});
        for state_kind in 0..5 {
            let mut waiting = s.clone();
            match state_kind {
                0 => waiting["connected"] = false.into(),
                1 => waiting["data"]["PlayerInfo"] = json!({}),
                2 => waiting["data"]["Status"]["IsLoading"] = true.into(),
                3 => waiting["data"]["Status"]["IsDataUnavailable"] = true.into(),
                _ => waiting["data"]["PlayerInfo"]["MaxHP"] = 0.into(),
            }
            view.frame(&s, 0.0);
            let scene = view.frame(&waiting, 1.0);
            assert!(view.hits.is_empty());
            assert_eq!(scene.draws.len(), 1);
            match &scene.draws[0].kind {
                crate::scene::Kind::Image { rect, .. } => {
                    assert!((rect[2] / rect[3] - 0.5).abs() < 0.001);
                    assert!((rect[0] + rect[2] / 2. - 438.).abs() < 0.001);
                }
                _ => panic!("Waiting scene must contain only game artwork"),
            }
            assert!(view.click(400., 712., 2.).is_empty());
            let restored = view.frame(&s, 3.0);
            assert!(restored.draws.len() > 1);
            assert!(!view.hits.is_empty());
        }
    }
    #[test]
    fn equip_uses_protocol_id_and_inventory_version() {
        let mut view = View::default();
        let s = state();
        view.page = 1;
        view.frame(&s, 0.0);
        assert_eq!(
            view.click(400.0, 712.0, 1.0),
            vec![json!({"action":"use","id":90,"version":4})]
        );
        assert!(view.click(400.0, 712.0, 1.1).is_empty());
    }
    #[test]
    fn action_gates_follow_live_state_and_radio_range() {
        for field in [
            "IsDataUnavailable",
            "IsLoading",
            "IsPlayerDead",
            "IsPipboyNotEquipped",
            "IsPlayerInDialogue",
            "IsInVats",
            "IsInVatsPlayback",
            "IsPlayerPipboyLocked",
            "IsPlayerMovementLocked",
            "IsInAnimation",
        ] {
            let mut view = View::default();
            let mut s = state();
            s["data"]["Status"][field] = true.into();
            view.page = 1;
            view.frame(&s, 0.0);
            assert!(view.click(400.0, 712.0, 1.0).is_empty(), "{field}");
        }
        let mut view = View::default();
        view.page = 4;
        view.frame(&state(), 0.0);
        assert!(view.click(400.0, 712.0, 1.0).is_empty());
    }
    #[test]
    fn confirmation_blocks_double_tap_and_dismisses_token() {
        let mut view = View::default();
        let mut s = state();
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        s["confirm"] = json!({"token":"challenge","label":"Use Test aid?","expires":epoch+5.0});
        view.frame(&s, 0.0);
        assert!(view.click(540.0, 423.0, 0.1).is_empty());
        view.frame(&s, 0.4);
        assert_eq!(
            view.click(540.0, 423.0, 0.4),
            vec![json!({"action":"confirm","token":"challenge"})]
        );
        view.frame(&s, 0.5);
        assert!(view.challenge.is_none());
    }
    #[test]
    fn confirmation_expiry_and_cancel_never_activate_underlying_action() {
        let mut view = View::default();
        let mut s = state();
        let epoch = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs_f64();
        s["confirm"] = json!({"token":"one","expires":epoch+5.0});
        view.frame(&s, 0.0);
        assert_eq!(
            view.click(230.0, 423.0, 0.2),
            vec![json!({"action":"cancel"})]
        );
        s["confirm"] = json!({"token":"two","expires":epoch+1.0});
        view.frame(&s, 1.0);
        view.frame(&s, 3.0);
        assert!(view.challenge.is_none());
    }
    #[test]
    fn affine_map_coordinates_round_trip_and_reject_degenerate_extents() {
        let e = Some([10.0, 100.0, 110.0, 120.0, 30.0, 0.0]);
        let uv = world_to_uv(e, 70.0, 60.0).unwrap();
        assert!((uv[0] - 0.5).abs() < 1e-5 && (uv[1] - 0.5).abs() < 1e-5);
        assert_eq!(
            screen_to_world(e, [0.0, 0.0, 500.0, 500.0], 250.0, 250.0),
            Some([70.0, 60.0])
        );
        assert!(world_to_uv(Some([0.0; 6]), 1.0, 1.0).is_none());
    }
    #[test]
    fn map_drag_never_places_marker_and_local_tab_requests_snapshot() {
        let mut view = View::default();
        let mut s = state();
        view.page = 3;
        s["data"]["Map"] = json!({"CurrWorldspace":"Commonwealth","World":{"Extents":{"NWX":0,"NWY":100,"NEX":100,"NEY":100,"SWX":0,"SWY":0}}});
        view.frame(&s, 0.0);
        view.pointer_down(350.0, 300.0);
        view.pointer_move(400.0, 340.0);
        assert!(view.pointer_up(400.0, 340.0, 1.0).is_empty());
        assert!(view.map_selection.is_none());
        assert_eq!(
            {
                let hit = view
                    .hits
                    .iter()
                    .find(|h| matches!(h.action, Action::Category(1)))
                    .unwrap()
                    .rect;
                view.click(hit[0] + hit[2] / 2.0, hit[1] + hit[3] / 2.0, 2.0)
            },
            vec![json!({"action":"localmap"})]
        );
    }
    #[test]
    fn radio_wave_preserves_native_timer_and_continuity() {
        let mut wave = RadioWave::default();
        let item = json!({"_id":1,"active":true,"frequency":110});
        wave.update(&item, 0.0);
        assert_eq!(wave.freq, 10.0);
        assert_eq!(wave.points.len(), 226);
        let first = wave.points.clone();
        wave.update(&item, 0.02);
        assert_eq!(wave.points, first);
        wave.update(&item, 0.041);
        assert_eq!(&wave.points[..216], &first[10..]);
        assert!(wave.points.iter().all(|v| (0.0..=200.0).contains(v)));
    }
    #[test]
    fn world_map_opens_at_native_scale_centered_on_player() {
        let mut view = View::default();
        let mut s = state();
        view.page = 3;
        s["data"]["Map"] = json!({"CurrWorldspace":"Commonwealth","World":{"Player":{"X":20,"Y":70},"Extents":[0,100,100,100,0,0]}});
        view.frame(&s, 0.0);
        assert!((view.map_geometry[2] - 2560.0).abs() < 0.01);
        assert!(
            (view.map_geometry[0] + view.map_geometry[2] * 0.2 - (MAP[0] + MAP[2] / 2.0)).abs()
                < 0.01
        );
        assert!(
            (view.map_geometry[1] + view.map_geometry[3] * 0.3 - (MAP[1] + MAP[3] / 2.0)).abs()
                < 0.01
        );
    }
    #[test]
    fn quest_animation_uses_normalized_game_path_then_native_summary() {
        let mut view = View::default();
        let mut s = state();
        view.page = 2;
        s["data"]["Quests"] = json!([{"_id":13,"text":"A quest","description":"Quest summary","SWFFile":"Components\\Quest.swf","objectives":[]}]);
        s["assets"] = json!({"animations":{"quests":{"byPath":{"components/quest.swf":{"viewBox":[100,200,300,400],"frames":["assets/quest.svg"],"fps":30,"playOnce":true}}}}});
        let scene = view.frame(&s, 0.0);
        assert!(scene.draws.iter().any(|d| matches!(&d.kind,crate::scene::Kind::Image{path,rect,..} if path=="assets/quest.svg" && (rect[0]-478.5).abs()<0.01)));
        view.frame(&s, 0.1);
        assert!(view.quest_summary);
        assert_eq!(
            view.click(400.0, 711.0, 0.2),
            vec![json!({"action":"quest","id":13})]
        );
    }
}
