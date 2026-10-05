"""PCB-Shell-V1 共用工具：读取配置、坐标换算、二维圆角轮廓。

整机坐标：X 向前、Y 向左、Z 向上，毫米。
主板竖放在 XZ 平面，顶层朝 +Y。PCB 数据坐标（毫米，Y 向上）u = -X，v = Z。
嘉立创接口单位为密耳（1 mil = 0.0254 mm），数据坐标 Y 轴向上。
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "pcb-shell-v1.json"
GEOMETRY = ROOT / "config" / "pcb-parts-geometry.json"
OUTPUT = ROOT / "outputs" / "pcb-shell-v1"
MIL = 0.0254


def load_config():
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def load_geometry():
    return json.loads(GEOMETRY.read_text(encoding="utf-8"))["parts"]


def resolve_lcsc(config, value):
    """配置里阻容用别名（如 R_10k），这里换成立创编号。"""
    return config["parts_common"].get(value, value)


def global_to_uv(x, z):
    return -x, z


def uv_to_global(u, v):
    return -u, v


def mil(mm):
    return mm / MIL


def rotate(px, py, deg):
    a = math.radians(deg)
    return px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a)


def daughter_ab_to_uv(config, a, b):
    """扳机小板局部坐标 (a, b) → 拼板中的 PCB 数据坐标 (u, v)。

    小板装配后：a → 整机 Y，b → 整机 Z，顶层朝 +X。
    拼板时小板绕自身原点旋转 panel_rotation_deg，再平移到 panel_origin_uv。
    """
    d = config["board"]["daughter"]
    du, dv = rotate(a, b, d["panel_rotation_deg"])
    return d["panel_origin_uv"][0] + du, d["panel_origin_uv"][1] + dv


def part_uv_rot(config, part):
    """返回器件在 PCB 数据坐标中的位置 (u, v) 毫米与旋转角（度，逆时针）。"""
    if part.get("daughter"):
        u, v = daughter_ab_to_uv(config, *part["ab"])
        rot = (part["rot_db"] + config["board"]["daughter"]["panel_rotation_deg"]) % 360
        return u, v, rot
    u, v = global_to_uv(*part["xz"])
    return u, v, part["rot"] % 360


def fillet_polygon(points, segment=0.8):
    """points: [(x, z, r), ...] 闭合多边形，按每个顶点半径倒圆，返回加密后的点列。"""
    n = len(points)
    out = []
    for i in range(n):
        px, pz, r = points[i]
        ax, az, _ = points[i - 1]
        bx, bz, _ = points[(i + 1) % n]
        u1 = _unit(ax - px, az - pz)
        u2 = _unit(bx - px, bz - pz)
        cosang = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        half = math.acos(cosang) / 2
        if r <= 0 or half < 1e-6 or abs(half - math.pi / 2) < 1e-6:
            out.append((px, pz))
            continue
        t = r / math.tan(half)
        t = min(t, 0.45 * math.dist((px, pz), (ax, az)), 0.45 * math.dist((px, pz), (bx, bz)))
        r_eff = t * math.tan(half)
        bis = _unit(u1[0] + u2[0], u1[1] + u2[1])
        cx = px + bis[0] * r_eff / math.sin(half)
        cz = pz + bis[1] * r_eff / math.sin(half)
        t1 = (px + u1[0] * t, pz + u1[1] * t)
        t2 = (px + u2[0] * t, pz + u2[1] * t)
        a1 = math.atan2(t1[1] - cz, t1[0] - cx)
        a2 = math.atan2(t2[1] - cz, t2[0] - cx)
        da = (a2 - a1 + math.pi) % (2 * math.pi) - math.pi
        steps = max(2, int(abs(da) * r_eff / segment) + 1)
        for k in range(steps + 1):
            a = a1 + da * k / steps
            out.append((cx + r_eff * math.cos(a), cz + r_eff * math.sin(a)))
    return out


def fillet_segments(points):
    """与 fillet_polygon 相同的圆角，但输出 [('line', p0, p1) | ('arc', p0, pm, p1)] 段列表（真圆弧）。"""
    n = len(points)
    corners = []
    for i in range(n):
        px, pz, r = points[i]
        ax, az, _ = points[i - 1]
        bx, bz, _ = points[(i + 1) % n]
        u1 = _unit(ax - px, az - pz)
        u2 = _unit(bx - px, bz - pz)
        cosang = max(-1.0, min(1.0, u1[0] * u2[0] + u1[1] * u2[1]))
        half = math.acos(cosang) / 2
        if r <= 0 or half < 1e-6 or abs(half - math.pi / 2) < 1e-6:
            corners.append(((px, pz), None, (px, pz)))
            continue
        t = min(r / math.tan(half), 0.45 * math.dist((px, pz), (ax, az)), 0.45 * math.dist((px, pz), (bx, bz)))
        r_eff = t * math.tan(half)
        bis = _unit(u1[0] + u2[0], u1[1] + u2[1])
        mid = (px + bis[0] * (r_eff / math.sin(half) - r_eff), pz + bis[1] * (r_eff / math.sin(half) - r_eff))
        corners.append(((px + u1[0] * t, pz + u1[1] * t), mid, (px + u2[0] * t, pz + u2[1] * t)))
    segs = []
    for i in range(n):
        start, mid, end = corners[i]
        if mid is not None:
            segs.append(("arc", start, mid, end))
        nxt = corners[(i + 1) % n][0]
        if math.dist(end, nxt) > 1e-6:
            segs.append(("line", end, nxt))
    return segs


def _unit(x, y):
    n = math.hypot(x, y)
    return (x / n, y / n) if n else (0.0, 0.0)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
