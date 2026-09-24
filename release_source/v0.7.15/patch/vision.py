"""Pure image recognition. No desktop access or input events in this module."""
from dataclasses import dataclass, field
from pathlib import Path
import json
import cv2
import numpy as np
from photometric import ButtonProfiles

ROOMS = ("farm", "wood", "mine")
LABELS = {"farm": "농장", "wood": "목공소", "mine": "광산"}
MAIN_MARKERS = ("main_menu", "main_character", "main_pet")


def state_label(state):
    labels = {"exit_dialog": "게임 종료 확인창", "sleep": "절전 화면", "main": "게임 화면", "menu": "오른쪽 메뉴",
              "equipment": "장비 비교창", "reward": "보상 표시", "offline_reward": "오프라인 보상", "unknown": "미인식",
              "ranking":"랭킹", "boss_select":"월드보스 선택", "boss":"월드보스",
              "boss_rank":"월드보스 랭킹", "relic":"유물", "excavation":"유물 발굴", "training":"수련"}
    for key, value in LABELS.items():
        labels.update({key+"_ready": value+" / 수령 가능", key+"_empty": value+" / 수령 불가",
                       key+"_wait": value+" / 버튼 대기"})
    return labels.get(state, state)


@dataclass(frozen=True)
class Match:
    name: str
    score: float
    mae: float
    center: tuple


@dataclass
class Screen:
    state: str
    matches: dict
    diagnostics: dict = field(default_factory=dict)


def relative_color_check(patch, color, gray_patch, gray_template):
    """Compare local color/contrast structure without a constant color cast.

    Desktop recordings and MuMu's direct ADB PNG can have different channel
    means. Keep the glyph/edge pattern and contrast checks: an inactive button
    must not pass just because its fill color can be shifted to match.
    """
    delta = patch.astype(np.float32) - color.astype(np.float32)
    centered_mae = float(np.abs(delta-delta.mean(axis=(0, 1), keepdims=True)).mean())
    blurred_patch = cv2.GaussianBlur(patch, (3, 3), .7)
    blurred_color = cv2.GaussianBlur(color, (3, 3), .7)
    correlation = float(cv2.matchTemplate(blurred_patch, blurred_color, cv2.TM_CCOEFF_NORMED)[0, 0])
    contrast = float(gray_patch.std() / max(float(gray_template.std()), 1.0))
    light = float(gray_patch.mean() / max(float(gray_template.mean()), 1.0))
    passed = centered_mae <= 12 and correlation >= .90 and .75 <= contrast <= 1.60 and .80 <= light <= 1.45
    return passed, {"centered_mae": centered_mae, "color_correlation": correlation,
                    "contrast_ratio": contrast, "light_ratio": light}


def foreground_luma_check(patch, template, mask):
    """Recognize fixed boss glyphs across gold video / white ADB captures.

    Compare only stable foreground pixels. Full-icon shape must already pass;
    local contrast and brightness still reject dim overlays and missing glyphs.
    Never use this fallback to decide whether a reward button is active.
    """
    if int(mask.sum()) < 25:
        return False, {"foreground_pixels": int(mask.sum())}
    def values(im):
        gray = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (3, 3), .7)
        return gray[mask].astype(np.float32)
    a, b = values(patch), values(template)
    delta = a-b
    mae = float(np.abs(delta-delta.mean()).mean())
    light = float(a.mean()/max(float(b.mean()), 1.0))
    contrast = float(a.std()/max(float(b.std()), 1.0))
    a, b = a-a.mean(), b-b.mean()
    denominator = float(np.linalg.norm(a)*np.linalg.norm(b))
    correlation = float(np.dot(a,b)/denominator) if denominator > 1 else 0.0
    passed = mae <= 8 and correlation >= .95 and .75 <= contrast <= 1.45 and .90 <= light <= 1.40
    return passed, {"foreground_luma_mae": mae, "foreground_luma_correlation": correlation,
                    "foreground_luma_contrast": contrast, "foreground_luma_light": light}


class Vision:
    def __init__(self, assets=None):
        assets = Path(assets or Path(__file__).parent / "assets")
        self.specs = json.loads((assets / "templates.json").read_text(encoding="utf-8"))
        from daily_vision import DailyVision
        self.daily = DailyVision(assets)
        self.templates = {}
        self.foreground_masks = {}
        self.button_profiles = ButtonProfiles(assets)
        for name in self.specs:
            im = cv2.imdecode(np.fromfile(assets / (name + ".png"), np.uint8), cv2.IMREAD_COLOR)
            if im is None:
                raise ValueError("인식 이미지가 없습니다: " + name)
            gray = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (3, 3), .7)
            self.templates[name] = (im, gray)
            if self.specs[name].get("foreground_color", False):
                hsv = cv2.cvtColor(im, cv2.COLOR_BGR2HSV)
                self.foreground_masks[name] = ((hsv[:,:,2] >= 160) & (hsv[:,:,0] >= 10)
                    & (hsv[:,:,0] <= 40) & (hsv[:,:,1] >= 15) & (hsv[:,:,1] <= 180))

    def recognize(self, bgr):
        if bgr is None or bgr.ndim != 3 or min(bgr.shape[:2]) < 200:
            return Screen("unknown", {})
        h, w = bgr.shape[:2]
        if abs(w / h - 16 / 9) > .055:
            return Screen("unknown", {})
        im = cv2.resize(bgr[:, :, :3], (960, 540), interpolation=cv2.INTER_AREA)
        gray = cv2.GaussianBlur(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY), (3, 3), .7)
        matches, diagnostics = {}, {}
        for name, spec in self.specs.items():
            target = spec.get("alias", name)
            x1, y1, x2, y2 = spec["box"]
            pad = 7
            x0, y0 = max(0, x1-pad), max(0, y1-pad)
            roi = gray[y0:min(540, y2+pad), x0:min(960, x2+pad)]
            color, template = self.templates[name]
            scores = cv2.matchTemplate(roi, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, loc = cv2.minMaxLoc(scores)
            xx, yy = x0+loc[0], y0+loc[1]
            th, tw = template.shape
            patch = im[yy:yy+th, xx:xx+tw]
            mae = float(np.abs(patch.astype(np.float32)-color.astype(np.float32)).mean())
            shape_ok = score >= spec["threshold"]
            is_claim = target.startswith(('ready_', 'empty_')) or target.endswith(('_active', '_empty'))
            color_ok = mae <= spec["max_mae"]
            details = {"score": float(score), "required_score": spec["threshold"],
                       "canonical_name": target,
                       "color_mae": mae, "max_color_mae": spec["max_mae"],
                       "position": [xx, yy], "color_method": "absolute"}
            if not is_claim:
                # Static labels and icons are identities, not color swatches.
                # Match their grayscale shape and visible contrast; RGB means
                # vary between recordings, ADB captures and render settings.
                gp=gray[yy:yy+th,xx:xx+tw]
                contrast=float(gp.std()/max(float(template.std()),1.0))
                light=float(gp.mean()/max(float(template.mean()),1.0))
                color_ok=.60<=contrast<=1.80 and light>=.65 and float(gp.std())>=3
                details.update(structure_contrast=contrast,structure_light=light)
                details['color_method']='structure'
            # Legacy button references stay conservative if their independent
            # page context cannot be calibrated below.
            if is_claim and shape_ok and not color_ok and (name.startswith(("ready_", "empty_")) or spec.get("relative_color", False)):
                color_ok, relative = relative_color_check(patch, color, gray[yy:yy+th, xx:xx+tw], template)
                details.update(relative)
                details["color_method"] = "relative"
            if not color_ok and score >= max(spec["threshold"], .90) and name in self.foreground_masks:
                if not is_claim:
                    color_ok, luminance = foreground_luma_check(patch, color, self.foreground_masks[name])
                    details.update(luminance)
                    details["color_method"] = "foreground_luma"
            details["accepted"] = bool(shape_ok and color_ok)
            details["rejection"] = "" if details["accepted"] else ("shape" if not shape_ok else "visibility" if not is_claim else "color_or_contrast")
            diagnostics[name] = details
            if shape_ok and color_ok and (target not in matches or score > matches[target].score):
                matches[target] = Match(target, float(score), mae, (xx+tw/2, yy+th/2))
        calibrated, photo_diagnostics = self.button_profiles.recognize(gray)
        groups={}
        for result in calibrated.values():
            groups.setdefault(result['names'],[]).append(result)
        for names, evidence in groups.items():
            for name in names:matches.pop(name,None)
            if any(not all(marker in matches for marker in e.get('required',())) for e in evidence):continue
            candidates=[e['match'] for e in evidence if e['match'] is not None]
            # Native ADB and recorded video can render glyph edges differently.
            # All decisive references must agree; disagreement stays unknown.
            if candidates and len({c[0] for c in candidates})==1:
                name,score,error,center=min(candidates,key=lambda c:c[2])
                matches[name]=Match(name,score,error,center)
        diagnostics['_button_calibration']=photo_diagnostics
        # A partially recognized exit modal must also block background navigation.
        if "exit_title" in matches or all(key in matches for key in ("exit_cancel", "exit_confirm")):
            return Screen("exit_dialog", matches, diagnostics)
        if all(key in matches for key in ("offline_title", "offline_rewards", "offline_confirm")):
            return Screen("offline_reward", matches, diagnostics)
        if "sleep" in matches:
            return Screen("sleep", matches, diagnostics)
        if "reward" in matches or "reward_close" in matches:
            return Screen("reward", matches, diagnostics)
        if all(key in matches for key in ("equipment_current", "equipment_lock", "main_character", "main_pet")):
            return Screen("equipment", matches, diagnostics)
        daily_state, daily_matches = self.daily.recognize(im)
        matches.update(daily_matches)
        if daily_state:
            return Screen(daily_state, matches, diagnostics)
        from task_catalog import PAGE_MARKERS
        for page,markers in PAGE_MARKERS.items():
            if all(key in matches for key in markers):
                if page == "boss_select":
                    from world_boss import boss_notices
                    for boss, center in boss_notices(im).items():
                        name = "x_boss_notice_"+boss
                        matches[name] = Match(name, 1.0, 0.0, center)
                return Screen(page,matches,diagnostics)
        if all("menu_" + room in matches for room in ROOMS):
            return Screen("menu", matches, diagnostics)
        for room in ROOMS:
            if "room_" + room in matches:
                if "ready_" + room in matches and "empty_" + room not in matches:
                    return Screen(room + "_ready", matches, diagnostics)
                if "empty_" + room in matches and "ready_" + room not in matches:
                    return Screen(room + "_empty", matches, diagnostics)
                return Screen(room + "_wait", matches, diagnostics)
        # The menu button alone is not enough to identify the game's main screen.
        if all(name in matches for name in MAIN_MARKERS):
            return Screen("main", matches, diagnostics)
        return Screen("unknown", matches, diagnostics)
