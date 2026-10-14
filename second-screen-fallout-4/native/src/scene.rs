pub const WIDTH: f32 = 876.0;
pub const HEIGHT: f32 = 740.0;
pub type Rect = [f32; 4];
#[derive(Clone, Debug)]
pub enum Kind {
    SolidQuad {
        corners: [[f32; 2]; 4],
        shade: f32,
    },
    Model {
        form_id: u32,
        path: Option<String>,
        rect: Rect,
    },
    Rect {
        rect: Rect,
        shade: f32,
    },
    Image {
        path: String,
        rect: Rect,
        shade: f32,
        uv: Option<Rect>,
    },
    ImageQuad {
        path: String,
        corners: [[f32; 2]; 4],
        shade: f32,
        uv: Option<Rect>,
    },
    Text {
        text: String,
        x: f32,
        y: f32,
        size: f32,
        shade: f32,
        bold: bool,
        align: f32,
    },
}
#[derive(Clone, Debug)]
pub struct Draw {
    pub kind: Kind,
    pub clip: Option<Rect>,
}
#[derive(Default)]
pub struct Scene {
    pub draws: Vec<Draw>,
    clip: Option<Rect>,
}
impl Scene {
    pub fn model(&mut self, form_id: u32, path: Option<&str>, rect: Rect) {
        self.draws.push(Draw {
            kind: Kind::Model {
                form_id,
                path: path.map(str::to_owned),
                rect,
            },
            clip: self.clip,
        });
    }
    pub fn line(&mut self, from: [f32; 2], to: [f32; 2], width: f32, shade: f32) {
        let dx = to[0] - from[0];
        let dy = to[1] - from[1];
        let length = dx.hypot(dy);
        if length <= 0.0 {
            return;
        }
        let x = -dy / length * width * 0.5;
        let y = dx / length * width * 0.5;
        let corners = [
            [from[0] + x, from[1] + y],
            [to[0] + x, to[1] + y],
            [to[0] - x, to[1] - y],
            [from[0] - x, from[1] - y],
        ];
        self.draws.push(Draw {
            kind: Kind::SolidQuad { corners, shade },
            clip: self.clip,
        });
    }

    pub fn rect(&mut self, rect: Rect, shade: f32) {
        self.draws.push(Draw {
            kind: Kind::Rect { rect, shade },
            clip: self.clip,
        });
    }
    pub fn image(&mut self, path: impl Into<String>, rect: Rect, shade: f32) {
        self.image_uv(path, rect, shade, None);
    }
    pub fn image_uv(&mut self, path: impl Into<String>, rect: Rect, shade: f32, uv: Option<Rect>) {
        self.draws.push(Draw {
            kind: Kind::Image {
                path: path.into(),
                rect,
                shade,
                uv,
            },
            clip: self.clip,
        });
    }
    pub fn image_quad(
        &mut self,
        path: impl Into<String>,
        corners: [[f32; 2]; 4],
        shade: f32,
        uv: Option<Rect>,
    ) {
        self.draws.push(Draw {
            kind: Kind::ImageQuad {
                path: path.into(),
                corners,
                shade,
                uv,
            },
            clip: self.clip,
        });
    }
    pub fn text(
        &mut self,
        text: impl Into<String>,
        x: f32,
        y: f32,
        size: f32,
        shade: f32,
        bold: bool,
    ) {
        self.draws.push(Draw {
            kind: Kind::Text {
                text: text.into(),
                x,
                y,
                size,
                shade,
                bold,
                align: 0.,
            },
            clip: self.clip,
        });
    }
    pub fn text_center(
        &mut self,
        text: impl Into<String>,
        x: f32,
        y: f32,
        size: f32,
        shade: f32,
        bold: bool,
    ) {
        self.draws.push(Draw {
            kind: Kind::Text {
                text: text.into(),
                x,
                y,
                size,
                shade,
                bold,
                align: 0.5,
            },
            clip: self.clip,
        });
    }
    pub fn clip(&mut self, clip: Option<Rect>) {
        self.clip = clip;
    }
    pub fn outline(&mut self, r: Rect, thickness: f32, shade: f32) {
        let [x, y, w, h] = r;
        for q in [
            [x, y, w, thickness],
            [x, y + h - thickness, w, thickness],
            [x, y, thickness, h],
            [x + w - thickness, y, thickness, h],
        ] {
            self.rect(q, shade);
        }
    }
}
