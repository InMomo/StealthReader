import sys
import requests
import json
import os
import threading
import time
import keyboard
from PyQt5.QtWidgets import (QApplication, QWidget, QVBoxLayout, QMenu,
                             QAction, QDialog, QFormLayout, QLineEdit, QSlider,
                             QSpinBox, QPushButton, QSystemTrayIcon, QStyle,
                             QColorDialog, QCheckBox, QHBoxLayout,
                             QFrame, QTextEdit, QShortcut, QListWidget,
                             QListWidgetItem, QLabel)
from PyQt5.QtCore import Qt, QPoint, QRect, pyqtSignal, QObject, QThread
from PyQt5.QtGui import QFont, QColor, QCursor, QKeySequence

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
    "window_width": 400,
    "window_height": 300
}

DARK_STYLESHEET = """
    QDialog, QWidget { background-color: #2b2b2b; color: #cccccc; }
    QLineEdit { background-color: #3c3c3c; color: white; border: 1px solid #555; padding: 5px; border-radius: 4px; }
    QListWidget { background-color: #333; color: #ddd; border: 1px solid #444; }
    QListWidget::item:selected { background-color: #505050; color: white; }
    QListWidget::item:hover { background-color: #3e3e3e; }
    QPushButton { background-color: #444; color: white; border: 1px solid #555; padding: 5px; border-radius: 4px; }
    QPushButton:hover { background-color: #555; }
    QLabel { color: #aaa; }
"""


# ================= 独立窗口：书籍选择器 (修复版) =================
class BookSelector(QDialog):
    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window  # 持有主窗口引用，以便实时获取数据
        self.setWindowTitle("📚 书架")
        self.resize(400, 500)
        self.selected_book = None
        self.setStyleSheet(DARK_STYLESHEET)
        self.initUI()

        # 初始化时先加载一次当前有的数据
        self.populate_list(self.main_window.books)

    def initUI(self):
        layout = QVBoxLayout()

        # 顶部操作区
        top_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("🔍 搜索书名或作者...")
        self.search_input.textChanged.connect(self.filter_books)
        top_layout.addWidget(self.search_input)

        # [新增] 刷新按钮
        btn_refresh = QPushButton("🔄 刷新")
        btn_refresh.setFixedWidth(60)
        btn_refresh.clicked.connect(self.manual_refresh)
        top_layout.addWidget(btn_refresh)

        layout.addLayout(top_layout)

        # 列表
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.on_item_double_clicked)
        layout.addWidget(self.list_widget)

        self.setLayout(layout)

    def manual_refresh(self):
        self.setWindowTitle("📚 书架 (加载中...)")
        # 调用主窗口的方法去获取数据
        self.main_window.fetch_bookshelf_silent()

    def update_data(self, books):
        """当主窗口数据更新时被调用"""
        self.setWindowTitle(f"📚 书架 (共 {len(books)} 本)")
        # 如果正在搜索，保持搜索结果；否则显示全部
        current_search = self.search_input.text()
        if current_search:
            self.filter_books(current_search)
        else:
            self.populate_list(books)

    def populate_list(self, books_to_show):
        self.list_widget.clear()
        if not books_to_show:
            return

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
        self.temp_text_color = self.config.get("text_color")
        self.temp_bg_color = self.config.get("bg_color")
        self.setWindowTitle("设置")
        self.resize(350, 400)
        self.setStyleSheet(DARK_STYLESHEET)
        self.initUI()

    def initUI(self):
        layout = QFormLayout()
        self.ip_input = QLineEdit(self.config.get("ip"))
        layout.addRow("Legado地址:", self.ip_input)
        self.opacity_slider = QSlider(Qt.Horizontal)
        self.opacity_slider.setRange(10, 100)
        self.opacity_slider.setValue(int(self.config.get("opacity") * 100))
        layout.addRow("正常不透明度:", self.opacity_slider)
        self.font_spin = QSpinBox()
        self.font_spin.setRange(8, 60)
        self.font_spin.setValue(self.config.get("font_size"))
        layout.addRow("字体大小:", self.font_spin)
        self.btn_text_color = QPushButton("文字颜色")
        self.btn_text_color.setStyleSheet(f"background-color: {self.temp_text_color};")
        self.btn_text_color.clicked.connect(self.pick_text_color)
        self.btn_bg_color = QPushButton("背景颜色")
        self.btn_bg_color.setStyleSheet(f"background-color: {self.temp_bg_color};")
        self.btn_bg_color.clicked.connect(self.pick_bg_color)
        layout.addRow(self.btn_text_color, self.btn_bg_color)
        self.check_ghost_mode = QCheckBox("启用“幽灵模式” (鼠标移开变透明)")
        self.check_ghost_mode.setChecked(self.config.get("ghost_mode", False))
        layout.addRow(self.check_ghost_mode)
        self.boss_key_input = QLineEdit(self.config.get("boss_key", "Esc"))
        layout.addRow("全局老板键:", self.boss_key_input)
        hint_label = QPushButton("⚠️ IP设置后重启生效更佳")
        hint_label.setFlat(True)
        hint_label.setStyleSheet("color: gray; text-align: left; border: none;")
        layout.addRow(hint_label)
        btn_save = QPushButton("💾 保存并应用")
        btn_save.clicked.connect(self.save_settings)
        layout.addRow(btn_save)
        self.setLayout(layout)

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

    def save_settings(self):
        self.config["ip"] = self.ip_input.text().strip()
        self.config["opacity"] = self.opacity_slider.value() / 100.0
        self.config["font_size"] = self.font_spin.value()
        self.config["boss_key"] = self.boss_key_input.text().strip()
        self.config["text_color"] = self.temp_text_color
        self.config["bg_color"] = self.temp_bg_color
        self.config["ghost_mode"] = self.check_ghost_mode.isChecked()
        self.accept()


# ================= 主程序 =================
class StealthReader(QWidget):
    update_text_signal = pyqtSignal(str)
    hotkey_signal = pyqtSignal()
    # [新增] 书架数据更新的信号
    bookshelf_updated_signal = pyqtSignal(list)

    def __init__(self):
        super().__init__()
        self.load_config()
        self.is_settings_open = False
        self.books = []
        self.current_book = None
        self.current_chapter_index = 0
        self.current_toc = []

        self.is_mouse_in = False
        self.is_resizing = False
        self.is_moving = False
        self.resize_margin = 20
        self.last_toggle_time = 0
        self.local_shortcut = None

        # 记录当前打开的书架窗口实例
        self.book_selector_dialog = None

        self.initUI()
        self.initTray()

        self.update_text_signal.connect(self.on_update_text_safe)
        self.hotkey_signal.connect(self.toggle_window)
        # 连接书架更新信号到处理槽
        self.bookshelf_updated_signal.connect(self.on_bookshelf_updated)

        self.refresh_hotkeys()

        # [修复] 只要IP不为空且以http开头，就尝试连接，不再限制 192.168
        if self.config["ip"] and self.config["ip"].startswith("http"):
            self.fetch_bookshelf_silent()

        self.update_text_signal.emit("初始化完成。\n右键可打开【书架】。\n已移除启动IP限制。")

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
            print(f"保存配置失败: {e}")

    def on_update_text_safe(self, text):
        self.text_edit.setPlainText(text)
        if "加载" not in text and "连接" not in text and "失败" not in text:
            self.text_edit.verticalScrollBar().setValue(0)

    def on_bookshelf_updated(self, books):
        """当书架数据拉取成功，更新内存并通知书架窗口"""
        self.books = books
        # 如果书架窗口是打开的，通知它更新
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

        self.content_frame = QFrame()
        self.content_layout = QVBoxLayout(self.content_frame)
        self.content_layout.setContentsMargins(10, 10, 10, 10)

        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setFrameStyle(QFrame.NoFrame)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_edit.setTextInteractionFlags(Qt.NoTextInteraction)
        self.text_edit.setFocusPolicy(Qt.NoFocus)

        self.content_layout.addWidget(self.text_edit)
        self.main_layout.addWidget(self.content_frame)
        self.setLayout(self.main_layout)

        w = self.config.get("window_width", 400)
        h = self.config.get("window_height", 300)
        self.resize(w, h)
        self.move(100, 100)
        self.oldPos = self.pos()

        self.apply_style()

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
            self.setWindowOpacity(self.config['opacity'])
            self.activateWindow()

    def apply_style(self):
        self.setWindowOpacity(self.config["opacity"])
        frame_style = f"""
            QFrame {{
                background-color: {self.config['bg_color']};
                border-radius: 5px;
            }}
        """
        self.content_frame.setStyleSheet(frame_style)
        text_style = f"""
            QTextEdit {{
                color: {self.config['text_color']};
                background-color: transparent;
            }}
        """
        self.text_edit.setStyleSheet(text_style)
        self.text_edit.setFont(QFont(self.config['font_family'], self.config['font_size']))

    def enterEvent(self, event):
        self.is_mouse_in = True
        if self.config.get("ghost_mode", False):
            self.setWindowOpacity(self.config['opacity'])
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.is_mouse_in = False
        if self.is_settings_open or self.is_resizing or self.is_moving: return
        global_pos = QCursor.pos()
        local_pos = self.mapFromGlobal(global_pos)
        if self.rect().contains(local_pos): return
        if self.config.get("ghost_mode", False):
            self.setWindowOpacity(0.01)
        super().leaveEvent(event)

    # ================= 业务逻辑 =================
    def fetch_bookshelf_silent(self):
        threading.Thread(target=self._fetch_bookshelf_thread, daemon=True).start()

    def _fetch_bookshelf_thread(self):
        try:
            url = f"{self.config['ip']}/getBookshelf"
            res = requests.get(url, timeout=3)
            if res.status_code == 200:
                data = res.json()
                # 成功后，通过信号发送数据回主线程
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
        # 每次打开都尝试刷新一下
        self.fetch_bookshelf_silent()

        # 使用 self.book_selector_dialog 保持引用
        self.book_selector_dialog = BookSelector(self, self)

        # 临时恢复透明度，防止看不见
        self.setWindowOpacity(self.config["opacity"])

        if self.book_selector_dialog.exec_() == QDialog.Accepted:
            if self.book_selector_dialog.selected_book:
                self.load_book(self.book_selector_dialog.selected_book)

        self.book_selector_dialog = None  # 关闭后释放引用

    def open_toc_selector(self):
        if not self.current_book:
            self.update_text_signal.emit("请先选择一本书！")
            return

        if not hasattr(self, 'current_toc') or self.current_toc is None:
            self.current_toc = []

        self.setWindowOpacity(self.config["opacity"])

        toc = TocSelector(self.config['ip'], self.current_book['bookUrl'],
                          self.current_chapter_index, self.current_toc, self)

        if toc.exec_() == QDialog.Accepted:
            if toc.selected_index is not None:
                self.current_chapter_index = toc.selected_index
                self.update_text_signal.emit(f"跳转到章节: {self.current_chapter_index}")
                self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index)

    def load_book(self, book):
        self.current_book = book
        self.current_chapter_index = book.get('durChapterIndex', 0)
        self.current_toc = []
        self.update_text_signal.emit(f"打开: {book['name']}")
        self.fetch_chapter_content(book['bookUrl'], self.current_chapter_index)
        self.fetch_toc_silent(book['bookUrl'])

    def fetch_chapter_content(self, book_url, chapter_index):
        t = threading.Thread(target=self._fetch_chapter_thread,
                             args=(book_url, chapter_index), daemon=True)
        t.start()

    def _fetch_chapter_thread(self, book_url, chapter_index):
        try:
            url = f"{self.config['ip']}/getBookContent"
            params = {'url': book_url, 'index': chapter_index}
            res = requests.get(url, params=params, timeout=5)
            if res.status_code == 200:
                data = res.json()
                if not data.get("isSuccess"):
                    self.update_text_signal.emit(f"读取失败: {data.get('errorMsg')}")
                    return
                raw_content = data.get("data", "")
                content = raw_content.replace("<br>", "\n").replace("&nbsp;", " ")
                self.update_text_signal.emit(content)
                self.sync_progress_async()
            else:
                self.update_text_signal.emit(f"HTTP错误: {res.status_code}")
        except Exception as e:
            self.update_text_signal.emit(f"网络错误: {str(e)}")

    def sync_progress_async(self):
        if not self.current_book: return
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
            res = requests.post(url, json=data, timeout=3)
            # print(f"同步: {res.status_code}")
        except:
            pass

    def scroll_page(self, direction):
        scrollbar = self.text_edit.verticalScrollBar()
        current_val = scrollbar.value()
        max_val = scrollbar.maximum()
        min_val = scrollbar.minimum()
        page_step = self.text_edit.viewport().height()
        overlap = 30
        step = (page_step - overlap) * direction
        target_val = current_val + step
        tolerance = 5
        if direction > 0:
            if current_val >= max_val - tolerance:
                self.next_chapter()
            elif target_val >= max_val:
                scrollbar.setValue(max_val)
            else:
                scrollbar.setValue(target_val)
        else:
            if current_val <= min_val + tolerance:
                self.prev_chapter()
            elif target_val <= min_val:
                scrollbar.setValue(min_val)
            else:
                scrollbar.setValue(target_val)

    def next_chapter(self):
        self.current_chapter_index += 1
        self.update_text_signal.emit("加载下一章...")
        self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index)

    def prev_chapter(self):
        if self.current_chapter_index > 0:
            self.current_chapter_index -= 1
            self.update_text_signal.emit("加载上一章...")
            self.fetch_chapter_content(self.current_book['bookUrl'], self.current_chapter_index)

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
                new_h = max(event.pos().y(), 50)
                self.resize(new_w, new_h)
            elif self.is_moving:
                delta = QPoint(event.globalPos() - self.oldPos)
                self.move(self.x() + delta.x(), self.y() + delta.y())
                self.oldPos = event.globalPos()

    def mouseReleaseEvent(self, event):
        self.is_resizing = False
        self.is_moving = False
        self.setCursor(Qt.ArrowCursor)

    def contextMenuEvent(self, event):
        cmenu = QMenu(self)
        cmenu.addAction("📚 书架 (搜索)").triggered.connect(self.open_book_selector)
        cmenu.addAction("📖 章节目录").triggered.connect(self.open_toc_selector)
        cmenu.addSeparator()
        cmenu.addAction("⚙️ 设置").triggered.connect(self.open_settings)
        cmenu.addSeparator()
        cmenu.addAction("❌ 退出").triggered.connect(self.quit_app)
        cmenu.exec_(self.mapToGlobal(event.pos()))

    def open_settings(self):
        self.is_settings_open = True
        self.setWindowOpacity(self.config["opacity"])
        dialog = SettingsDialog(self.config, self)
        if dialog.exec_() == QDialog.Accepted:
            self.config = dialog.config
            self.save_config()
            self.apply_style()
            self.refresh_hotkeys()
            self.fetch_bookshelf_silent()
        self.is_settings_open = False
        if self.config.get("ghost_mode", False) and not self.underMouse():
            self.setWindowOpacity(0.01)

    def keyPressEvent(self, event):
        key = event.key()
        if key in [Qt.Key_Right, Qt.Key_Down, Qt.Key_Space, Qt.Key_PageDown]:
            self.scroll_page(1)
        elif key in [Qt.Key_Left, Qt.Key_Up, Qt.Key_PageUp]:
            self.scroll_page(-1)

    def closeEvent(self, event):
        self.sync_progress_async()
        super().closeEvent(event)

    def quit_app(self):
        keyboard.unhook_all()
        QApplication.instance().quit()


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    ex = StealthReader()
    ex.show()
    sys.exit(app.exec_())