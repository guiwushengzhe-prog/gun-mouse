"""仅用原生重绘焊盘/网络基准计算新路径；不读取或复制任何旧走线。"""
from __future__ import annotations

import heapq
import json
import math
import random
from collections import defaultdict
from pathlib import Path

import numpy as np
from scipy.ndimage import binary_dilation

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "pcb/嘉立创原生重绘版/原生器件与焊盘基准.json"
OUTPUT = ROOT / ".logs/嘉立创最终版/原生布线路径计划.json"

GRID = 0.10
MIL_TO_MM = 0.0254
MM_TO_MIL = 1.0 / MIL_TO_MM
X0, X1 = 5.0, 57.0
Y0, Y1 = 5.0, 87.0
NX = round((X1 - X0) / GRID) + 1
NY = round((Y1 - Y0) / GRID) + 1
TRACK_WIDTH_MM = 0.30
PAD_CLEARANCE_MM = 0.25
BOARD_EDGE_CLEARANCE_MM = 0.50
RASTER_MARGIN_MM = GRID * math.sqrt(2) / 2 + 1e-6
TRACK_OBSTACLE_RADIUS_MM = TRACK_WIDTH_MM + PAD_CLEARANCE_MM + RASTER_MARGIN_MM
PAD_OBSTACLE_ADD_MM = TRACK_WIDTH_MM / 2 + PAD_CLEARANCE_MM + RASTER_MARGIN_MM
BOARD_EDGE_MARGIN_MM = TRACK_WIDTH_MM / 2 + BOARD_EDGE_CLEARANCE_MM + RASTER_MARGIN_MM
ANTENNA_ROUTE_MARGIN_MM = TRACK_WIDTH_MM / 2 + RASTER_MARGIN_MM
MAX_ASTAR_EXPANSIONS = 150_000
VIA_DIAMETER_MM = 0.70
VIA_DRILL_MM = 0.30
VIA_PENALTY_GRID = 12.0


def cell(point: tuple[float, float]) -> tuple[int, int]:
    x, y = point
    return round((x - X0) / GRID), round((y - Y0) / GRID)


def cell_point(ix: int, iy: int) -> tuple[float, float]:
    return X0 + ix * GRID, Y0 + iy * GRID


def distance_to_segment_grid(xx, yy, a, b):
    ax, ay = a
    bx, by = b
    dx, dy = bx - ax, by - ay
    denom = dx * dx + dy * dy
    if not denom:
        return np.hypot(xx - ax, yy - ay)
    t = np.clip(((xx - ax) * dx + (yy - ay) * dy) / denom, 0.0, 1.0)
    return np.hypot(xx - (ax + t * dx), yy - (ay + t * dy))


def board_and_keepout_masks(outline):
    xs = X0 + np.arange(NX) * GRID
    ys = Y0 + np.arange(NY) * GRID
    xx, yy = np.meshgrid(xs, ys)
    inside = (xx >= 5) & (xx <= 57) & (yy >= 5) & (yy <= 87) & ((xx >= 20) | (yy <= 35))
    edge_distance = np.full((NY, NX), np.inf, dtype=np.float32)
    closed = outline[1:] + outline[:1]
    for a, b in zip(outline, closed):
        edge_distance = np.minimum(edge_distance, distance_to_segment_grid(xx, yy, a, b))
    blocked_edge = ~inside | (edge_distance < BOARD_EDGE_MARGIN_MM)

    # 与嘉立创已建立的天线禁铜区及螺钉头禁布区保持一致，并为栅格线宽留余量。
    antenna = (23.42, 32.58, 16.42, 28.58)
    extra = ANTENNA_ROUTE_MARGIN_MM
    antenna_mask = ((xx >= antenna[0] - extra) & (xx <= antenna[1] + extra) &
                    (yy >= antenna[2] - extra) & (yy <= antenna[3] + extra))
    screw_mask = np.zeros((NY, NX), dtype=bool)
    for sx, sy, travel in ((43.25, 7.7, 0.0), (23.75, 7.7, 0.6)):
        dx = np.maximum(np.abs(xx - sx) - travel, 0)
        radius = 2.7 + ANTENNA_ROUTE_MARGIN_MM
        screw_mask |= dx * dx + (yy - sy) ** 2 <= radius * radius
    top = blocked_edge | antenna_mask | screw_mask
    bottom = blocked_edge | antenna_mask
    return {1: top, 2: bottom}


def pad_center_mm(pad):
    return pad["x"] * MIL_TO_MM, -pad["y"] * MIL_TO_MM


def pad_radius_mm(pad):
    shape = pad.get("pad") or ["ELLIPSE", 70.9, 70.9]
    if len(shape) >= 3:
        half_width = float(shape[1]) * MIL_TO_MM / 2
        half_height = float(shape[2]) * MIL_TO_MM / 2
    else:
        half_width = half_height = float(shape[1]) * MIL_TO_MM / 2
    # 目标库目前均为圆形或椭圆形通孔焊盘；取最大半径并额外加安全间距。
    return max(half_width, half_height) + PAD_OBSTACLE_ADD_MM


def add_circle_obstacle(mask, center, radius):
    x, y = center
    cx, cy = cell(center)
    reach = math.ceil(radius / GRID)
    xlo, xhi = max(0, cx - reach), min(NX, cx + reach + 1)
    ylo, yhi = max(0, cy - reach), min(NY, cy + reach + 1)
    dx = X0 + np.arange(xlo, xhi) * GRID - x
    dy = Y0 + np.arange(ylo, yhi) * GRID - y
    yy, xx = np.meshgrid(dy, dx, indexing="ij")
    mask[ylo:yhi, xlo:xhi] |= xx * xx + yy * yy <= radius * radius


def layer_blocked(net, layer, base_masks, pads, occupied):
    blocked = base_masks[layer].copy()
    blocked |= occupied[layer]
    for pad in pads:
        if pad.get("net") == net:
            continue
        add_circle_obstacle(blocked, pad_center_mm(pad), pad_radius_mm(pad))
    return blocked


NEIGHBORS = []
for dy in (-1, 0, 1):
    for dx in (-1, 0, 1):
        if dx or dy:
            NEIGHBORS.append((dx, dy, math.sqrt(2) if dx and dy else 1.0))


def heuristic(a, b):
    dx, dy = abs(a[0] - b[0]), abs(a[1] - b[1])
    return max(dx, dy) + (math.sqrt(2) - 1) * min(dx, dy)


def astar(blocked, start_mm, end_mm):
    start = cell(start_mm)
    goal = cell(end_mm)
    if start == goal:
        return [start], 0.0
    if blocked[start[1], start[0]] or blocked[goal[1], goal[0]]:
        return None, math.inf
    costs = {start: 0.0}
    parents = {start: None}
    queue = [(heuristic(start, goal), 0.0, start[0], start[1])]
    expanded = 0
    while queue and expanded < MAX_ASTAR_EXPANSIONS:
        _, cost, x, y = heapq.heappop(queue)
        here = (x, y)
        if cost != costs.get(here):
            continue
        if here == goal:
            path = []
            node = here
            while node is not None:
                path.append(node)
                node = parents[node]
            path.reverse()
            return path, cost * GRID
        expanded += 1
        for dx, dy, step_cost in NEIGHBORS:
            nx, ny = x + dx, y + dy
            if nx < 0 or nx >= NX or ny < 0 or ny >= NY or blocked[ny, nx]:
                continue
            if dx and dy and (blocked[y, nx] or blocked[ny, x]):
                continue
            nxt = (nx, ny)
            new_cost = cost + step_cost
            if new_cost >= costs.get(nxt, math.inf):
                continue
            costs[nxt] = new_cost
            parents[nxt] = here
            heapq.heappush(queue, (new_cost + 1.12 * heuristic(nxt, goal), new_cost, nx, ny))
    return None, math.inf


def dilation_disk(radius_mm):
    reach = math.ceil(radius_mm / GRID)
    yy, xx = np.ogrid[-reach:reach + 1, -reach:reach + 1]
    return (xx * xx + yy * yy) * GRID * GRID <= radius_mm * radius_mm


def via_blocked_mask(net, base_masks, pads, layer_use, via_use):
    # 过孔环形铜与板边、天线禁铜区、螺丝头禁布区的间距。
    blocked = binary_dilation(base_masks[1] | base_masks[2], structure=dilation_disk(0.20))
    # 与其他网络的焊盘保持 0.25 mm 间距；相对走线中心多出 0.20 mm 环形铜半径差。
    for pad in pads:
        if pad.get("net") == net:
            continue
        add_circle_obstacle(blocked, pad_center_mm(pad), pad_radius_mm(pad) + 0.20)
    # 过孔到已有不同网络走线的中心距离为 0.35 + 0.15 + 0.25 mm。
    for layer in (1, 2):
        for other_net, mask in layer_use[layer].items():
            if other_net != net:
                blocked |= binary_dilation(mask, structure=dilation_disk(0.20))
    # 过孔到过孔中心距离为 0.70 + 0.25 mm。
    for other_net, points in via_use.items():
        for point in points:
            add_circle_obstacle(blocked, point, VIA_DIAMETER_MM + 0.25 + RASTER_MARGIN_MM)
            if other_net == net:
                ix, iy = cell(point)
                blocked[iy, ix] = False
    return blocked


def astar_two_layers(blocked, via_blocked, start_mm, end_mm):
    start = cell(start_mm)
    goal = cell(end_mm)
    if start == goal:
        return [(1, *start)], 0.0
    starts = [(layer, start[0], start[1]) for layer in (1, 2)
              if not blocked[layer][start[1], start[0]]]
    if not starts:
        return None, math.inf
    goal_states = {(layer, goal[0], goal[1]) for layer in (1, 2)
                   if not blocked[layer][goal[1], goal[0]]}
    if not goal_states:
        return None, math.inf
    costs = {state: 0.0 for state in starts}
    parents = {state: None for state in starts}
    queue = []
    for state in starts:
        _, x, y = state
        queue.append((heuristic((x, y), goal), 0.0, state))
    heapq.heapify(queue)
    expanded = 0
    while queue and expanded < MAX_ASTAR_EXPANSIONS:
        _, cost, here = heapq.heappop(queue)
        if cost != costs.get(here):
            continue
        if here in goal_states:
            path = []
            node = here
            while node is not None:
                path.append(node)
                node = parents[node]
            path.reverse()
            return path, cost * GRID
        expanded += 1
        layer, x, y = here
        for dx, dy, step_cost in NEIGHBORS:
            nx, ny = x + dx, y + dy
            if nx < 0 or nx >= NX or ny < 0 or ny >= NY or blocked[layer][ny, nx]:
                continue
            if dx and dy and (blocked[layer][y, nx] or blocked[layer][ny, x]):
                continue
            nxt = (layer, nx, ny)
            new_cost = cost + step_cost
            if new_cost < costs.get(nxt, math.inf):
                costs[nxt] = new_cost
                parents[nxt] = here
                heapq.heappush(queue, (new_cost + 1.12 * heuristic((nx, ny), goal), new_cost, nxt))
        if not via_blocked[y, x]:
            nxt = (3 - layer, x, y)
            new_cost = cost + VIA_PENALTY_GRID
            if new_cost < costs.get(nxt, math.inf):
                costs[nxt] = new_cost
                parents[nxt] = here
                heapq.heappush(queue, (new_cost + 1.12 * heuristic((x, y), goal), new_cost, nxt))
    return None, math.inf


def path_for_net(net, layer, group, pads, base_masks, occupied):
    blocked = layer_blocked(net, layer, base_masks, pads, occupied)
    root = min(range(len(group)), key=lambda i: sum(
        math.dist(pad_center_mm(group[i]), pad_center_mm(other)) for other in group
    ))
    connected = {root}
    remaining = set(range(len(group))) - connected
    connections = []
    total_cost = 0.0
    while remaining:
        options = sorted(
            (math.dist(pad_center_mm(group[a]), pad_center_mm(group[b])), a, b)
            for a in connected for b in remaining
        )
        picked = None
        for _, parent, child in options:
            path, cost = astar(blocked, pad_center_mm(group[parent]), pad_center_mm(group[child]))
            if path:
                picked = parent, child, path, cost
                break
        if picked is None:
            return None, math.inf, f"{net} 在第 {layer} 层无法连接剩余焊盘"
        parent, child, path, cost = picked
        connections.append({"from": group[parent], "to": group[child], "cells": path, "lengthMm": cost})
        total_cost += cost
        connected.add(child)
        remaining.remove(child)
    return connections, total_cost, None


def simplify(points):
    if len(points) <= 2:
        return points
    out = [points[0]]
    for i in range(1, len(points) - 1):
        a, b, c = out[-1], points[i], points[i + 1]
        cross = (b[0] - a[0]) * (c[1] - b[1]) - (b[1] - a[1]) * (c[0] - b[0])
        if abs(cross) > 1e-8:
            out.append(b)
    out.append(points[-1])
    return out


def connection_points(connection):
    start = pad_center_mm(connection["from"])
    end = pad_center_mm(connection["to"])
    cells = connection["cells"]
    points = [start]
    points.extend(cell_point(ix, iy) for ix, iy in cells)
    points.append(end)
    return simplify(points)


def mark_track_obstacle(mask, connections):
    radius = TRACK_OBSTACLE_RADIUS_MM
    offsets = []
    r = math.ceil(radius / GRID)
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            if (dx * GRID) ** 2 + (dy * GRID) ** 2 <= radius * radius:
                offsets.append((dx, dy))
    for connection in connections:
        for ix, iy in connection["cells"]:
            for dx, dy in offsets:
                x, y = ix + dx, iy + dy
                if 0 <= x < NX and 0 <= y < NY:
                    mask[y, x] = True


def segment_key(net, layer, a, b):
    p1 = tuple(round(v, 4) for v in a)
    p2 = tuple(round(v, 4) for v in b)
    return (net, layer, *sorted((p1, p2)))


def main(include_ground=False):
    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    all_pads = []
    nets = defaultdict(list)
    for component in data["components"]:
        for pad in component["pads"]:
            item = {**pad, "reference": component["reference"]}
            all_pads.append(item)
            if item.get("net"):
                nets[item["net"]].append(item)
    for pad in data["mechanicalPads"]:
        all_pads.append({**pad, "net": ""})

    outline = [tuple(p) for p in data["outline"]]
    base_masks = board_and_keepout_masks(outline)
    occupied = {1: np.zeros((NY, NX), dtype=bool), 2: np.zeros((NY, NX), dtype=bool)}

    candidates = [net for net in nets if include_ground or net != "GND"]
    span = {net: max(math.dist(pad_center_mm(a), pad_center_mm(b))
                     for a in nets[net] for b in nets[net]) for net in candidates}
    distance_order = sorted(candidates, key=lambda net: span[net], reverse=True)
    constrained_order = ["TOUCH", "SDA", "SCL", "JOY_SW", "JOY_Y", "JOY_X",
                         "TRIG", "BAT_SW", "VBAT_ADC", "TOUCH_ELECTRODE",
                         "BTN_R", "BAT_RAW", "3V3"]
    degree_order = sorted(candidates, key=lambda net: (len(nets[net]), span[net]), reverse=True)
    critical_order = ["JOY_Y", "JOY_X", "3V3", "TRIG", "BAT_SW", "VBAT_ADC",
                      "TOUCH", "JOY_SW", "BAT_RAW", "BTN_R", "TOUCH_ELECTRODE", "SDA", "SCL"]
    strategies = [
        ("最远网络优先", distance_order),
        ("受天线区约束网络优先", constrained_order),
        ("多焊盘网络优先", degree_order),
        ("拥堵网络优先", critical_order),
        ("近距离网络优先", list(reversed(distance_order))),
    ]
    # 同一组网络试不同起点，避免一条长线过早占住后续必经通道。
    strategies.extend((f"最远优先轮换{offset}", distance_order[offset:] + distance_order[:offset])
                      for offset in (2, 4, 6, 8))
    rng = random.Random(20261018)
    for index in range(12):
        order = list(candidates)
        rng.shuffle(order)
        strategies.append((f"受限随机顺序{index + 1}", order))
    if include_ground:
        strategies=[('地线先行：'+label,['GND']+[net for net in order if net!='GND']) for label,order in strategies]

    def plan_order(order):
        layer_use = {1: {}, 2: {}}
        via_use = defaultdict(list)
        selected, summary, completed_nets = [], [], []
        for net in order:
            net_length = 0.0
            layer_counts = {1: 0, 2: 0}
            net_vias = 0
            group = nets[net]
            root = min(range(len(group)), key=lambda i: sum(
                math.dist(pad_center_mm(group[i]), pad_center_mm(other)) for other in group
            ))
            connected = {root}
            remaining = set(range(len(group))) - connected
            while remaining:
                other_tracks = {}
                for layer in (1, 2):
                    used = np.zeros((NY, NX), dtype=bool)
                    for other_net, mask in layer_use[layer].items():
                        if other_net != net:
                            used |= mask
                    other_tracks[layer] = used
                blocked = {layer: layer_blocked(net, layer, base_masks, all_pads,
                                                 {1: other_tracks[1], 2: other_tracks[2]})
                           for layer in (1, 2)}
                for other_net, points in via_use.items():
                    if other_net == net:
                        continue
                    for point in points:
                        for layer in (1, 2):
                            add_circle_obstacle(blocked[layer], point,
                                VIA_DIAMETER_MM / 2 + TRACK_WIDTH_MM / 2 +
                                PAD_CLEARANCE_MM + RASTER_MARGIN_MM)
                via_blocked = via_blocked_mask(net, base_masks, all_pads, layer_use, via_use)
                pairs = sorted(
                    (math.dist(pad_center_mm(group[a]), pad_center_mm(group[b])), a, b)
                    for a in connected for b in remaining
                )
                selected_pair = None
                errors = []
                for _, parent, child in pairs:
                    a, b = pad_center_mm(group[parent]), pad_center_mm(group[child])
                    path, cost = astar_two_layers(blocked, via_blocked, a, b)
                    if path:
                        selected_pair = (parent, child, path, cost)
                        break
                    errors.append(f"{group[parent]['reference']}.{group[parent]['number']} → "
                                  f"{group[child]['reference']}.{group[child]['number']} 两层均无可行路径")
                if selected_pair is None:
                    return None, {"failedNet": net, "details": errors[-8:],
                                  "completedNets": completed_nets}
                parent, child, path, cost = selected_pair
                connection = {"from": group[parent], "to": group[child],
                              "states": path, "lengthMm": cost}
                selected.append((net, connection))
                route_layer = path[0][0]
                layer_cells = [path[0][1:]]
                start_cell, goal_cell = cell(pad_center_mm(group[parent])), cell(pad_center_mm(group[child]))
                for state in path[1:]:
                    layer, ix, iy = state
                    if layer == route_layer:
                        layer_cells.append((ix, iy))
                        continue
                    net_mask = layer_use[route_layer].setdefault(net, np.zeros((NY, NX), dtype=bool))
                    mark_track_obstacle(net_mask, [{"cells": layer_cells}])
                    layer_counts[route_layer] += 1
                    if (ix, iy) not in (start_cell, goal_cell):
                        point = cell_point(ix, iy)
                        if not any(math.dist(point, old) < GRID / 2 for old in via_use[net]):
                            via_use[net].append(point)
                            net_vias += 1
                    route_layer = layer
                    layer_cells = [(ix, iy)]
                net_mask = layer_use[route_layer].setdefault(net, np.zeros((NY, NX), dtype=bool))
                mark_track_obstacle(net_mask, [{"cells": layer_cells}])
                layer_counts[route_layer] += 1
                net_length += cost
                connected.add(child)
                remaining.remove(child)
            completed_nets.append(net)
            summary.append({"net": net, "padCount": len(nets[net]), "layers": layer_counts,
                            "viaCount": net_vias, "lengthMm": round(net_length, 3),
                            "connections": len(group) - 1})
        return (selected, summary), None

    selected = summary = chosen_order = None
    attempts = []
    seen_orders = set()
    for label, order in strategies:
        key = tuple(order)
        if key in seen_orders:
            continue
        seen_orders.add(key)
        result, failure = plan_order(order)
        if failure:
            attempts.append({"strategy": label, **failure})
            continue
        selected, summary = result
        chosen_order = label
        break
    if selected is None:
        raise RuntimeError("原生布线规划在多个网络顺序下均未完成：" + json.dumps(attempts, ensure_ascii=False))

    segments, vias = [], []
    seen_segments, seen_vias = set(), set()
    geometry = []
    for net, connection in selected:
        states = connection["states"]
        start, end = pad_center_mm(connection["from"]), pad_center_mm(connection["to"])
        start_cell, end_cell = cell(start), cell(end)
        active_layer = states[0][0]
        points = [start]
        if cell_point(*start_cell) != start:
            points.append(cell_point(*start_cell))
        layer_segments = []
        via_points = []
        for previous, state in zip(states, states[1:]):
            layer, ix, iy = state
            point = cell_point(ix, iy)
            if layer != active_layer:
                if len(points) > 1:
                    layer_segments.append({"layer": active_layer, "pointsMm": points})
                if (ix, iy) not in (start_cell, end_cell):
                    via_points.append(point)
                active_layer = layer
                points = [point]
            else:
                points.append(point)
        if math.dist(points[-1], end) > 1e-8:
            points.append(end)
        if len(points) > 1:
            layer_segments.append({"layer": active_layer, "pointsMm": points})
        for item in layer_segments:
            item["pointsMm"] = simplify(item["pointsMm"])
        from_name = connection["from"]["reference"] + "." + connection["from"]["number"]
        to_name = connection["to"]["reference"] + "." + connection["to"]["number"]
        geometry.append({"net": net, "from": from_name, "to": to_name,
                         "layerSegments": [{"layer": item["layer"],
                           "pointsMm": [[round(x, 4), round(y, 4)] for x, y in item["pointsMm"]]}
                           for item in layer_segments],
                         "viaPointsMm": [[round(x, 4), round(y, 4)] for x, y in via_points]})
        for point in via_points:
            key = (net, tuple(round(v, 4) for v in point))
            if key in seen_vias:
                continue
            seen_vias.add(key)
            vias.append({"net": net, "x": point[0] * MM_TO_MIL,
                         "y": -point[1] * MM_TO_MIL,
                         "hole": VIA_DRILL_MM * MM_TO_MIL,
                         "diameter": VIA_DIAMETER_MM * MM_TO_MIL})
        for item in layer_segments:
            points = item["pointsMm"]
            for a, b in zip(points, points[1:]):
                if math.dist(a, b) < 0.01:
                    continue
                key = segment_key(net, item["layer"], a, b)
                if key in seen_segments:
                    continue
                seen_segments.add(key)
                segments.append({
                    "net": net,
                    "layer": item["layer"],
                    "startX": a[0] * MM_TO_MIL,
                    "startY": -a[1] * MM_TO_MIL,
                    "endX": b[0] * MM_TO_MIL,
                    "endY": -b[1] * MM_TO_MIL,
                    "lineWidth": TRACK_WIDTH_MM * MM_TO_MIL,
                })

    output = {
        "source": str(SOURCE),
        "method": "由原生焊盘/网络基准独立计算，双层加过孔A*栅格路径；未读取旧导线、过孔或覆铜",
        "gridMm": GRID,
        "trackWidthMm": TRACK_WIDTH_MM,
        "clearanceMm": PAD_CLEARANCE_MM,
        "boardEdgeClearanceMm": BOARD_EDGE_CLEARANCE_MM,
        "routeOrderStrategy": chosen_order,
        "plannedNets": summary,
        "plannedConnections": geometry,
        "segments": segments,
        "segmentCount": len(segments),
        "vias": vias,
        "viaCount": len(vias),
        "gndConnectedByCopperPour": True,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"plannedNets": summary, "segmentCount": len(segments),
                      "viaCount": len(vias), "output": str(OUTPUT)}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
