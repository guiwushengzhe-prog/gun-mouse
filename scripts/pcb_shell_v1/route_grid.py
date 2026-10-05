"""两层板网格布线器（A* 迷宫算法），用于替代后台模式下无法启动的嘉立创自动布线。

输入：layout.json（板框、开槽、孔、拼板连接筋）与 pads.js 导出的全部焊盘（密耳，Y 向上）。
输出：导线段（含线宽）与过孔（毫米），由 routes.js 写回嘉立创；之后用嘉立创设计规则检查复核。

模型：分别记录各网络的焊盘铜皮、细线中心、粗线中心、过孔中心。每次连线只在局部窗口内，
按"新线半宽 + 间距 + 对方铜皮半宽"精确膨胀出禁布区，因此不同线宽可以共存。
规则：网格 0.1；信号线 0.15，电源线 0.3（走不通时该段退为 0.15）；线间距 0.13，焊盘/过孔间距 0.165；
过孔 0.6/0.3；导线距板边 ≥ 0.3。均在嘉立创两层板常规工艺内。
"""

import heapq
import math

import numpy as np

MIL = 0.0254
G = 0.1
W_SIG = 0.15
W_PWR = 0.30
CLEAR = 0.13          # 走线之间（嘉立创规则 4 mil）
CLEAR_PAD = 0.165     # 焊盘/过孔到走线、过孔到焊盘（规则 6 mil）
SLOT_CLEAR = 0.32     # 封装定位孔/开槽到走线（规则 11.8 mil）
HOLE_GAP = 0.32       # 孔到孔（规则 11.8 mil）
PAD_GROW = 0.075      # 焊盘作障碍时外扩：网格点只覆盖焊盘内部，真实边缘可能再往外半格
MARGIN = 0.03
VIA_D = 0.6
VIA_HOLE = 0.3
EDGE_CLEAR = 0.30
VIA_COST = 25.0
TURN_COST = 0.4
BOTTOM_PENALTY = 1.3
H_WEIGHT = 1.3
WINDOW = 25.0
MAX_EXPAND = 3_000_000
POWER_NETS = {"VBUS", "VBAT", "VSYS", "3V3", "GND"}
PRIORITY = ["USB_DP", "USB_DN", "SDA", "SCL", "IMU_INT1", "IMU_INT2", "IMU_CS", "3V3"]
SQ2 = math.sqrt(2)
MOVES = [(0, 1, 1.0), (0, -1, 1.0), (1, 0, 1.0), (-1, 0, 1.0),
         (1, 1, SQ2), (1, -1, SQ2), (-1, 1, SQ2), (-1, -1, SQ2)]
# 铜皮类别及其半宽（毫米）
CLS_PAD, CLS_SIG, CLS_PWR, CLS_VIA = 0, 1, 2, 3
HALF = {CLS_PAD: 0.0, CLS_SIG: W_SIG / 2, CLS_PWR: W_PWR / 2, CLS_VIA: VIA_D / 2}


def disc(radius_mm):
    r = int(math.ceil(radius_mm / G - 1e-9))
    return [(di, dj) for di in range(-r, r + 1) for dj in range(-r, r + 1)
            if (di * G) ** 2 + (dj * G) ** 2 <= radius_mm ** 2 + 1e-9]


def dilate(mask, radius_mm):
    """二维布尔数组按圆盘膨胀（边界外按 False）。"""
    if radius_mm <= 0:
        return mask.copy()
    out = mask.copy()
    H, W = mask.shape
    for di, dj in disc(radius_mm):
        if di == 0 and dj == 0:
            continue
        src = mask[max(0, -di):H - max(0, di), max(0, -dj):W - max(0, dj)]
        out[max(0, di):H - max(0, -di), max(0, dj):W - max(0, -dj)] |= src
    return out


def point_in_poly(X, Y, poly):
    inside = np.zeros(X.shape, dtype=bool)
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        if y1 == y2:
            continue
        cond = (Y >= min(y1, y2)) & (Y < max(y1, y2))
        xint = x1 + (Y - y1) * (x2 - x1) / (y2 - y1)
        inside ^= cond & (X < xint)
    return inside


def dist_to_poly(X, Y, poly):
    d = np.full(X.shape, np.inf)
    n = len(poly)
    for k in range(n):
        x1, y1 = poly[k]
        x2, y2 = poly[(k + 1) % n]
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        t = np.clip(((X - x1) * dx + (Y - y1) * dy) / L2, 0, 1) if L2 > 0 else 0
        d = np.minimum(d, np.hypot(X - (x1 + t * dx), Y - (y1 + t * dy)))
    return d


def pad_geometry(p):
    shape = p["pad"][0]
    if shape == "POLYGON":
        path = [v for v in p["pad"][1] if isinstance(v, (int, float))]
        xs, ys = path[0::2], path[1::2]
        return "RECT", (max(xs) - min(xs)) * MIL, (max(ys) - min(ys)) * MIL, p.get("rot") or 0
    return shape, p["pad"][1] * MIL, p["pad"][2] * MIL, p.get("rot") or 0


def pad_layers(p):
    return {1: [0], 2: [1]}.get(p["layer"], [0, 1])


class Router:
    def __init__(self, layout, pads):
        outline = layout["outline_uv"]
        us = [p[0] for p in outline]
        vs = [p[1] for p in outline]
        self.u0, self.v0 = min(us) - 2, min(vs) - 2
        self.W = int((max(us) - self.u0 + 2) / G) + 1
        self.H = int((max(vs) - self.v0 + 2) / G) + 1
        jj, ii = np.meshgrid(np.arange(self.W), np.arange(self.H))
        self.U = self.u0 + jj * G
        self.V = self.v0 + ii * G
        inside = point_in_poly(self.U, self.V, outline)
        dist = dist_to_poly(self.U, self.V, outline)
        for c in layout["cutouts"]:
            inside &= ~point_in_poly(self.U, self.V, c["uv"])
            dist = np.minimum(dist, dist_to_poly(self.U, self.V, c["uv"]))
        for (a0, b0, a1, b1) in layout.get("tabs_uv") or []:
            inside &= ~((self.U >= a0) & (self.U <= a1) & (self.V >= b0) & (self.V <= b1))
        self.edge_dist = np.where(inside, dist, -1.0)
        self.pads = pads
        self.nets = sorted({p["net"] for p in pads if p["net"]})
        self.nid = {n: k for k, n in enumerate(self.nets)}
        # owner[类别][层]：网络编号，-1 空，-2 无网络障碍
        self.owner = np.full((4, 2, self.H, self.W), -1, dtype=np.int16)
        self.pad_cells = []
        self.own_pad = np.full((2, self.H, self.W), -1, dtype=np.int16)
        for p in pads:
            nid = self.nid[p["net"]] if p["net"] else -2
            mg, gi0, gj0 = self._pad_raster(p, PAD_GROW)
            m, i0, j0 = self._pad_raster(p, 0.0)
            cells = []
            for L in pad_layers(p):
                view = self.owner[CLS_PAD, L, gi0:gi0 + mg.shape[0], gj0:gj0 + mg.shape[1]]
                view[mg] = nid
                ov = self.own_pad[L, i0:i0 + m.shape[0], j0:j0 + m.shape[1]]
                ov[m] = nid
                ii, jj2 = np.nonzero(m)
                cells += [(L, i0 + a, j0 + b) for a, b in zip(ii, jj2)]
            self.pad_cells.append(cells)
        for h in layout["mount_holes"]:
            self._mark_round(h["uv"][0], h["uv"][1], h["d"] / 2 + 0.1)
        for (u, v) in layout["mousebites_uv"]:
            self._mark_round(u, v, layout["mousebite_d"] / 2 + 0.1)
        for h in layout.get("footprint_npth") or []:
            self._mark_round(h["uv"][0], h["uv"][1], h["d"] / 2 + SLOT_CLEAR - CLEAR_PAD)
        self.any_pad = (self.owner[CLS_PAD] != -1).any(axis=0)
        self.paths = []      # (net, width, [(L,i,j), ...])
        self.vias = []       # (net, i, j)
        self.links = {}      # net → [(焊盘序号a, 焊盘序号b, 路径格)]

    def cell(self, u, v):
        return int(round((v - self.v0) / G)), int(round((u - self.u0) / G))

    def uv(self, i, j):
        return self.u0 + j * G, self.v0 + i * G

    def _pad_raster(self, p, grow=0.0):
        shape, w, h, rot = pad_geometry(p)
        w, h = w + 2 * grow, h + 2 * grow
        cu, cv = p["x"] * MIL, p["y"] * MIL
        r = max(w, h) / 2 + G
        i0, j0 = self.cell(cu - r, cv - r)
        i1, j1 = self.cell(cu + r, cv + r)
        i0, j0, i1, j1 = max(i0, 0), max(j0, 0), min(i1, self.H - 1), min(j1, self.W - 1)
        x0 = self.U[i0:i1 + 1, j0:j1 + 1] - cu
        y0 = self.V[i0:i1 + 1, j0:j1 + 1] - cv
        a = math.radians(-rot)
        x = x0 * math.cos(a) - y0 * math.sin(a)
        y = x0 * math.sin(a) + y0 * math.cos(a)
        if shape in ("RECT", "POLYGON"):
            m = (np.abs(x) <= w / 2) & (np.abs(y) <= h / 2)
        elif w >= h:
            m = np.hypot(np.clip(np.abs(x) - (w - h) / 2, 0, None), y) <= h / 2
        else:
            m = np.hypot(x, np.clip(np.abs(y) - (h - w) / 2, 0, None)) <= w / 2
        if not m.any():
            ci, cj = self.cell(cu, cv)
            m[ci - i0, cj - j0] = True
        return m, i0, j0

    def _mark_round(self, u, v, r):
        ci, cj = self.cell(u, v)
        for di, dj in disc(r):
            i, j = ci + di, cj + dj
            if 0 <= i < self.H and 0 <= j < self.W:
                self.owner[CLS_PAD, :, i, j] = -2

    # ---------------------------------------------------------- 可通行区域

    def maps(self, nid, width, win):
        """窗口内：线中心可走区域 ok[2,h,w]、可放过孔 vok[h,w]。"""
        i0, i1, j0, j1 = win
        own = self.owner[:, :, i0:i1, j0:j1]
        ok = np.ones((2, i1 - i0, j1 - j0), dtype=bool)
        vblock = np.zeros((i1 - i0, j1 - j0), dtype=bool)
        for cls in (CLS_PAD, CLS_SIG, CLS_PWR, CLS_VIA):
            clr = CLEAR if cls in (CLS_SIG, CLS_PWR) else CLEAR_PAD
            for L in (0, 1):
                other = (own[cls, L] != -1) & (own[cls, L] != nid)
                if not other.any():
                    continue
                ok[L] &= ~dilate(other, HALF[cls] + clr + width / 2 + MARGIN)
                vblock |= dilate(other, HALF[cls] + CLEAR_PAD + VIA_D / 2 + MARGIN)
        # 同网络过孔之间也要满足孔距；过孔不压任何焊盘
        vblock |= dilate(own[CLS_VIA, 0] == nid, VIA_HOLE + HOLE_GAP)
        vblock |= dilate(self.any_pad[i0:i1, j0:j1], VIA_D / 2 + 0.05)
        edge = self.edge_dist[i0:i1, j0:j1]
        ok &= edge >= EDGE_CLEAR + width / 2
        # 本网络焊盘铜皮内始终可走
        for L in (0, 1):
            ok[L] |= self.own_pad[L, i0:i1, j0:j1] == nid
        vok = ok[0] & ok[1] & ~vblock & (edge >= EDGE_CLEAR + VIA_D / 2)
        return ok, vok

    def window(self, cells, extra=WINDOW):
        ii = [c[1] for c in cells]
        jj = [c[2] for c in cells]
        m = int(extra / G)
        return (max(0, min(ii) - m), min(self.H, max(ii) + m + 1), max(0, min(jj) - m), min(self.W, max(jj) + m + 1))

    # ---------------------------------------------------------- A*

    def astar(self, ok, vok, win, sources, targets, centers):
        i0, i1, j0, j1 = win
        h, w = i1 - i0, j1 - j0
        hw = h * w
        okb = ok.tobytes()
        vb = vok.tobytes()
        cen = [(ci - i0, cj - j0) for ci, cj in centers]

        def hcost(idx):
            i, j = divmod(idx % hw, w)
            best = 1e18
            for ci, cj in cen:
                di, dj = abs(i - ci), abs(j - cj)
                best = min(best, max(di, dj) + (SQ2 - 1) * min(di, dj))
            return best * H_WEIGHT

        gbest, came, heap = {}, {}, []
        for (L, i, j) in sources:
            if not (i0 <= i < i1 and j0 <= j < j1):
                continue
            s = L * hw + (i - i0) * w + (j - j0)
            if not okb[s]:
                continue
            gbest[s] = 0.0
            came[s] = -1
            heapq.heappush(heap, (hcost(s), 0.0, s))
        expanded = 0
        while heap:
            f, gc, cur = heapq.heappop(heap)
            if gc > gbest.get(cur, 1e18) + 1e-9:
                continue
            if cur in targets:
                path = [cur]
                while came[path[-1]] != -1:
                    path.append(came[path[-1]])
                out = []
                for idx in reversed(path):
                    L, rem = divmod(idx, hw)
                    i, j = divmod(rem, w)
                    out.append((L, i + i0, j + j0))
                return out, expanded
            expanded += 1
            if expanded > MAX_EXPAND:
                return None, expanded
            L, rem = divmod(cur, hw)
            i, j = divmod(rem, w)
            prev = came[cur]
            pdi = pdj = None
            if prev >= 0 and prev // hw == L:
                pr = prev % hw
                pdi, pdj = i - pr // w, j - pr % w
            base = L * hw
            mult = 1.0 if L == 0 else BOTTOM_PENALTY
            for di, dj, c in MOVES:
                ni, nj = i + di, j + dj
                if ni < 0 or nj < 0 or ni >= h or nj >= w:
                    continue
                nidx = base + ni * w + nj
                if not okb[nidx]:
                    continue
                if di and dj and not (okb[base + ni * w + j] and okb[base + i * w + nj]):
                    continue
                ng = gc + c * mult + (TURN_COST if pdi is not None and (pdi, pdj) != (di, dj) else 0.0)
                if ng < gbest.get(nidx, 1e18):
                    gbest[nidx] = ng
                    came[nidx] = cur
                    heapq.heappush(heap, (ng + hcost(nidx), ng, nidx))
            if vb[rem]:
                nidx = (1 - L) * hw + rem
                ng = gc + VIA_COST
                if okb[nidx] and ng < gbest.get(nidx, 1e18):
                    gbest[nidx] = ng
                    came[nidx] = cur
                    heapq.heappush(heap, (ng + hcost(nidx), ng, nidx))
        return None, expanded

    def _commit(self, net, width, path):
        nid = self.nid[net]
        cls = CLS_PWR if width >= W_PWR - 1e-9 else CLS_SIG
        for (L, i, j) in path:
            if self.owner[cls, L, i, j] == -1:
                self.owner[cls, L, i, j] = nid
        for a, b in zip(path, path[1:]):
            if a[0] != b[0]:
                self.owner[CLS_VIA, :, b[1], b[2]] = nid
                self.vias.append((net, b[1], b[2]))
        self.paths.append((net, width, path))

    def _connect(self, net, width, tree, targets_by_pad, centers):
        """在窗口内寻路；失败时扩大窗口重试。返回 (路径, 到达的焊盘序号)。"""
        nid = self.nid[net]
        all_cells = list(tree) + [c for cells in targets_by_pad.values() for c in cells]
        for extra in (WINDOW, 80.0, 400.0):
            win = self.window(all_cells, extra)
            ok, vok = self.maps(nid, width, win)
            i0, i1, j0, j1 = win
            h, w = i1 - i0, j1 - j0
            targets = {}
            for k, cells in targets_by_pad.items():
                for (L, i, j) in cells:
                    if i0 <= i < i1 and j0 <= j < j1 and ok[L, i - i0, j - j0]:
                        targets[L * h * w + (i - i0) * w + (j - j0)] = k
            if not targets:
                continue
            path, _ = self.astar(ok, vok, win, tree, targets, centers)
            if path:
                last = path[-1]
                key = last[0] * h * w + (last[1] - i0) * w + (last[2] - j0)
                return path, targets[key]
        return None, None

    def _groups(self, net, idxs):
        """按预连线合并焊盘：返回 {组号: 格子集合}，组号取组内首个焊盘序号。"""
        parent = {k: k for k in idxs}

        def find(k):
            while parent[k] != k:
                parent[k] = parent[parent[k]]
                k = parent[k]
            return k
        extra = {}
        for ka, kb, cells in self.links.get(net, []):
            ra, rb = find(ka), find(kb)
            parent[rb] = ra
            extra.setdefault(ka, []).extend(cells)
        groups = {}
        for k in idxs:
            groups.setdefault(find(k), set()).update(self.pad_cells[k])
        for k, cells in extra.items():
            groups[find(k)].update(cells)
        return groups

    def preroute(self, pairs, log):
        ok_all = True
        for pr in pairs:
            net = pr["net"]
            ka = next(k for k, p in enumerate(self.pads) if p["ref"] == pr["a"][0] and p["n"] == pr["a"][1])
            kb = next(k for k, p in enumerate(self.pads) if p["ref"] == pr["b"][0] and p["n"] == pr["b"][1])
            if self.pads[ka]["net"] != net or self.pads[kb]["net"] != net:
                raise ValueError(f"预连线网络不符：{pr}")
            base_w = W_PWR if net in POWER_NETS else W_SIG
            path = None
            centers = [self.cell(self.pads[kb]["x"] * MIL, self.pads[kb]["y"] * MIL)]
            for width in ([base_w, W_SIG] if base_w > W_SIG else [W_SIG]):
                path, _ = self._connect(net, width, set(self.pad_cells[ka]), {kb: self.pad_cells[kb]}, centers)
                if path:
                    break
            if not path:
                log.append(f"预连线失败：{pr}")
                ok_all = False
                continue
            self._commit(net, width, path)
            self.links.setdefault(net, []).append((ka, kb, list(path)))
        return ok_all

    def route_net(self, net, log):
        idxs = [k for k, p in enumerate(self.pads) if p["net"] == net]
        if len(idxs) < 2:
            return True
        base_w = W_PWR if net in POWER_NETS else W_SIG
        groups = self._groups(net, idxs)
        first = next(iter(groups))
        tree = set(groups.pop(first))
        remaining = groups
        while remaining:
            centers = []
            for cells in remaining.values():
                c = next(iter(cells))
                centers.append((c[1], c[2]))
            path, k, width = None, None, base_w
            for width in ([base_w, W_SIG] if base_w > W_SIG else [W_SIG]):
                path, k = self._connect(net, width, tree, remaining, centers)
                if path:
                    break
            if not path:
                names = ", ".join(f"{self.pads[k]['ref']}.{self.pads[k]['n']}" for k in remaining)
                log.append(f"{net}: 无法连到 {names}")
                return False
            self._commit(net, width, path)
            tree.update(path)
            tree.update(remaining.pop(k))
        return True

    def unroute_all(self):
        self.owner[CLS_SIG:] = -1
        self.paths, self.vias, self.links = [], [], {}

    def segments(self):
        lines = []
        for net, width, path in self.paths:
            run = [path[0]]
            for a, b in zip(path, path[1:]):
                if a[0] != b[0]:
                    lines += self._compress(net, width, run)
                    run = [b]
                else:
                    run.append(b)
            lines += self._compress(net, width, run)
        vias = [(net, *self.uv(i, j)) for net, i, j in self.vias]
        return lines, vias

    def _compress(self, net, width, run):
        if len(run) < 2:
            return []
        L = run[0][0]
        out = []
        start = run[0]
        d0 = (run[1][1] - run[0][1], run[1][2] - run[0][2])
        for k in range(1, len(run) - 1):
            d = (run[k + 1][1] - run[k][1], run[k + 1][2] - run[k][2])
            if d != d0:
                out.append((net, L, width, *self.uv(start[1], start[2]), *self.uv(run[k][1], run[k][2])))
                start = run[k]
                d0 = d
        out.append((net, L, width, *self.uv(start[1], start[2]), *self.uv(run[-1][1], run[-1][2])))
        return out


def route(layout, pads, passes=4, progress=print):
    """返回 (lines, vias, report, router)。lines: (net, layer0/1, width, u1, v1, u2, v2) 毫米。"""
    r = Router(layout, pads)
    sizes = {}
    for n in r.nets:
        ps = [p for p in pads if p["net"] == n]
        us = [p["x"] for p in ps]
        vs = [p["y"] for p in ps]
        sizes[n] = (max(us) - min(us) + max(vs) - min(vs)) * MIL * (1 + 0.15 * len(ps))
    first = [n for n in PRIORITY if n in r.nets]
    # 后台会话无法计算覆铜填充，地网络与其他网络一样用导线完整连通，放在最后布
    order = first + sorted([n for n in r.nets if n != "GND" and n not in first], key=lambda n: sizes[n])
    if "GND" in r.nets:
        order.append("GND")
    log, warnings, failed = [], [], []
    for attempt in range(passes):
        log.append(f"第 {attempt + 1} 轮")
        failed = []
        if not r.preroute(layout.get("prerouted_pairs") or [], log):
            failed.append("预连线")
        for n in order:
            if not r.route_net(n, log):
                failed.append(n)
            progress(f"  {n}: {'失败' if n in failed else '完成'}")
        if not failed:
            break
        r.unroute_all()
        order = failed + [n for n in order if n not in failed and n != "GND"] + (["GND"] if "GND" not in failed and "GND" in r.nets else [])
    lines, vias = r.segments()
    widths = {}
    for net, L, w, *_ in lines:
        widths.setdefault(net, set()).add(round(w, 2))
    report = {"rules_mm": {"grid": G, "signal": W_SIG, "power": W_PWR, "clearance_track": CLEAR,
                           "clearance_pad_via": CLEAR_PAD, "slot": SLOT_CLEAR, "via": [VIA_D, VIA_HOLE],
                           "edge": EDGE_CLEAR},
              "nets": len(r.nets), "failed": failed, "warnings": warnings, "lines": len(lines), "vias": len(vias),
              "power_widths": {n: sorted(v) for n, v in widths.items() if n in POWER_NETS}, "log": log[-60:]}
    return lines, vias, report, r


def draw(r, lines, vias, path):
    from PIL import Image, ImageDraw
    scale = 6
    W, H = int(r.W * G * scale) + 1, int(r.H * G * scale) + 1
    img = Image.new("RGB", (W, H), "white")
    dr = ImageDraw.Draw(img)

    def P(u, v):
        return ((u - r.u0) * scale, H - (v - r.v0) * scale)
    ii, jj = np.nonzero(r.edge_dist >= 0)
    for i, j in zip(ii[::9], jj[::9]):
        dr.point(P(*r.uv(i, j)), fill=(222, 236, 226))
    for p in r.pads:
        x, y = P(p["x"] * MIL, p["y"] * MIL)
        dr.rectangle([x - 2, y - 2, x + 2, y + 2], fill=(200, 140, 40))
    for net, L, w, u1, v1, u2, v2 in lines:
        dr.line([P(u1, v1), P(u2, v2)], fill=(210, 40, 40) if L == 0 else (40, 70, 210), width=max(1, int(w * scale)))
    for net, u, v in vias:
        x, y = P(u, v)
        dr.ellipse([x - 3, y - 3, x + 3, y + 3], outline=(0, 0, 0))
    img.save(path)
