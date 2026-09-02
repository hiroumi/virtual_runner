"""Phase 2: the actual pseudo-3D racing game.

Rear-view, segment-based scrolling road (see road.py), one player car,
a handful of slow-moving traffic cars to avoid, one ~60-90s course,
and a TIME/SCORE/SPEED HUD. Everything red/black, original placeholder
shapes only -- no imported art.

Simulation runs exactly once per frame (see Game.update). Only drawing
branches per eye, through StereoRenderer -- see stereo_renderer.py and
docs/PHASE2_STEREO_TEST_LOG.md for the depth->disparity design this
reuses unchanged. Each road segment's near and far edge are at different
distances from the camera, so (unlike the single-depth sprites) its four
corners are projected individually through StereoRenderer.project_x --
that's the "per road segment" disparity the project spec calls for,
not one shift for the whole road.
"""
from __future__ import annotations

import argparse
import math
import random

import pygame

from config import load_config, save_config
from road import DRAW_DISTANCE, ROAD_WIDTH, SEGMENT_LENGTH, build_track, track_length
from stereo_renderer import StereoRenderer

BLACK = (0, 0, 0)
MOUNTAIN_COLOR = (100, 15, 15)
CLOUD_COLOR = (55, 0, 0)
GRASS_DARK = (18, 4, 4)
GRASS_LIGHT = (26, 6, 6)
RUMBLE_DARK = (120, 15, 15)
RUMBLE_LIGHT = (190, 30, 30)
ROAD_DARK = (40, 9, 9)
ROAD_LIGHT = (52, 12, 12)
TREE_COLOR = (150, 20, 20)
TRAFFIC_COLOR = (170, 25, 25)
PLAYER_COLOR = (255, 45, 45)
HUD_BORDER = (200, 40, 40)
HUD_TEXT = (255, 90, 90)
DEBUG_TEXT = (190, 190, 190)
MESSAGE_COLOR = (255, 210, 110)

CAMERA_HEIGHT = 6.0
FOV_DEG = 110.0
CAMERA_DEPTH = 1.0 / math.tan(math.radians(FOV_DEG / 2))

RACE_TIME = 90.0
PLAYER_CAR_DEPTH = 3.0  # matches the Phase 2 test scene's tuned value

MAX_SPEED = 45.0
OFFROAD_MAX_SPEED = 20.0
ACCEL = 25.0
BRAKE = 70.0
FRICTION = 12.0
OFFROAD_FRICTION = 45.0
STEER_RATE = 1.6
CENTRIFUGAL = 2.5
PLAYER_X_LIMIT = 2.2

TRAFFIC_SPEED = 14.0
COLLISION_Z_RANGE = SEGMENT_LENGTH * 2.5
COLLISION_X_RANGE = 0.7
COLLISION_PENALTY = 0.5
COLLISION_COOLDOWN = 1.0

SCORE_PER_SECOND_PER_SPEED = 2.0


def _font(size: int) -> pygame.font.Font:
    return pygame.font.SysFont("consolas,couriernew,monospace", size)


def project(world_x: float, world_z: float, cam_x: float, cam_z: float, width: float, height: float):
    trans_z = max(world_z - cam_z, 0.1)
    scale = CAMERA_DEPTH / trans_z
    sx = width / 2 + scale * (world_x - cam_x) * width / 2
    sy = height / 2 + scale * CAMERA_HEIGHT * height / 2
    sw = scale * ROAD_WIDTH * width / 2
    return sx, sy, sw, trans_z


def draw_tree(surf: pygame.Surface, cx: float, base_y: float, scale: float, color) -> None:
    trunk_h = 22 * scale
    top = (cx, base_y - trunk_h)
    pygame.draw.line(surf, color, (cx, base_y), top, max(1, int(2 * scale)))
    for angle_deg in (-135, -105, -75, -45):
        rad = math.radians(angle_deg)
        length = 16 * scale
        end = (top[0] + length * math.cos(rad), top[1] + length * math.sin(rad))
        pygame.draw.line(surf, color, top, end, max(1, int(2 * scale)))


def draw_car(surf: pygame.Surface, cx: float, base_y: float, scale: float, color) -> None:
    body_w, body_h = 44 * scale, 16 * scale
    cab_w, cab_h = 28 * scale, 11 * scale
    pygame.draw.rect(surf, color, (cx - body_w / 2, base_y - body_h, body_w, body_h))
    pygame.draw.rect(surf, color, (cx - cab_w / 2, base_y - body_h - cab_h + 2, cab_w, cab_h))


class TrafficCar:
    def __init__(self, z: float, x: float, speed: float):
        self.z = z
        self.x = x
        self.speed = speed


class Player:
    def __init__(self):
        self.x = 0.0
        self.z = 0.0
        self.speed = 0.0


class Game:
    def __init__(self, cfg):
        self.cfg = cfg
        self.segments = build_track()
        self.track_length = track_length(self.segments)
        self.screen = self._make_display()
        self.renderer = StereoRenderer(self.screen, cfg)
        self.font_hud = _font(13)
        self.font_debug = _font(12)
        self.font_message = _font(18)
        self.clock = pygame.time.Clock()

        self.player = Player()
        self.traffic = self._build_traffic()
        self.decor = self._build_decor()

        self.time_left = RACE_TIME
        self.score = 0.0
        self.finished = False
        self.time_up = False
        self.collision_cooldown = 0.0
        self.show_debug = False
        self.last_frame_ms = 0.0

    def _make_display(self) -> pygame.Surface:
        flags = pygame.FULLSCREEN if self.cfg.fullscreen else 0
        return pygame.display.set_mode((self.cfg.output_width, self.cfg.output_height), flags)

    def _build_traffic(self) -> list[TrafficCar]:
        rng = random.Random(42)
        cars = []
        start = 120
        end = len(self.segments) - 60
        step = 90
        for base in range(start, max(start + 1, end), step):
            lane = rng.choice([-0.5, 0.0, 0.5])
            cars.append(TrafficCar(z=base * SEGMENT_LENGTH, x=lane, speed=TRAFFIC_SPEED))
        return cars

    def _build_decor(self) -> list[tuple[float, float, float]]:
        """(world_z, side, scale) for roadside trees, evenly spaced."""
        decor = []
        for i in range(10, len(self.segments) - 5, 14):
            side = 1.0 if (i // 14) % 2 == 0 else -1.0
            decor.append((i * SEGMENT_LENGTH, side, 1.0 + (i % 5) * 0.08))
        return decor

    # -- main loop ------------------------------------------------------
    def run(self, test_frames: int | None = None) -> None:
        running = True
        frame = 0
        while running:
            dt = self.clock.tick(60) / 1000.0
            dt = min(dt, 0.05)
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if not self._handle_keydown(event):
                        running = False
            keys = pygame.key.get_pressed()
            self.update(dt, keys)
            self._draw()
            pygame.display.flip()
            frame += 1
            if test_frames is not None and frame >= test_frames:
                running = False
        pygame.quit()

    def _handle_keydown(self, event: pygame.event.Event) -> bool:
        renderer, cfg = self.renderer, self.cfg
        key = event.key
        if key == pygame.K_ESCAPE:
            return False
        elif key == pygame.K_r:
            self._restart()
        elif key == pygame.K_LEFTBRACKET:
            renderer.parallax_scale = max(0.0, renderer.parallax_scale - 0.05)
        elif key == pygame.K_RIGHTBRACKET:
            renderer.parallax_scale = min(2.0, renderer.parallax_scale + 0.05)
        elif key == pygame.K_z:
            renderer.zero_parallax = not renderer.zero_parallax
        elif key == pygame.K_i:
            renderer.flip_debug = not renderer.flip_debug
        elif key == pygame.K_d:
            self.show_debug = not self.show_debug
        elif key == pygame.K_f:
            cfg.fullscreen = not cfg.fullscreen
            self.screen = self._make_display()
            renderer.screen = self.screen
        elif key == pygame.K_s:
            cfg.parallax_scale = renderer.parallax_scale
            save_config(cfg)
        return True

    def _restart(self) -> None:
        self.player = Player()
        self.time_left = RACE_TIME
        self.score = 0.0
        self.finished = False
        self.time_up = False
        self.collision_cooldown = 0.0
        self.traffic = self._build_traffic()

    # -- simulation (runs once, regardless of how many eyes we draw) ----
    def update(self, dt: float, keys) -> None:
        start = pygame.time.get_ticks()
        self.collision_cooldown = max(0.0, self.collision_cooldown - dt)

        racing = not self.finished and not self.time_up
        if racing:
            offroad = abs(self.player.x) > 1.0
            max_speed = OFFROAD_MAX_SPEED if offroad else MAX_SPEED
            friction = OFFROAD_FRICTION if offroad else FRICTION

            if keys[pygame.K_UP] or keys[pygame.K_w]:
                self.player.speed += ACCEL * dt
            elif keys[pygame.K_DOWN] or keys[pygame.K_s]:
                self.player.speed -= BRAKE * dt
            else:
                self.player.speed -= friction * dt
            self.player.speed = max(0.0, min(max_speed, self.player.speed))

            speed_frac = self.player.speed / MAX_SPEED
            steer = 0.0
            if keys[pygame.K_LEFT] or keys[pygame.K_a]:
                steer -= 1.0
            if keys[pygame.K_RIGHT] or keys[pygame.K_d]:
                steer += 1.0
            self.player.x += steer * STEER_RATE * speed_frac * dt

            segment = self._segment_at(self.player.z)
            self.player.x -= segment.curve * CENTRIFUGAL * speed_frac * dt
            self.player.x = max(-PLAYER_X_LIMIT, min(PLAYER_X_LIMIT, self.player.x))

            self.player.z += self.player.speed * dt
            self.score += self.player.speed * dt * SCORE_PER_SECOND_PER_SPEED

            for car in self.traffic:
                car.z = min(car.z + car.speed * dt, self.track_length)
                if (
                    self.collision_cooldown <= 0.0
                    and abs(self.player.z - car.z) < COLLISION_Z_RANGE
                    and abs(self.player.x - car.x) < COLLISION_X_RANGE
                ):
                    self.player.speed *= COLLISION_PENALTY
                    self.collision_cooldown = COLLISION_COOLDOWN

            self.time_left -= dt
            if self.player.z >= self.track_length:
                self.player.z = self.track_length
                self.finished = True
            elif self.time_left <= 0.0:
                self.time_left = 0.0
                self.time_up = True

        self.last_frame_ms = pygame.time.get_ticks() - start

    def _segment_at(self, world_z: float):
        idx = int(world_z / SEGMENT_LENGTH)
        idx = max(0, min(len(self.segments) - 1, idx))
        return self.segments[idx]

    # -- drawing ----------------------------------------------------------
    def _draw(self) -> None:
        renderer = self.renderer
        renderer.begin_frame(BLACK)
        self._draw_background()
        self._draw_road()
        for wz, side, scale in self.decor:
            self._draw_decor_object(wz, side, scale)
        for car in self.traffic:
            self._draw_traffic_car(car)
        renderer.draw_world(PLAYER_CAR_DEPTH, self._draw_player_car)
        renderer.draw_flat(self._draw_hud)
        renderer.present()
        if self.finished or self.time_up:
            self._draw_message()
        if self.show_debug:
            self._draw_debug_overlay()

    def _draw_background(self) -> None:
        def draw(surf: pygame.Surface, ox: float) -> None:
            w, h = surf.get_size()
            horizon = int(h * 0.5)
            for cx_frac, cy, r in ((0.28, horizon * 0.28, 10), (0.6, horizon * 0.42, 13), (0.82, horizon * 0.2, 8)):
                rect = pygame.Rect(0, 0, int(r * 2.2), int(r))
                rect.center = (int(w * cx_frac + ox), int(cy))
                pygame.draw.ellipse(surf, CLOUD_COLOR, rect)
            pts = [
                (0, horizon), (w * 0.18, horizon - 18), (w * 0.35, horizon - 4),
                (w * 0.55, horizon - 22), (w * 0.75, horizon - 8), (w * 0.9, horizon - 16), (w, horizon),
            ]
            pygame.draw.polygon(surf, MOUNTAIN_COLOR, [(x + ox, y) for x, y in pts])

        self.renderer.draw_world(250.0, draw)

    def _road_center_x(self) -> float:
        return self._segment_at(self.player.z).world_x + self.player.x * ROAD_WIDTH

    def _draw_road(self) -> None:
        renderer = self.renderer
        left, right = renderer.left_surface, renderer.right_surface
        width, height = left.get_size()
        cam_x = self._road_center_x()
        cam_z = self.player.z

        base_idx = int(self.player.z / SEGMENT_LENGTH)
        max_idx = len(self.segments) - 1

        # world_z always advances with n, even past the last real segment
        # (near the finish line) -- otherwise every point beyond the track
        # end would collapse onto the same segment at distance ~0 and the
        # road would degenerate into one overlapping blob instead of
        # continuing to recede into the distance.
        points = []
        for n in range(DRAW_DISTANCE, -1, -1):
            idx = base_idx + n
            look_idx = min(idx, max_idx)
            seg = self.segments[look_idx]
            world_z = idx * SEGMENT_LENGTH
            sx, sy, sw, tz = project(seg.world_x, world_z, cam_x, cam_z, width, height)
            points.append((look_idx, sx, sy, sw, tz))

        for i in range(len(points) - 1):
            idx_f, sxf, syf, swf, tzf = points[i]
            idx_n, sxn, syn, swn, tzn = points[i + 1]
            dark = self.segments[idx_n].looks_dark
            grass = GRASS_DARK if dark else GRASS_LIGHT
            rumble = RUMBLE_DARK if dark else RUMBLE_LIGHT
            road = ROAD_DARK if dark else ROAD_LIGHT

            for color, mult in ((grass, 3.0), (rumble, 1.15), (road, 1.0)):
                lf, rf = renderer.project_x(sxf, tzf)
                ln, rn = renderer.project_x(sxn, tzn)
                wf, wn = swf * mult, swn * mult
                pygame.draw.polygon(left, color, [(lf - wf, syf), (lf + wf, syf), (ln + wn, syn), (ln - wn, syn)])
                pygame.draw.polygon(right, color, [(rf - wf, syf), (rf + wf, syf), (rn + wn, syn), (rn - wn, syn)])

    def _draw_decor_object(self, world_z: float, side: float, scale: float) -> None:
        seg = self._segment_at(world_z)
        cam_x = self._road_center_x()
        cam_z = self.player.z
        width, height = self.renderer.left_surface.get_size()
        world_x = seg.world_x + side * ROAD_WIDTH * 1.4
        sx, sy, sw, tz = project(world_x, world_z, cam_x, cam_z, width, height)
        if tz > SEGMENT_LENGTH * (DRAW_DISTANCE + 1) or world_z < cam_z:
            return

        def draw(surf: pygame.Surface, ox: float) -> None:
            draw_tree(surf, sx + ox, sy, max(0.3, scale * (sw / (ROAD_WIDTH * 6))), TREE_COLOR)

        self.renderer.draw_world(tz, draw)

    def _draw_traffic_car(self, car: TrafficCar) -> None:
        seg = self._segment_at(car.z)
        cam_x = self._road_center_x()
        cam_z = self.player.z
        width, height = self.renderer.left_surface.get_size()
        world_x = seg.world_x + car.x * ROAD_WIDTH
        sx, sy, sw, tz = project(world_x, car.z, cam_x, cam_z, width, height)
        if tz > SEGMENT_LENGTH * (DRAW_DISTANCE + 1) or car.z < cam_z:
            return

        def draw(surf: pygame.Surface, ox: float) -> None:
            draw_car(surf, sx + ox, sy, max(0.35, sw / (ROAD_WIDTH * 3.5)), TRAFFIC_COLOR)

        self.renderer.draw_world(tz, draw)

    def _draw_player_car(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        cx = w / 2 + self.player.x * 10 + ox
        draw_car(surf, cx, h - 34, 1.0, PLAYER_COLOR)

    def _draw_hud(self, surf: pygame.Surface, ox: float) -> None:
        w, h = surf.get_size()
        speed_kmh = int(self.player.speed * 4)
        boxes = [
            ("TIME", f"{int(self.time_left):02d}"),
            ("SCORE", f"{int(self.score):06d}"),
            ("SPEED", f"{speed_kmh:03d}"),
        ]
        box_w = w / len(boxes)
        for i, (label, value) in enumerate(boxes):
            x0 = int(i * box_w) + 2
            rect = pygame.Rect(x0, h - 30, int(box_w) - 4, 26)
            pygame.draw.rect(surf, HUD_BORDER, rect, 1)
            surf.blit(self.font_hud.render(label, True, HUD_TEXT), (rect.x + 3, rect.y + 1))
            surf.blit(self.font_hud.render(value, True, HUD_TEXT), (rect.x + 3, rect.y + 13))

    def _draw_message(self) -> None:
        text = "FINISH!" if self.finished else "TIME UP"
        sub = f"score {int(self.score)}  -  R to restart"
        surf1 = self.font_message.render(text, True, MESSAGE_COLOR)
        surf2 = self.font_debug.render(sub, True, MESSAGE_COLOR)
        cx = self.cfg.output_width // 2
        cy = self.cfg.output_height // 2
        self.screen.blit(surf1, surf1.get_rect(center=(cx, cy - 10)))
        self.screen.blit(surf2, surf2.get_rect(center=(cx, cy + 14)))

    def _draw_debug_overlay(self) -> None:
        renderer, cfg = self.renderer, self.cfg
        max_in, max_out = renderer.max_disparity_range()
        fps = self.clock.get_fps()
        lines = [
            f"fps={fps:5.1f}  frame_ms={self.last_frame_ms:4.1f}  parallax={renderer.parallax_scale:.2f}([/])"
            f"  zero={'ON' if renderer.zero_parallax else 'off'}(Z)  flip={'ON' if renderer.flip_debug else 'off'}(I)",
            f"caps=[{max_out:+.0f},{max_in:+.0f}]px  player.z={self.player.z:7.1f}/{self.track_length:.0f}"
            f"  player.x={self.player.x:+.2f}  speed={self.player.speed:5.1f}",
        ]
        y = 4
        for line in lines:
            surf = self.font_debug.render(line, True, DEBUG_TEXT)
            self.screen.blit(surf, (6, y))
            y += 13


def run(test_frames: int | None = None) -> None:
    pygame.init()
    pygame.display.set_caption("Virtual Boy Stereo Racing - Phase 2")
    cfg = load_config()
    Game(cfg).run(test_frames=test_frames)


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 2 racing game")
    parser.add_argument(
        "--test-frames",
        type=int,
        default=None,
        help="Run N frames and exit automatically (smoke test / CI, no input needed).",
    )
    args = parser.parse_args()
    run(test_frames=args.test_frames)


if __name__ == "__main__":
    main()
