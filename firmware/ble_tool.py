"""现有飞鼠的蓝牙状态、握持校准及无线升级工具。"""
import argparse
import asyncio
import hashlib
import importlib.metadata
import json
import math
from pathlib import Path
import statistics
import struct
import sys
import time

from bleak import BleakClient
from bleak.backends.device import BLEDevice

HERE = Path(__file__).resolve().parent
SERVICE = "a38b0001-62da-4c13-9f07-908d8b921571"
CONTROL = "a38b0002-62da-4c13-9f07-908d8b921571"
DATA = "a38b0003-62da-4c13-9f07-908d8b921571"
STATUS = "a38b0004-62da-4c13-9f07-908d8b921571"
DETAILS = "a38b0005-62da-4c13-9f07-908d8b921571"
DEFAULT_ADDRESS = "90:DA:72:73:98:25"


def connection(address):
    # Windows可按已知配对地址直接打开设备；不要求正在使用的鼠标重新广播。
    device = BLEDevice(address, "GunMouse SuperMini", None)
    return BleakClient(device, pair=True, timeout=25,
                       winrt={"use_cached_services": False})


async def status(client):
    result = json.loads((await client.read_gatt_char(STATUS)).decode("utf-8"))
    if result.get("project") != "gunmouse":
        raise RuntimeError("设备身份或加密配对状态不符合要求")
    return result


async def wait_for(client, condition, timeout=10):
    started = time.monotonic()
    while time.monotonic() - started < timeout:
        current = await status(client)
        if condition(current):
            return current
        if current["ota"] == 3:
            raise RuntimeError(f"设备已停止升级，错误码{current['error']}；原运行分区保留")
        await asyncio.sleep(.04)
    raise TimeoutError("等待设备处理超时")


async def send(client, text):
    await client.write_gatt_char(CONTROL, text.encode("ascii"), response=True)


def image_elf_hash(payload):
    if (len(payload) < 288 or payload[0] != 0xE9
            or struct.unpack_from("<H", payload, 12)[0] != 9
            or struct.unpack_from("<I", payload, 32)[0] != 0xABCD5432):
        raise ValueError("需要ESP32-S3应用文件，不能使用完整合并镜像或其他板型的文件")
    # 官方应用描述位于24字节镜像头和8字节首段头之后；构建校验值在描述内偏移144。
    identity = payload[176:208]
    if b"GunMouse SuperMini\0" not in payload or identity in (bytes(32), b"\xff" * 32):
        raise ValueError("应用文件缺少飞鼠标识或有效的程序构建校验值")
    return identity.hex()


def image_payload(path):
    payload = path.read_bytes()
    image_elf_hash(payload)
    if len(payload) > 0x140000:
        raise ValueError("应用文件超过当前无线升级分区容量")
    digest = hashlib.sha256(payload).hexdigest()
    manifest_path = path.parent.parent / "build-manifest.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        entry = manifest.get("artifacts", {}).get(path.name)
        if entry and entry["sha256"] != digest:
            raise ValueError("应用文件与构建清单校验值不一致")
    return payload, digest


def verify_running_image(before, after, expected_hash):
    if after["slot"] == before["slot"]:
        raise RuntimeError("重启后仍在旧分区，尚不能确认无线升级成功")
    if after.get("elf") != expected_hash:
        raise RuntimeError("重启后的程序构建校验值与发送文件不一致，尚不能确认无线升级成功")


async def upload(address, path, *, abort_after=None):
    payload, digest = image_payload(path)
    expected_hash = image_elf_hash(payload)
    report = {"设备": address, "文件": str(path), "字节数": len(payload), "SHA256": digest,
              "程序构建SHA256": expected_hash, "蓝牙库版本": importlib.metadata.version("bleak"), "成功": False}
    started = time.monotonic()
    async with connection(address) as client:
        before = await status(client)
        report["更新前"] = before
        await send(client, "ABORT")
        await wait_for(client, lambda s: s["ota"] == 0)
        await send(client, f"BEGIN {len(payload)} {digest}")
        await wait_for(client, lambda s: s["ota"] == 1)
        chunk_size = min(240, max(1, client.mtu_size - 7))
        print(f"已连接，开始无线传输，共{len(payload)}字节，每包{chunk_size}字节", flush=True)
        offset, printed = 0, -1
        try:
            while offset < len(payload):
                for _ in range(8):
                    if offset == len(payload):
                        break
                    chunk = payload[offset:offset + chunk_size]
                    await client.write_gatt_char(DATA, struct.pack("<I", offset) + chunk, response=True)
                    offset += len(chunk)
                await wait_for(client, lambda s: s["received"] >= offset)
                progress = offset * 100 // len(payload)
                if progress // 10 != printed:
                    printed = progress // 10
                    print(f"已传输{progress}%", flush=True)
                if abort_after and offset >= abort_after:
                    await send(client, "ABORT")
                    after = await wait_for(client, lambda s: s["ota"] == 0)
                    if after["slot"] != before["slot"]:
                        raise RuntimeError("中止后运行分区意外改变")
                    report.update({"中止验证": after, "成功": True})
                    return report
            await send(client, "END")
            report["写入校验"] = await wait_for(client, lambda s: s["ota"] == 2, timeout=15)
        except BaseException:
            if client.is_connected:
                try:
                    await send(client, "ABORT")
                except Exception:
                    pass
            raise
    print("设备已完成校验，等待重启并确认新分区", flush=True)
    await asyncio.sleep(3)
    error = None
    for attempt in range(3):
        try:
            async with connection(address) as client:
                after = await wait_for(client, lambda s: s["diag"].get("fw", 0) >= 3, timeout=10)
                verify_running_image(before, after, expected_hash)
                report["更新后"] = after
                report["成功"] = True
                report["秒数"] = round(time.monotonic() - started, 2)
                print(f"无线升级完成，当前分区{after['slot']}", flush=True)
                return report
        except Exception as exc:
            error = exc
            if attempt < 2:
                await asyncio.sleep(2)
    raise RuntimeError(f"传输校验完成，但重新连接核对未完成：{error}")


def fit_horizontal_trace(segments):
    segments = [(x, y) for x, y in segments if math.isfinite(x) and math.isfinite(y)
                and abs(x) >= 1 and abs(x) + abs(y) >= 2]
    positive = sum(x for x, _ in segments if x > 0)
    negative = -sum(x for x, _ in segments if x < 0)
    xx = sum(x*x for x, _ in segments)
    xy = sum(x*y for x, y in segments)
    yy = sum(y*y for _, y in segments)
    if len(segments) < 20 or min(positive, negative) < 20 or xx < 400:
        raise ValueError("有效的触摸左右往返轨迹不足，保留原校准值")
    slope = xy / xx
    residual = max(0, yy - xy*xy/xx)
    if abs(slope) > 2 or residual > .20 * (xx + yy):
        raise ValueError("轨迹方向不一致或接近竖直，保留原校准值")
    return {"斜率": slope, "角度": math.degrees(math.atan(slope)), "有效段数": len(segments),
            "向右像素": positive, "向左像素": negative}


async def horizontal(client):
    import ctypes
    if sys.platform != "win32":
        raise RuntimeError("屏幕轨迹校准使用Windows鼠标坐标，请在电脑端运行")
    before = await status(client)
    d = before["diag"]
    if "invx" not in d or "invy" not in d:
        raise RuntimeError("请先升级到支持屏幕轨迹校准的3.1版固件")
    class Point(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    user32 = ctypes.windll.user32
    point = Point()
    x0, y0 = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
    x1, y1 = x0 + user32.GetSystemMetrics(78), y0 + user32.GetSystemMetrics(79)
    def position():
        if not user32.GetCursorPos(ctypes.byref(point)):
            raise OSError("无法读取屏幕光标位置")
        return point.x, point.y
    def inside(p):
        return x0 + 8 < p[0] < x1 - 8 and y0 + 8 < p[1] < y1 - 8
    input("把光标放在屏幕中间，准备摸住触摸片并水平左右小幅往返，其他鼠标保持不动。准备好按回车：")
    print("开始采样8秒：保持正常握姿、摸住触摸片，光标不要碰到屏幕边缘。", flush=True)
    previous, previous_touch = position(), False
    segments = []
    started = time.monotonic()
    while time.monotonic() - started < 8:
        current = await status(client)
        here = position()
        touched = bool(current["diag"].get("touch"))
        if time.monotonic() - started > .5 and touched and previous_touch and inside(previous) and inside(here):
            segments.append((here[0] - previous[0], here[1] - previous[1]))
        previous, previous_touch = here, touched
        await asyncio.sleep(.015)
    fit = fit_horizontal_trace(segments)
    sign = -1 if bool(d["invx"]) != bool(d["invy"]) else 1
    correction = d["cross"] + fit["斜率"] * sign
    if abs(correction) > 2:
        raise ValueError("所需校正量过大，保留原值，请检查握姿及安装方向")
    await send(client, f"CMD hcross {correction:.6f}")
    after = await wait_for(client, lambda s: abs(s["diag"]["cross"] - correction) < .00002)
    print(f"测得屏幕轨迹偏斜{fit['角度']:+.1f}度，校正已保存；请再试一次左右移动。", flush=True)
    return {"修改前": before, "屏幕轨迹": fit, "修改后": after,
            "范围": "全局光标轨迹，需保持其他鼠标不动；修正后的实际手感仍需试用"}


async def sample_touch(client, seconds=2):
    samples = []
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        current = await status(client)
        samples.append(current["diag"])
        await asyncio.sleep(.04)
    return samples


async def calibrate_touch(client):
    input("正常握住装置但别碰触摸片，准备好后按回车：")
    await send(client, "CMD tcal")
    await asyncio.sleep(.6)
    await wait_for(client, lambda s: s["diag"].get("ready") == 1)
    released = await sample_touch(client)
    input("保持同样握姿，正常摸住触摸片，准备好后按回车：")
    touched = await sample_touch(client)
    base = statistics.median(s["base"] for s in released)
    high = max(s["raw"] for s in released)
    low = min(s["raw"] for s in touched)
    noise = max(s["noise"] for s in released)
    gap = low - high
    if gap < max(base * .005, noise * 6):
        raise RuntimeError("触摸与未触摸读数间隔不足，先检查触摸片位置、绝缘和接线，不能仅靠门限解决")
    press = (high + gap * .35 - base) / base * 100
    release = (high + gap * .15 - base) / base * 100
    if not .05 < release < press < 50:
        raise RuntimeError("测得门限超出有效范围，请检查触摸片并重新校准")
    await send(client, f"CMD tp {press:.4f}")
    await send(client, f"CMD tr {release:.4f}")
    result = await wait_for(client, lambda s: abs(s["diag"].get("tp", 0) - press / 100) < .0002
                            and abs(s["diag"].get("tr", 0) - release / 100) < .0002)
    print(f"触摸校准已保存，触发门限{press:.2f}%，松开门限{release:.2f}%", flush=True)
    return result


def show_status(result):
    d = result["diag"]
    print(f"当前运行分区：{result['slot']}；程序版本：{d.get('build', d.get('fw', '?'))}")
    print(f"触摸：{'已触摸' if d.get('touch') else '未触摸'}；原始读数：{d.get('raw')}；基线：{d.get('base')}")
    print(f"左右串轴校正：{d.get('cross')}；触摸门限：{100*d.get('tp', 0):.2f}% / {100*d.get('tr', 0):.2f}%")
    if 'details' in result:
        extra = result['details']
        joystick = extra['joy']
        print(f"摇杆：{'启用' if joystick['enabled'] else '停用'}；中心有效：{bool(joystick['ready'])}；原始值：{joystick['raw']}；中心：{joystick['center']}；速度：{joystick['speed']}")
        print(f"体感灵敏度：{extra['sens']}；电池连接点采样：{extra['power']['mv']}毫伏；充电状态：未知（硬件未接入反馈）")


async def run(args):
    if args.action == "update":
        return await upload(args.address, args.image.resolve())
    async with connection(args.address) as client:
        if args.action == "horizontal":
            return await horizontal(client)
        if args.action == "touch":
            return await calibrate_touch(client)
        if args.action == "command":
            if not args.command:
                raise ValueError("未指定设置命令")
            await send(client, "CMD " + args.command)
            await asyncio.sleep(.15)
        result = await status(client)
        if client.services.get_characteristic(DETAILS) is not None:
            result['details'] = json.loads((await client.read_gatt_char(DETAILS)).decode('utf-8'))
        show_status(result)
        return result


def main():
    parser = argparse.ArgumentParser(description="枪型飞鼠蓝牙工具：查看状态、校准和无线升级")
    parser.add_argument("--address", default=DEFAULT_ADDRESS, help="已配对飞鼠的蓝牙地址，换板时可指定")
    parser.add_argument("--action", choices=("menu", "status", "update", "horizontal", "touch", "command"), default="menu")
    parser.add_argument("--image", type=Path, default=HERE / "bin/gun_mouse_supermini.ino.bin", help="要升级的应用文件")
    parser.add_argument("--command", help="诊断设置命令")
    parser.add_argument("--report", type=Path, help="保存本次结果记录")
    args = parser.parse_args()
    if args.action == "menu":
        print("枪型飞鼠蓝牙工具\n1. 查看状态\n2. 无线升级当前固件\n3. 校准左右方向\n4. 校准触摸\n0. 退出")
        choice = input("请选择：").strip()
        if choice == "0":
            return
        args.action = {"1": "status", "2": "update", "3": "horizontal", "4": "touch"}.get(choice)
        if not args.action:
            raise SystemExit("选择无效")
    try:
        result = asyncio.run(run(args))
        if args.report:
            args.report.parent.mkdir(parents=True, exist_ok=True)
            args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except KeyboardInterrupt:
        raise SystemExit("操作已取消")
    except Exception as exc:
        raise SystemExit(f"操作未完成：{exc}")


if __name__ == "__main__":
    main()
