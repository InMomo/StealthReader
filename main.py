import sys
import requests
import json
import os
import threading
import time
import keyboard
import ctypes
import traceback
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QMenu,
                             QAction, QDialog, QFormLayout, QLineEdit, QSlider,
                             QSpinBox, QPushButton, QSystemTrayIcon, QStyle,
                             QColorDialog, QCheckBox, QHBoxLayout,
                             QFrame, QTextEdit, QShortcut, QListWidget,
                             QListWidgetItem, QLabel, QFontComboBox, QSizePolicy, QFileDialog)
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal, QObject, QThread, QTimer, QEvent
from PyQt5.QtGui import QFont, QColor, QCursor, QKeySequence, QPainter, QPen, QFontMetrics

# 启用高分屏支持
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)

CONFIG_FILE = "config.json"

DEFAULT_CONFIG = {
    "ip": "http://192.168.1.10:1122",
    "opacity": 0.9,
    "font_size": 14,
    "font_family": "Microsoft YaHei",
    "text_color": "rgba(200, 200, 200, 255)",
    "bg_color": "rgba(30, 30, 30, 200)",
    "boss_key": "Esc",
    "ghost_mode": False,
    "auto_mode": False,
    "antishot_mode": False,
    "window_width": 400,
    "window_height": 300,
    "last_local_file": "",
    "last_local_pos": 0
}

DARK_STYLESHEET = """
    QDialog, QWidget { background-color: #2b2b2b; color: #cccccc; }
    QLineEdit { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 5px; border-radius: 4px; }
    QListWidget { background-color: #333; color: #ddd; border: 1px solid #444; }
    QListWidget::item:selected { background-color: #505050; color: white; }
    QListWidget::item:hover { background-color: #3e3e3e; }
    QPushButton { background-color: #444; color: white; border: 1px solid #555; padding: 5px; border-radius: 4px; }
    QPushButton:hover { background-color: #555; }
    QComboBox { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 5px; }
    QComboBox QAbstractItemView { background-color: #3c3c3c; color: white; selection-background-color: #505050; }
    QLabel { color: #aaa; }
"""


# ================= Windows 防截屏 API 封装 =================
def set_window_protection(hwnd, enable=True):
    try:
        user32 = ctypes.windll.user32
        WDA_NONE = 0x00000000
        WDA_MONITOR = 0x00000001
        WDA_EXCLUDEFROMCAPTURE = 0x00000011  # Win10 2004+

        mode = WDA_EXCLUDEFROMCAPTURE if enable else WDA_NONE
        user32.SetWindowDisplayAffinity(hwnd, mode)
    except Exception as e:
        print(f"防截屏设置失败: {e}")


# ================= 辅助类：绘制背景和角标 =================
class CornerFrame(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.is_auto_mode = False
        self.corner_color = QColor(128, 128, 128, 200)
        self.auto_bg_fill = QColor(0, 0, 0, 2)

    def set_mode(self, auto_mode):
        self.is_auto_mode = auto_mode
        self.update()

    def set_auto_bg_color(self, color):
        self.auto_bg_fill = QColor(color)
        self.auto_bg_fill.setAlpha(2)
        if self.is_auto_mode:
            self.update()

    def set_draw_corners(self, enable):
        self.update()

    def paintEvent(self, event):
        if not self.is_auto_mode:
            super().paintEvent(event)
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), self.auto_bg_fill)

        if self.height() > 20:
            painter.setPen(QPen(self.corner_color, 3))
            w, h = self.width(), self.height()
            length = 15
            painter.drawLine(0, 0, length, 0)
            painter.drawLine(0, 0, 0, length)
            painter.drawLine(w, h, w - length, h)
            painter.drawLine(w, h, w, h - length)


# ================= 独立窗口：书籍选择器 =================
class BookSelector(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window
        self.setWindowTitle("📚 书架")
        self.resize(400, 500)
        self.setStyleSheet(DARK_STYLESHEET)
        self.initUI()
        self.populate_list(self.main_window.books)

    def initUI(self):
        layout = QVBoxLayout()
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索书名或作者...")
        self.search_input.textChanged.connect(self.filter_books)
        top_layout.addWidget(self.search_input)

        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setFixedWidth(60)
        btn_refresh.clicked.connect(self.manual_refresh)
        top_layout.addWidget(btn_refresh)

        layout.addLayout(top_layout)
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

    def manual_refresh(self):
        self.setWindowTitle("📚 书架 (加载中...)")
        self.main_window.fetch_bookshelf_silent()

    def update_data(self, books):
        self.setWindowTitle(f"📚 书架 (共 {len(books)} 本)")
        current_search = self.search_input.text()
        if current_search:
            self.filter_books(current_search)
        else:
            self.populate_list(books)

    def populate_list(self, books_to_show):
        self.list_widget.clear()
        if not books_to_show: return
        for book in books_to_show:
            display_text = f"{book['name']} - {book['author']}"
            item = QListWidgetItem(display_text)
            item.setData(Qt.UserRole, book)
            self.list_widget.addItem(item)

    def filter_books(self, text):
        text = text.lower()
        filtered = []
        for book in self.main_window.books:
            if text in book['name'].lower() or text in book['author'].lower():
                filtered.append(book)
        self.populate_list(filtered)

    def on_item_double_clicked(self, item):
        self.selected_book = item.data(Qt.UserRole)
        self.accept()


# ================= 独立窗口：目录选择器 =================
class ChapterLoader(QThread):
    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, ip, book_url):
        super().__init__()
        self.ip = ip
        self.book_url = book_url

    def run(self):
        try:
            url = f"{self.ip}/getChapterList"
            res = requests.get(url, params={"url": self.book_url}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data['isSuccess']:
                    self.loaded.emit(data['data'])
                else:
                    self.failed.emit(data.get('errorMsg', '未知错误'))
            else:
                self.failed.emit(f"HTTP {res.status_code}")
        except Exception as e:
            self.failed.emit(str(e))


class TocSelector(QDialog):
    def __init__(self, ip, book_url, current_index, cached_toc=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("📖 目录加载中...")
        self.resize(400, 600)
        self.ip = ip
        self.book_url = book_url
        self.selected_index = None
        self.main_window = parent
        self.target_index = current_index
        self.loader = None
        self.setStyleSheet(DARK_STYLESHEET)

        self.initUI()

        if cached_toc and len(cached_toc) > 0:
            self.on_loaded(cached_toc)
        else:
            self.loader = ChapterLoader(ip, book_url)
            self.loader.loaded.connect(self.on_loaded)
            self.loader.failed.connect(self.on_failed)
            self.loader.start()

    def initUI(self):
        layout = QVBoxLayout()
        self.status_label = QLabel("正在从手机获取目录...")
        self.status_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self.status_label)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        self.list_widget.hide()
        layout.addWidget(self.list_widget)
        self.setLayout(layout)

    def on_loaded(self, chapters):
        try:
            self.setWindowTitle(f"📖 目录 (共 {len(chapters)} 章)")
            self.status_label.hide()
            self.list_widget.show()

            if self.main_window:
                self.main_window.current_toc = chapters

            for i, chapter in enumerate(chapters):
                title = str(chapter.get('title', f'第 {i + 1} 章'))
                item = QListWidgetItem(title)
                idx = chapter.get('index', i)
                item.setData(Qt.UserRole, idx)
                self.list_widget.addItem(item)
                if i == self.target_index:
                    item.setSelected(True)
                    self.list_widget.scrollToItem(item, QListWidget.PositionAtCenter)
        except Exception as e:
            self.status_label.setText(f"数据解析错误: {str(e)}")
            self.status_label.show()

    def on_failed(self, msg):
        self.status_label.setText(f"目录加载失败: {msg}")

    def on_item_double_clicked(self, item):
        self.selected_index = item.data(Qt.UserRole)
        self.accept()

    def closeEvent(self, event):
        if self.loader and self.loader.isRunning():
            self.loader.terminate()
            self.loader.wait()
        super().closeEvent(event)


# ================= 设置窗口 =================
class SettingsDialog(QDialog):
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.main_window = parent
        self.original_opacity = self.config.get("opacity", 0.9)
        self.temp_text_color = self.config.get("text_color")
        self.temp_bg_color = self.config.get("bg_color")

        self.setWindowTitle("设置")
        self.resize(350, 560)
        self.setStyleSheet(DARK_STYLESHEET)
        self.initUI()

    def initUI(self):
        layout = QFormLayout()
        self.ip_input = QLineEdit(self.config.get("ip"))
        layout.addRow("Legado地址:", self.ip_input)

        self.check_auto_mode = QCheckBox("🦎 自动挡 (变色龙)")
        self.check_auto_mode.setToolTip("开启后，背景变为背景色+极低透明度。\n字体颜色自动反转。")
        self.check_auto_mode.setChecked(self.config.get("auto_mode", False))
        self.check_auto_mode.toggled.connect(self.on_auto_mode_toggled)
        layout.addRow(self.check_auto_mode)

        self.check_antishot = QCheckBox("🛡️ 系统级防截屏")
        self.check_antishot.setToolTip("开启后，肉眼可见，但截图/录屏时窗口会完全消失（透明）。\n使用 Windows 系统底层保护。")
        self.check_antishot.setChecked(self.config.get("antishot_mode", False))
        self.check_antishot.toggled.connect(self.on_antishot_toggled)
        layout.addRow(self.check_antishot)

        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(self.config.get("opacity") * 100))
        self.opacity_slider.valueChanged.connect(self.on_opacity_change)
        layout.addRow("不透明度:", self.opacity_slider)

        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 60)
        self.font_spin.setValue(self.config.get("font_size"))
        layout.addRow("字体大小:", self.font_spin)

        self.font_combo = QFontComboBox()
        current_font_family = self.config.get("font_family", "Microsoft YaHei")
        self.font_combo.setCurrentFont(QFont(current_font_family))
        layout.addRow("字体样式:", self.font_combo)

        self.btn_text_color = QPushButton("文字颜色 (手动)")
        self.btn_text_color.setStyleSheet(f"background-color: {self.temp_text_color};")
        self.btn_text_color.clicked.connect(self.pick_text_color)
        self.btn_bg_color = QPushButton("背景颜色 (手动)")
        self.btn_bg_color.setStyleSheet(f"background-color: {self.temp_bg_color};")
        self.btn_bg_color.clicked.connect(self.pick_bg_color)
        layout.addRow(self.btn_text_color, self.btn_bg_color)

        self.check_ghost_mode = QCheckBox("👻 幽灵模式 (移开变透明)")
        self.check_ghost_mode.setChecked(self.config.get("ghost_mode", False))
        layout.addRow(self.check_ghost_mode)

        self.boss_key_input = QLineEdit(self.config.get("boss_key", "Esc"))
        layout.addRow("全局老板键:", self.boss_key_input)

        btn_save = QPushButton("💾 保存并应用")
        btn_save.clicked.connect(self.accept)
        layout.addRow(btn_save)

        self.on_auto_mode_toggled(self.check_auto_mode.isChecked())
        self.on_antishot_toggled(self.check_antishot.isChecked())
        self.setLayout(layout)

    def on_auto_mode_toggled(self, checked):
        self.btn_bg_color.setEnabled(not checked)
        self.btn_text_color.setEnabled(not checked)
        self.opacity_slider.setEnabled(True)

    def on_antishot_toggled(self, checked):
        if self.main_window:
            hwnd = int(self.main_window.winId())
            set_window_protection(hwnd, checked)

    def on_opacity_change(self, value):
        new_opacity = value / 100.0
        self.config["opacity"] = new_opacity
        if self.main_window:
            self.main_window.apply_style()

    def pick_text_color(self):
        color = QColorDialog.getColor()
        if color.isValid():
            self.temp_text_color = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
            self.btn_text_color.setStyleSheet(f"background-color: {self.temp_text_color};")

    def pick_bg_color(self):
        color = QColorDialog.getColor(options=QColorDialog.ShowAlphaChannel)
        if color.isValid():
            self.temp_bg_color = f"rgba({color.red()}, {color.green()}, {color.blue()}, {color.alpha()})"
            self.btn_bg_color.setStyleSheet(f"background-color: {self.temp_bg_color};")

    def accept(self):
        self.config["ip"] = self.ip_input.text().strip()
        self.config["font_size"] = self.font_spin.value()
        self.config["font_family"] = self.font_combo.currentFont().family()
        self.config["boss_key"] = self.boss_key_input.text().strip()
        self.config["text_color"] = self.temp_text_color
        self.config["bg_color"] = self.temp_bg_color
        self.config["ghost_mode"] = self.check_ghost_mode.isChecked()
        self.config["auto_mode"] = self.check_auto_mode.isChecked()
        self.config["antishot_mode"] = self.check_antishot.isChecked()
        super().accept()

    def reject(self):
        self.config["opacity"] = self.original_opacity
        if self.main_window:
            self.main_window.apply_style()
            set_window_protection(int(self.main_window.winId()), self.config.get("antishot_mode", False))
        super().reject()


# ================= 主程序 =================
class StealthReader(QWidget):
    update_text_signal = pyqtSignal(str, bool)
    hotkey_signal = pyqtSignal()
    bookshelf_updated_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.load_config()
        self.is_settings_open = False

        # --- 网络书架数据 ---
        self.books = []
        self.current_book = None
        self.current_chapter_index = 0
        self.current_toc = []

        # --- 本地书籍数据 ---
        self.is_local_mode = False  # 模式标记
        self.local_full_text = ""  # 本地文件全文内容
        self.local_start_index = 0  # 当前页起始字符在全文中的索引 (锚点)
        self.local_page_history = []  # 记录翻页历史，用于"上一页"
        self.local_file_path = ""  # 当前文件路径

        # --- 界面控制 ---
        self.single_line_height = 20
        self.is_mouse_in = False
        self.is_resizing = False
        self.is_moving = False
        self.resize_margin = 15
        self.last_toggle_time = 0
        self.local_shortcut = None
        self.book_selector_dialog = None
        self.oldPos = QPoint(0, 0)

        self.chameleon_timer = QTimer(self)
        self.chameleon_timer.setInterval(500)
        self.chameleon_timer.timeout.connect(self.adjust_color_to_background)

        self.initUI()
        self.initTray()

        self.update_text_signal.connect(self.on_update_text_safe)
        self.hotkey_signal.connect(self.toggle_window)
        self.bookshelf_updated_signal.connect(self.on_bookshelf_updated)

        self.refresh_hotkeys()

        # 尝试恢复上次打开的本地文件
        if self.config.get("last_local_file") and os.path.exists(self.config["last_local_file"]):
            self.update_text_signal.emit("正在恢复上次阅读...", False)
            QTimer.singleShot(500, self.restore_last_local_file)
        elif self.config["ip"] and self.config["ip"].startswith("http"):
            self.fetch_bookshelf_silent()
            self.update_text_signal.emit("初始化完成。\n右键菜单可打开本地TXT文件。", False)
        else:
            self.update_text_signal.emit("欢迎使用。\n右键打开本地书籍或设置Legado。", False)

        if self.config.get("antishot_mode", False):
            QTimer.singleShot(100, lambda: set_window_protection(int(self.winId()), True))

    def restore_last_local_file(self):
        path = self.config["last_local_file"]
        pos = self.config.get("last_local_pos", 0)
        self.load_local_file(path, target_pos=pos)

    # --- 打开本地文件 (防止 0xC0000409 崩溃) ---
    def open_local_file_dialog(self):
        options = QFileDialog.Options()
        # 【关键】禁用 Windows 原生对话框，改用 Qt 内置对话框
        options |= QFileDialog.DontUseNativeDialog

        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "选择文本文件",
            "",
            "Text Files (*.txt);;All Files (*)",
            options=options
        )

        if file_path:
            # 检查是否是同一本书
            last_file = self.config.get("last_local_file", "")

            is_same_file = False
            if last_file:
                try:
                    is_same_file = os.path.normpath(file_path) == os.path.normpath(last_file)
                except:
                    is_same_file = (file_path == last_file)

            if is_same_file:
                # 是同一本书：恢复上次进度
                saved_pos = self.config.get("last_local_pos", 0)
                self.load_local_file(file_path, target_pos=saved_pos)
            else:
                # 是新书：从头开始
                self.load_local_file(file_path, target_pos=0)

    def load_local_file(self, file_path, target_pos=0):
        try:
            content = ""
            # 尝试多种编码读取
            try:
                with open(file_path, 'r', encoding='utf-8-sig') as f:
                    content = f.read()
            except UnicodeDecodeError:
                try:
                    with open(file_path, 'r', encoding='gb18030') as f:
                        content = f.read()
                except Exception as e:
                    self.update_text_signal.emit(f"编码无法识别，请转为UTF-8或GBK", False)
                    return

            if not content:
                self.update_text_signal.emit("文件为空", False)
                return

            self.is_local_mode = True
            self.local_file_path = file_path
            self.local_full_text = content

            # 安全校验索引
            safe_pos = min(max(0, target_pos), len(content) - 1)
            self.local_start_index = safe_pos
            self.local_page_history = []

            # 【关键】加载时立即保存配置
            self.config["last_local_file"] = file_path
            self.config["last_local_pos"] = safe_pos
            self.save_config()

            self.render_local_page()

            if safe_pos > 0:
                self.update_text_signal.emit(f"已恢复进度: {os.path.basename(file_path)}", False)

        except Exception as e:
            traceback.print_exc()
            self.update_text_signal.emit(f"打开文件失败: {str(e)}", False)

    # --- 本地分页渲染算法 (锚点核心) ---
    def render_local_page(self):
        if not self.is_local_mode or not self.local_full_text:
            return

        # 截取缓冲区（保证填满屏幕，取5000字足以覆盖各种屏幕）
        buffer_length = 5000
        end_buffer = min(self.local_start_index + buffer_length, len(self.local_full_text))

        display_text = self.local_full_text[self.local_start_index: end_buffer]

        self.text_edit.setPlainText(display_text)

        # 【关键】强制滚动条回顶，确保 local_start_index 对应的字符永远在第一行
        self.text_edit.verticalScrollBar().setValue(0)

    # --- 核心：基于几何坐标探测下一页起始位置 ---
    def calc_next_page_start(self):
        """利用视图几何坐标，探测屏幕底部边缘的字符位置"""
        viewport_h = self.text_edit.viewport().height()
        # 探测点：视图左下角再往下一点点 (取下一行的开头)
        target_y = viewport_h + 2

        cursor = self.text_edit.cursorForPosition(QPoint(0, target_y))
        next_pos_in_buffer = cursor.position()

        # 异常处理：如果一页装不满，cursor会指向文档末尾
        if next_pos_in_buffer >= len(self.text_edit.toPlainText()):
            return len(self.text_edit.toPlainText())

        return next_pos_in_buffer

    # --- 核心：基于反向排版探测上一页起始位置 ---
    def calc_prev_page_start(self):
        """通过加载前文并滚到底部，探测上一页的起始位置"""
        if self.local_start_index == 0:
            return 0

        self.text_edit.setUpdatesEnabled(False)
        try:
            buffer_size = 5000
            temp_start = max(0, self.local_start_index - buffer_size)
            prev_content = self.local_full_text[temp_start: self.local_start_index]

            self.text_edit.setPlainText(prev_content)

            scrollbar = self.text_edit.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())

            cursor = self.text_edit.cursorForPosition(QPoint(0, 0))
            chars_in_prev_page = len(prev_content) - cursor.position()

            real_prev_start = self.local_start_index - chars_in_prev_page

            return max(0, real_prev_start)
        finally:
            self.text_edit.setUpdatesEnabled(True)

    # --- 翻页逻辑 (即时存档 + 几何分页) ---
    def scroll_page(self, direction):
        if self.is_local_mode:
            # --- 本地模式 ---
            if direction > 0:  # 下一页
                if self.local_start_index >= len(self.local_full_text):
                    return

                # 几何计算本页内容量
                step = self.calc_next_page_start()
                if step == 0 and self.local_start_index < len(self.local_full_text):
                    step = 1

                self.local_page_history.append(self.local_start_index)
                self.local_start_index += step

                if self.local_start_index > len(self.local_full_text):
                    self.local_start_index = len(self.local_full_text)

                self.render_local_page()

            else:  # 上一页
                if self.local_page_history:
                    # 优先使用历史
                    self.local_start_index = self.local_page_history.pop()
                else:
                    # 无历史时，反向排版计算
                    self.local_start_index = self.calc_prev_page_start()

                self.render_local_page()

            # 【关键】即时存档
            self.config["last_local_pos"] = self.local_start_index
            self.save_config()

        else:
            # --- 网络模式 ---
            scrollbar = self.text_edit.verticalScrollBar()
            current_val = scrollbar.value()
            max_val = scrollbar.maximum()
            min_val = scrollbar.minimum()

            target_val = current_val + (direction * (self.text_edit.viewport().height() - 30))

            if direction > 0:
                if current_val >= max_val - 5:
                    self.next_chapter()
                else:
                    scrollbar.setValue(min(target_val, max_val))
            else:
                if current_val <= min_val + 5:
                    self.prev_chapter()
                else:
                    scrollbar.setValue(max(target_val, min_val))

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    file_config = json.load(f)
                    self.config = {**DEFAULT_CONFIG, **file_config}
            except:
                self.config = DEFAULT_CONFIG.copy()
        else:
            self.config = DEFAULT_CONFIG.copy()

    def save_config(self):
        try:
            self.config["window_width"] = self.width()
            self.config["window_height"] = self.height()
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
        except Exception as e:
            print(f"Failed to save config: {e}")

    def on_update_text_safe(self, text, is_bottom):
        self.text_edit.setPlainText(text)
        if "加载" in text or "连接" in text or "失败" in text:
            return

        scrollbar = self.text_edit.verticalScrollBar()
        if is_bottom:
            scrollbar.setValue(scrollbar.maximum())
        else:
            scrollbar.setValue(0)

    def on_bookshelf_updated(self, books):
        self.books = books
        if self.book_selector_dialog and self.book_selector_dialog.isVisible():
            self.book_selector_dialog.update_data(books)

    def refresh_hotkeys(self):
        hotkey_str = self.config.get("boss_key", "Esc")
        try:
            keyboard.unhook_all()
            keyboard.add_hotkey(hotkey_str, self.on_global_hotkey_triggered)
        except:
            pass
        try:
            if self.local_shortcut:
                self.local_shortcut.setKey(QKeySequence())
                self.local_shortcut = None
            self.local_shortcut = QShortcut(QKeySequence(hotkey_str), self)
            self.local_shortcut.activated.connect(self.toggle_window)
        except:
            pass

    def on_global_hotkey_triggered(self):
        self.hotkey_signal.emit()

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)

        self.main_layout = QVBoxLayout()
        self.main_layout.setContentsMargins(0, 0, 0, 0)
        self.main_layout.setSpacing(0)

        self.content_frame = CornerFrame()
        self.content_layout = QVBoxLayout(self.content_frame)

        self.content_layout.setContentsMargins(5, 0, 5, 0)
        self.content_layout.setSpacing(0)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFrameStyle(QFrame.NoFrame)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text_edit.setFocusPolicy(Qt.NoFocus)

        self.text_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Ignored)
        self.text_edit.setMinimumHeight(0)
        self.text_edit.document().setDocumentMargin(0)

        self.text_edit.installEventFilter(self)

        self.content_layout.addWidget(self.text_edit)
        self.main_layout.addWidget(self.content_frame)
        self.setLayout(self.main_layout)

        w = self.config.get("window_width", 400)
        h = self.config.get("window_height", 300)
        self.resize(w, h)
        self.move(100, 100)
        self.oldPos = self.pos()

        self.apply_style()

    def eventFilter(self, source, event):
        if source == self.text_edit and event.type() == QEvent.Wheel:
            delta = event.angleDelta().y()
            if self.is_local_mode:
                if delta < 0:
                    self.scroll_page(1)
                elif delta > 0:
                    self.scroll_page(-1)
                return True
            else:
                scrollbar = self.text_edit.verticalScrollBar()
                if delta < 0:
                    if scrollbar.value() >= scrollbar.maximum() - 2:
                        self.next_chapter()
                        return True
                elif delta > 0:
                    if scrollbar.value() <= scrollbar.minimum() + 2:
                        self.prev_chapter()
                        return True
        return super().eventFilter(source, event)

    def initTray(self):
        self.tray_icon = QSystemTrayIcon(self)
        icon = self.style().standardIcon(QStyle.SP_ComputerIcon)
        self.tray_icon.setIcon(icon)
        tray_menu = QMenu()
        tray_menu.addAction("显示/隐藏").triggered.connect(self.toggle_window)
        tray_menu.addAction("退出").triggered.connect(self.quit_app)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.on_tray_activated)
        self.tray_icon.show()

    def on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick:
            self.toggle_window()

    def toggle_window(self):
        current_time = time.time()
        if current_time - self.last_toggle_time < 0.3:
            return
        self.last_toggle_time = current_time

        if self.isVisible():
            self.sync_progress_async()
            self.hide()
        else:
            self.showNormal()
            self.apply_style()
            self.activateWindow()
            if self.config.get("auto_mode", False):
                self.chameleon_timer.start()
                self.adjust_color_to_background()

            if self.config.get("antishot_mode", False):
                set_window_protection(int(self.winId()), True)

    def adjust_color_to_background(self):
        if not self.isVisible() or not self.config.get("auto_mode"):
            self.chameleon_timer.stop()
            return

        screen = QApplication.primaryScreen()
        if not screen: return

        pick_x = self.x() - 5
        pick_y = self.y() + 10

        if pick_x < 0:
            pick_x = self.x() + self.width() + 5

        pixmap = screen.grabWindow(0, pick_x, pick_y, 1, 1)
        img = pixmap.toImage()

        if img.width() > 0:
            color = img.pixelColor(0, 0)
            brightness = 0.299 * color.red() + 0.587 * color.green() + 0.114 * color.blue()

            self.content_frame.set_auto_bg_color(color)
            base_text_color = (0, 0, 0) if brightness > 128 else (255, 255, 255)
            user_alpha = int(self.config.get("opacity", 0.9) * 255)
            rgba_color = f"rgba({base_text_color[0]}, {base_text_color[1]}, {base_text_color[2]}, {user_alpha})"

            self.text_edit.setStyleSheet(f"""
                QTextEdit {{
                    color: {rgba_color};
                    background-color: transparent;
                    padding: 0px; margin: 0px; border: none;
                }}
            """)

    def apply_style(self):
        font_family = self.config.get('font_family', 'Microsoft YaHei')
        font_size = self.config['font_size']
        font = QFont(font_family, font_size)

        self.text_edit.setFont(font)

        fm = QFontMetrics(font)
        self.single_line_height = fm.lineSpacing()
        base_css = "padding: 0px; margin: 0px; border: none;"

        if self.config.get("auto_mode", False):
            self.setWindowOpacity(1.0)
            self.content_frame.set_mode(True)
            self.content_frame.setStyleSheet("background: transparent; border: none;")
            self.content_frame.set_draw_corners(True)
            self.chameleon_timer.start()
            self.adjust_color_to_background()
        else:
            self.chameleon_timer.stop()
            self.content_frame.set_draw_corners(False)
            self.setWindowOpacity(self.config["opacity"])
            self.setStyleSheet("")
            self.content_frame.set_mode(False)
            frame_style = f"""
                CornerFrame {{
                    background-color: {self.config['bg_color']};
                    border-radius: 5px;
                }}
            """
            self.content_frame.setStyleSheet(frame_style)
            text_style = f"""
                QTextEdit {{
                    color: {self.config['text_color']};
                    background-color: transparent;
                    {base_css}
                }}
            """
            self.text_edit.setStyleSheet(text_style)

            # 本地模式下修改样式需要重绘页面
            if self.is_local_mode:
                self.render_local_page()

    def enterEvent(self, event):
        self.is_mouse_in = True
        if self.config.get("ghost_mode", False):
            self.apply_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_mouse_in = False
        if self.is_settings_open or self.is_resizing or self.is_moving: return

        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        if self.rect().contains(local_pos): return

        if self.config.get("ghost_mode", False):
            if self.config.get("auto_mode", False):
                self.chameleon_timer.stop()
                self.content_frame.set_draw_corners(False)
                current_bg = self.content_frame.auto_bg_fill
                r, g, b = current_bg.red(), current_bg.green(), current_bg.blue()
                ghost_bg_style = f"rgba({r}, {g}, {b}, 2)"
                self.text_edit.setStyleSheet(f"""
                    QTextEdit {{
                        color: transparent; 
                        background-color: {ghost_bg_style};
                        padding: 0px; margin: 0px; border: none;
                    }}
                """)
                self.setWindowOpacity(1.0)
            else:
                self.setWindowOpacity(0.005)
        super().leaveEvent(event)

    def fetch_bookshelf_silent(self):
        threading.Thread(target=self._fetch_bookshelf_thread, daemon=True).start()

    def _fetch_bookshelf_thread(self):
        try:
            url = f"{self.config['ip']}/getBookshelf"
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                data = res.json()
                self.bookshelf_updated_signal.emit(data.get("data", []))
        except:
            pass

    def fetch_toc_silent(self, book_url):
        threading.Thread(target=self._fetch_toc_thread, args=(book_url,), daemon=True).start()

    def _fetch_toc_thread(self, book_url):
        try:
            url = f"{self.config['ip']}/getChapterList"
            res = requests.get(url, params={"url": book_url}, timeout=10)
            if res.status_code == 200:
                data = res.json()
                if data['isSuccess']:
                    self.current_toc = data['data']
        except:
            pass

    def open_book_selector(self):
        self.fetch_bookshelf_silent()
        self.book_selector_dialog = BookSelector(self, self)

        was_auto = self.config.get("auto_mode")
        if was_auto:
            self.setWindowOpacity(0.95)
            self.content_frame.setStyleSheet(f"background-color: {self.config['bg_color']};")
            self.content_frame.set_mode(False)

        if self.book_selector_dialog.exec_() == QDialog.Accepted:
            if self.book_selector_dialog.selected_book:
                self.load_book(self.book_selector_dialog.selected_book)

        self.apply_style()
        self.book_selector_dialog = None

    def open_toc_selector(self):
        if not self.current_book:
            self.update_text_signal.emit("请先选择一本书！", False)
            return

        if not hasattr(self, 'current_toc') or self.current_toc is None:
            self.current_toc = []

        was_auto = self.config.get("auto_mode")
        if was_auto:
            self.setWindowOpacity(0.95)
            self.content_frame.setStyleSheet(f"background-color: {self.config['bg_color']};")
            self.content_frame.set_mode(False)

        toc = TocSelector(self.config['ip'], self.current_book['bookUrl'],
                          self.current_chapter_index, self.current_toc, self)

        if toc.exec_() == QDialog.Accepted:
            if toc.selected_index is not None:
                self.current_chapter_index = toc.selected_index
                self.update_text_signal.emit(f"跳转到章节: {self.current_chapter_index}", False)
                self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index, False)

        self.apply_style()

    def load_book(self, book):
        self.is_local_mode = False  # 切换回网络模式
        self.current_book = book
        self.current_chapter_index = book.get('durChapterIndex', 0)
        self.current_toc = []
        self.update_text_signal.emit(f"打开: {book['name']}", False)
        self.fetch_chapter_content(book['bookUrl'], self.current_chapter_index, False)
        self.fetch_toc_silent(book['bookUrl'])

    def fetch_chapter_content(self, book_url, chapter_index, scroll_to_bottom=False):
        t = threading.Thread(target=self._fetch_chapter_thread,
                             args=(book_url, chapter_index, scroll_to_bottom), daemon=True)
        t.start()

    def _fetch_chapter_thread(self, book_url, chapter_index, scroll_to_bottom):
        try:
            chapter_title = ""
            if hasattr(self, 'current_toc') and self.current_toc:
                if 0 <= chapter_index < len(self.current_toc):
                    chapter_title = self.current_toc[chapter_index].get('title', '')

            if not chapter_title:
                chapter_title = f"第 {chapter_index + 1} 章"

            url = f"{self.config['ip']}/getBookContent"
            params = {'url': book_url, 'index': chapter_index}
            res = requests.get(url, params=params, timeout=5)

            if res.status_code == 200:
                data = res.json()
                if not data.get("isSuccess"):
                    self.update_text_signal.emit(f"读取失败: {data.get('errorMsg')}", False)
                    return

                raw_content = data.get("data", "")
                content = raw_content.replace("<br>", "\n").replace("&nbsp;", " ")

                full_text = f"【 {chapter_title} 】\n\n{content}"

                self.update_text_signal.emit(full_text, scroll_to_bottom)
                self.sync_progress_async()
            else:
                self.update_text_signal.emit(f"HTTP错误: {res.status_code}", False)
        except Exception as e:
            self.update_text_signal.emit(f"网络错误: {str(e)}", False)

    def sync_progress_async(self):
        if not self.current_book or self.is_local_mode: return
        threading.Thread(target=self._sync_task, daemon=True).start()

    def _sync_task(self):
        try:
            title = ""
            if self.current_toc and 0 <= self.current_chapter_index < len(self.current_toc):
                title = self.current_toc[self.current_chapter_index].get("title", "")

            data = {
                "name": self.current_book['name'],
                "author": self.current_book['author'],
                "durChapterIndex": self.current_chapter_index,
                "durChapterPos": 0,
                "durChapterTime": int(time.time() * 1000),
                "durChapterTitle": title
            }
            url = f"{self.config['ip']}/saveBookProgress"
            requests.post(url, json=data, timeout=3)
        except:
            pass

    def next_chapter(self):
        self.current_chapter_index += 1
        self.update_text_signal.emit("加载下一章...", False)
        self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index, False)

    def prev_chapter(self):
        if self.current_chapter_index > 0:
            self.current_chapter_index -= 1
            self.update_text_signal.emit("加载上一章...", False)
            self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index, True)

    def is_in_resize_area(self, pos):
        rect = self.rect()
        resize_rect = QRect(rect.width() - self.resize_margin,
                            rect.height() - self.resize_margin,
                            self.resize_margin, self.resize_margin)
        return resize_rect.contains(pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.is_in_resize_area(event.pos()):
                self.is_resizing = True
                self.is_moving = False
            else:
                self.is_moving = True
                self.is_resizing = False
                self.oldPos = event.globalPos()

    def mouseMoveEvent(self, event):
        if self.is_in_resize_area(event.pos()):
            self.setCursor(Qt.SizeFDiagCursor)
        elif not self.is_resizing:
            self.setCursor(Qt.ArrowCursor)

        if event.buttons() == Qt.LeftButton:
            if self.is_resizing:
                new_w = max(event.pos().x(), 100)
                min_h = getattr(self, 'single_line_height', 20)
                new_h = max(event.pos().y(), min_h)
                self.resize(new_w, new_h)

                # 【核心逻辑】调整大小时基于锚点重绘
                if self.is_local_mode:
                    self.render_local_page()

            elif self.is_moving:
                delta = QPoint(event.globalPos() - self.oldPos)
                self.move(self.x() + delta.x(), self.y() + delta.y())
                self.oldPos = event.globalPos()

            if self.config.get("auto_mode"):
                self.adjust_color_to_background()

    def mouseReleaseEvent(self, event):
        self.is_resizing = False
        self.is_moving = False
        self.setCursor(Qt.ArrowCursor)
        self.save_config()

    def contextMenuEvent(self, event):
        cmenu = QMenu(self)
        cmenu.addAction("📂 打开本地 TXT").triggered.connect(self.open_local_file_dialog)
        cmenu.addSeparator()
        cmenu.addAction("📚 网络书架 (搜索)").triggered.connect(self.open_book_selector)
        cmenu.addAction("📖 章节目录 (网络)").triggered.connect(self.open_toc_selector)
        cmenu.addSeparator()
        cmenu.addAction("⚙️ 设置").triggered.connect(self.open_settings)
        cmenu.addSeparator()
        cmenu.addAction("❌ 退出").triggered.connect(self.quit_app)
        cmenu.exec_(self.mapToGlobal(event.pos()))

    def open_settings(self):
        self.is_settings_open = True
        was_auto = self.config.get("auto_mode")
        if was_auto:
            self.content_frame.set_mode(False)
            self.setWindowOpacity(0.95)
            self.content_frame.setStyleSheet(f"background-color: {self.config['bg_color']};")

        dialog = SettingsDialog(self.config, self)

        if dialog.exec_() == QDialog.Accepted:
            self.config = dialog.config
            self.save_config()
            self.apply_style()
            self.refresh_hotkeys()
            if self.config["ip"].startswith("http"):
                self.fetch_bookshelf_silent()
        else:
            self.apply_style()

        self.is_settings_open = False
        self.showNormal()
        self.activateWindow()

    def keyPressEvent(self, event):
        key = event.key()
        if key in [Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown]:
            self.scroll_page(1)
        elif key in [Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp]:
            self.scroll_page(-1)

    def closeEvent(self, event):
        self.sync_progress_async()
        if self.is_local_mode:
            self.config["last_local_pos"] = self.local_start_index
            self.save_config()
        super().closeEvent(event)

    def quit_app(self):
        # 退出前强制保存本地进度
        if self.is_local_mode:
            self.config["last_local_pos"] = self.local_start_index
            self.save_config()

        keyboard.unhook_all()
        QApplication.instance().quit()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ex = StealthReader()
    ex.show()
    sys.exit(app.exec_())