# -*- coding: utf-8 -*-
"""
Mk launcher — лаунчер Minecraft на Python (PyQt6)
• Список версий и снапшотов берётся онлайн с серверов Mojang — обновлять лаунчер не нужно
• Java скачивается автоматически (официальный рантайм Mojang)
• Моды с Modrinth (с картинками) ставятся прямо в лаунчере, вместе с зависимостями
• Папку игры можно менять в настройках
• При первом запуске создаётся ярлык на рабочем столе
"""
import sys
import os
import re
import json
import uuid
import hashlib
import subprocess
import threading
import traceback
from pathlib import Path

import requests
import minecraft_launcher_lib as mll

from PyQt6.QtCore import (Qt, QThread, QTimer, QRectF, QPointF, QUrl, pyqtSignal)
from PyQt6.QtGui import (QPainter, QColor, QPixmap, QImage, QPainterPath, QPen, QFont,
                         QLinearGradient, QRadialGradient, QPolygonF, QIcon,
                         QDesktopServices)
from PyQt6.QtWidgets import (QApplication, QWidget, QFrame, QVBoxLayout, QHBoxLayout,
                             QPushButton, QLabel, QLineEdit, QComboBox, QProgressBar,
                             QStackedWidget, QScrollArea, QSlider, QFileDialog,
                             QAbstractButton, QSizeGrip, QStyledItemDelegate,
                             QSizePolicy, QMessageBox)

APP_NAME = "Mk launcher"
APP_VERSION = "1.0"
APP_DIR = (Path(os.getenv("APPDATA")) if os.getenv("APPDATA") else Path.home() / ".config") / "MkLauncher"
CACHE_DIR = APP_DIR / "cache"
ICON_ICO = APP_DIR / "icon.ico"
ICON_PNG = APP_DIR / "icon.png"
ARROW_PNG = APP_DIR / "arrow.png"
MODS_DB = APP_DIR / "mods.json"
CONFIG_FILE = APP_DIR / "config.json"

API = "https://api.modrinth.com/v2"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = "MkLauncher/1.0 (minecraft launcher)"

ACCENT = "#30D158"
MUTED = "#8FA39A"
TEXT = "#F2F6F4"

# ───────────────────────────── конфиг ─────────────────────────────


class Config:
    DEFAULTS = {
        "username": "Player",
        "game_dir": "",
        "ram": 4.0,
        "vtype": "release",
        "version": "",
        "loader": "Vanilla",
        "close_on_launch": False,
        "first_run": True,
    }

    def __init__(self):
        self.data = dict(self.DEFAULTS)
        try:
            self.data.update(json.loads(CONFIG_FILE.read_text(encoding="utf-8")))
        except Exception:
            pass
        if not self.data["game_dir"]:
            self.data["game_dir"] = str(mll.utils.get_minecraft_directory())

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v
        self.save()

    def save(self):
        try:
            APP_DIR.mkdir(parents=True, exist_ok=True)
            CONFIG_FILE.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass


# ───────────────────────────── потоки ─────────────────────────────

_TASKS = set()


class Task(QThread):
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as e:
            self.failed.emit(str(e) or e.__class__.__name__)


def run_async(fn, args=(), done=None, fail=None):
    t = Task(fn, args)
    if done:
        t.done.connect(done)
    if fail:
        t.failed.connect(fail)
    _TASKS.add(t)
    t.finished.connect(lambda: _TASKS.discard(t))
    t.start()
    return t


# ───────────────────────────── логотип и иконки ─────────────────────────────


def draw_logo(p: QPainter, x, y, s):
    """Якорь на зелёном скруглённом квадрате (плавные градиенты, без зерна)."""
    p.save()
    p.translate(x, y)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    g = QLinearGradient(0, 0, s, s)
    g.setColorAt(0, QColor("#4BE88A"))
    g.setColorAt(1, QColor("#0C9A63"))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(g)
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.225, s * 0.225)
    pen = QPen(QColor("white"), s * 0.07)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    f = lambda a, b: QPointF(a * s, b * s)
    p.drawEllipse(f(0.5, 0.24), s * 0.065, s * 0.065)
    p.drawLine(f(0.5, 0.305), f(0.5, 0.80))
    p.drawLine(f(0.39, 0.42), f(0.61, 0.42))
    p.drawArc(QRectF(0.25 * s, 0.40 * s, 0.5 * s, 0.40 * s), 180 * 16, 180 * 16)
    p.drawLine(f(0.25, 0.60), f(0.19, 0.52))
    p.drawLine(f(0.75, 0.60), f(0.81, 0.52))
    p.restore()


def render_icon(path, size=256):
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    draw_logo(p, 0, 0, size)
    p.end()
    img.save(str(path))
    return img


def app_icon():
    try:
        APP_DIR.mkdir(parents=True, exist_ok=True)
        img = render_icon(ICON_PNG, 256)
        try:
            img.save(str(ICON_ICO))
        except Exception:
            pass
        return QIcon(QPixmap.fromImage(img))
    except Exception:
        return QIcon()


def make_arrow(path):
    img = QImage(24, 24, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#9FB3AA"), 2.6)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawPolyline(QPolygonF([QPointF(6, 9), QPointF(12, 15), QPointF(18, 9)]))
    p.end()
    img.save(str(path))


# ───────────────────────────── стили ─────────────────────────────

QSS = """
* { font-family: "SF Pro Display","Segoe UI Variable Display","Segoe UI","Inter","Helvetica Neue",Arial,sans-serif;
    font-size: 13px; color: @TEXT; outline: 0; }
#root { background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #0F1A16, stop:1 #091015);
        border-radius: 18px; border: 1px solid rgba(255,255,255,0.09); }
#root[max="true"] { border-radius: 0px; }
#sidebar { background: rgba(255,255,255,0.025); border-bottom-left-radius: 17px; }
QLabel { background: transparent; }
QLabel#h1 { font-size: 26px; font-weight: 800; }
QLabel#h2 { font-size: 15px; font-weight: 700; }
QLabel#muted { color: @MUTED; font-size: 12px; }
QLabel#cap { color: @MUTED; font-size: 11px; font-weight: 600; }
QLabel#title { font-size: 12px; color: @MUTED; font-weight: 600; }

QPushButton#tlr, QPushButton#tly, QPushButton#tlg { border: none; border-radius: 7px;
    min-width: 14px; max-width: 14px; min-height: 14px; max-height: 14px; }
QPushButton#tlr { background: #FF5F57; } QPushButton#tlr:hover { background: #FF8A84; }
QPushButton#tly { background: #FEBC2E; } QPushButton#tly:hover { background: #FFD25F; }
QPushButton#tlg { background: #28C840; } QPushButton#tlg:hover { background: #58E06D; }

QPushButton#nav { text-align: left; padding: 12px 16px; border: none; border-radius: 12px;
    color: @MUTED; font-weight: 600; font-size: 14px; background: transparent; }
QPushButton#nav:hover { background: rgba(255,255,255,0.06); color: @TEXT; }
QPushButton#nav:checked { background: rgba(48,209,88,0.16); color: @ACCENT; }

QPushButton#play { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #44E67B, stop:1 #1DB357);
    color: #04140A; border: none; border-radius: 14px; font-size: 18px; font-weight: 800;
    padding: 0 40px; min-height: 58px; }
QPushButton#play:hover { background: qlineargradient(x1:0,y1:0,x2:0,y2:1, stop:0 #5CF08D, stop:1 #26C464); }
QPushButton#play:pressed { background: #17A04D; }
QPushButton#play:disabled { background: rgba(255,255,255,0.10); color: @MUTED; }

QPushButton#ghost { background: rgba(255,255,255,0.07); border: none; border-radius: 10px;
    padding: 9px 16px; font-weight: 600; }
QPushButton#ghost:hover { background: rgba(255,255,255,0.12); }
QPushButton#ghost:disabled { color: @MUTED; }
QPushButton#install { background: @ACCENT; color: #04140A; border: none; border-radius: 10px;
    padding: 9px 20px; font-weight: 700; min-width: 96px; }
QPushButton#install:hover { background: #55E27B; }
QPushButton#install:disabled { background: rgba(255,255,255,0.10); color: @MUTED; }
QPushButton#danger { background: rgba(255,69,58,0.16); color: #FF7A72; border: none;
    border-radius: 10px; padding: 9px 20px; font-weight: 700; min-width: 96px; }
QPushButton#danger:hover { background: rgba(255,69,58,0.26); }

QLineEdit, QComboBox { background: rgba(255,255,255,0.065); border: 1px solid rgba(255,255,255,0.08);
    border-radius: 12px; padding: 9px 14px; min-height: 20px;
    selection-background-color: @ACCENT; selection-color: #04140A; }
QLineEdit:focus, QComboBox:focus { border: 1px solid @ACCENT; }
QComboBox::drop-down { border: none; width: 30px; }
QComboBox::down-arrow { image: url(@ARROW); width: 12px; height: 12px; }
QComboBox QAbstractItemView { background: #121C18; border: 1px solid rgba(255,255,255,0.12);
    border-radius: 10px; padding: 6px; selection-background-color: rgba(48,209,88,0.25);
    selection-color: @TEXT; outline: 0; }
QComboBox QAbstractItemView::item { min-height: 30px; padding-left: 8px; border-radius: 8px; }

QFrame#card { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.07); border-radius: 18px; }
QFrame#modcard { background: rgba(255,255,255,0.045); border: 1px solid rgba(255,255,255,0.07); border-radius: 16px; }
QFrame#modcard:hover { background: rgba(255,255,255,0.07); border: 1px solid rgba(48,209,88,0.35); }
QLabel#modicon { border-radius: 14px; background: qlineargradient(x1:0,y1:0,x2:1,y2:1, stop:0 #1E8F63, stop:1 #0F5E45);
    font-size: 26px; font-weight: 800; color: white; }

QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: rgba(255,255,255,0.18); border-radius: 3px; min-height: 40px; }
QScrollBar::handle:vertical:hover { background: rgba(255,255,255,0.32); }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: none; }

QProgressBar { background: rgba(255,255,255,0.09); border: none; border-radius: 4px;
    min-height: 8px; max-height: 8px; color: transparent; }
QProgressBar::chunk { border-radius: 4px; background: qlineargradient(x1:0,y1:0,x2:1,y2:0, stop:0 #30D158, stop:1 #6BF5AE); }

QSlider::groove:horizontal { height: 6px; background: rgba(255,255,255,0.12); border-radius: 3px; }
QSlider::sub-page:horizontal { background: @ACCENT; border-radius: 3px; }
QSlider::handle:horizontal { width: 20px; height: 20px; margin: -7px 0; border-radius: 10px; background: white; }
"""


def build_qss():
    q = QSS.replace("@ACCENT", ACCENT).replace("@MUTED", MUTED).replace("@TEXT", TEXT)
    return q.replace("@ARROW", str(ARROW_PNG).replace("\\", "/"))


# ───────────────────────────── виджеты ─────────────────────────────


class Toggle(QAbstractButton):
    """Переключатель как в iOS."""

    def __init__(self, checked=False):
        super().__init__()
        self.setCheckable(True)
        self.setChecked(checked)
        self.setFixedSize(48, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(ACCENT) if self.isChecked() else QColor(255, 255, 255, 45))
        p.drawRoundedRect(QRectF(0, 0, 48, 28), 14, 14)
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(22 if self.isChecked() else 2, 2, 24, 24))


class Hero(QWidget):
    """Большая плавная картинка с холмами (без зернистости)."""

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        w, h = self.width(), self.height()
        clip = QPainterPath()
        clip.addRoundedRect(QRectF(0, 0, w, h), 22, 22)
        p.setClipPath(clip)
        g = QLinearGradient(0, 0, 0, h)
        g.setColorAt(0, QColor("#07263A"))
        g.setColorAt(0.5, QColor("#0F7F63"))
        g.setColorAt(1, QColor("#2FDB7F"))
        p.fillRect(self.rect(), g)
        rg = QRadialGradient(w * 0.74, h * 0.30, h * 0.65)
        rg.setColorAt(0, QColor(255, 255, 255, 120))
        rg.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillRect(self.rect(), rg)
        layers = [(0.64, 0.10, 0.0, "#1FA56F"), (0.74, 0.09, 0.35, "#147E52"), (0.86, 0.07, 0.7, "#0B5A3A")]
        for base, amp, shift, col in layers:
            path = QPainterPath()
            path.moveTo(0, h)
            path.lineTo(0, h * (base + amp * 0.3))
            path.cubicTo(w * (0.22 + shift * 0.1), h * (base - amp), w * (0.42 + shift * 0.1), h * (base + amp),
                         w * 0.66, h * (base - amp * 0.2))
            path.cubicTo(w * 0.82, h * (base - amp * 0.9), w * 0.93, h * (base + amp * 0.3), w, h * (base - amp * 0.4))
            path.lineTo(w, h)
            path.closeSubpath()
            p.fillPath(path, QColor(col))
        draw_logo(p, 36, 34, 74)
        p.setPen(QColor("white"))
        f = QFont("Segoe UI Variable Display")
        f.setPixelSize(44)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QPointF(128, 78), APP_NAME)
        f.setPixelSize(15)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(255, 255, 255, 200))
        p.drawText(QPointF(130, 106), "Minecraft: Java Edition")


def style_combo(cb: QComboBox):
    cb.setItemDelegate(QStyledItemDelegate())
    cb.setMaxVisibleItems(12)
    try:
        win = cb.view().window()
        win.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        win.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        win.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
    except Exception:
        pass
    cb.setCursor(Qt.CursorShape.PointingHandCursor)


def labeled(caption, widget):
    box = QVBoxLayout()
    box.setSpacing(6)
    lab = QLabel(caption.upper())
    lab.setObjectName("cap")
    box.addWidget(lab)
    box.addWidget(widget)
    return box


def fmt_num(n):
    n = int(n)
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


def rounded_pixmap(data, size, radius):
    pm = QPixmap()
    if not pm.loadFromData(data):
        return None
    pm = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((size - pm.width()) // 2, (size - pm.height()) // 2, pm)
    p.end()
    return out


def open_folder(path):
    Path(path).mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


# ───────────────────────────── ярлык на рабочем столе ─────────────────────────────


def _psq(s):
    return str(s).replace("'", "''")


def create_shortcut():
    try:
        frozen = getattr(sys, "frozen", False)
        if sys.platform == "win32":
            if frozen:
                target, args, icon = sys.executable, "", sys.executable
                workdir = str(Path(sys.executable).parent)
            else:
                pyw = Path(sys.executable).with_name("pythonw.exe")
                target = str(pyw if pyw.exists() else sys.executable)
                script = Path(sys.argv[0]).resolve()
                args, workdir = f'"{script}"', str(script.parent)
                icon = str(ICON_ICO) if ICON_ICO.exists() else target
            ps = (
                "$d=[Environment]::GetFolderPath('Desktop');"
                "$s=(New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path $d 'Mk launcher.lnk'));"
                f"$s.TargetPath='{_psq(target)}';$s.Arguments='{_psq(args)}';"
                f"$s.WorkingDirectory='{_psq(workdir)}';$s.IconLocation='{_psq(icon)},0';"
                "$s.Description='Mk launcher';$s.Save()"
            )
            subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
                           creationflags=0x08000000, timeout=30)
            return True
        if sys.platform.startswith("linux"):
            desktop = Path.home() / "Desktop"
            desktop.mkdir(exist_ok=True)
            exe = sys.executable if frozen else f'{sys.executable} "{Path(sys.argv[0]).resolve()}"'
            f = desktop / "mk-launcher.desktop"
            f.write_text(f"[Desktop Entry]\nType=Application\nName={APP_NAME}\nExec={exe}\n"
                         f"Icon={ICON_PNG}\nTerminal=false\nCategories=Game;\n", encoding="utf-8")
            f.chmod(0o755)
            return True
    except Exception:
        pass
    return False


# ───────────────────────────── запуск игры ─────────────────────────────


def offline_uuid(name):
    h = hashlib.md5(("OfflinePlayer:" + name).encode()).digest()
    return str(uuid.UUID(bytes=h, version=3))


def find_loader_id(game_dir, loader, mc):
    for v in mll.utils.get_installed_versions(game_dir):
        i = v["id"]
        if loader == "Fabric" and i.startswith("fabric-loader-") and i.endswith("-" + mc):
            return i
        if loader == "Quilt" and i.startswith("quilt-loader-") and i.endswith("-" + mc):
            return i
        if loader == "Forge" and "forge" in i.lower() and i.startswith(mc):
            return i
    return None


class LaunchWorker(QThread):
    status = pyqtSignal(str)
    progress = pyqtSignal(int)
    maximum = pyqtSignal(int)
    ok = pyqtSignal()
    fail = pyqtSignal(str)

    def __init__(self, game_dir, version, loader, username, ram):
        super().__init__()
        self.game_dir, self.version, self.loader = game_dir, version, loader
        self.username, self.ram = username, ram

    def run(self):
        try:
            self._run()
        except Exception as e:
            try:
                APP_DIR.mkdir(parents=True, exist_ok=True)
                (APP_DIR / "error.log").write_text(traceback.format_exc(), encoding="utf-8")
            except Exception:
                pass
            self.fail.emit(str(e) or e.__class__.__name__)

    def _java(self, mc, d, cb):
        try:
            info = mll.runtime.get_version_runtime_information(mc, d)
            name = info["name"] if info else "jre-legacy"
            path = mll.runtime.get_executable_path(name, d)
            if not path:
                self.status.emit("Скачивание Java…")
                mll.runtime.install_jvm_runtime(name, d, callback=cb)
                path = mll.runtime.get_executable_path(name, d)
            if path and sys.platform == "win32":
                w = Path(path).with_name("javaw.exe")
                if w.exists():
                    path = str(w)
            return path
        except Exception:
            return None

    def _run(self):
        d, mc, loader = self.game_dir, self.version, self.loader
        Path(d).mkdir(parents=True, exist_ok=True)
        cb = {"setStatus": lambda t: self.status.emit(str(t)),
              "setProgress": lambda v: self.progress.emit(int(v)),
              "setMax": lambda v: self.maximum.emit(int(v))}
        self.status.emit(f"Подготовка Minecraft {mc}…")
        mll.install.install_minecraft_version(mc, d, callback=cb)
        java = self._java(mc, d, cb)
        launch_id = mc

        if loader == "Fabric":
            self.status.emit("Установка Fabric…")
            if not mll.fabric.is_minecraft_version_supported(mc):
                raise RuntimeError("Fabric не поддерживает эту версию")
            mll.fabric.install_fabric(mc, d, callback=cb, java=java)
            launch_id = find_loader_id(d, loader, mc)
        elif loader == "Quilt":
            self.status.emit("Установка Quilt…")
            if not mll.quilt.is_minecraft_version_supported(mc):
                raise RuntimeError("Quilt не поддерживает эту версию")
            mll.quilt.install_quilt(mc, d, callback=cb, java=java)
            launch_id = find_loader_id(d, loader, mc)
        elif loader == "Forge":
            self.status.emit("Установка Forge…")
            fv = mll.forge.find_forge_version(mc)
            if not fv:
                raise RuntimeError("Для этой версии нет Forge")
            if not mll.forge.supports_automatic_install(fv):
                raise RuntimeError("Эту версию Forge нельзя поставить автоматически")
            mll.forge.install_forge_version(fv, d, callback=cb, java=java)
            launch_id = find_loader_id(d, loader, mc)
        if not launch_id:
            raise RuntimeError("Не удалось найти установленный загрузчик")

        n = int(self.ram * 1024)
        opts = {"username": self.username, "uuid": offline_uuid(self.username), "token": "",
                "jvmArguments": [f"-Xmx{n}M", f"-Xms{min(n, 1024)}M"],
                "launcherName": "MkLauncher", "launcherVersion": APP_VERSION,
                "gameDirectory": d}
        if java:
            opts["executablePath"] = java
        cmd = mll.command.get_minecraft_command(launch_id, d, opts)
        self.status.emit("Запуск игры…")
        APP_DIR.mkdir(parents=True, exist_ok=True)
        log = open(APP_DIR / "game.log", "wb")
        kw = {}
        if sys.platform == "win32":
            kw["creationflags"] = 0x08000000 | 0x00000008 | 0x00000200
        else:
            kw["start_new_session"] = True
        subprocess.Popen(cmd, cwd=d, stdout=log, stderr=subprocess.STDOUT, **kw)
        self.ok.emit()


# ───────────────────────────── Modrinth ─────────────────────────────

_db_lock = threading.Lock()


def db_load():
    try:
        return json.loads(MODS_DB.read_text(encoding="utf-8"))
    except Exception:
        return {}


def db_save(db):
    APP_DIR.mkdir(parents=True, exist_ok=True)
    MODS_DB.write_text(json.dumps(db, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_image(url):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    f = CACHE_DIR / hashlib.sha1(url.encode()).hexdigest()
    if f.exists():
        return f.read_bytes()
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    f.write_bytes(r.content)
    return r.content


def modrinth_search(query, mc, loader, index, offset):
    facets = [["project_type:mod"], [f"versions:{mc}"], [f"categories:{loader.lower()}"]]
    r = SESSION.get(API + "/search", params={"query": query, "facets": json.dumps(facets), "index": index,
                                             "limit": 20, "offset": offset}, timeout=25)
    r.raise_for_status()
    return r.json()


def install_mod(project_id, mc, loader, mods_dir, title="", depth=0, seen=None):
    seen = seen if seen is not None else set()
    if project_id in seen:
        return []
    seen.add(project_id)
    r = SESSION.get(f"{API}/project/{project_id}/version", timeout=25,
                    params={"game_versions": json.dumps([mc]), "loaders": json.dumps([loader.lower()])})
    r.raise_for_status()
    versions = r.json()
    if not versions:
        raise RuntimeError(f"Нет версии для {mc} / {loader}")
    v = versions[0]
    fl = next((x for x in v["files"] if x.get("primary")), v["files"][0])
    mods_dir = Path(mods_dir)
    mods_dir.mkdir(parents=True, exist_ok=True)
    dest = mods_dir / fl["filename"]
    with SESSION.get(fl["url"], stream=True, timeout=60) as resp:
        resp.raise_for_status()
        with open(dest, "wb") as out:
            for chunk in resp.iter_content(1 << 16):
                out.write(chunk)
    with _db_lock:
        db = db_load()
        db[project_id] = {"title": title or fl["filename"], "file": str(dest)}
        db_save(db)
    done = [title or fl["filename"]]
    for dep in v.get("dependencies", []):
        if dep.get("dependency_type") == "required" and dep.get("project_id") and depth < 3:
            try:
                done += install_mod(dep["project_id"], mc, loader, mods_dir, "", depth + 1, seen)
            except Exception:
                pass
    return done


def remove_mod(project_id):
    with _db_lock:
        db = db_load()
        e = db.pop(project_id, None)
        db_save(db)
    if e:
        Path(e["file"]).unlink(missing_ok=True)


def mod_installed(project_id):
    e = db_load().get(project_id)
    return bool(e and Path(e["file"]).exists())


class ModCard(QFrame):
    def __init__(self, hit, page):
        super().__init__()
        self.setObjectName("modcard")
        self.hit, self.page = hit, page
        self.pid = hit["project_id"]
        self.installed = mod_installed(self.pid)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(16)
        self.icon = QLabel((hit["title"][:1] or "M").upper())
        self.icon.setObjectName("modicon")
        self.icon.setFixedSize(68, 68)
        self.icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.icon)
        col = QVBoxLayout()
        col.setSpacing(3)
        t = QLabel(hit["title"])
        t.setObjectName("h2")
        meta = QLabel(f'от {hit.get("author", "?")}  ·  ⬇ {fmt_num(hit.get("downloads", 0))}  ·  ♥ {fmt_num(hit.get("follows", 0))}')
        meta.setObjectName("muted")
        desc = hit.get("description", "")
        d = QLabel(desc if len(desc) < 150 else desc[:147] + "…")
        d.setObjectName("muted")
        d.setWordWrap(True)
        for w in (t, meta, d):
            col.addWidget(w)
        lay.addLayout(col, 1)
        self.btn = QPushButton()
        self.btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn.clicked.connect(self.on_click)
        lay.addWidget(self.btn, 0, Qt.AlignmentFlag.AlignVCenter)
        self.refresh()
        url = hit.get("icon_url")
        if url:
            run_async(fetch_image, (url,), self.set_icon)

    def set_icon(self, data):
        pm = rounded_pixmap(data, 68, 14)
        if pm:
            self.icon.setStyleSheet("background: transparent;")
            self.icon.setText("")
            self.icon.setPixmap(pm)

    def refresh(self):
        self.btn.setEnabled(True)
        if self.installed:
            self.btn.setText("Удалить")
            self.btn.setObjectName("danger")
        else:
            self.btn.setText("Установить")
            self.btn.setObjectName("install")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)

    def on_click(self):
        if self.installed:
            remove_mod(self.pid)
            self.installed = False
            self.refresh()
            return
        self.btn.setEnabled(False)
        self.btn.setText("Установка…")
        run_async(install_mod, (self.pid, self.page.mc(), self.page.loader(), self.page.mods_dir(), self.hit["title"]),
                  self.on_done, self.on_fail)

    def on_done(self, res):
        self.installed = True
        self.refresh()
        if len(res) > 1:
            self.btn.setToolTip("Также установлены зависимости: " + ", ".join(res[1:]))

    def on_fail(self, err):
        self.btn.setText("Ошибка")
        self.btn.setToolTip(err)
        self.btn.setEnabled(True)
        self.btn.setObjectName("install")
        self.btn.style().unpolish(self.btn)
        self.btn.style().polish(self.btn)


class ModsPage(QWidget):
    LOADERS = ["Fabric", "Quilt", "Forge", "NeoForge"]
    SORTS = [("Популярные", "downloads"), ("Релевантные", "relevance"), ("Новые", "newest"), ("Обновлённые", "updated")]

    def __init__(self, cfg, play):
        super().__init__()
        self.cfg, self.play = cfg, play
        self.gen = 0
        self.offset = 0
        self.more_btn = None
        self.first = True
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 6, 28, 22)
        lay.setSpacing(14)
        h = QLabel("Моды")
        h.setObjectName("h1")
        lay.addWidget(h)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.q = QLineEdit()
        self.q.setPlaceholderText("Поиск модов на Modrinth…")
        self.q.textChanged.connect(lambda: self.timer.start(450))
        self.loader_cb = QComboBox()
        self.loader_cb.addItems(self.LOADERS)
        self.ver_cb = QComboBox()
        self.sort_cb = QComboBox()
        self.sort_cb.addItems([s[0] for s in self.SORTS])
        for cb in (self.loader_cb, self.ver_cb, self.sort_cb):
            style_combo(cb)
            cb.currentIndexChanged.connect(lambda: self.timer.start(150))
        self.ver_cb.setMinimumWidth(110)
        row.addWidget(self.q, 1)
        row.addWidget(self.loader_cb)
        row.addWidget(self.ver_cb)
        row.addWidget(self.sort_cb)
        lay.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.search)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.inner = QWidget()
        self.list = QVBoxLayout(self.inner)
        self.list.setContentsMargins(0, 0, 6, 0)
        self.list.setSpacing(10)
        self.list.addStretch(1)
        self.scroll.setWidget(self.inner)
        lay.addWidget(self.scroll, 1)
        foot = QHBoxLayout()
        self.path_lbl = QLabel()
        self.path_lbl.setObjectName("muted")
        foot.addWidget(self.path_lbl, 1)
        b = QPushButton("Открыть папку модов")
        b.setObjectName("ghost")
        b.clicked.connect(lambda: open_folder(self.mods_dir()))
        foot.addWidget(b)
        lay.addLayout(foot)
        self.update_path()

    # параметры
    def mc(self):
        return self.ver_cb.currentText()

    def loader(self):
        return self.loader_cb.currentText()

    def mods_dir(self):
        return Path(self.cfg["game_dir"]) / "mods"

    def update_path(self):
        self.path_lbl.setText(f"Папка модов: {self.mods_dir()}")

    def on_show(self):
        self.update_path()
        ver = self.play.version_cb.currentText()
        ld = self.play.loader_cb.currentText()
        ld = ld if ld in self.LOADERS else "Fabric"
        rel = [v["id"] for v in self.play.versions if v["type"] == "release"]
        if ver and ver not in rel:
            rel.insert(0, ver)
        changed = self.first or ver != self.mc() or ld != self.loader()
        for cb in (self.ver_cb, self.loader_cb):
            cb.blockSignals(True)
        if [self.ver_cb.itemText(i) for i in range(self.ver_cb.count())] != rel:
            self.ver_cb.clear()
            self.ver_cb.addItems(rel)
        if ver:
            self.ver_cb.setCurrentText(ver)
        self.loader_cb.setCurrentText(ld)
        for cb in (self.ver_cb, self.loader_cb):
            cb.blockSignals(False)
        if changed and self.mc():
            self.first = False
            self.search()

    # поиск
    def clear(self):
        while self.list.count() > 1:
            w = self.list.takeAt(0).widget()
            if w:
                w.deleteLater()
        self.more_btn = None

    def search(self):
        if not self.mc():
            return
        self.gen += 1
        self.offset = 0
        self.clear()
        self.note("Загрузка…")
        self.fetch()

    def note(self, text):
        lab = QLabel(text)
        lab.setObjectName("muted")
        lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lab.setMinimumHeight(80)
        self.list.insertWidget(self.list.count() - 1, lab)

    def fetch(self):
        gen = self.gen
        idx = self.SORTS[self.sort_cb.currentIndex()][1]
        run_async(modrinth_search, (self.q.text().strip(), self.mc(), self.loader(), idx, self.offset),
                  lambda res: self.on_results(gen, res), lambda e: self.on_error(gen, e))

    def drop_notes(self):
        for i in reversed(range(self.list.count() - 1)):
            w = self.list.itemAt(i).widget()
            if isinstance(w, QLabel) or w is self.more_btn:
                self.list.takeAt(i)
                w.deleteLater()
        self.more_btn = None

    def on_results(self, gen, res):
        if gen != self.gen:
            return
        self.drop_notes()
        hits = res.get("hits", [])
        if not hits and self.offset == 0:
            self.note("Ничего не найдено")
            return
        for h in hits:
            self.list.insertWidget(self.list.count() - 1, ModCard(h, self))
        self.offset += len(hits)
        if self.offset < res.get("total_hits", 0):
            self.more_btn = QPushButton("Показать ещё")
            self.more_btn.setObjectName("ghost")
            self.more_btn.clicked.connect(self.load_more)
            self.list.insertWidget(self.list.count() - 1, self.more_btn)

    def load_more(self):
        self.more_btn.setText("Загрузка…")
        self.more_btn.setEnabled(False)
        self.fetch()

    def on_error(self, gen, err):
        if gen != self.gen:
            return
        self.drop_notes()
        self.note(f"Не удалось загрузить: {err}")


# ───────────────────────────── страницы ─────────────────────────────


class PlayPage(QWidget):
    versions_ready = pyqtSignal()
    TYPES = [("Релизы", "release"), ("Снапшоты", "snapshot"), ("Старая бета", "old_beta"), ("Старая альфа", "old_alpha")]
    LOADERS = ["Vanilla", "Fabric", "Quilt", "Forge"]

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        self.versions = []
        self.worker = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 6, 28, 24)
        lay.setSpacing(16)
        self.hero = Hero()
        self.hero.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        lay.addWidget(self.hero, 1)

        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(20, 18, 20, 18)
        cl.setSpacing(14)
        self.status = QLabel("Загрузка списка версий…")
        self.status.setObjectName("muted")
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        cl.addWidget(self.status)
        cl.addWidget(self.bar)

        row = QHBoxLayout()
        row.setSpacing(12)
        self.user = QLineEdit(cfg["username"])
        self.user.setPlaceholderText("Ник")
        self.user.setMaxLength(16)
        self.user.setMinimumWidth(130)
        self.type_cb = QComboBox()
        self.type_cb.addItems([t[0] for t in self.TYPES])
        self.version_cb = QComboBox()
        self.version_cb.setMinimumWidth(150)
        self.loader_cb = QComboBox()
        self.loader_cb.addItems(self.LOADERS)
        for cb in (self.type_cb, self.version_cb, self.loader_cb):
            style_combo(cb)
        tindex = [t[1] for t in self.TYPES].index(cfg["vtype"]) if cfg["vtype"] in [t[1] for t in self.TYPES] else 0
        self.type_cb.setCurrentIndex(tindex)
        self.loader_cb.setCurrentText(cfg["loader"])
        self.type_cb.currentIndexChanged.connect(self.fill_versions)
        self.version_cb.currentIndexChanged.connect(self.save_sel)
        self.loader_cb.currentIndexChanged.connect(self.save_sel)
        self.refresh_btn = QPushButton("↻")
        self.refresh_btn.setObjectName("ghost")
        self.refresh_btn.setToolTip("Обновить список версий")
        self.refresh_btn.setFixedSize(42, 42)
        self.refresh_btn.clicked.connect(self.load_versions)
        row.addLayout(labeled("Ник", self.user))
        row.addLayout(labeled("Тип", self.type_cb))
        vb = QVBoxLayout()
        vb.setSpacing(6)
        cap = QLabel("ВЕРСИЯ")
        cap.setObjectName("cap")
        vb.addWidget(cap)
        vrow = QHBoxLayout()
        vrow.setSpacing(6)
        vrow.addWidget(self.version_cb, 1)
        vrow.addWidget(self.refresh_btn)
        vb.addLayout(vrow)
        row.addLayout(vb, 1)
        row.addLayout(labeled("Загрузчик", self.loader_cb))
        self.play_btn = QPushButton("ИГРАТЬ")
        self.play_btn.setObjectName("play")
        self.play_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.play_btn.clicked.connect(self.start)
        row.addWidget(self.play_btn, 0, Qt.AlignmentFlag.AlignBottom)
        cl.addLayout(row)
        lay.addWidget(card)
        self.load_versions()

    # версии онлайн
    def load_versions(self):
        self.status.setText("Загрузка списка версий…")
        self.refresh_btn.setEnabled(False)
        run_async(self._fetch, (self.cfg["game_dir"],), self.on_versions, self.on_versions_fail)

    @staticmethod
    def _fetch(game_dir):
        try:
            lst = mll.utils.get_version_list()
        except Exception:
            lst = None
        try:
            inst = [v["id"] for v in mll.utils.get_installed_versions(game_dir)]
        except Exception:
            inst = []
        return lst, inst

    def on_versions(self, res):
        lst, inst = res
        self.refresh_btn.setEnabled(True)
        if lst:
            self.versions = [{"id": v["id"], "type": v["type"]} for v in lst]
            self.status.setText(f"Готово к запуску · доступно версий: {len(self.versions)}")
        else:
            self.versions = [{"id": i, "type": "release"} for i in inst]
            self.status.setText("Нет интернета — показаны установленные версии")
        self.fill_versions()
        self.versions_ready.emit()

    def on_versions_fail(self, err):
        self.refresh_btn.setEnabled(True)
        self.status.setText(f"Ошибка загрузки версий: {err}")

    def fill_versions(self):
        t = self.TYPES[self.type_cb.currentIndex()][1]
        ids = [v["id"] for v in self.versions if v["type"] == t]
        self.version_cb.blockSignals(True)
        self.version_cb.clear()
        self.version_cb.addItems(ids)
        if self.cfg["version"] in ids:
            self.version_cb.setCurrentText(self.cfg["version"])
        self.version_cb.blockSignals(False)
        self.save_sel()

    def save_sel(self):
        self.cfg.data["vtype"] = self.TYPES[self.type_cb.currentIndex()][1]
        if self.version_cb.currentText():
            self.cfg.data["version"] = self.version_cb.currentText()
        self.cfg.data["loader"] = self.loader_cb.currentText()
        self.cfg.save()

    # запуск
    def set_busy(self, busy):
        for w in (self.play_btn, self.user, self.type_cb, self.version_cb, self.loader_cb, self.refresh_btn):
            w.setEnabled(not busy)
        self.play_btn.setText("ЗАПУСК…" if busy else "ИГРАТЬ")

    def start(self):
        name = self.user.text().strip()
        ver = self.version_cb.currentText()
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
            self.status.setText("Ник: 3–16 символов, латиница, цифры и _")
            return
        if not ver:
            self.status.setText("Выберите версию")
            return
        self.cfg["username"] = name
        self.set_busy(True)
        self.bar.setRange(0, 0)
        self.worker = LaunchWorker(self.cfg["game_dir"], ver, self.loader_cb.currentText(), name, self.cfg["ram"])
        self.worker.status.connect(self.status.setText)
        self.worker.maximum.connect(self.on_max)
        self.worker.progress.connect(self.bar.setValue)
        self.worker.ok.connect(self.on_ok)
        self.worker.fail.connect(self.on_fail)
        self.worker.start()

    def on_max(self, m):
        self.bar.setRange(0, max(m, 1))

    def on_ok(self):
        self.status.setText("Игра запущена ✓")
        self.bar.setRange(0, 100)
        self.bar.setValue(100)
        self.set_busy(False)
        if self.cfg["close_on_launch"]:
            QTimer.singleShot(2500, self.window().close)

    def on_fail(self, err):
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.set_busy(False)
        self.status.setText(f"Ошибка: {err}")


class SettingsPage(QWidget):
    dir_changed = pyqtSignal()

    def __init__(self, cfg):
        super().__init__()
        self.cfg = cfg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 6, 28, 24)
        lay.setSpacing(14)
        h = QLabel("Настройки")
        h.setObjectName("h1")
        lay.addWidget(h)

        # папка
        c1 = self.card()
        t = QLabel("Расположение файлов игры")
        t.setObjectName("h2")
        c1.layout().addWidget(t)
        r = QHBoxLayout()
        self.dir_edit = QLineEdit(cfg["game_dir"])
        self.dir_edit.setReadOnly(True)
        b1 = QPushButton("Изменить…")
        b1.setObjectName("ghost")
        b1.clicked.connect(self.pick_dir)
        b2 = QPushButton("Открыть")
        b2.setObjectName("ghost")
        b2.clicked.connect(lambda: open_folder(self.cfg["game_dir"]))
        r.addWidget(self.dir_edit, 1)
        r.addWidget(b1)
        r.addWidget(b2)
        c1.layout().addLayout(r)
        hint = QLabel("Версии, библиотеки, Java, моды и миры будут храниться в этой папке.")
        hint.setObjectName("muted")
        c1.layout().addWidget(hint)
        lay.addWidget(c1)

        # память
        c2 = self.card()
        r = QHBoxLayout()
        t = QLabel("Выделенная память (RAM)")
        t.setObjectName("h2")
        self.ram_lbl = QLabel()
        self.ram_lbl.setObjectName("h2")
        self.ram_lbl.setStyleSheet(f"color:{ACCENT}")
        r.addWidget(t, 1)
        r.addWidget(self.ram_lbl)
        c2.layout().addLayout(r)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(2, 32)  # шаг 0.5 ГБ
        self.slider.setValue(int(cfg["ram"] * 2))
        self.slider.valueChanged.connect(self.on_ram)
        c2.layout().addWidget(self.slider)
        self.on_ram(self.slider.value())
        lay.addWidget(c2)

        # переключатель
        c3 = self.card()
        r = QHBoxLayout()
        col = QVBoxLayout()
        a = QLabel("Закрывать лаунчер после запуска игры")
        a.setObjectName("h2")
        col.addWidget(a)
        self.tg = Toggle(cfg["close_on_launch"])
        self.tg.toggled.connect(lambda v: cfg.__setitem__("close_on_launch", bool(v)))
        r.addLayout(col, 1)
        r.addWidget(self.tg)
        c3.layout().addLayout(r)
        lay.addWidget(c3)

        # ярлык
        c4 = self.card()
        r = QHBoxLayout()
        a = QLabel("Ярлык на рабочем столе")
        a.setObjectName("h2")
        b = QPushButton("Создать ярлык")
        b.setObjectName("ghost")
        b.clicked.connect(self.make_shortcut)
        r.addWidget(a, 1)
        r.addWidget(b)
        c4.layout().addLayout(r)
        lay.addWidget(c4)
        lay.addStretch(1)
        info = QLabel(f"{APP_NAME} {APP_VERSION} · Java скачивается автоматически · версии берутся онлайн")
        info.setObjectName("muted")
        lay.addWidget(info)

    def card(self):
        f = QFrame()
        f.setObjectName("card")
        l = QVBoxLayout(f)
        l.setContentsMargins(20, 16, 20, 16)
        l.setSpacing(12)
        return f

    def pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Выберите папку игры", self.cfg["game_dir"])
        if d:
            self.cfg["game_dir"] = str(Path(d))
            self.dir_edit.setText(self.cfg["game_dir"])
            self.dir_changed.emit()

    def on_ram(self, v):
        gb = v / 2
        self.cfg["ram"] = gb
        self.ram_lbl.setText(f"{gb:g} ГБ")

    def make_shortcut(self):
        ok = create_shortcut()
        QMessageBox.information(self, APP_NAME, "Ярлык создан на рабочем столе." if ok else "Не удалось создать ярлык.")


# ───────────────────────────── окно ─────────────────────────────


class TitleBar(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.setFixedHeight(48)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 0, 18, 0)
        lay.setSpacing(8)
        for name, fn in (("tlr", win.close), ("tly", win.showMinimized), ("tlg", win.toggle_max)):
            b = QPushButton()
            b.setObjectName(name)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(fn)
            lay.addWidget(b)
        lay.addStretch(1)
        t = QLabel(APP_NAME)
        t.setObjectName("title")
        lay.addWidget(t)
        lay.addStretch(1)
        sp = QWidget()
        sp.setFixedWidth(66)
        lay.addWidget(sp)

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()

    def mouseDoubleClickEvent(self, e):
        self.win.toggle_max()


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.cfg = Config()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(app_icon())
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(1120, 720)
        self.setMinimumSize(920, 620)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.root = QFrame()
        self.root.setObjectName("root")
        self.root.setProperty("max", False)
        outer.addWidget(self.root)
        v = QVBoxLayout(self.root)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        v.addWidget(TitleBar(self))
        body = QHBoxLayout()
        body.setSpacing(0)
        v.addLayout(body, 1)

        side = QFrame()
        side.setObjectName("sidebar")
        side.setFixedWidth(224)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 16, 14, 16)
        sl.setSpacing(6)
        self.stack = QStackedWidget()
        self.play = PlayPage(self.cfg)
        self.mods = ModsPage(self.cfg, self.play)
        self.settings = SettingsPage(self.cfg)
        self.settings.dir_changed.connect(self.on_dir)
        self.navs = []
        for i, (txt, page) in enumerate((("▶   Играть", self.play), ("✦   Моды", self.mods), ("⚙   Настройки", self.settings))):
            b = QPushButton(txt)
            b.setObjectName("nav")
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, k=i: self.go(k))
            sl.addWidget(b)
            self.navs.append(b)
            self.stack.addWidget(page)
        sl.addStretch(1)
        ver = QLabel(f"{APP_NAME}  v{APP_VERSION}")
        ver.setObjectName("muted")
        ver.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sl.addWidget(ver)
        body.addWidget(side)
        body.addWidget(self.stack, 1)
        self.grip = QSizeGrip(self.root)
        self.grip.setFixedSize(16, 16)
        self.go(0)
        if self.cfg["first_run"]:
            QTimer.singleShot(1500, self.first_run)

    def go(self, i):
        for k, b in enumerate(self.navs):
            b.setChecked(k == i)
        self.stack.setCurrentIndex(i)
        if i == 1:
            self.mods.on_show()

    def on_dir(self):
        self.mods.update_path()
        self.play.load_versions()

    def first_run(self):
        run_async(create_shortcut)
        self.cfg["first_run"] = False

    def toggle_max(self):
        self.showNormal() if self.isMaximized() else self.showMaximized()

    def changeEvent(self, e):
        if hasattr(self, "root"):
            self.root.setProperty("max", self.isMaximized())
            self.root.style().unpolish(self.root)
            self.root.style().polish(self.root)
        super().changeEvent(e)

    def resizeEvent(self, e):
        if hasattr(self, "grip"):
            self.grip.move(self.root.width() - 20, self.root.height() - 20)
        super().resizeEvent(e)


def main():
    if sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mk.launcher.app")
        except Exception:
            pass
    APP_DIR.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setStyle("Fusion")
    make_arrow(ARROW_PNG)
    app.setStyleSheet(build_qss())
    app.setWindowIcon(app_icon())
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()